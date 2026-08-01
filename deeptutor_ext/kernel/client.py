"""与容器里的 Jupyter 服务通话：建内核、执行代码、收输出、关内核。

只依赖 Jupyter 服务对外的 HTTP 与 WebSocket 接口，不碰内核的 ZeroMQ 协议，
所以宿主与容器之间只需要放通一个端口，别的什么都不用共享。

执行一格的过程是：往 WebSocket 发一条 ``execute_request``，然后按 ``msg_id``
过滤回来的消息，直到看见内核报告自己回到空闲状态为止。超时的话主动发一个中断请求，
否则内核会一直忙着，后面的格子全都排不上。
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

import httpx
import websockets

from deeptutor_ext.kernel import config
from deeptutor_ext.kernel.outputs import CellOutput, OutputCollector

logger = logging.getLogger(__name__)


class KernelUnavailable(RuntimeError):
    """内核容器没起来，或者口令不对。消息面向使用者，可以直接显示。"""


def _auth_headers() -> dict[str, str]:
    token = config.read_token()
    if not token:
        raise KernelUnavailable(
            "读不到内核容器的访问口令。先在 ~/DeepTutor-ext 执行 make kernel-start 启动容器。"
        )
    return {"Authorization": f"token {token}"}


def _ws_url(kernel_id: str) -> str:
    base = config.BASE_URL.replace("http://", "ws://").replace("https://", "wss://")
    return f"{base}/api/kernels/{kernel_id}/channels"


async def _request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    url = f"{config.BASE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method, url, headers=_auth_headers(), **kwargs)
    except httpx.HTTPError as exc:
        raise KernelUnavailable(
            f"连不上内核容器（{config.BASE_URL}）：{type(exc).__name__}。"
            "先确认它在运行：cd ~/DeepTutor-ext && make kernel-status"
        ) from exc
    if response.status_code >= 400:
        raise KernelUnavailable(
            f"内核容器返回 {response.status_code}。口令可能已过期，重启容器后会重新生成。"
        )
    return response


async def ping() -> bool:
    """容器是否可用。用于自检，不抛异常。"""
    try:
        await _request("GET", "/api/status")
        return True
    except KernelUnavailable:
        return False


async def start_kernel() -> str:
    response = await _request("POST", "/api/kernels", json={"name": "python3"})
    return str(response.json()["id"])


async def shutdown_kernel(kernel_id: str) -> None:
    try:
        await _request("DELETE", f"/api/kernels/{kernel_id}")
    except KernelUnavailable:
        logger.debug("关闭内核 %s 时容器已不可用，忽略", kernel_id)


async def interrupt_kernel(kernel_id: str) -> None:
    try:
        await _request("POST", f"/api/kernels/{kernel_id}/interrupt")
    except KernelUnavailable:
        logger.debug("中断内核 %s 时容器已不可用，忽略", kernel_id)


async def list_kernel_ids() -> list[str]:
    response = await _request("GET", "/api/kernels")
    return [str(item["id"]) for item in response.json()]


def _execute_message(code: str) -> tuple[str, str]:
    msg_id = uuid.uuid4().hex
    payload = {
        "header": {
            "msg_id": msg_id,
            "username": "deeptutor",
            "session": uuid.uuid4().hex,
            "msg_type": "execute_request",
            "version": "5.3",
        },
        "parent_header": {},
        "metadata": {},
        "channel": "shell",
        "content": {
            "code": code,
            "silent": False,
            "store_history": True,
            "user_expressions": {},
            "allow_stdin": False,
            # 出错也不要中止后续消息，我们要把回溯完整收下来。
            "stop_on_error": False,
        },
    }
    return msg_id, json.dumps(payload)


async def execute(
    kernel_id: str,
    code: str,
    *,
    artifact_dir: Path,
    url_prefix: str,
    timeout_s: int | None = None,
) -> CellOutput:
    """在 *kernel_id* 上执行一段代码，产生的图片写进 *artifact_dir*。"""
    timeout = min(timeout_s or config.DEFAULT_EXEC_TIMEOUT_S, config.MAX_EXEC_TIMEOUT_S)
    msg_id, message = _execute_message(code)
    collector = OutputCollector(artifact_dir, url_prefix)

    token = config.read_token()
    if not token:
        raise KernelUnavailable(
            "读不到内核容器的访问口令。先在 ~/DeepTutor-ext 执行 make kernel-start 启动容器。"
        )

    try:
        async with websockets.connect(
            f"{_ws_url(kernel_id)}?token={token}",
            open_timeout=15,
            close_timeout=5,
            max_size=64 * 1024 * 1024,  # 图片是随消息回来的，默认上限太小
        ) as socket:
            await socket.send(message)
            while True:
                try:
                    raw = await _recv_with_deadline(socket, timeout)
                except TimeoutError:
                    await interrupt_kernel(kernel_id)
                    return collector.finish("timeout")
                frame = json.loads(raw)
                if frame.get("parent_header", {}).get("msg_id") != msg_id:
                    continue
                msg_type = frame.get("msg_type", "")
                content = frame.get("content") or {}
                if msg_type == "status" and content.get("execution_state") == "idle":
                    break
                collector.feed(msg_type, content)
    except (OSError, websockets.WebSocketException) as exc:
        raise KernelUnavailable(
            f"与内核的连接中断：{type(exc).__name__}。可以重置内核后重试。"
        ) from exc

    return collector.finish()


async def _recv_with_deadline(socket, timeout_s: int):
    import asyncio

    return await asyncio.wait_for(socket.recv(), timeout=timeout_s)


__all__ = [
    "KernelUnavailable",
    "execute",
    "interrupt_kernel",
    "list_kernel_ids",
    "ping",
    "shutdown_kernel",
    "start_kernel",
]
