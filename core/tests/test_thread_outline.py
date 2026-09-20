from __future__ import annotations

import asyncio
from types import SimpleNamespace

from lamtools_core.app.live_operations import handle_thread_outline_operation
from lamtools_core.app.thread_outline import (
    MAX_THREAD_OUTLINE_CHAR_LIMIT,
    build_thread_outline,
    normalize_thread_outline_char_limit,
)
from lamtools_core.cli import build_parser, cmd_session_outline


def _snapshot() -> dict:
    return {
        "thread_id": "thread-outline",
        "items": {
            "u1": {
                "item_id": "u1",
                "turn_id": "turn-1",
                "type": "userMessage",
                "seq": 1,
                "content": [{"type": "text", "text": "first prompt"}],
            },
            "u-steered": {
                "item_id": "u-steered",
                "turn_id": "turn-1",
                "type": "userMessage",
                "status": "completed",
                "seq": 4,
                "content": [{"type": "text", "text": "steered prompt"}],
            },
            "u-nested": {
                "item_id": "u-nested",
                "turn_id": "turn-1",
                "parent_item_id": "sub-agent",
                "type": "userMessage",
                "seq": 5,
                "content": [{"type": "text", "text": "internal"}],
            },
            "u2": {
                "item_id": "u2",
                "turn_id": "turn-2",
                "type": "userMessage",
                "seq": 7,
                "content": [{"type": "text", "text": "second prompt"}],
            },
        },
        "item_order": ["u1", "u-steered", "u-nested", "u2"],
        "turns": {
            "turn-1": {
                "turn_id": "turn-1",
                "created_at": "2026-09-19T10:00:00+08:00",
                "items": ["u1", "u-steered"],
            },
            "turn-2": {"turn_id": "turn-2", "items": ["u2"]},
        },
        "core": {
            "items": {
                "a1": {
                    "item_id": "a1",
                    "turn_id": "turn-1",
                    "seq": 2,
                    "payload": {"type": "agentMessage", "content": "first answer"},
                },
                "protocol": {
                    "item_id": "protocol",
                    "turn_id": "turn-1",
                    "seq": 3,
                    "payload": {"type": "agentMessage", "content": '{"event":"delta","payload":{}}'},
                },
                "nested-answer": {
                    "item_id": "nested-answer",
                    "turn_id": "turn-1",
                    "parent_item_id": "sub-agent",
                    "seq": 6,
                    "payload": {"type": "agentMessage", "content": "internal answer"},
                },
                "a2": {
                    "item_id": "a2",
                    "turn_id": "turn-2",
                    "seq": 8,
                    "payload": {"type": "agentMessage", "content": "second answer"},
                },
            },
            "item_order": ["a1", "protocol", "nested-answer", "a2"],
        },
    }


def test_build_thread_outline_uses_global_order_and_hides_internal_content() -> None:
    result = build_thread_outline(_snapshot())

    assert result == {
        "thread": {"id": "thread-outline"},
        "items": [
            {
                "message_id": "u1",
                "turn_id": "turn-1",
                "seq": 1,
                "timestamp": "2026-09-19T10:00:00+08:00",
                "prompt": "first prompt",
                "response_excerpt": "first answer",
            },
            {
                "message_id": "u-steered",
                "turn_id": "turn-1",
                "seq": 4,
                "timestamp": "2026-09-19T10:00:00+08:00",
                "prompt": "steered prompt",
                "response_excerpt": "",
            },
            {
                "message_id": "u2",
                "turn_id": "turn-2",
                "seq": 7,
                "timestamp": None,
                "prompt": "second prompt",
                "response_excerpt": "second answer",
            },
        ],
    }


def test_thread_outline_limits_unicode_text_and_uses_snapshot_timestamp_only() -> None:
    snapshot = _snapshot()
    snapshot["items"]["u1"]["content"] = [{"type": "text", "text": "😀" * 1000}]
    result = build_thread_outline(snapshot, char_limit=1)
    assert len(result["items"][0]["prompt"]) == 1
    assert result["items"][2]["timestamp"] is None
    assert normalize_thread_outline_char_limit(10_000) == MAX_THREAD_OUTLINE_CHAR_LIMIT


def test_thread_outline_does_not_synthesize_unlocatable_queue_or_steer_rows() -> None:
    snapshot = {
        "thread_id": "thread-events",
        "items": {},
        "queue": [{
            "queue_item_id": "queue-1",
            "status": "queued",
            "input": [{"type": "text", "text": "later"}],
        }],
        "core": {"items": {}, "item_order": []},
    }
    assert build_thread_outline(snapshot)["items"] == []


class _AsyncSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


def test_thread_outline_operation_validates_thread_and_returns_contract() -> None:
    snapshot = _snapshot()

    class Store:
        async def get(self, thread_id):
            return object() if thread_id == "thread-outline" else None

    class Persistence:
        async def load(self, _db, _thread_id):
            return snapshot

        async def list_thread(self, _db, *, thread_id):
            raise AssertionError("thread outline must not read the full event log")

    context = SimpleNamespace(
        host=SimpleNamespace(session_store=Store()),
        session_factory=lambda: _AsyncSession(),
        persistence=Persistence(),
    )
    outcome = asyncio.run(
        handle_thread_outline_operation(
            request_id=1,
            params={"thread_id": "thread-outline"},
            context=context,
        )
    )
    assert outcome.response["result"]["thread"] == {"id": "thread-outline"}
    assert len(outcome.response["result"]["items"]) == 3

    missing = asyncio.run(
        handle_thread_outline_operation(
            request_id=2,
            params={"thread_id": "missing"},
            context=context,
        )
    )
    assert missing.response["error"]["message"] == "thread not found"


def test_session_outline_cli_parser_and_human_output(monkeypatch, capsys) -> None:
    parser = build_parser()
    args = parser.parse_args(["session", "outline", "thread-outline", "--raw"])
    assert args.session_command == "outline"
    assert args.thread_id == "thread-outline"
    assert args.raw is True

    async def fake_invoke(_args, _operation):
        return {
            "thread": {"id": "thread-outline"},
            "items": [{
                "message_id": "u1",
                "turn_id": "turn-1",
                "seq": 1,
                "timestamp": None,
                "prompt": "hello",
                "response_excerpt": "world",
            }],
        }

    monkeypatch.setattr("lamtools_core.cli._invoke_live", fake_invoke)
    args.raw = False
    assert asyncio.run(cmd_session_outline(args)) == 0
    output = capsys.readouterr().out
    assert "hello -> world" in output
