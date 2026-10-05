"""An approval waiting for the user must survive leaving the session and an app restart.

Reported behaviour: while a turn is parked on 审批/提问, switching away from the
session (or closing Sunday) and coming back leaves the request gone, unusable,
or unresponsive to clicks.

Both paths are exercised end to end against the real live operations: a real
turn (scripted model) parks on an approval, then

* ``thread/resume`` — what the client does when the user returns to the
  session — must still project the pending request, and ``approval.respond``
  must still resolve it;
* the startup sweep (``recover_stale_active_turns``, run by the app on boot)
  must leave the parked approval answerable instead of cancelling the turn and
  wiping the pending decision.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from lamtools_core.app import open_core_app_db
from lamtools_core.app.default_agent import (
    CoreAgentPaths,
    CoreAgentSpec,
    create_core_agent_operations,
)
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.live_operations import (
    CoreLiveContext,
    handle_approval_respond_operation,
    handle_thread_resume_operation,
    handle_turn_start_operation,
    recover_stale_active_turns,
)
from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent, LLMToolCall
from lamtools_core.runtime import RuntimeTaskRegistry

THREAD_ID = "thread-approval-survival"


class ScriptedWriteLLM:
    """First pass asks to write a file (approval-gated), the continuation answers."""

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("core agent operation should use streaming when available")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="call-write",
                        name="write_file",
                        arguments={"path": "approved.md", "content": "approved content\n"},
                    )
                ],
            )
            return
        yield LLMStreamEvent(kind="content_delta", content="Saved approved.md.")
        yield LLMStreamEvent(kind="done")


def _build_context(
    handle: Any,
    llm: ScriptedWriteLLM,
    *,
    work_root: Path,
    hub: CoreAppEventHub,
    registry: RuntimeTaskRegistry,
) -> CoreLiveContext:
    operations = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=work_root.parent / "data", work_root=work_root),
        model_provider=llm,
        db_session_factory=handle.session_factory,
        app_event_store=handle.event_store,
        thread_snapshot_store=handle.snapshot_store,
        app_event_hub=hub,
        runtime_state_store=handle.runtime_state_store,
        runtime_task_registry=registry,
    )
    return CoreLiveContext(
        session_factory=handle.session_factory,
        event_store=handle.event_store,
        snapshot_store=handle.snapshot_store,
        operations=operations,
        hub=hub,
        runtime_task_registry=registry,
        runtime_state_store=handle.runtime_state_store,
    )


async def _park_turn_on_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Start one real turn that stops at a tool approval, exactly like the app.

    The config root is isolated so the developer's own permission settings
    cannot turn this into an auto-approved run.
    """
    monkeypatch.setenv("LAMTOOLS_CORE_CONFIG_ROOT", str(tmp_path / "config-root"))
    handle = await open_core_app_db(tmp_path / "core.db")
    work_root = tmp_path / "work"
    work_root.mkdir()
    llm = ScriptedWriteLLM()
    hub = CoreAppEventHub()
    registry = RuntimeTaskRegistry()
    context = _build_context(handle, llm, work_root=work_root, hub=hub, registry=registry)

    outcome = await handle_turn_start_operation(
        request_id=1,
        params={
            "thread_id": THREAD_ID,
            "client_message_id": "client-approval-survival",
            "input": [{"type": "text", "text": "write a file"}],
            "permission_preset": "ask",
            "work_root": str(work_root),
        },
        context=context,
    )
    runtime_start = outcome.runtime_start
    assert isinstance(runtime_start, dict), outcome.response
    turn_id = str(runtime_start["turn_id"])
    task = registry.task(THREAD_ID, run_id=turn_id)
    if task is not None:
        await task

    state = await handle.runtime_state_store.get(THREAD_ID)
    assert state is not None
    assert str(state.status) == "waiting", state.status
    pending = state.metadata.get("pending_approval")
    assert isinstance(pending, dict), state.metadata
    request_id = str(pending.get("request_id") or "")
    assert request_id, pending
    assert await _snapshot_has_pending_request(handle) is True
    return handle, context, llm, registry, work_root, request_id


