"""把「一次学习会话」和「一个长驻内核」对应起来。

学生连着跑好几格代码，靠的是同一个内核里累积下来的变量，所以内核必须跨调用活着。
但内核不能无限增长：每个大约占 150 到 300 MB，加载数据集后更多。这里做三件事：

* 按会话标识找内核，没有就新建，并把工作目录切到该课 notebook 所在的位置——
  课程里的代码用的是 ``'../../data/xxx.csv'`` 这样的相对路径，工作目录不对就读不到数据；
* 内核数超过上限时，回收最久没用过的那个；
* 闲置超时的内核也回收。

产物（图表）落在 DeepTutor 已经放行给 ``/api/outputs`` 的目录下，前端因此不需要
任何额外的接口就能显示图片。选这个位置是有意的：宿主对哪些路径可以公开访问有一份
白名单，``workspace/chat/<任务>/code_runs/`` 正在其中，我们沿用它，不去改宿主。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import re
import time
from pathlib import Path

from deeptutor_ext.kernel import client, config
from deeptutor_ext.kernel.outputs import CellOutput

logger = logging.getLogger(__name__)

_SAFE_KEY = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass
class KernelSession:
    key: str
    kernel_id: str
    workdir: Path
    url_prefix: str
    cwd: str = ""
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    executions: int = 0


class SessionManager:
    """进程内唯一的一份会话到内核的映射。"""

    def __init__(self) -> None:
        self._sessions: dict[str, KernelSession] = {}
        self._lock = asyncio.Lock()

    # ── 位置计算 ────────────────────────────────────────────────────────

    @staticmethod
    def _safe_key(session_key: str) -> str:
        cleaned = _SAFE_KEY.sub("-", session_key.strip()) or "default"
        return cleaned[:64]

    def _workspace_for(self, session_key: str) -> tuple[Path, str]:
        """返回（产物目录，对应的公开访问前缀）。

        公开地址由实际路径相对数据根推导，不手工拼接——宿主的目录层级不是一眼能猜准的
        （``get_task_workspace("chat", …)`` 落在 ``workspace/chat/chat/`` 下，中间那层
        容易漏掉），拼错的后果是前端图裂而后端一切正常，很难归因。
        """
        from deeptutor.services.path_service import get_path_service

        path_service = get_path_service()
        task_id = f"notebook_{self._safe_key(session_key)}"
        workdir = path_service.get_task_workspace("chat", task_id) / "code_runs"
        relative = workdir.resolve().relative_to(path_service.get_public_outputs_root().resolve())
        url_prefix = "/api/outputs/" + relative.as_posix()
        return workdir, url_prefix

    # ── 会话生命周期 ────────────────────────────────────────────────────

    async def get(self, session_key: str, *, cwd: str = "") -> KernelSession:
        """取这个会话的内核，没有就新建。*cwd* 变了会把内核的工作目录切过去。"""
        async with self._lock:
            await self._reap_locked()
            session = self._sessions.get(session_key)
            if session is None:
                session = await self._create_locked(session_key)
            session.last_used = time.time()

        if cwd and cwd != session.cwd:
            await self._chdir(session, cwd)
        return session

    async def _create_locked(self, session_key: str) -> KernelSession:
        if len(self._sessions) >= config.MAX_LIVE_KERNELS:
            oldest = min(self._sessions.values(), key=lambda s: s.last_used)
            logger.info("内核数达到上限，回收最久未用的会话 %s", oldest.key)
            await self._drop_locked(oldest.key)

        kernel_id = await client.start_kernel()
        workdir, url_prefix = self._workspace_for(session_key)
        workdir.mkdir(parents=True, exist_ok=True)
        session = KernelSession(
            key=session_key,
            kernel_id=kernel_id,
            workdir=workdir,
            url_prefix=url_prefix,
        )
        self._sessions[session_key] = session
        logger.info("为会话 %s 启动了新内核", session_key)
        return session

    async def _drop_locked(self, session_key: str) -> None:
        session = self._sessions.pop(session_key, None)
        if session is not None:
            await client.shutdown_kernel(session.kernel_id)

    async def _reap_locked(self) -> None:
        deadline = time.time() - config.IDLE_TIMEOUT_S
        stale = [key for key, s in self._sessions.items() if s.last_used < deadline]
        for key in stale:
            logger.info("会话 %s 闲置超时，回收内核", key)
            await self._drop_locked(key)

    async def reset(self, session_key: str) -> None:
        """丢掉当前内核，下次执行时会起一个干净的。"""
        async with self._lock:
            await self._drop_locked(session_key)

    async def shutdown_all(self) -> None:
        async with self._lock:
            for key in list(self._sessions):
                await self._drop_locked(key)

    # ── 执行 ────────────────────────────────────────────────────────────

    async def _chdir(self, session: KernelSession, cwd: str) -> None:
        """把内核的工作目录切到 *cwd*。课程代码全用相对路径，这一步不能省。"""
        code = f"import os\nos.chdir({cwd!r})"
        result = await client.execute(
            session.kernel_id,
            code,
            artifact_dir=session.workdir,
            url_prefix=session.url_prefix,
            timeout_s=30,
        )
        if result.error:
            raise client.KernelUnavailable(
                f"切换工作目录失败：{result.error['ename']}: {result.error['evalue']}"
            )
        session.cwd = cwd

    async def execute(
        self,
        session_key: str,
        code: str,
        *,
        cwd: str = "",
        timeout_s: int | None = None,
    ) -> CellOutput:
        session = await self.get(session_key, cwd=cwd)
        result = await client.execute(
            session.kernel_id,
            code,
            artifact_dir=session.workdir,
            url_prefix=session.url_prefix,
            timeout_s=timeout_s,
        )
        session.last_used = time.time()
        session.executions += 1
        return result

    def describe(self) -> list[dict[str, object]]:
        """给自检与状态接口看的快照。"""
        now = time.time()
        return [
            {
                "session": s.key,
                "kernel_id": s.kernel_id,
                "cwd": s.cwd,
                "executions": s.executions,
                "idle_s": round(now - s.last_used, 1),
            }
            for s in self._sessions.values()
        ]


_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager


__all__ = ["KernelSession", "SessionManager", "get_session_manager"]
