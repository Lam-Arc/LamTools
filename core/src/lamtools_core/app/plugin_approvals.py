"""user:“继续，把 2 阶段都做完”+(审批请求与决定写入原会话事件库，迟到或失效回答不得转成批准)。"""
import asyncio
import math
import uuid

from lamtools_core.plugin_system.approval_access import (
    ANSWERER, ApprovalAccessError, ApprovalRequest, ApprovalResult, PluginApprovalAPI, _Answerer,
)
from .event_store import AppEventInput
from lamtools_core.plugin_system.sessions import SessionError


async def _settle(task):
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


class PluginApprovalService:
    def __init__(self, sessions, registry):
        self._sessions, self._registry = sessions, registry
        self._pending = 0

    def for_scope(self, scope):
        scope.check_open()
        return PluginApprovalAPI(self, scope)

    def _live(self, record):
        return record is not None and isinstance(record.value, _Answerer) and record.live and record.scope.accepting and self._registry.record(ANSWERER.name) is record

    async def request(self, scope, session_id, *, tool_name, call_id, reason, timeout):
        for value, maximum in [(session_id, 256), (tool_name, 128), (call_id, 256)]:
            if type(value) is not str or not value.strip() or len(value) > maximum:
                raise ApprovalAccessError("approval/invalid-request", "Session, tool and call identifiers must be bounded nonblank strings")
        if type(reason) is not str or len(reason) > 2000 or type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ApprovalAccessError("approval/invalid-request", "Reason is at most 2000 characters; timeout must be within (0, 30]")
        if self._pending >= 128:
            raise ApprovalAccessError("approval/busy", "Too many pending approval requests")
        self._pending += 1
        try:
            return await self._run(scope, session_id, tool_name=tool_name, call_id=call_id, reason=reason, timeout=timeout)
        except ApprovalAccessError:
            raise
        except SessionError as error:
            code = "closed" if error.code == "session/closed" else "not-found" if error.code == "session/not-found" else "host-changed"
            raise ApprovalAccessError("approval/" + code, "Approval session host is unavailable") from None
        except Exception:
            raise ApprovalAccessError("approval/audit-failed", "Approval protocol did not finish durably; no grant may be used") from None
        finally:
            self._pending -= 1

    async def _run(self, scope, session_id, *, tool_name, call_id, reason, timeout):
        caller = asyncio.current_task()
        cancelling = caller.cancelling()
        context = self._sessions._context()
        await self._sessions._snapshot(context, session_id)
        request_id = "approval_" + uuid.uuid4().hex
        async def asked(db):
            state = self._sessions._state(context, session_id, await context.persistence.load_metadata(db, session_id))
            if not state.running or not state.active_turn_id:
                raise ApprovalAccessError("approval/no-active-turn", "Approval requires an active persisted turn")
            event = await context.persistence.append(db, AppEventInput(thread_id=session_id, turn_id=state.active_turn_id,
                method="plugin/approvalAsked", payload={"request_id": request_id, "plugin": scope.owner,
                "tool_name": tool_name, "call_id": call_id, "reason": reason}))
            return event, state.active_turn_id
        cancelled = False
        transaction = asyncio.create_task(context.persistence.write(asked))
        try:
            envelope, turn_id = await asyncio.shield(transaction)
        except asyncio.CancelledError:
            cancelled = True
            envelope, turn_id = await _settle(transaction)
        request = ApprovalRequest(request_id, scope.owner, session_id, turn_id, tool_name, call_id, reason)
        record = self._registry.record(ANSWERER.name)
        task = asyncio.create_task(record.value.decide(request)) if not cancelled and self._live(record) else None
        outcome = "cancelled" if cancelled else "unavailable"
        try:
            if task is not None:
                deadline = asyncio.get_running_loop().time() + timeout
                try:
                    while True:
                        if not scope.accepting or not self._live(record) or self._sessions._closed.is_set():
                            outcome = "cancelled"
                            break
                        if task.done():
                            outcome = task.result()
                            break
                        if asyncio.get_running_loop().time() >= deadline:
                            outcome = "cancelled"
                            break
                        await asyncio.wait({task}, timeout=min(0.05, max(0, deadline - asyncio.get_running_loop().time())))
                except asyncio.CancelledError:
                    outcome, cancelled = "cancelled", True
                except Exception:
                    outcome = "unavailable"
            if task is not None and not task.done():
                task.cancel()
            async def decided(db):
                actual = outcome
                state = self._sessions._state(context, session_id, await context.persistence.load_metadata(db, session_id))
                if actual == "allowed-once" and (not scope.accepting or not self._live(record) or not state.running or state.active_turn_id != turn_id):
                    actual = "cancelled"
                event = await context.persistence.append(db, AppEventInput(thread_id=session_id, turn_id=turn_id,
                    method="plugin/approvalDecided", payload={"request_id": request_id, "outcome": actual, "plugin": scope.owner}))
                return event, actual
            try:
                committed, outcome = await _settle(asyncio.create_task(context.persistence.write(decided)))
            except Exception:
                raise ApprovalAccessError("approval/audit-failed", "Decision audit did not commit; no grant may be used") from None
            if cancelled or caller.cancelling() > cancelling:
                raise asyncio.CancelledError
            return ApprovalResult(request_id, outcome, envelope.seq, committed.seq)
        finally:
            if task is not None:
                if not task.done():
                    task.cancel()
                try:
                    await _settle(task)
                except (asyncio.CancelledError, Exception):
                    pass
