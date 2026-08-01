"""与容器里的 Jupyter 服务通话：建内核、执行代码、收输出、关内核。

只依赖 Jupyter 服务对外的 HTTP 与 WebSocket 接口，不碰内核的 ZeroMQ 协议，
所以宿主与容器之间只需要放通一个端口，别的什么都不用共享。

关于连接：每个内核保持一条长连接，而不是每执行一格新建一条。一开始是每次新建的，
结果连着跑好几格时后面的格子会卡到超时——新连接刚建立、服务端还没把它接到内核的
消息通道上，我们发出去的执行请求已经出去了，内核回的消息广播时这条连接还没在收，
于是永远等不到「执行完毕」。改成长连接顺带解决了这个问题，还省掉了每格一次握手。
连接建立后先发一次内核信息查询并等回复，确认通道真的通了再开始干活。
"""

from __future__ import annotations

import asyncio
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

# kernel_id -> (连接, 串行锁)。同一个内核同一时刻只跑一格，锁保证消息不会交错。
_connections: dict[str, tuple[Any, asyncio.Lock]] = {}


class KernelUnavailable(RuntimeError):
    """内核容器没起来，或者口令不对。消息面向使用者，可以直接显示。"""


def _require_token() -> str:
    token = config.read_token()
    if not token:
        raise KernelUnavailable(
            "读不到内核容器的访问口令。先在 ~/DeepTutor-ext 执行 make kernel-start 启动容器。"
        )
    return token


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"token {_require_token()}"}


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
    await _close_connection(kernel_id)
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


# ── 连接管理 ────────────────────────────────────────────────────────────────


def _message(msg_type: str, content: dict[str, Any], channel: str = "shell") -> tuple[str, str]:
    msg_id = uuid.uuid4().hex
    payload = {
        "header": {
            "msg_id": msg_id,
            "username": "deeptutor",
            "session": uuid.uuid4().hex,
            "msg_type": msg_type,
            "version": "5.3",
        },
        "parent_header": {},
        "metadata": {},
        "channel": channel,
        "content": content,
    }
    return msg_id, json.dumps(payload)


async def _handshake(socket) -> None:
    """确认这条连接真的接到内核上了，再让调用方开始执行代码。

    超时给得比较宽：容器刚起来时第一个内核要冷启动，加载 IPython 那一套要十几秒，
    赶上机器忙还会更久。这里卡得太紧的表现是「点第一次运行报连不上，再点一次就好了」，
    对使用者来说非常费解。
    """
    msg_id, message = _message("kernel_info_request", {})
    await socket.send(message)
    deadline = 90
    while True:
        raw = await asyncio.wait_for(socket.recv(), timeout=deadline)
        frame = json.loads(raw)
        if frame.get("msg_type") == "kernel_info_reply" and (
            frame.get("parent_header", {}).get("msg_id") == msg_id
        ):
            return


def _is_open(socket) -> bool:
    """连接是否还活着。websockets 各版本暴露的字段不同，两种都认。"""
    state = getattr(socket, "state", None)
    if state is not None:
        return getattr(state, "name", "") == "OPEN"
    return not getattr(socket, "closed", True)


async def _get_connection(kernel_id: str):
    """取这个内核的长连接，没有或已断开就重建。返回（连接，串行锁）。"""
    entry = _connections.get(kernel_id)
    if entry is not None:
        socket, lock = entry
        if _is_open(socket):
            return socket, lock
        _connections.pop(kernel_id, None)

    token = _require_token()
    try:
        socket = await websockets.connect(
            f"{_ws_url(kernel_id)}?token={token}",
            open_timeout=90,   # 同上：冷启动慢，宁可等也别报连不上
            close_timeout=5,
            ping_interval=20,
            # 图片是随消息回来的，默认上限对一张普通图表都不够。
            max_size=64 * 1024 * 1024,
        )
        await _handshake(socket)
    except (OSError, asyncio.TimeoutError, websockets.WebSocketException) as exc:
        raise KernelUnavailable(
            f"连不上内核（{type(exc).__name__}）。可以点重置再试一次。"
        ) from exc

    lock = asyncio.Lock()
    _connections[kernel_id] = (socket, lock)
    return socket, lock


async def _close_connection(kernel_id: str) -> None:
    entry = _connections.pop(kernel_id, None)
    if entry is None:
        return
    socket, _ = entry
    try:
        await socket.close()
    except Exception:
        logger.debug("关闭内核 %s 的连接时出错，忽略", kernel_id, exc_info=True)


async def close_all() -> None:
    for kernel_id in list(_connections):
        await _close_connection(kernel_id)


# ── 执行 ────────────────────────────────────────────────────────────────────


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
    collector = OutputCollector(artifact_dir, url_prefix)
    socket, lock = await _get_connection(kernel_id)

    msg_id, message = _message(
        "execute_request",
        {
            "code": code,
            "silent": False,
            "store_history": True,
            "user_expressions": {},
            "allow_stdin": False,
            # 出错也不要中止后续消息，我们要把回溯完整收下来。
            "stop_on_error": False,
        },
    )

    async with lock:
        try:
            await socket.send(message)
            while True:
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=timeout)
                except asyncio.TimeoutError:
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
            await _close_connection(kernel_id)
            raise KernelUnavailable(
                f"与内核的连接中断：{type(exc).__name__}。可以点重置再试一次。"
            ) from exc

    return collector.finish()


__all__ = [
    "KernelUnavailable",
    "close_all",
    "execute",
    "interrupt_kernel",
    "list_kernel_ids",
    "ping",
    "shutdown_kernel",
    "start_kernel",
]
