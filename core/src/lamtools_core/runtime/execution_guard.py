"""执行代际守卫：让"这次执行还作数吗"变成可查询、可强杀的运行时状态。

user:“优先解决 to_thread 无法强制终止执行的问题。引入受管执行进程与进程组，
确保取消、超时、租约失效后，旧执行不能继续修改工作区或产生未经授权的副作用”
+(不重写 Agent Loop：只在实际执行边界加两道闸——开工前查代际、开工后登记属主；
一旦代际失效，立刻吊销并在下一处执行边界拒绝继续，同时把已起的进程树整体杀掉)。

为什么需要它：`asyncio.to_thread` 里的同步代码无法被 `task.cancel()` 终止，
所以"取消"过去只是不再等结果，工具实际上还在跑。这里把"有没有权利继续"
做成一个显式对象，并在真正产生副作用的地方检查它。
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

import logging
import threading

_logger = logging.getLogger(__name__)

REVOKE_CANCELLED = "cancelled"
REVOKE_LEASE_LOST = "lease-lost"
REVOKE_TIMEOUT = "timeout"
REVOKE_STOPPED = "stopped"
REVOKE_OWNER_GONE = "owner-gone"


class ExecutionRevoked(RuntimeError):
    """这次执行已经失去继续产生副作用的权利。"""

    def __init__(self, reason: str, *, execution_id: str = "") -> None:
        self.reason = reason
        self.execution_id = execution_id
        detail = f" ({execution_id})" if execution_id else ""
        super().__init__(f"execution revoked: {reason}{detail}")


@dataclass
class ManagedProcess:
    process: Any
    job_handle: int | None
    label: str
    killed: bool = False


class ExecutionGuard:
    """一次执行（execution_id）的属主与吊销开关。"""

    def __init__(
        self,
        *,
        execution_id: str,
        job_id: str = "",
        fencing_token: int = 0,
        worker_id: str = "",
    ) -> None:
        self.execution_id = execution_id
        self.job_id = job_id
        self.fencing_token = fencing_token
        self.worker_id = worker_id
        self._revoked_reason = ""
        self._lock = threading.Lock()
        self._processes: dict[int, ManagedProcess] = {}
        self.spawn_count = 0
        self.spawn_rejected = 0
        self.killed_processes = 0

    # ------------------------------------------------------------------ 状态
    @property
    def revoked(self) -> bool:
        return bool(self._revoked_reason)

    @property
    def revoked_reason(self) -> str:
        return self._revoked_reason

    def revoke(self, reason: str) -> bool:
        with self._lock:
            if self._revoked_reason:
                return False
            self._revoked_reason = str(reason or REVOKE_CANCELLED)
        _logger.info(
            "execution %s revoked: %s", self.execution_id, self._revoked_reason
        )
        return True

    def ensure_spawn_allowed(self) -> None:
        if self._revoked_reason:
            with self._lock:
                self.spawn_rejected += 1
            raise ExecutionRevoked(self._revoked_reason, execution_id=self.execution_id)

    # ------------------------------------------------------------------ 进程属主
    def attach(self, process: Any, *, job_handle: int | None = None, label: str = "") -> None:
        with self._lock:
            self._processes[int(getattr(process, "pid", 0) or 0)] = ManagedProcess(
                process=process, job_handle=job_handle, label=label
            )
            self.spawn_count += 1
            revoked = self._revoked_reason
        if revoked:
            # 吊销与启动撞车：新起的进程必须立刻死，不能留下越权副作用。
            self._kill_one(process, job_handle)

    def detach(self, process: Any) -> None:
        with self._lock:
            self._processes.pop(int(getattr(process, "pid", 0) or 0), None)

    def terminate_all(self) -> int:
        """杀掉本次执行名下的全部进程树，返回处理的进程数。"""
        with self._lock:
            items = list(self._processes.values())
            self._processes.clear()
        killed = 0
        for item in items:
            if self._kill_one(item.process, item.job_handle):
                killed += 1
        with self._lock:
            self.killed_processes += killed
        return killed

    def _kill_one(self, process: Any, job_handle: int | None) -> bool:
        try:
            from lamtools_core.tool.command import terminate_process_tree

            terminate_process_tree(process, job_handle=job_handle)
            return True
        except Exception:  # noqa: BLE001 — 杀不掉也要留痕，不能假装成功
            _logger.warning(
                "failed to terminate process for execution %s", self.execution_id, exc_info=True
            )
            return False

    def live_processes(self) -> int:
        with self._lock:
            return len(self._processes)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "execution_id": self.execution_id,
                "job_id": self.job_id,
                "fencing_token": self.fencing_token,
                "revoked": bool(self._revoked_reason),
                "revoked_reason": self._revoked_reason,
                "live_processes": len(self._processes),
                "spawn_count": self.spawn_count,
                "spawn_rejected": self.spawn_rejected,
                "killed_processes": self.killed_processes,
            }


# ---------------------------------------------------------------------- 上下文
_CURRENT_GUARD: ContextVar[ExecutionGuard | None] = ContextVar(
    "lamtools_execution_guard", default=None
)


def bind_guard(guard: ExecutionGuard | None) -> Token:
    return _CURRENT_GUARD.set(guard)


def reset_guard(token: Token) -> None:
    _CURRENT_GUARD.reset(token)


def current_guard() -> ExecutionGuard | None:
    return _CURRENT_GUARD.get()


def execution_revoked_reason() -> str:
    guard = _CURRENT_GUARD.get()
    if guard is None:
        return ""
    return guard.revoked_reason if guard.revoked else ""


def ensure_spawn_allowed() -> None:
    """在任何真正产生副作用之前调用。"""
    guard = _CURRENT_GUARD.get()
    if guard is not None:
        guard.ensure_spawn_allowed()


def register_process(process: Any, *, job_handle: int | None = None, label: str = "") -> None:
    guard = _CURRENT_GUARD.get()
    if guard is not None:
        guard.attach(process, job_handle=job_handle, label=label)


def unregister_process(process: Any) -> None:
    guard = _CURRENT_GUARD.get()
    if guard is not None:
        guard.detach(process)


__all__ = [
    "ExecutionGuard",
    "ExecutionRevoked",
    "ManagedProcess",
    "REVOKE_CANCELLED",
    "REVOKE_LEASE_LOST",
    "REVOKE_OWNER_GONE",
    "REVOKE_STOPPED",
    "REVOKE_TIMEOUT",
    "bind_guard",
    "current_guard",
    "ensure_spawn_allowed",
    "execution_revoked_reason",
    "register_process",
    "reset_guard",
    "unregister_process",
]
