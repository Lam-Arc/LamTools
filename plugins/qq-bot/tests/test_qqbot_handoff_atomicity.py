"""user:“该修修，相关插件也要修”+(QQ 引导共用宿主持久化入口，不能只写内存)。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from qqbot.session_target import SessionTargetClient


@pytest.mark.asyncio
@pytest.mark.parametrize("queued", [False, True])
async def test_running_target_uses_durable_live_steering(queued):
    live = SimpleNamespace(
        steer_turn=AsyncMock(return_value={"ok": True, "result": {"applied": not queued, "queued": queued}}),
        start_turn=AsyncMock(side_effect=AssertionError("running guidance cannot start another turn")),
    )
    registry = SimpleNamespace(inject_guidance=Mock(side_effect=AssertionError("must persist before injecting")))
    context = SimpleNamespace(service=lambda name: live if name == "live_turn_service" else None, runtime_task_registry=registry)
    client = SessionTargetClient(context)
    mode, error, payload = await client._send_operation(
        session_id="thread", text="guidance", client_message_id="qq-message", active_run_id="logical-turn",
    )
    assert not error
    assert mode == ("queued" if queued else "steered")
    live.steer_turn.assert_awaited_once_with(
        thread_id="thread", turn_id="logical-turn", text="guidance", client_message_id="qq-message",
    )
    registry.inject_guidance.assert_not_called()


@pytest.mark.asyncio
async def test_steering_storage_failure_is_reported_without_in_memory_fallback():
    live = SimpleNamespace(steer_turn=AsyncMock(side_effect=RuntimeError("storage unavailable")))
    registry = SimpleNamespace(inject_guidance=Mock(return_value=True))
    context = SimpleNamespace(service=lambda name: live if name == "live_turn_service" else None, runtime_task_registry=registry)
    mode, error, _ = await SessionTargetClient(context)._send_operation(
        session_id="thread", text="guidance", client_message_id="qq-message", active_run_id="logical-turn",
    )
    assert mode == "error"
    assert "storage unavailable" in error
    registry.inject_guidance.assert_not_called()