def _pending_request_items(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Snapshot items the UI recognises as a waiting decision.

    Mirrors the client projection: the item type may sit on the item itself or
    inside the nested payload a ``core/runItem`` event projected to.
    """
    found: list[dict[str, Any]] = []
    for item in (snapshot.get("core", {}).get("items") or {}).values():
        if not isinstance(item, dict):
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        item_type = str(item.get("type") or payload.get("type") or "")
        if item_type != "serverRequest" or str(item.get("status") or "") != "waiting":
            continue
        found.append(item)
    return found


async def _snapshot_has_pending_request(handle: Any) -> bool:
    async with handle.session_factory() as db:
        snapshot = await handle.persistence.load(db, THREAD_ID)
    return bool(_pending_request_items(snapshot))


async def _await_continuation(registry: RuntimeTaskRegistry) -> None:
    """The respond RPC returns as soon as the decision is durable; the approved
    tool run and the model continuation happen on a background task."""
    task = registry.task(THREAD_ID)
    if task is not None:
        await task
        return
    for _ in range(200):
        await asyncio.sleep(0.01)
        task = registry.task(THREAD_ID)
        if task is not None:
            await task
            return


@pytest.mark.asyncio
async def test_returning_to_the_session_keeps_the_approval_answerable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Switching away and back must not lose the pending request."""
    handle, context, llm, registry, work_root, request_id = await _park_turn_on_approval(
        tmp_path, monkeypatch
    )
    try:
        # What the client does when the user returns to the session.
        resumed = await handle_thread_resume_operation(
            request_id=2,
            params={"thread_id": THREAD_ID, "last_seen_seq": 0},
            context=context,
        )
        page = resumed.response["result"]["snapshot"]
        pending_items = _pending_request_items(page)
        assert pending_items, "the resumed snapshot no longer carries the pending request"
        assert any(str(item.get("payload", {}).get("request_id") or "") == request_id for item in pending_items)

        responded = await handle_approval_respond_operation(
            request_id=3,
            params={
                "thread_id": THREAD_ID,
                "request_id": request_id,
                "decision": "approve_once",
                "guidance": "",
            },
            context=context,
        )
        assert "result" in responded.response, responded.response
        await _await_continuation(registry)
        assert (work_root / "approved.md").read_text(encoding="utf-8") == "approved content\n"
        assert len(llm.requests) == 2
    finally:
        registry.clear()
        await handle.close()


@pytest.mark.asyncio
async def test_restart_keeps_the_approval_answerable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closing and reopening the app must not cancel a parked approval."""
    handle, context, llm, registry, work_root, request_id = await _park_turn_on_approval(
        tmp_path, monkeypatch
    )
    try:
        # App restart: a fresh live context over the same database, then the
        # startup sweep the app runs before it serves anything.
        registry.clear()
        restarted_registry = RuntimeTaskRegistry()
        restarted = _build_context(
            handle,
            llm,
            work_root=work_root,
            hub=CoreAppEventHub(),
            registry=restarted_registry,
        )
        await recover_stale_active_turns(context=restarted)

        assert await _snapshot_has_pending_request(handle) is True, (
            "the startup sweep dropped the parked approval from the thread"
        )
        state = await handle.runtime_state_store.get(THREAD_ID)
        assert state is not None
        assert str(state.status) == "waiting", state.status

        responded = await handle_approval_respond_operation(
            request_id=4,
            params={
                "thread_id": THREAD_ID,
                "request_id": request_id,
                "decision": "approve_once",
                "guidance": "",
            },
            context=restarted,
        )
        assert "result" in responded.response, responded.response
        await _await_continuation(restarted_registry)
        assert (work_root / "approved.md").read_text(encoding="utf-8") == "approved content\n"
    finally:
        restarted_registry.clear()
        await handle.close()


@pytest.mark.asyncio
async def test_restart_still_reaps_an_unanswerable_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wait nobody can answer must keep being reaped, not block the thread.

    ``executing`` means the decision is already durable and only the
    continuation was cut short; ``approval.respond`` refuses that state, so
    keeping the turn would leave the session with no way forward.
    """
    handle, context, llm, registry, work_root, request_id = await _park_turn_on_approval(
        tmp_path, monkeypatch
    )
    try:
        state = await handle.runtime_state_store.get(THREAD_ID)
        assert state is not None
        pending = dict(state.metadata["pending_approval"])
        pending["status"] = "executing"
        state.metadata["pending_approval"] = pending
        await handle.runtime_state_store.save(state)

        registry.clear()
        restarted_registry = RuntimeTaskRegistry()
        restarted = _build_context(
            handle,
            llm,
            work_root=work_root,
            hub=CoreAppEventHub(),
            registry=restarted_registry,
        )
        recovered = await recover_stale_active_turns(context=restarted)
        # One dangling item + the turn terminal: the turn itself must be reaped.
        assert recovered > 0, "the unanswerable wait was left blocking the thread"

        assert await _snapshot_has_pending_request(handle) is False
        reconciled = await handle.runtime_state_store.get(THREAD_ID)
        assert reconciled is not None
        assert str(reconciled.status) == "cancelled"
        assert "pending_approval" not in reconciled.metadata
    finally:
        restarted_registry.clear()
        await handle.close()
