from __future__ import annotations

import asyncio
import json

import pytest

from lamtools_core.app.cli_live import (
    CliLiveFormatter,
    watch_live_events,
)
from lamtools_core.cli import build_parser


def core_run_item(kind: str, payload: dict, **extra: object) -> dict:
    return {
        "event": "app_server_event",
        "data": {
            "method": "core/runItem",
            "payload": {
                "kind": kind,
                "thread_id": "thread-1",
                "event_id": f"event-{kind}",
                "turn_id": "turn-1",
                "item_id": f"item-{kind}",
                "payload": payload,
                **extra,
            },
        },
    }


def test_live_formatter_keeps_writer_compatible_run_item_lines() -> None:
    formatter = CliLiveFormatter()

    assert formatter.format(core_run_item("message", {"type": "agentMessage", "delta": "done"})) == [
        "[00:00] reply done"
    ]
    assert formatter.format(
        core_run_item(
            "tool_call",
            {"type": "dynamicToolCall", "tool_name": "write_file", "arguments": {"path": "draft.md"}, "message": "writing"},
            status="running",
        )
    ) == ["[00:00] file write_file draft.md writing"]
    assert formatter.format(
        core_run_item("status", {"type": "turn", "raw_end_reason": "llm_error"}, status="failed")
    ) == ["[00:00] failed llm_error"]


def test_live_formatter_formats_approval_and_compaction_compatibly() -> None:
    formatter = CliLiveFormatter()

    assert formatter.format(
        core_run_item("approval_request", {"request_id": "req-1", "message": "Approve?"}, status="waiting")
    ) == ["[00:00] waiting_for_user Approve?"]
    assert formatter.format(
        core_run_item(
            "message",
            {
                "type": "compaction",
                "label": "\u4e0a\u4e0b\u6587\u5df2\u538b\u7f29",
                "before_tokens": 18000,
                "after_tokens": 7200,
                "compacted_messages": 8,
            },
            status="completed",
        )
    ) == ["[00:00] done \u4e0a\u4e0b\u6587\u5df2\u538b\u7f29\uff1a18000 -> 7200 tokens\uff0c\u538b\u7f29 8 \u6761\u6d88\u606f\u3002"]


def test_core_cli_exposes_generic_live_watch() -> None:
    args = build_parser().parse_args([
        "watch",
        "thread-1",
        "--base-url",
        "http://core.test",
        "--raw",
    ])

    assert args.command == "watch"
    assert args.thread_id == "thread-1"
    assert args.base_url == "http://core.test"
    assert args.raw is True


def test_core_cli_watch_uses_opt_in_timeout_and_explicit_machine_approval() -> None:
    parser = build_parser()

    default_args = parser.parse_args(["watch", "thread-1"])
    raw_args = parser.parse_args([
        "watch",
        "thread-1",
        "--raw",
        "--event-timeout",
        "0",
        "--approval-decision",
        "approve_once",
        "--ws-path",
        "/custom/live",
        "--token",
        "secret",
    ])

    assert default_args.event_timeout is None
    assert raw_args.event_timeout is None
    assert raw_args.approval_decision == "approve_once"
    assert raw_args.ws_path == "/custom/live"
    assert raw_args.token == "secret"


class FakeClient:
    def __init__(self, events: list[dict | BaseException]) -> None:
        self._events = events
        self.connect_calls: list[tuple[str, int]] = []
        self.closed = False

    async def connect(self, *, thread_id: str, last_seen_seq: int = 0) -> None:
        self.connect_calls.append((thread_id, last_seen_seq))

    async def events(self):
        for item in self._events:
            if isinstance(item, BaseException):
                raise item
            yield item

    async def close(self) -> None:
        self.closed = True

    async def respond_approval(self, *, request_id: str, decision: str, guidance: str = "") -> None:
        self.approval_responses.append((request_id, decision, guidance))


@pytest.mark.asyncio
async def test_watch_resumes_from_last_seen_sequence_after_disconnect() -> None:
    first = FakeClient([
        {**core_run_item("message", {"delta": "part"}), "data": {**core_run_item("message", {"delta": "part"})["data"], "seq": 4}},
        ConnectionError("socket closed"),
    ])
    second = FakeClient([
        {**core_run_item("status", {"type": "turn"}, status="completed"), "data": {**core_run_item("status", {"type": "turn"}, status="completed")["data"], "seq": 5}},
    ])
    clients = iter((first, second))
    output: list[str] = []

    result = await watch_live_events(
        client_factory=lambda: next(clients),
        thread_id="thread-1",
        formatter=CliLiveFormatter(),
        output=output.append,
        reconnect_delay=0,
        max_reconnects=1,
    )

    assert result.completed is True
    assert result.failed is False
    assert result.last_seen_seq == 5
    assert first.connect_calls == [("thread-1", 0)]
    assert second.connect_calls == [("thread-1", 4)]
    assert output == ["[00:00] reply part", "[00:00] error socket closed", "[00:00] done"]
    assert first.closed is True
    assert second.closed is True


@pytest.mark.asyncio
async def test_watch_uses_injected_approval_callback_and_resets_after_resume() -> None:
    client = FakeClient([
        core_run_item("approval_request", {"request_id": "req-1", "message": "Approve?"}, status="waiting"),
        {"event": "app_server_event", "data": {"method": "serverRequest/resolved", "payload": {}}},
        core_run_item("status", {"type": "turn"}, status="completed"),
    ])
    client.approval_responses = []
    output: list[str] = []

    result = await watch_live_events(
        client_factory=lambda: client,
        thread_id="thread-1",
        formatter=CliLiveFormatter(),
        output=output.append,
        approval=lambda: "yes",
    )

    assert result.exit_code == 0
    assert client.approval_responses == [("req-1", "approve_once", "yes")]
    assert output == ["[00:00] waiting_for_user Approve?", "[00:00] resumed", "[00:00] done"]


