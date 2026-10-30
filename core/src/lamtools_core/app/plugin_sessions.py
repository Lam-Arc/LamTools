"""Session facade over the desktop host's existing control and persistence.

user:“宿主能力补齐和接口完善与文档更新”+(插件与桌面共用接收、引导、排队、取消及持久状态，不新建另一套会话运行时)。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import uuid
from collections.abc import Callable, AsyncIterator
from typing import Any, Literal

from lamtools_core.async_tasks import finish_on_cancel
from lamtools_core.plugin_system.sessions import (
    CancelReceipt, MessageReceipt, QueueChange, SessionError, SessionEventPage, SessionState, SessionWaitResult,
)
from .queue_state import ACTIVE_TURN_STATUSES, effective_thread_status, latest_active_turn_id

RECEIPT_METHODS = {"queue/itemAccepted", "turn/steered"}


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"{name} must be a non-blank string of at most 256 characters")
    return value.strip()


def _text(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("text must contain non-whitespace text")
    return value


class PluginSessionService:
    def __init__(self, context_factory: Callable[[], Any], *, poll_interval: float = 0.25) -> None:
        if not math.isfinite(poll_interval) or not 0 < poll_interval <= 1:
            raise ValueError("poll_interval must be finite and in (0, 1]")
        self._factory = context_factory
        self._poll_interval = poll_interval
        self._closed = asyncio.Event()
        self._persistence = context_factory().persistence

    def shutdown(self) -> None:
        """Owned by application shutdown; wakes readers before closing SQLite."""
        self._closed.set()

    def _context(self):
        if self._closed.is_set():
            raise SessionError("session/closed", "", "host session service is closed")
        context = self._factory()
        if context.persistence is not self._persistence:
            raise SessionError("session/host-changed", "", "host persistence changed; obtain the new service")
        return context

    async def _snapshot(self, context, session_id: str) -> dict:
        store = getattr(context.host, "session_store", None)
        exists = await store.get(session_id) is not None if store is not None else False
        if store is not None and not exists:
            raise SessionError("session/not-found", session_id, "session is unknown or unavailable")
        async with context.session_factory() as db:
            snapshot = await context.persistence.load_metadata(db, session_id)
        if not exists and not snapshot.get("snapshot_seq"):
            raise SessionError("session/not-found", session_id, "session does not exist")
        return snapshot

    @staticmethod
    def _state(context, session_id: str, snapshot: dict) -> SessionState:
        status = effective_thread_status(snapshot)
        registry = context.host.runtime_task_registry
        run_id = registry.active_run_id(session_id) or None
        active = latest_active_turn_id(snapshot)
        turns = dict(snapshot.get("turns") or {})
        core = snapshot.get("core") or {}
        turns.update(core.get("turns") or {})
        paused = [(int(turn.get("last_seq") or turn.get("seq") or 0), str(turn.get("turn_id") or key))
                  for key, turn in turns.items() if isinstance(turn, dict) and turn.get("status") == "paused"]
        queued = [item for item in snapshot.get("queue") or [] if isinstance(item, dict) and item.get("status") == "queued"]
        queued.sort(key=lambda item: (int(item.get("seq") or 0), str(item.get("queue_item_id") or "")))
        return SessionState(session_id, int(snapshot.get("snapshot_seq") or 0), status,
                            status in ACTIVE_TURN_STATUSES or bool(run_id), active, run_id,
                            max(paused)[1] if paused and status == "paused" else None, len(queued),
                            tuple(str(item["queue_item_id"]) for item in queued))

    async def state(self, session_id: str) -> SessionState:
        session_id = _identifier(session_id, "session_id")
        context = self._context()
        return self._state(context, session_id, await self._snapshot(context, session_id))

    async def _execute(self, context, session_id: str, name: str, params: dict) -> dict:
        outcome = await context.host.execute(name, request_id=None, params=params, context=context)
        response = getattr(outcome, "response", None)
        if not isinstance(response, dict):
            raise SessionError("session/invalid-response", session_id, "live host returned no response object")
        error = response.get("error")
        if "error" in response and not isinstance(error, dict):
            raise SessionError("session/invalid-response", session_id, "live host returned an invalid error object")
        if isinstance(error, dict):
            data = error.get("data") if isinstance(error.get("data"), dict) else {}
            raise SessionError(str(data.get("code") or "session/operation-failed"), session_id,
                               str(error.get("message") or "live operation failed"), details={"rpc_code": error.get("code"), **data})
        result = response.get("result")
        if not isinstance(result, dict):
            raise SessionError("session/invalid-response", session_id, "live host returned no result object")
        # These controls publish their own committed events. Re-publishing
        # outcome.publish_events would duplicate desktop notifications.
        return result

    async def create(self, *, session_id: str | None = None, title: str = "") -> SessionState:
        session_id = _identifier(session_id if session_id is not None else "session_" + uuid.uuid4().hex, "session_id")
        if not isinstance(title, str):
            raise TypeError("title must be a string")
        context = self._context()
        async def create_once():
            try:
                await self._snapshot(context, session_id)
            except SessionError as error:
                if error.code != "session/not-found":
                    raise
            else:
                raise SessionError("session/already-exists", session_id, "create cannot reset an existing session")
            await self._execute(context, session_id, "thread.start", {"thread_id": session_id, "title": title, "expected_revision": 0, "require_new": True})
            return self._state(context, session_id, await self._snapshot(context, session_id))
        return await finish_on_cancel(context.host.session_actors.run("plugin-session:" + session_id, create_once), name="plugin-session-create:" + session_id)

    async def _receipt(self, context, session_id: str, message_id: str):
        async with context.session_factory() as db:
            return await context.persistence.find_client_event(db, thread_id=session_id, client_message_id=message_id, methods=RECEIPT_METHODS)

    async def _wake(self, context, session_id: str, work_root: str) -> str | None:
        from .live.queue_dispatch import _dispatch_next_queue_item
        async def dispatch():
            state = self._state(context, session_id, await self._snapshot(context, session_id))
            if state.running or state.status not in {"idle", "completed"} or not state.queued_count:
                return
            if not context.operations.has("turn.start"):
                raise SessionError("session/runtime-unavailable", session_id, "queued input is durable but no runtime can start it")
            await _dispatch_next_queue_item(context=context, thread_id=session_id, work_root=work_root, completed_turn_id="")
        try:
            await context.host.session_actors.run("session:" + session_id, dispatch)
        except Exception as error:
            # Acceptance was already committed. A wake failure must not turn
            # a durable receipt into a false rejection and trigger duplicate input.
            return str(error)
        return None

    async def prompt(self, session_id: str, *, request_id: str, text: str, mode: Literal["queue", "steer"] = "queue", work_root: str = "") -> MessageReceipt:
        session_id, request_id = _identifier(session_id, "session_id"), _identifier(request_id, "request_id")
        text = _text(text)
        if mode not in {"queue", "steer"}:
            raise ValueError("mode must be queue or steer")
        if not isinstance(work_root, str):
            raise TypeError("work_root must be a string")
        context = self._context()
        digest = hashlib.sha256(json.dumps([session_id, request_id], ensure_ascii=False).encode("utf-8")).hexdigest()
        message_id = "plugin-session:" + digest
        async def accept():
            snapshot = await self._snapshot(context, session_id)
            receipt = await self._receipt(context, session_id, message_id)
            if receipt is None:
                params = {"thread_id": session_id, "client_message_id": message_id,
                          "input": [{"type": "text", "text": text}], "work_root": work_root, "include_snapshot": False}
                active = latest_active_turn_id(snapshot)
                if mode == "steer" and active:
                    result = await self._execute(context, session_id, "turn.steer", {**params, "turn_id": active})
                    # A live owner can change between the passive read and
                    # steering. Preserve the input as a next-turn message
                    # only when the shared handler explicitly refused it.
                    if result.get("applied") is False and not result.get("queued") and result.get("reason") in {"active_turn_mismatch", "run_not_active"}:
                        await self._execute(context, session_id, "queue.create", {**params, "queue_item_id": "queue:" + digest, "mode": "next_turn"})
                else:
                    await self._execute(context, session_id, "queue.create", {**params, "queue_item_id": "queue:" + digest, "mode": "next_turn"})
                receipt = await self._receipt(context, session_id, message_id)
            if receipt is None:
                raise SessionError("session/not-accepted", session_id, "live control produced no durable acceptance receipt")
            queued = receipt.method == "queue/itemAccepted"
            wake_error = await self._wake(context, session_id, work_root) if queued else None
            return MessageReceipt(session_id, request_id, message_id, "queued" if queued else "steered", receipt.seq,
                                  receipt.item_id if queued else None, receipt.turn_id or None, wake_error)
        return await finish_on_cancel(context.host.session_actors.run("plugin-session:" + session_id, accept), name="plugin-session-prompt:" + session_id)

    async def update_queue(self, session_id: str, queue_item_id: str, *, text: str | None = None, delete: bool = False) -> QueueChange:
        session_id, queue_item_id = _identifier(session_id, "session_id"), _identifier(queue_item_id, "queue_item_id")
        if type(delete) is not bool or (delete and text is not None):
            raise ValueError("choose either text replacement or deletion")
        if not delete:
            text = _text(text)
        context = self._context()
        await self._snapshot(context, session_id)
        result = await self._execute(context, session_id, "queue.delete" if delete else "queue.update",
                                     {"thread_id": session_id, "queue_item_id": queue_item_id, "include_snapshot": False,
                                      **({} if delete else {"text": text})})
        return QueueChange(session_id, queue_item_id, result.get("applied") is not False, result.get("reason"))

    async def cancel(self, session_id: str, *, turn_id: str | None = None) -> CancelReceipt:
        session_id = _identifier(session_id, "session_id")
        if turn_id is not None:
            turn_id = _identifier(turn_id, "turn_id")
        context = self._context()
        state = self._state(context, session_id, await self._snapshot(context, session_id))
        target = turn_id or state.active_turn_id or state.paused_turn_id
        if target is None and state.active_run_id:
            target = context.host.runtime_task_registry.active_turn_id(session_id) or state.active_run_id
        if target is None:
            return CancelReceipt(session_id, None, "idle", completed=True)
        result = await self._execute(context, session_id, "turn.cancel", {"thread_id": session_id, "turn_id": target})
        status = str(result.get("status") or "cancelling")
        return CancelReceipt(session_id, target, status, completed=status == "idle")

    async def events(self, session_id: str, *, after_seq: int = 0, limit: int = 100, max_bytes: int = 1024 * 1024) -> SessionEventPage:
        session_id = _identifier(session_id, "session_id")
        if type(after_seq) is not int or after_seq < 0:
            raise ValueError("after_seq must be a non-negative integer")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("limit must be in [1, 500]")
        if type(max_bytes) is not int or not 512 <= max_bytes <= 4 * 1024 * 1024:
            raise ValueError("max_bytes must be in [512, 4194304]")
        context = self._context()
        snapshot = await self._snapshot(context, session_id)
        revision = int(snapshot.get("snapshot_seq") or 0)
        if after_seq > revision:
            raise SessionError("session/invalid-cursor", session_id, "cursor is ahead of durable history")
        async with context.session_factory() as db:
            records = await context.persistence.list_after(db, thread_id=session_id, after_seq=after_seq, limit=limit + 1)
        cursor, size, items = after_seq, 0, []
        for record in records[:limit]:
            if record.seq != cursor + 1:
                raise SessionError("session/cursor-expired", session_id, "durable history has a gap; reload history")
            item = record.to_dict()
            item_size = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
            if size + item_size > max_bytes:
                if not items:
                    raise SessionError("session/event-too-large", session_id, "one record exceeds the requested byte budget")
                break
            items.append(item)
            size += item_size
            cursor = record.seq
        if not records and after_seq < revision:
            raise SessionError("session/cursor-expired", session_id, "durable records are no longer available")
        return SessionEventPage(session_id, tuple(items), cursor, len(records) > len(items) or cursor < revision)

    async def _pause(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._closed.wait(), timeout=seconds)
        except TimeoutError:
            pass

    async def follow(self, session_id: str, *, after_seq: int = 0, limit: int = 100, max_bytes: int = 1024 * 1024) -> AsyncIterator[dict[str, Any]]:
        cursor = after_seq
        while not self._closed.is_set():
            page = await self.events(session_id, after_seq=cursor, limit=limit, max_bytes=max_bytes)
            for item in page.events:
                if self._closed.is_set():
                    return
                cursor = item["seq"]
                yield item
            if not page.has_more:
                await self._pause(self._poll_interval)

    async def wait(self, session_id: str, *, timeout: float = 30) -> SessionWaitResult:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 <= timeout <= 60:
            raise ValueError("timeout must be finite and in [0, 60] seconds")
        deadline = asyncio.get_running_loop().time() + timeout
        state = await self.state(session_id)
        while True:
            if self._closed.is_set():
                return SessionWaitResult("closed", state)
            if state.status in {"paused", "waiting"} or state.queued_count and state.status in {"failed", "cancelled"}:
                return SessionWaitResult("blocked", state)
            if not state.running and not state.queued_count:
                return SessionWaitResult("idle", state)
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return SessionWaitResult("timeout", state)
            await self._pause(min(remaining, self._poll_interval))
            if not self._closed.is_set():
                state = await self.state(session_id)


def install_plugin_session_services(context, context_factory: Callable[[], Any]) -> PluginSessionService:
    """Publish once the desktop live host and database are ready."""
    from .live_plugin_service import LiveTurnService
    service = PluginSessionService(context_factory)
    context.set_service("live_turn_service", LiveTurnService(context_factory))
    context.set_service("sessions", service)
    # user:“宿主能力补齐和接口完善与文档更新”+(手动压缩使用同一桌面会话宿主，不覆盖旧 agent preset 的 compaction 服务)。
    from .plugin_compaction import PluginCompactionService
    context.set_service("compaction_control", PluginCompactionService(service))
    # user:“宿主能力补齐和接口完善与文档更新”+(权限读取使用同一桌面会话存储，与原权限判断器分开登记)。
    from .plugin_permissions import PluginPermissionService
    context.set_service("permission_access", PluginPermissionService(service))
    from .plugin_session_query import PluginSessionQueryService
    context.set_service("session_query", PluginSessionQueryService(service))
    from .plugin_approvals import PluginApprovalService
    context.set_service("approval_access", PluginApprovalService(service, context._service_registry))
    # user:“继续，把 2 阶段都做完”+(目录共用原会话存储；另存执行目录，不动原项目身份)。
    from .plugin_working_directory import PluginWorkingDirectoryService
    context.set_service("working_directory", PluginWorkingDirectoryService(service))
    # user:“给我把 2 阶段做完，前端除外”+(附件、标题和投影复用已就绪的桌面数据库)。
    from .plugin_session_data import PluginSessionDataService
    context.set_service("session_data", PluginSessionDataService(service, context.data_dir))
    return service


__all__ = ["PluginSessionService", "install_plugin_session_services"]
