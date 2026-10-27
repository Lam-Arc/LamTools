"""Protocol, middleware, channel and binding tests for the QQ bot port."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from qqbot.binding import BindingService, build_connect_url, decrypt_secret, render_qr_svg_data_url
from qqbot.channels import (
    ApprovalChannel,
    QuestionChannel,
    answer_text,
    build_approval_keyboard,
    build_question_keyboard,
    decode_button_data,
    encode_button_data,
    parse_answer,
)
from qqbot.middleware import (
    MemoryHistoryStore,
    MemoryRefIndexStore,
    MiddlewareContext,
    access_policy,
    build_agent_body,
    content_sanitizer,
    history_buffer,
    mention_gate,
    message_filter,
    quote_ref,
    run_chain,
)
from qqbot.protocol import (
    InboundMessage,
    MsgIdCache,
    QQApi,
    ReplyLimiter,
    ReplyTarget,
    StreamSession,
    parse_inbound,
)
from qqbot.runtime import MergeGuard, merge_contexts
from qqbot.util import chunk_markdown_text, is_path_allowed, sniff_image_media_type


# ── Utilities / protocol ───────────────────────────────────────────────────

def test_chunk_markdown_preserves_code_and_table() -> None:
    text = "intro\n```python\nprint(1)\nprint(2)\n```\n|a|b|\n|1|2|\nend"
    chunks = chunk_markdown_text(text, 20)
    assert all("```" not in chunk or chunk.count("```") % 2 == 0 for chunk in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_path_allowed(tmp_path: Path) -> None:
    allowed = tmp_path / "media" / "a.txt"
    allowed.parent.mkdir()
    allowed.write_text("x", encoding="utf-8")
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    assert is_path_allowed(allowed, [tmp_path / "media"], True)
    assert not is_path_allowed(outside, [tmp_path / "media"], True)
    assert is_path_allowed(outside, [tmp_path / "media"], False)


def test_sniff_image() -> None:
    assert sniff_image_media_type(b"\x89PNG\r\n\x1a\n" + b"0" * 8) == "image/png"
    assert sniff_image_media_type(b"\xff\xd8\xff" + b"0" * 9) == "image/jpeg"
    assert sniff_image_media_type(b"not an image") is None


def test_parse_inbound_c2c_and_group() -> None:
    c2c = parse_inbound(
        "C2C_MESSAGE_CREATE",
        {
            "author": {"user_openid": "u1"},
            "content": "hi",
            "id": "m1",
            "timestamp": "2026-10-26T10:00:00Z",
            "attachments": [{"content_type": "image/png", "url": "https://x/y.png"}],
        },
    )
    assert c2c is not None
    assert c2c.scope == "c2c"
    assert c2c.peer_id == "u1"
    assert c2c.reply_target.msg_id == "m1"
    group = parse_inbound(
        "GROUP_AT_MESSAGE_CREATE",
        {
            "author": {"member_openid": "u2", "username": "Ann"},
            "group_openid": "g1",
            "content": "hello",
            "id": "m2",
            "mentions": [{"is_you": True}],
        },
    )
    assert group is not None
    assert group.scope == "group"
    assert group.peer_id == "g1"
    assert group.sender_name == "Ann"


def test_reply_limiter_and_msgid_cache() -> None:
    limiter = ReplyLimiter(limit=2)
    assert limiter.check("m")[0]
    limiter.record("m")
    limiter.record("m")
    assert limiter.check("m") == (False, "limit_exceeded")
    cache = MsgIdCache()
    cache.cache_msg("c2c", "u", "m1")
    cache.cache_event("c2c", "u", "e1")
    ids = cache.get("c2c", "u")
    assert [item.kind for item in ids] == ["event", "msg"]


async def test_api_send_markdown_body() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "getAppAccessToken" in str(request.url):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})
        return httpx.Response(200, json={"id": "sent"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    api = QQApi(app_id="app", app_secret="secret", client=client)
    try:
        result = await api.send_markdown(
            ReplyTarget("c2c", "user", "msg-1"),
            "hello",
            keyboard=build_approval_keyboard(),
        )
        assert result["id"] == "sent"
    finally:
        await api.close()
    body = json.loads(requests[-1].content)
    assert body["msg_type"] == 2
    assert body["markdown"]["content"] == "hello"
    assert body["msg_id"] == "msg-1"
    assert "msg_seq" in body
    assert "keyboard" in body


async def test_token_cache_single_fetch() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    api = QQApi(app_id="app", app_secret="secret", client=client)
    try:
        assert await api.tokens.get() == "tok"
        assert await api.tokens.get() == "tok"
    finally:
        await api.close()
    assert calls == 1


async def test_stream_session_updates_and_completes() -> None:
    class FakeApi:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def send_stream_chunk(self, target, **kwargs):
            self.calls.append(kwargs)
            return {"id": "stream-1"}

    fake = FakeApi()
    stream = StreamSession(fake, ReplyTarget("c2c", "u", "m"), throttle_ms=300)
    await stream.update("hello")
    await asyncio.sleep(0.35)
    await stream.complete()
    assert fake.calls
    assert fake.calls[-1]["state"] == "done"
    assert fake.calls[-1]["text"] == "hello"


# ── Middleware ─────────────────────────────────────────────────────────────

def _message(**kwargs) -> InboundMessage:
    defaults = {
        "raw_event_type": "C2C_MESSAGE_CREATE",
        "kind": "c2c",
        "sender_id": "u1",
        "content": "hi",
        "message_id": "m1",
    }
    defaults.update(kwargs)
    return InboundMessage(**defaults)


async def test_message_filter_dedup() -> None:
    middleware = message_filter()
    ctx1 = MiddlewareContext(_message())
    await run_chain([middleware], ctx1)
    assert not ctx1.stopped
    ctx2 = MiddlewareContext(_message())
    await run_chain([middleware], ctx2)
    assert ctx2.stopped
    assert ctx2.stop_reason == "deduplication"


async def test_access_policy_and_mention_gate() -> None:
    ctx = MiddlewareContext(_message(kind="c2c", sender_id="blocked"))
    await run_chain([access_policy({"c2cMode": "allowlist", "c2cAllow": ["allowed"]})], ctx)
    assert ctx.stopped

    group = MiddlewareContext(
        _message(kind="group", group_openid="g1", raw_event_type="GROUP_MESSAGE_CREATE")
    )
    await run_chain([mention_gate(require_mention=True)], group)
    assert group.stopped
    assert group.stop_reason == "mention-gate:no_mention"

    group2 = MiddlewareContext(
        _message(kind="group", group_openid="g1", raw_event_type="GROUP_AT_MESSAGE_CREATE")
    )
    await run_chain([mention_gate(require_mention=True)], group2)
    assert not group2.stopped


async def test_content_sanitizer() -> None:
    ctx = MiddlewareContext(_message(content="<@!app> 你好 [<face,id=0/>]"))
    ctx.bot = SimpleNamespace(app_id="app")
    await run_chain([content_sanitizer(parse_face_tags=True)], ctx)
    assert ctx.message.content == "你好 😊"


async def test_history_buffer_and_quote_ref() -> None:
    store = MemoryHistoryStore()
    key = lambda ctx: "g1" if ctx.message.kind == "group" else None
    first = MiddlewareContext(_message(kind="group", group_openid="g1", content="first"))
    await run_chain([history_buffer(store, limit=10, group_key=key)], first)
    second = MiddlewareContext(_message(kind="group", group_openid="g1", content="second"))
    await run_chain([history_buffer(store, limit=10, group_key=key)], second)
    assert second.state["history"][0]["content"] == "first"

    ref_store = MemoryRefIndexStore()
    quoted = MiddlewareContext(
        _message(
            ref_msg_idx="idx-1",
            msg_elements=[{"content": "quoted text"}],
        )
    )
    await run_chain([quote_ref(ref_store)], quoted)
    assert quoted.state["quote"]["text"] == "quoted text"


async def test_build_agent_body_group_history_and_media() -> None:
    ctx = MiddlewareContext(
        _message(
            kind="group",
            group_openid="g1",
            sender_id="u2",
            sender_name="Ann",
            content="current",
            raw_event_type="GROUP_AT_MESSAGE_CREATE",
            attachments=[
                {"content_type": "image/png", "filename": "a.png", "url": "https://x/a.png"}
            ],
        )
    )
    ctx.state["mention"] = {"wasMentioned": True}
    ctx.state["history"] = [
        {"senderId": "u1", "senderName": "Bob", "content": "earlier"}
    ]
    ctx.state["downloadedFiles"] = [
        {"filename": "a.png", "localPath": "C:/media/a.png", "contentType": "image"}
    ]
    body = build_agent_body(ctx, history_limit=10)
    assert "[Chat history begins]" in body
    assert "Bob (u1)] earlier" in body
    assert "[Ann (u2)] current\n[图片] (@you)" in body
    assert "Image: C:/media/a.png" in body


async def test_merge_guard_merges_buffered_messages() -> None:
    seen: list[str] = []

    async def downstream(ctx: MiddlewareContext) -> None:
        seen.append(ctx.message.content)
        await asyncio.sleep(0.05)

    guard = MergeGuard(10)
    first = MiddlewareContext(_message(content="one"))
    second = MiddlewareContext(_message(content="two"))
    third = MiddlewareContext(_message(content="three"))

    async def run_all() -> None:
        await asyncio.gather(
            guard.run(first, downstream),
            guard.run(second, downstream),
            guard.run(third, downstream),
        )

    await run_all()
    assert seen[0] == "one"
    merged = seen[1]
    assert "two" in merged and "three" in merged


# ── Buttons / channels ─────────────────────────────────────────────────────

def test_button_helpers_and_parse_answer() -> None:
    data = encode_button_data({"t": "approval", "d": "allow"})
    assert decode_button_data(data) == {"t": "approval", "d": "allow"}
    assert decode_button_data("not json") is None
    keyboard = build_question_keyboard(
        {"id": "q1", "options": [{"label": "A"}, {"label": "B"}, {"label": "C"}]}
    )
    assert len(keyboard["content"]["rows"]) == 2
    question = {"id": "q1", "options": [{"label": "A"}, {"label": "B"}]}
    assert parse_answer(question, "2")["selected"] == ["B"]
    assert parse_answer(question, "B")["selected"] == ["B"]
    assert parse_answer(question, "自定义")["custom"] == "自定义"


async def test_approval_channel_allow() -> None:
    channel = ApprovalChannel(logger=__import__("logging").getLogger("test"))

    class Session:
        key = "k"
        sent: list[str] = []

        async def send_markdown(self, content, keyboard=None):
            self.sent.append(content)

    session = Session()

    class Manager:
        def get(self, scope, peer):
            return session

    manager = Manager()
    task = asyncio.create_task(
        channel.ask(
            session,
            {
                "tool_call": {"name": "run_command", "arguments": {"command": "echo hi"}},
                "request_payload": {"message": "允许吗"},
            },
            timeout_ms=5000,
        )
    )
    await asyncio.sleep(0.05)
    matched = channel.handle_interaction(
        {
            "user_openid": "u",
            "data": {"resolved": {"button_data": encode_button_data({"t": "approval", "d": "allow"})}},
        },
        manager,
    )
    assert matched
    assert await task == "allow"
    assert "echo hi" in session.sent[0]


async def test_question_channel_text_answer() -> None:
    channel = QuestionChannel(logger=__import__("logging").getLogger("test"))

    class Session:
        key = "k"

        async def send_markdown(self, content, keyboard=None):
            return None

    session = Session()

    class Manager:
        def get(self, scope, peer):
            return session

    manager = Manager()
    task = asyncio.create_task(
        channel.ask(
            session,
            {
                "request_payload": {
                    "request_id": "q1",
                    "message": "选一个",
                    "options": [{"label": "A"}, {"label": "B"}],
                }
            },
            timeout_ms=5000,
            require_mention=False,
        )
    )
    await asyncio.sleep(0.05)
    assert channel.handle_text("c2c", "u", "2", manager)
    answer = await task
    assert answer is not None
    assert answer["selected"] == ["B"]
    assert answer_text(answer) == "B"


async def test_question_channel_asks_multiple_questions() -> None:
    channel = QuestionChannel(logger=__import__("logging").getLogger("test"))

    class Session:
        key = "k"
        sent: list[str] = []

        async def send_markdown(self, content, keyboard=None):
            self.sent.append(content)

    session = Session()

    class Manager:
        def get(self, scope, peer):
            return session

    manager = Manager()
    pending = {
        "tool_call": {
            "name": "question",
            "arguments": {
                "questions": [
                    {"header": "One", "question": "First?", "options": [{"label": "A"}, {"label": "B"}]},
                    {"header": "Two", "question": "Second?", "options": [{"label": "C"}, {"label": "D"}]},
                ]
            },
        },
        "request_payload": {"request_id": "batch", "message": "First?"},
    }
    task = asyncio.create_task(
        channel.ask(session, pending, timeout_ms=5000, require_mention=False)
    )
    await asyncio.sleep(0.05)
    assert channel.handle_text("c2c", "u", "1", manager)
    await asyncio.sleep(0.05)
    assert channel.handle_text("c2c", "u", "2", manager)
    answers = await task
    assert isinstance(answers, list)
    assert answers[0]["selected"] == ["A"]
    assert answers[1]["selected"] == ["D"]
    text = answer_text(answers)
    assert "问题 1: A" in text
    assert "问题 2: D" in text


# ── Binding ────────────────────────────────────────────────────────────────

def test_decrypt_secret_roundtrip() -> None:
    key = os.urandom(32)
    nonce = os.urandom(12)
    plaintext = "app-secret".encode()
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    payload = base64.b64encode(nonce + ciphertext).decode()
    assert decrypt_secret(payload, base64.b64encode(key).decode()) == "app-secret"


def test_connect_url_and_qr() -> None:
    url = build_connect_url("task-1", "src")
    assert url.startswith("https://q.qq.com/qqbot/openclaw/connect.html?task_id=task-1")
    data_url = render_qr_svg_data_url("https://example.com")
    assert data_url.startswith("data:image/svg+xml;base64,")


async def test_binding_service_completes() -> None:
    key = base64.b64encode(os.urandom(32)).decode()
    nonce = os.urandom(12)
    secret = AESGCM(base64.b64decode(key)).encrypt(nonce, b"secret", None)
    encrypted = base64.b64encode(nonce + secret).decode()

    class FakeClient:
        async def create_task(self):
            return {"taskId": "task-1", "key": key}

        async def poll(self, task_id):
            return {
                "status": 2,
                "botAppId": "app-1",
                "botEncryptSecret": encrypted,
                "userOpenid": "u",
            }

        async def close(self):
            return None

    done = asyncio.Event()
    credentials: dict = {}

    async def on_success(value):
        credentials.update(value)
        done.set()

    service = BindingService(
        client=FakeClient(),
        logger=__import__("logging").getLogger("test"),
        on_success=on_success,
        poll_interval=0.01,
        render_qr=lambda url: "data:image/svg+xml;base64,AA==",
    )
    service.start()
    await asyncio.wait_for(done.wait(), timeout=2)
    assert credentials == {"appId": "app-1", "appSecret": "secret"}
    assert service.state.phase == "saving"
    await service.dispose()
