from __future__ import annotations

from types import SimpleNamespace

from qqbot.protocol import ReplyTarget
from qqbot.runtime import QQBotRuntime


class _Api:
    def __init__(self) -> None:
        self.sent: list[tuple[ReplyTarget, str]] = []

    async def send_proactive_markdown(self, target: ReplyTarget, content: str):
        self.sent.append((target, content))
        return {"id": f"m{len(self.sent)}"}


def _runtime(api: _Api) -> QQBotRuntime:
    runtime = object.__new__(QQBotRuntime)
    runtime._api = api
    runtime.config = {"textChunkLimit": 4500}
    runtime._target_peers = {"session-1": {"c2c:u1": ReplyTarget("c2c", "u1")}}
    runtime._target_sent_items = {}
    runtime._target_sent_texts = {}
    return runtime


async def test_target_event_forwards_intermediate_text_and_dedupes() -> None:
    api = _Api()
    runtime = _runtime(api)
    message = SimpleNamespace(
        payload={
            "kind": "message",
            "turn_id": "turn-1",
            "item_id": "item-1",
            "status": "completed",
            "payload": {"type": "agentMessage", "content": "第一行\n第二行"},
        }
    )

    await runtime._forward_target_event("session-1", message)
    await runtime._forward_target_event("session-1", message)

    assert [content for _target, content in api.sent] == ["第一行", "第二行"]
    assert api.sent[0][0].scope == "c2c"
    assert api.sent[0][0].target_id == "u1"


async def test_target_terminal_does_not_repeat_already_sent_text() -> None:
    api = _Api()
    runtime = _runtime(api)
    await runtime._forward_target_event(
        "session-1",
        SimpleNamespace(
            payload={
                "kind": "message",
                "turn_id": "turn-1",
                "item_id": "item-1",
                "status": "completed",
                "payload": {"type": "agentMessage", "content": "回复"},
            }
        ),
    )
    await runtime._forward_target_event(
        "session-1",
        SimpleNamespace(
            payload={
                "kind": "status",
                "turn_id": "turn-1",
                "payload": {"status": "completed", "message": "回复"},
            }
        ),
    )

    assert [content for _target, content in api.sent] == ["回复"]
