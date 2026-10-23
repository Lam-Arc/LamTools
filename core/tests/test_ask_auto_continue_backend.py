"""Backend-owned question expiry.

The renderer used to own this timer, so CLI, mobile, background sessions,
switched-away threads and restarts never auto-continued.  These tests pin the
backend rules: only questions expire, never approvals, never paused turns, and
only after the durable ``asked_at_ms`` window.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from lamtools_core.app import memory_resume_supervisor as supervisor_module
from lamtools_core.app.memory_resume_supervisor import MemoryResumeSupervisor
from lamtools_core.app.memory_resume_supervisor import _due_question_request_id


def _state(*, status="waiting", loop_state="wait", kind="question", pending_status="waiting", asked_at=1_000):
    return SimpleNamespace(
        session_id="thread",
        status=status,
        loop_state=loop_state,
        metadata={
            "pending_approval": {
                "request_id": "request-1",
                "status": pending_status,
                "asked_at_ms": asked_at,
                "tool_call": {"id": "call-1", "name": kind},
            },
            "pending_waiting_request": {"request_kind": "question" if kind == "question" else "permission"},
        },
    )


def test_due_question_is_recognised_after_the_window():
    assert _due_question_request_id(_state(), now_ms=1_000 + 300_001, timeout_ms=300_000) == "request-1"


def test_fresh_question_is_not_due():
    assert _due_question_request_id(_state(), now_ms=1_000 + 10_000, timeout_ms=300_000) == ""


def test_approval_never_expires():
    assert _due_question_request_id(_state(kind="run_command"), now_ms=9_000_000, timeout_ms=300_000) == ""


def test_paused_and_non_waiting_states_are_skipped():
    assert _due_question_request_id(_state(status="paused"), now_ms=9_000_000, timeout_ms=300_000) == ""
    assert _due_question_request_id(_state(loop_state="continue"), now_ms=9_000_000, timeout_ms=300_000) == ""
    assert _due_question_request_id(_state(pending_status="executing"), now_ms=9_000_000, timeout_ms=300_000) == ""


def test_missing_timestamp_never_expires():
    assert _due_question_request_id(_state(asked_at=0), now_ms=9_000_000, timeout_ms=300_000) == ""


@pytest.mark.asyncio
async def test_scheduler_calls_the_live_responder_once(monkeypatch):
    calls: list[dict] = []
    answered = asyncio.Event()

    async def fake_respond(**kwargs):
        calls.append(kwargs)
        answered.set()
        return SimpleNamespace(response={"status": "accepted"})

    import lamtools_core.app.live_operations as live_operations

    monkeypatch.setattr(live_operations, "handle_approval_respond_operation", fake_respond)
    monkeypatch.setattr(supervisor_module, "ask_auto_continue_enabled", lambda: True)

    class Store:
        async def list_pending_approvals(self):
            state = _state()
            state.status = "waiting"
            return [state]

    class Registry:
        def is_running(self, thread_id):
            return False

    context = SimpleNamespace(runtime_state_store=Store(), runtime_task_registry=Registry())
    supervisor = MemoryResumeSupervisor(context=context, poll_seconds=1)

    assert await supervisor._auto_continue_questions() == 1
    await asyncio.wait_for(answered.wait(), timeout=2)
    await asyncio.sleep(0)

    assert len(calls) == 1
    params = calls[0]["params"]
    assert params["request_id"] == "request-1"
    assert params["decision"] == "skip"
    assert "跳过" in params["guidance"]
    # A second pass while the same request is already resolved does not call
    # again (the fake store still reports it; the in-flight guard is per id and
    # the task has completed, so the durable claim is what protects production).
    assert calls[0]["context"] is context