@pytest.mark.asyncio
async def test_watch_emits_raw_timeout_error_envelope() -> None:
    class BlockingClient(FakeClient):
        async def events(self):
            await asyncio.Event().wait()
            yield {}

    client = BlockingClient([])
    output: list[str] = []

    result = await watch_live_events(
        client_factory=lambda: client,
        thread_id="thread-1",
        formatter=CliLiveFormatter(),
        output=output.append,
        raw=True,
        event_timeout=0.01,
        max_reconnects=0,
    )

    assert result.exit_code == 2
    assert json.loads(output[0])["event"] == "live_error"


@pytest.mark.asyncio
async def test_raw_watch_still_responds_to_approval_through_injected_callback() -> None:
    client = FakeClient([
        core_run_item("approval_request", {"request_id": "req-1", "message": "Approve?"}, status="waiting"),
        core_run_item("status", {"type": "turn"}, status="completed"),
    ])
    client.approval_responses = []
    output: list[str] = []

    result = await watch_live_events(
        client_factory=lambda: client,
        thread_id="thread-1",
        formatter=CliLiveFormatter(),
        output=output.append,
        raw=True,
        approval=lambda: "approve_once",
        approval_decision=lambda value: value,
    )

    assert result.exit_code == 0
    assert client.approval_responses == [("req-1", "approve_once", "approve_once")]
    assert [json.loads(value)["event"] for value in output] == ["app_server_event", "app_server_event"]


@pytest.mark.asyncio
async def test_raw_watch_fails_with_an_explicit_approval_error_without_callback() -> None:
    client = FakeClient([
        core_run_item("approval_request", {"request_id": "req-1", "message": "Approve?"}, status="waiting"),
    ])
    output: list[str] = []

    result = await watch_live_events(
        client_factory=lambda: client,
        thread_id="thread-1",
        formatter=CliLiveFormatter(),
        output=output.append,
        raw=True,
        max_reconnects=0,
    )

    assert result.exit_code == 2
    assert result.error == "approval decision is required for raw watch"
    assert json.loads(output[-1])["data"]["error"] == "approval decision is required for raw watch"


def test_display_formatting_has_no_stdout_side_effect(capsys) -> None:
    formatter = CliLiveFormatter()

    lines = formatter.format({
        "event": "display",
        "data": {"kind": "reply", "content": "delta", "metadata": {"delta": True}},
    })

    assert lines == ["delta"]
    assert capsys.readouterr().out == ""


def test_formatter_inserts_one_explicit_newline_after_inline_deltas() -> None:
    formatter = CliLiveFormatter()
    delta = {"event": "display", "data": {"kind": "reply", "content": "partial", "metadata": {"delta": True}}}
    final = {"event": "display", "data": {"kind": "reply", "content": "final", "metadata": {}}}

    assert [(str(chunk), chunk.end) for chunk in formatter.format_chunks(delta)] == [("partial", "")]
    assert [(str(chunk), chunk.end) for chunk in formatter.format_chunks(delta)] == [("partial", "")]
    assert [(str(chunk), chunk.end) for chunk in formatter.format_chunks(final)] == [
        ("\n", ""),
        ("[00:00] reply final", "\n"),
    ]


def test_formatter_closes_inline_delta_before_a_line_event() -> None:
    formatter = CliLiveFormatter()
    delta = {"event": "display", "data": {"kind": "reply", "content": "partial", "metadata": {"delta": True}}}

    formatter.format_chunks(delta)
    chunks = formatter.format_chunks(core_run_item("status", {"type": "turn"}, status="completed"))

    assert [(str(chunk), chunk.end) for chunk in chunks] == [
        ("\n", ""),
        ("[00:00] done", "\n"),
    ]


@pytest.mark.asyncio
async def test_watch_emits_display_delta_to_callback_without_newline_chunk() -> None:
    client = FakeClient([
        {"event": "display", "data": {"kind": "reply", "content": "delta", "metadata": {"delta": True}}},
        core_run_item("status", {"type": "turn"}, status="completed"),
    ])
    output: list[object] = []

    await watch_live_events(
        client_factory=lambda: client,
        thread_id="thread-1",
        formatter=CliLiveFormatter(),
        output=output.append,
    )

    assert [(str(chunk), getattr(chunk, "end", None)) for chunk in output] == [
        ("delta", ""),
        ("\n", ""),
        ("[00:00] done", "\n"),
    ]


@pytest.mark.asyncio
async def test_close_error_does_not_replace_the_original_watch_error() -> None:
    class CloseFailingClient(FakeClient):
        async def close(self) -> None:
            raise RuntimeError("close failed")

    output: list[str] = []
    result = await watch_live_events(
        client_factory=lambda: CloseFailingClient([ConnectionError("socket closed")]),
        thread_id="thread-1",
        formatter=CliLiveFormatter(),
        output=output.append,
        max_reconnects=0,
    )

    assert result.error == "socket closed"


@pytest.mark.asyncio
async def test_watch_without_an_explicit_timeout_stays_alive_during_silence() -> None:
    class SilentClient(FakeClient):
        def __init__(self) -> None:
            super().__init__([])
            self.waiting = asyncio.Event()

        async def events(self):
            self.waiting.set()
            await asyncio.Event().wait()
            yield {}

    client = SilentClient()
    task = asyncio.create_task(watch_live_events(
        client_factory=lambda: client,
        thread_id="thread-1",
        formatter=CliLiveFormatter(),
        output=lambda _chunk: None,
    ))
    await asyncio.wait_for(client.waiting.wait(), timeout=1)
    await asyncio.sleep(0.02)

    assert task.done() is False
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
