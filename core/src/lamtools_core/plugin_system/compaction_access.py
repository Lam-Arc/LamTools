"""user:“宿主能力补齐和接口完善与文档更新”+(手动压缩固定启动代与目录，等待真实宿主结果，不冒充 DSH 压缩引擎)。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


class CompactionError(RuntimeError):
    def __init__(self, code: str, session_id: str, message: str, *, may_have_changed: bool = False):
        self.code, self.session_id, self.may_have_changed = code, session_id, may_have_changed
        super().__init__(message)


@dataclass(frozen=True)
class CompactionResult:
    session_id: str
    status: Literal["compacted", "not_needed", "cancelled"]
    summary: str
    reason: str | None = None
    before_tokens: int | None = None
    after_tokens: int | None = None
    compacted_messages: int | None = None
    retained_messages: int | None = None


def compaction_result(session_id: str, payload: dict) -> CompactionResult:
    status = payload.get("status")
    if status == "failed":
        raise CompactionError("compaction/operation-failed", session_id, "Compaction backend reported failure", may_have_changed=True)
    fields = ("before_tokens", "after_tokens", "compacted_messages", "retained_messages")
    counts = {key: payload.get(key) for key in fields}
    summary = payload.get("summary", "")
    reason = payload.get("reason")
    if (not isinstance(status, str) or status not in {"compacted", "not_needed", "cancelled"}
            or payload.get("session_id", session_id) != session_id
            or not isinstance(summary, str) or (reason is not None and not isinstance(reason, str))
            or any(value is not None and (type(value) is not int or value < 0) for value in counts.values())
            or (status == "compacted" and (not summary.strip() or any(value is None for value in counts.values())))):
        raise CompactionError("compaction/invalid-response", session_id, "Host returned an invalid compaction result; inspect persisted state before retrying", may_have_changed=True)
    return CompactionResult(session_id, status, summary, reason, **counts)


class PluginCompactionAPI:
    def __init__(self, host, scope, work_root):
        self._host, self._scope = host, scope
        self._work_root = Path(work_root).resolve()

    async def compact_now(self, session_id: str, *, expected_revision: int) -> CompactionResult:
        self._scope.acquire()
        try:
            if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 256:
                raise CompactionError("compaction/invalid-session", "", "session_id must be a nonblank string of at most 256 characters")
            session_id = session_id.strip()
            if type(expected_revision) is not int or expected_revision < 0:
                raise CompactionError("compaction/invalid-revision", session_id, "Read session state first and supply its non-negative integer last_event_seq")
            task = asyncio.current_task()
            cancelling = task.cancelling()
            result = await self._host.compact_now(session_id, expected_revision=expected_revision, work_root=str(self._work_root))
            # user:“每一个地方 sunday 都有等价或者近似接口”+(桌面压缩会持久记录取消并返回 cancelled；插件调用者自己的取消仍必须传播)。
            if task.cancelling() > cancelling:
                raise asyncio.CancelledError
            return result
        finally:
            self._scope.release()


__all__ = ["CompactionError", "CompactionResult", "PluginCompactionAPI"]
