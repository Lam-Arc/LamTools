"""Session item writes: API → snapshot (visible bubble) → broadcast, with guards.

user:“写测试：API 写入 → 快照/selectChatMessages 能读到 → 广播事件形状正确 →
非法 kind 被拒 → 幂等键去重；Python 测试用隔离库（LAMTOOLS_CORE_DB=...
\\ .lam\\tmp\\items-api.db），不要碰运行中的库。”+(所以每个用例都建自己的临时库，
走的是真实 turn 的持久化与投影路径：RunItemEvent → append_batch_atomic →
core_thread_snapshot_items + item_order → hub.publish。)

The snapshot assertions double as the backend half of `selectChatMessages`: the
row the API writes carries `kind='message'` + `payload.type='agentMessage'`, which
is exactly what the selector turns into an assistant bubble (see
`core/ui/tests/session-items-visible.test.ts` for the UI half).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from lamtools_core.app import open_core_app_db
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.session_items import (
    MAX_ITEM_CHARS,
    SessionItemsError,
    normalize_session_items,
    write_session_items,
)
from lamtools_core.http import create_core_router
from lamtools_core.session import InMemorySessionStore, SessionRecord


def _session_store(thread_id: str = "s1") -> InMemorySessionStore:
    store = InMemorySessionStore()
    store.create(SessionRecord(id=thread_id, member_id="core", title="Items", status="idle"))
    return store


async def _client(db, hub: CoreAppEventHub, thread_id: str = "s1") -> AsyncClient:
    """The real router with the real writer wired to this isolated database."""

    async def write_items(session_id: str, body) -> dict:
        return await write_session_items(
            thread_id=session_id,
            items=list(body.items or []),
            persistence=db.persistence,
            hub=hub,
            session_factory=db.session_factory,
            client_item_id=body.client_item_id,
            turn_id=body.turn_id,
        )

    app = FastAPI()
    app.include_router(
        create_core_router(session_store=_session_store(thread_id), write_items=write_items)
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _snapshot(db, thread_id: str = "s1") -> dict:
    async with db.session_factory() as session:
        return await db.snapshot_store.load(session, thread_id)


async def _item_rows(db, thread_id: str = "s1") -> int:
    async with db.session_factory() as session:
        result = await session.execute(
            select(func.count()).select_from(db.snapshot_store.item_model).where(
                db.snapshot_store.item_model.thread_id == thread_id
            )
        )
        return int(result.scalar_one())


def _drain(queue) -> list:
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


@pytest.mark.asyncio
async def test_items_write_lands_in_core_items_and_item_order(tmp_path: Path) -> None:
    """一条助手文本写进 core.items + item_order，快照里读得到（气泡不会为空）。"""
    db = await open_core_app_db(tmp_path / "items-api.db")
    hub = CoreAppEventHub()
    queue = hub.subscribe("s1")
    try:
        async with await _client(db, hub) as client:
            response = await client.post(
                "/sessions/s1/items",
                json={
                    "client_item_id": "acceptance-1",
                    "items": [
                        {
                            "kind": "text",
                            "role": "assistant",
                            "parts": [{"type": "text", "text": "验收会话现在有内容了。"}],
                        }
                    ],
                },
            )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["duplicated"] is False
        item_id = body["items"][0]["item_id"]
        assert item_id.startswith(f"{body['turn_id']}:item:")

        snapshot = await _snapshot(db)
        core = snapshot["core"]
        assert item_id in core["items"], "写进 messages 以外，必须真的落成 core.items"
        assert item_id in core["item_order"], "item_order 缺条目界面上就看不见"
        item = core["items"][item_id]
        assert item["kind"] == "message"
        assert item["status"] == "completed"
        assert item["content"] == "验收会话现在有内容了。"
        assert item["payload"]["type"] == "agentMessage"
        # 回合由这次写入创建并立刻收官：留着 running 会把会话一直标成忙碌。
        assert core["turns"][body["turn_id"]]["status"] == "completed"
        assert core["status"] == "completed"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_items_write_broadcasts_run_item_events(tmp_path: Path) -> None:
    """广播走真实 turn 的同一套事件：core/runItem + payload.kind/type。"""
    db = await open_core_app_db(tmp_path / "items-api.db")
    hub = CoreAppEventHub()
    queue = hub.subscribe("s1")
    try:
        async with await _client(db, hub) as client:
            response = await client.post(
                "/sessions/s1/items",
                json={"items": [{"kind": "text", "parts": [{"type": "text", "text": "hi"}]}]},
            )
        assert response.status_code == 201
        events = _drain(queue)
        assert [event.method for event in events] == ["core/runItem", "core/runItem"]
        message, status = events
        assert message.payload["kind"] == "message"
        assert message.payload["payload"]["type"] == "agentMessage"
        assert message.item_id == response.json()["items"][0]["item_id"]
        assert message.thread_id == "s1"
        # 收官事件不带 item_id：它不是一条聊天记录，只负责关掉这次写入的回合。
        assert status.payload["kind"] == "status"
        assert status.payload["payload"]["status"] == "completed"
        assert status.payload["turn_id"] == response.json()["turn_id"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_richer_parts_collapse_into_one_agent_message(tmp_path: Path) -> None:
    """chart/mermaid/interactive-html/writing 落成真实 turn 的围栏正文。"""
    db = await open_core_app_db(tmp_path / "items-api.db")
    hub = CoreAppEventHub()
    try:
        async with await _client(db, hub) as client:
            response = await client.post(
                "/sessions/s1/items",
                json={
                    "items": [
                        {
                            "kind": "text",
                            "parts": [
                                {"type": "text", "text": "看看这张图："},
                                {"type": "chart", "source": {"type": "bar", "categories": ["A"]}},
                                {"type": "mermaid", "source": "graph TD; A-->B;"},
                                {"type": "writing", "source": "正文", "title": "草稿"},
                            ],
                        }
                    ]
                },
            )
        assert response.status_code == 201, response.text
        snapshot = await _snapshot(db)
        item_id = response.json()["items"][0]["item_id"]
        content = snapshot["core"]["items"][item_id]["content"]
        assert content.startswith("看看这张图：")
        assert "```chart" in content
        assert '"type":"bar"' in content
        assert "```mermaid" in content
        assert '```writing{title="草稿"}' in content
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_client_item_id_makes_the_write_idempotent(tmp_path: Path) -> None:
    """同一个 client_item_id 重试不重复插入，也不重复广播。"""
    db = await open_core_app_db(tmp_path / "items-api.db")
    hub = CoreAppEventHub()
    queue = hub.subscribe("s1")
    payload = {
        "client_item_id": "same-key",
        "items": [{"kind": "text", "parts": [{"type": "text", "text": "只应该出现一次"}]}],
    }
    try:
        async with await _client(db, hub) as client:
            first = await client.post("/sessions/s1/items", json=payload)
            assert first.status_code == 201
            rows_after_first = await _item_rows(db)
            _drain(queue)
            second = await client.post("/sessions/s1/items", json=payload)
        assert second.status_code == 201
        assert second.json()["duplicated"] is True
        assert second.json()["items"] == first.json()["items"]
        assert await _item_rows(db) == rows_after_first
        assert _drain(queue) == []
        snapshot = await _snapshot(db)
        assert snapshot["core"]["items"][first.json()["items"][0]["item_id"]]["content"] == "只应该出现一次"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_execution_kinds_and_non_assistant_roles_are_rejected(tmp_path: Path) -> None:
    """工具/执行类与用户角色一律拒绝，避免伪造工具执行与审批卡。"""
    db = await open_core_app_db(tmp_path / "items-api.db")
    hub = CoreAppEventHub()
    try:
        async with await _client(db, hub) as client:
            tool_call = await client.post(
                "/sessions/s1/items",
                json={"items": [{"kind": "tool_call", "parts": [{"type": "text", "text": "x"}]}]},
            )
            assert tool_call.status_code == 422
            assert tool_call.json()["detail"]["code"] == "INVALID_ITEM"

            for kind in ("tool_result", "approval_request", "status", "userMessage"):
                bad_kind = await client.post(
                    "/sessions/s1/items",
                    json={"items": [{"kind": kind, "parts": [{"type": "text", "text": "x"}]}]},
                )
                assert bad_kind.status_code == 422, kind

            user_role = await client.post(
                "/sessions/s1/items",
                json={"items": [{"kind": "text", "role": "user", "parts": [{"type": "text", "text": "x"}]}]},
            )
            assert user_role.status_code == 422

            bad_part = await client.post(
                "/sessions/s1/items",
                json={"items": [{"kind": "text", "parts": [{"type": "tool_result", "text": "x"}]}]},
            )
            assert bad_part.status_code == 422

            empty = await client.post("/sessions/s1/items", json={"items": []})
            assert empty.status_code == 422

            unknown_session = await client.post(
                "/sessions/nope/items",
                json={"items": [{"kind": "text", "parts": [{"type": "text", "text": "x"}]}]},
            )
            assert unknown_session.status_code == 404

            unavailable = AsyncClient(
                transport=ASGITransport(
                    app=_app_without_writer(),
                ),
                base_url="http://test",
            )
            async with unavailable as bare:
                not_configured = await bare.post(
                    "/sessions/s1/items",
                    json={"items": [{"kind": "text", "parts": [{"type": "text", "text": "x"}]}]},
                )
            assert not_configured.status_code == 503
        assert await _item_rows(db) == 0, "被拒的请求不能留下任何行"
    finally:
        await db.close()


def _app_without_writer() -> FastAPI:
    app = FastAPI()
    app.include_router(create_core_router(session_store=_session_store()))
    return app


def test_oversized_items_are_rejected() -> None:
    huge = "x" * (MAX_ITEM_CHARS + 1)
    with pytest.raises(SessionItemsError) as excinfo:
        normalize_session_items([{"kind": "text", "parts": [{"type": "text", "text": huge}]}])
    assert excinfo.value.status_code == 422


def test_invalid_chart_json_is_rejected() -> None:
    with pytest.raises(SessionItemsError):
        normalize_session_items(
            [{"kind": "chart", "parts": [{"type": "chart", "source": "not json"}]}]
        )


@pytest.mark.asyncio
async def test_default_router_refuses_assistant_messages(tmp_path: Path) -> None:
    """POST /messages 不再静默成功：助手内容必须走 items。"""
    db = await open_core_app_db(tmp_path / "items-api.db")
    del db
    app = FastAPI()
    app.include_router(create_core_router(session_store=_session_store()))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assistant = await client.post(
            "/sessions/s1/messages",
            json={"id": "m1", "role": "assistant", "content": "看不见的回复"},
        )
        assert assistant.status_code == 400
        assert assistant.json()["detail"]["code"] == "ASSISTANT_MESSAGE_NOT_VISIBLE"
        assert assistant.json()["detail"]["use"] == "/api/core/sessions/s1/items"

        user = await client.post(
            "/sessions/s1/messages",
            json={"id": "m2", "role": "user", "content": "只存记录"},
        )
        assert user.status_code == 201
        assert user.json()["visible_in_ui"] is False
