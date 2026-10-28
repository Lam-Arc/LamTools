from __future__ import annotations

from types import SimpleNamespace

import pytest

from lamtools_core.app.live_plugin_service import LiveTurnService
from lamtools_core.app.live.turn_start import _resume_target_turn


def test_resume_target_uses_requested_paused_turn_even_without_seq() -> None:
    snapshot = {
        "turns": {
            "turn-completed": {
                "turn_id": "turn-completed",
                "status": "completed",
                "seq": 99,
            },
            "turn-paused": {
                "turn_id": "turn-paused",
                "status": "paused",
                "last_seq": 100,
            },
        }
    }

    latest, turn_id = _resume_target_turn(snapshot, "turn-paused")

    assert turn_id == "turn-paused"
    assert latest["status"] == "paused"


def test_resume_target_finds_paused_turn_in_core_projection() -> None:
    snapshot = {
        "turns": {
            "turn-completed": {
                "turn_id": "turn-completed",
                "status": "completed",
                "seq": 99,
            }
        },
        "core": {
            "turns": {
                "turn-paused": {
                    "turn_id": "turn-paused",
                    "status": "paused",
                    "last_seq": 100,
                }
            }
        },
    }

    latest, turn_id = _resume_target_turn(snapshot, "")

    assert turn_id == "turn-paused"
    assert latest["status"] == "paused"


@pytest.mark.asyncio
async def test_paused_session_is_resumed_with_the_new_message(monkeypatch) -> None:
    calls: list[dict] = []

    async def start(**kwargs):
        del kwargs
        return SimpleNamespace(
            response={
                "error": {
                    "message": "session has a paused turn",
                    "data": {"code": "SESSION_PAUSED", "paused_turn_id": "turn-paused"},
                }
            }
        )

    async def resume(**kwargs):
        calls.append(kwargs["params"])
        return SimpleNamespace(response={"result": {"turn_id": "turn-paused", "events": []}})

    service = LiveTurnService(lambda: object())
    # user:“该修修，相关插件也要修”+(服务现在通过共享宿主派发，单元测试在宿主边界模拟响应)。
    async def execute(name, params):
        handler = {"turn.start": start, "turn.resume": resume}[name]
        return None, await handler(params=params)

    monkeypatch.setattr(service, "_execute", execute)
    result = await service.start_turn(
        thread_id="session-1",
        text="继续一下",
        client_message_id="client-1",
    )

    assert result["ok"] is True
    assert result["turn_id"] == "turn-paused"
    assert calls == [
        {
            "thread_id": "session-1",
            "turn_id": "turn-paused",
            "client_message_id": "client-1",
            "input": [{"type": "text", "text": "继续一下"}],
        }
    ]


@pytest.mark.asyncio
async def test_normal_start_returns_runtime_turn_ids(monkeypatch) -> None:
    async def start(**kwargs):
        del kwargs
        return SimpleNamespace(
            response={
                "result": {
                    "runtime_start": {"turn_id": "turn-new", "run_id": "run-new"},
                    "events": [],
                }
            }
        )

    service = LiveTurnService(lambda: object())
    # user:“该修修，相关插件也要修”+(保持启动响应测试，同时让测试替身遵守共享宿主边界)。
    async def execute(name, params):
        assert name == "turn.start"
        return None, await start(params=params)

    monkeypatch.setattr(service, "_execute", execute)

    result = await service.start_turn(
        thread_id="session-1",
        text="hello",
        client_message_id="client-2",
    )

    assert result == {
        "ok": True,
        "turn_id": "turn-new",
        "run_id": "run-new",
        "result": {"runtime_start": {"turn_id": "turn-new", "run_id": "run-new"}, "events": []},
    }


@pytest.mark.asyncio
async def test_deliver_message_starts_when_idle(monkeypatch) -> None:
    service = LiveTurnService(lambda: object())

    async def start(**kwargs):
        return {"ok": True, "turn_id": "turn-new", "run_id": "run-new", "result": {}}

    monkeypatch.setattr(service, "start_turn", start)

    result = await service.deliver_message(
        thread_id="session-1",
        text="hello",
        client_message_id="client-1",
    )

    assert result["ok"] is True
    assert result["mode"] == "started"
    assert result["turn_id"] == "turn-new"


@pytest.mark.asyncio
async def test_deliver_message_steers_running_turn(monkeypatch) -> None:
    service = LiveTurnService(lambda: object())
    steered: list[dict] = []

    async def start(**kwargs):
        return {
            "ok": False,
            "error": "session has an active turn",
            "code": "SESSION_BUSY",
            "active_run_id": "turn-active",
            "data": {"code": "SESSION_BUSY", "active_run_id": "turn-active"},
        }

    async def steer(**kwargs):
        steered.append(kwargs)
        return {"ok": True, "result": {"applied": True, "events": []}}

    monkeypatch.setattr(service, "start_turn", start)
    monkeypatch.setattr(service, "steer_turn", steer)

    result = await service.deliver_message(
        thread_id="session-1",
        text="change it",
        client_message_id="client-2",
    )

    assert result["ok"] is True
    assert result["mode"] == "steered"
    assert result["turn_id"] == "turn-active"
    assert steered == [
        {
            "thread_id": "session-1",
            "turn_id": "turn-active",
            "text": "change it",
            "client_message_id": "client-2",
        }
    ]


@pytest.mark.asyncio
async def test_deliver_message_reports_queued_next_turn(monkeypatch) -> None:
    service = LiveTurnService(lambda: object())

    async def start(**kwargs):
        return {
            "ok": False,
            "error": "session has an active turn",
            "code": "SESSION_BUSY",
            "data": {"active_run_id": "turn-active"},
        }

    async def steer(**kwargs):
        return {"ok": True, "result": {"applied": False, "queued": True, "reason": "turn_ending"}}

    async def wait_new(thread_id: str, previous_turn_id: str) -> str:
        return "turn-next"

    monkeypatch.setattr(service, "start_turn", start)
    monkeypatch.setattr(service, "steer_turn", steer)
    monkeypatch.setattr(service, "_wait_for_new_turn", wait_new)

    result = await service.deliver_message(
        thread_id="session-1",
        text="after it ends",
        client_message_id="client-3",
    )

    assert result["ok"] is True
    assert result["mode"] == "queued"
    assert result["turn_id"] == "turn-next"


@pytest.mark.asyncio
async def test_deliver_message_steers_before_attempting_start(monkeypatch) -> None:
    service = LiveTurnService(lambda: object())
    steered: list[dict] = []

    async def active_turn(*, thread_id: str):
        return {"status": "running", "active_turn_id": "turn-active"}

    async def start(**kwargs):
        raise AssertionError("turn.start must not be called while a turn is active")

    async def steer(**kwargs):
        steered.append(kwargs)
        return {"ok": True, "result": {"applied": True, "events": []}}

    monkeypatch.setattr(service, "active_turn", active_turn)
    monkeypatch.setattr(service, "start_turn", start)
    monkeypatch.setattr(service, "steer_turn", steer)

    result = await service.deliver_message(
        thread_id="session-1",
        text="87642",
        client_message_id="client-1",
    )

    assert result["ok"] is True
    assert result["mode"] == "steered"
    assert result["turn_id"] == "turn-active"
    assert steered[0]["turn_id"] == "turn-active"
