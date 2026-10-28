"""Gateway protocol and outbound event routing tests."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import websockets

from qqbot.config import normalize
from qqbot.outbound import OutboundRouter
from qqbot.protocol import (
    GatewaySessionStore,
    MsgIdCache,
    QQGateway,
    ReplyLimiter,
    ReplyTarget,
)


class _FakeTokens:
    def __init__(self) -> None:
        self.cleared = 0

    async def get(self) -> str:
        return "token"

    def clear(self) -> None:
        self.cleared += 1


class _GatewayApi:
    def __init__(self, url: str) -> None:
        self.url = url
        self.tokens = _FakeTokens()

    async def get_gateway_url(self) -> str:
        return self.url


async def test_gateway_identifies_and_receives_c2c(tmp_path: Path) -> None:
    received: list = []
    ready = asyncio.Event()

    async def handler(ws):
        await ws.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 100}}))
        identify = json.loads(await ws.recv())
        assert identify["op"] == 2
        assert identify["d"]["token"] == "QQBot token"
        await ws.send(json.dumps({"op": 0, "s": 1, "t": "READY", "d": {"session_id": "sess-1"}}))
        await ws.send(
            json.dumps(
                {
                    "op": 0,
                    "s": 2,
                    "t": "C2C_MESSAGE_CREATE",
                    "d": {
                        "author": {"user_openid": "u1"},
                        "content": "hello",
                        "id": "m1",
                        "timestamp": "2026-10-26T10:00:00Z",
                    },
                }
            )
        )
        try:
            await asyncio.wait_for(ws.recv(), timeout=1.0)
        except Exception:
            pass

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        gateway = QQGateway(
            api=_GatewayApi(f"ws://127.0.0.1:{port}"),
            user_agent="test",
            logger=logging.getLogger("test"),
            session_store=GatewaySessionStore(tmp_path),
            on_message=lambda message: _collect(received, message),
            on_interaction=_noop_interaction,
            on_ready=lambda data: _set(ready),
        )
        task = gateway.start()
        try:
            await asyncio.wait_for(ready.wait(), timeout=3)
            for _ in range(100):
                if received:
                    break
                await asyncio.sleep(0.01)
            assert received
            assert received[0].content == "hello"
            assert received[0].scope == "c2c"
            assert gateway.connected is True
        finally:
            await gateway.stop()
            await asyncio.gather(task, return_exceptions=True)


async def _collect(received, message) -> None:
    received.append(message)


async def _noop_interaction(event) -> None:
    return None


async def _set(event: asyncio.Event) -> None:
    event.set()


class _FakeStream:
    def __init__(self) -> None:
        self.updates: list[str] = []
        self.completed = 0
        self.should_fallback = False

    async def update(self, text: str) -> None:
        self.updates.append(text)

    async def complete(self) -> None:
        self.completed += 1


class _OutboundApi:
    def __init__(self) -> None:
        self.sent: list[tuple] = []
        self.streams: list[_FakeStream] = []
        self.media: list[tuple] = []

    async def send_markdown(self, target, content, keyboard=None):
        self.sent.append((target, content, keyboard))
        return {"id": "sent"}

    def open_stream(self, target):
        stream = _FakeStream()
        self.streams.append(stream)
        return stream

    async def send_media(self, target, file_type, *, data=None, local_path=None, file_name=""):
        self.media.append((target, file_type, file_name))
        return {"upload": {"file_uuid": "uuid"}, "message": {"id": "mid"}}


def _event(name: str, payload: dict) -> SimpleNamespace:
    payload = dict(payload)
    payload.setdefault("sub_agent", {"agent": "qq_u"})
    return SimpleNamespace(name=name, payload=payload)


def _router(tmp_path: Path, api, session, config=None):
    return OutboundRouter(
        api=api,
        config=normalize(config or {"appId": "app", "streaming": True}),
        logger=logging.getLogger("test"),
        find_by_agent=lambda name: session if name == "qq_u" else None,
        cache=MsgIdCache(),
        limiter=ReplyLimiter(limit=4),
        data_dir=tmp_path,
        work_root=tmp_path,
    )


async def test_outbound_streams_c2c_and_sends_final(tmp_path: Path) -> None:
    api = _OutboundApi()
    session = SimpleNamespace(
        agent_name="qq_u",
        reply_target=ReplyTarget("c2c", "u", "m"),
        usage={"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    )
    router = _router(tmp_path, api, session)
    await router.handle_event(_event("runtime.reply_delta", {"content": "hel"}))
    await router.handle_event(_event("runtime.reply_delta", {"content": "lo"}))
    await router.handle_event(_event("runtime.reply", {"content": "hello"}))
    assert api.streams
    assert api.streams[0].updates[-1] == "hello"
    assert api.streams[0].completed == 1
    assert api.sent == []


async def test_outbound_streaming_splits_newline_bubbles(tmp_path: Path) -> None:
    api = _OutboundApi()
    session = SimpleNamespace(
        agent_name="qq_u",
        reply_target=ReplyTarget("c2c", "u", "m"),
        usage={"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    )
    router = _router(tmp_path, api, session)
    for delta in ("第一行", "\n", "第二行", "\n\n\n", "第三行"):
        await router.handle_event(_event("runtime.reply_delta", {"content": delta}))
    await router.handle_event(_event("runtime.reply", {"content": "第一行\n第二行\n\n\n第三行"}))

    assert [stream.updates[-1] for stream in api.streams] == ["第一行", "第二行", "第三行"]
    assert all(stream.completed == 1 for stream in api.streams)
    assert api.sent == []


async def test_outbound_streaming_keeps_code_block_together(tmp_path: Path) -> None:
    api = _OutboundApi()
    session = SimpleNamespace(
        agent_name="qq_u",
        reply_target=ReplyTarget("c2c", "u", "m"),
        usage={"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    )
    router = _router(tmp_path, api, session)
    for delta in ("说明", "\n", "```python", "\n", "a", "\n\n", "b", "\n", "```", "\n", "结尾"):
        await router.handle_event(_event("runtime.reply_delta", {"content": delta}))
    await router.handle_event(_event("runtime.reply", {"content": "说明\n```python\na\n\nb\n```\n结尾"}))

    assert len(api.streams) == 3
    assert api.streams[0].updates[-1] == "说明"
    assert api.streams[1].updates[-1] == "```python\na\n\nb\n```"
    assert api.streams[2].updates[-1] == "结尾"
    assert all(stream.completed == 1 for stream in api.streams)
    assert api.sent == []


async def test_outbound_streaming_keeps_table_together(tmp_path: Path) -> None:
    api = _OutboundApi()
    session = SimpleNamespace(
        agent_name="qq_u",
        reply_target=ReplyTarget("c2c", "u", "m"),
        usage={"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    )
    router = _router(tmp_path, api, session)
    for delta in (
        "说明",
        "\n",
        "| 名称 | 数量 |",
        "\n",
        "|---|---:|",
        "\n",
        "| A | 1 |",
        "\n",
        "| B | 2 |",
        "\n",
        "结尾",
    ):
        await router.handle_event(_event("runtime.reply_delta", {"content": delta}))
    await router.handle_event(_event("runtime.reply", {"content": "说明\n| 名称 | 数量 |\n|---|---:|\n| A | 1 |\n| B | 2 |\n结尾"}))

    assert [stream.updates[-1] for stream in api.streams] == [
        "说明",
        "| 名称 | 数量 |\n|---|---:|\n| A | 1 |\n| B | 2 |",
    ]
    assert all(stream.completed == 1 for stream in api.streams)
    assert [content for _target, content, _keyboard in api.sent] == ["结尾"]


async def test_outbound_streaming_keeps_list_together(tmp_path: Path) -> None:
    api = _OutboundApi()
    session = SimpleNamespace(
        agent_name="qq_u",
        reply_target=ReplyTarget("c2c", "u", "m"),
        usage={"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    )
    router = _router(tmp_path, api, session)
    for delta in (
        "- 列表项一",
        "\n",
        "  缩进续行",
        "\n\n",
        "- 列表项二",
        "\n",
        "结尾",
    ):
        await router.handle_event(_event("runtime.reply_delta", {"content": delta}))
    await router.handle_event(_event("runtime.reply", {"content": "- 列表项一\n  缩进续行\n\n- 列表项二\n结尾"}))

    assert [stream.updates[-1] for stream in api.streams] == [
        "- 列表项一\n  缩进续行\n\n- 列表项二",
    ]
    assert all(stream.completed == 1 for stream in api.streams)
    assert [content for _target, content, _keyboard in api.sent] == ["结尾"]


async def test_outbound_group_static_and_tool_error(tmp_path: Path) -> None:
    api = _OutboundApi()
    session = SimpleNamespace(
        agent_name="qq_u",
        reply_target=ReplyTarget("group", "g", "m"),
        usage={"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    )
    router = _router(tmp_path, api, session, {"appId": "app", "streaming": True})
    await router.handle_event(_event("runtime.reply_delta", {"content": "hi"}))
    await router.handle_event(_event("runtime.reply", {"content": "hi"}))
    assert api.sent and api.sent[0][1] == "hi"
    await router.handle_event(
        _event("runtime.tool.started", {"call_id": "c1", "tool_name": "run_command", "arguments": {}})
    )
    await router.handle_event(
        _event("runtime.tool.finished", {"call_id": "c1", "tool_name": "run_command", "error": "boom"})
    )
    assert any("❌" in content for _target, content, _keyboard in api.sent)


async def test_outbound_delivers_artifact(tmp_path: Path) -> None:
    api = _OutboundApi()
    artifact = tmp_path / "report.txt"
    artifact.write_text("hello", encoding="utf-8")
    session = SimpleNamespace(
        agent_name="qq_u",
        reply_target=ReplyTarget("c2c", "u", "m"),
        usage={"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    )
    router = _router(
        tmp_path,
        api,
        session,
        {
            "appId": "app",
            "streaming": True,
            "sendFile": {"restrictPaths": True, "sendPresentedFiles": True, "maxFiles": 4},
        },
    )
    await router.handle_event(
        _event(
            "runtime.tool.finished",
            {
                "call_id": "c1",
                "tool_name": "write_file",
                "content": "written",
                "artifacts": [{"kind": "file", "uri": str(artifact), "metadata": {"path": str(artifact)}}],
            },
        )
    )
    await router.handle_event(_event("runtime.done", {}))
    assert api.media
    assert api.media[0][2] == "report.txt"


async def test_outbound_safe_table_sends_cards_not_raw_pipes(tmp_path: Path) -> None:
    api = _OutboundApi()
    session = SimpleNamespace(
        agent_name="qq_u",
        reply_target=ReplyTarget("c2c", "u", "m"),
        usage={"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    )
    router = _router(
        tmp_path,
        api,
        session,
        {"appId": "app", "streaming": True, "bubbles": {"profile": "safe"}},
    )
    for delta in (
        "说明",
        "\n",
        "| 名称 | 数量 |",
        "\n",
        "|---|---:|",
        "\n",
        "| A | 1 |",
        "\n",
        "| B | 2 |",
        "\n",
        "结尾",
    ):
        await router.handle_event(_event("runtime.reply_delta", {"content": delta}))
    await router.handle_event(
        _event("runtime.reply", {"content": "说明\n| 名称 | 数量 |\n|---|---:|\n| A | 1 |\n| B | 2 |\n结尾"})
    )

    assert [stream.updates[-1] for stream in api.streams] == ["说明"]
    assert [content for _target, content, _keyboard in api.sent] == [
        "**表格 · 第 1 行**\n- 名称：A\n- 数量：1",
        "**表格 · 第 2 行**\n- 名称：B\n- 数量：2",
        "结尾",
    ]


async def test_outbound_safe_code_streams_quote_rendering(tmp_path: Path) -> None:
    api = _OutboundApi()
    session = SimpleNamespace(
        agent_name="qq_u",
        reply_target=ReplyTarget("c2c", "u", "m"),
        usage={"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    )
    router = _router(
        tmp_path,
        api,
        session,
        {"appId": "app", "streaming": True, "bubbles": {"profile": "safe"}},
    )
    for delta in ("```python", "\n", "x = 1", "\n", "```"):
        await router.handle_event(_event("runtime.reply_delta", {"content": delta}))
    await router.handle_event(_event("runtime.reply", {"content": "```python\nx = 1\n```"}))

    assert [stream.updates[-1] for stream in api.streams] == [
        "**代码 · python**\n> x = 1"
    ]
    assert all(stream.completed == 1 for stream in api.streams)
    assert api.sent == []
