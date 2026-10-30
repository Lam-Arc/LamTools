"""user:“每一个地方 sunday 都有等价或者近似接口”+(插件手动压缩复用桌面命令的运行认领、控制记录和取消流程)。"""
from __future__ import annotations

from lamtools_core.plugin_system.compaction_access import CompactionError, PluginCompactionAPI, compaction_result
from lamtools_core.plugin_system.sessions import SessionError


class PluginCompactionService:
    def __init__(self, sessions):
        self._sessions = sessions

    def for_scope(self, scope, work_root):
        scope.check_open()
        return PluginCompactionAPI(self, scope, work_root)

    async def compact_now(self, session_id, *, expected_revision, work_root):
        dispatched = False
        try:
            context = self._sessions._context()
            snapshot = await self._sessions._snapshot(context, session_id)
            state = self._sessions._state(context, session_id, snapshot)
            if state.running or state.status not in {"idle", "completed"}:
                raise CompactionError("compaction/busy", session_id, "Compaction requires an idle or completed session")
            if state.last_event_seq != expected_revision:
                raise CompactionError("compaction/conflict", session_id, "Session changed; refresh state and retry explicitly")
            dispatched = True
            result = await self._sessions._execute(context, session_id, "command.execute", {
                "thread_id": session_id, "command": "compact", "work_root": work_root,
                "expected_revision": expected_revision, "include_snapshot": False,
            })
            payload = result.get("result")
            if not isinstance(payload, dict):
                raise CompactionError("compaction/invalid-response", session_id, "Host returned no compaction result; inspect persisted state before retrying", may_have_changed=True)
            return compaction_result(session_id, payload)
        except SessionError as error:
            code = {"SESSION_BUSY": "busy", "REVISION_CONFLICT": "conflict",
                    "session/not-found": "not-found", "session/closed": "closed",
                    "session/host-changed": "host-changed", "session/invalid-response": "invalid-response"}.get(error.code, "operation-failed")
            raise CompactionError("compaction/" + code, session_id, str(error),
                                  may_have_changed=dispatched and code not in {"busy", "conflict"}) from None
        except CompactionError:
            raise
        except Exception:
            raise CompactionError("compaction/operation-failed", session_id,
                                  "Compaction host failed; inspect persisted state before retrying",
                                  may_have_changed=dispatched) from None


__all__ = ["PluginCompactionService"]
