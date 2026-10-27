"""user:“对比原版，能力应当只增不减”+(配置写入闸必须在执行层，不能仅靠章程)。"""
import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[2] / "plugins/bili-scroll/scripts/mcp_guard.py"


@pytest.fixture
def guard():
    spec = importlib.util.spec_from_file_location("bili_guard_acceptance", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_comment_requires_original_switches(guard):
    assert guard.write_denial("bili_reply", {}, {})
    assert guard.write_denial("bili_reply", {}, {"autoComment": True, "mentionName": "人", "dmMode": "only"})
    assert not guard.write_denial("bili_reply", {}, {"autoComment": True, "mentionName": "人", "dmMode": "both"})
    assert not guard.write_denial("bili_reply", {"force": True}, {})


def test_thread_replies_use_reply_switch_and_limit(guard):
    cfg = {"replyToComments": True, "replyPerRound": 1}
    assert not guard.write_denial("bili_reply", {"rpid": 123}, cfg)
    assert guard.write_denial("bili_reply", {"rpid": 123}, {**cfg, "replyPerRound": 0})


def test_private_message_only_goes_to_configured_owner(guard):
    cfg = {"dmMode": "only", "dmUid": 42}
    assert not guard.write_denial("bili_send_message", {"receiver_uid": 42}, cfg)
    assert guard.write_denial("bili_send_message", {"receiver_uid": 99}, cfg)
    assert guard.write_denial("bili_send_message", {"receiver_uid": 42}, {**cfg, "dmMode": "off", "dmWatch": False})


@pytest.mark.asyncio
async def test_denied_write_never_calls_vendor_and_force_is_not_forwarded(guard):
    calls = []
    async def original(bvid: str, text: str, rpid: int = 0):
        calls.append((bvid, text, rpid))
        return "sent"
    original.__name__ = "bili_reply"
    wrapped = guard.wrap_write(original, lambda: {})
    assert "blocked" in await wrapped("BV1234567890", "text")
    assert calls == []
    assert await wrapped("BV1234567890", "text", force=True) == "sent"
    assert len(calls) == 1
