"""Direct history locate: one bounded read for the window a message lives in."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lamtools_core.app.live_operations import handle_thread_page_around_operation
from lamtools_core.app.snapshot_store import (
    CoreAppSnapshotProjector,
    SqlAlchemyThreadSnapshotStore,
)
from lamtools_core.app.thread_history import _character_page_snapshot

THREAD = "thread-locate"


class Base(DeclarativeBase):
    pass


class ThreadSnapshotRow(Base):
    __tablename__ = "locate_thread_snapshots"

    # `revision` mirrors the production row: the store's parsed-metadata cache is
    # keyed on it, and the cheap probe needs it.
    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_turn_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class SnapshotItemRow(Base):
    __tablename__ = "locate_thread_snapshot_items"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


async def _store(tmp_path, *, turns: int = 30, assistants_per_turn: int = 4):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'locate.db'}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = SqlAlchemyThreadSnapshotStore(
        ThreadSnapshotRow, item_model=SnapshotItemRow, projector=CoreAppSnapshotProjector()
    )
    core_items: dict[str, dict] = {}
    user_items: dict[str, dict] = {}
    turn_items: dict[str, list[str]] = {}
    seq = 0
    for turn_index in range(turns):
        turn_id = f"turn-{turn_index:03d}"
        seq += 1
        user_id = f"{THREAD}:{turn_id}:user"
        user_items[user_id] = {
            "item_id": user_id,
            "turn_id": turn_id,
            "type": "userMessage",
            "seq": seq,
            "payload": {"type": "userMessage", "text": f"question {turn_index}"},
        }
        turn_items[turn_id] = [user_id]
        for assistant_index in range(assistants_per_turn):
            seq += 1
            item_id = f"{THREAD}:{turn_id}:a{assistant_index}"
            core_items[item_id] = {
                "item_id": item_id,
                "turn_id": turn_id,
                "type": "agentMessage",
                "seq": seq,
                "payload": {"type": "agentMessage", "text": f"answer {turn_index}.{assistant_index}"},
            }
            turn_items[turn_id].append(item_id)
    doc = {
        "thread_id": THREAD,
        "snapshot_seq": seq,
        "seen_event_ids": [],
        "turns": {
            turn_id: {"turn_id": turn_id, "status": "completed", "items": list(ids)}
            for turn_id, ids in turn_items.items()
        },
        "items": dict(user_items),
        "item_order": list(user_items),
        "requests": {},
        "queue": [],
        "artifacts": {},
        "status": "completed",
        "core": {
            "thread_id": THREAD,
            "snapshot_seq": seq,
            "items": {},
            "item_order": list(core_items),
            "turns": {
                turn_id: {"turn_id": turn_id, "status": "completed", "items": list(ids)}
                for turn_id, ids in turn_items.items()
            },
            "requests": {},
            "artifacts": {},
            "status": "completed",
            "resource_usage_version": 1,
        },
    }
    async with factory() as db:
        db.add(ThreadSnapshotRow(
            thread_id=THREAD, snapshot_seq=seq, revision=1, snapshot_json=doc
        ))
        for item in core_items.values():
            db.add(SnapshotItemRow(
                thread_id=THREAD,
                item_id=item["item_id"],
                seq=item["seq"],
                item_json=item,
            ))
        await db.commit()
    return store, factory, core_items, user_items, turn_items


def _context(store, factory) -> SimpleNamespace:
    class _Persistence:
        async def load_page_around(self, db, thread_id, *, item_id, item_byte_budget=None):
            kwargs = {"item_id": item_id}
            if item_byte_budget is not None:
                kwargs["item_byte_budget"] = int(item_byte_budget)
            return await store.load_page_around(db, thread_id, **kwargs)

        async def load(self, db, thread_id):
            return await store.load(db, thread_id)

    class _Factory:
        def __call__(self):
            return factory()

    return SimpleNamespace(
        session_factory=_Factory(),
        persistence=_Persistence(),
        host=SimpleNamespace(session_store=None),
    )


@pytest.mark.asyncio
async def test_resolve_item_seq_covers_rows_and_top_level_user_items(tmp_path):
    store, factory, core_items, user_items, _turns = await _store(tmp_path, turns=4, assistants_per_turn=2)
    async with factory() as db:
        for item_id, item in list(core_items.items())[:3]:
            assert await store.resolve_item_seq(db, THREAD, item_id) == item["seq"]
        for item_id, item in list(user_items.items())[:3]:
            # User messages have no item row: their seq lives in the metadata row.
            assert await store.resolve_item_seq(db, THREAD, item_id) == item["seq"]
        assert await store.resolve_item_seq(db, THREAD, "no-such-item") is None


@pytest.mark.asyncio
async def test_load_page_around_ends_at_the_target_and_reports_older_pages(tmp_path):
    store, factory, core_items, _user_items, _turns = await _store(tmp_path, turns=30, assistants_per_turn=4)
    target_id = f"{THREAD}:turn-010:a1"
    target_seq = core_items[target_id]["seq"]
    async with factory() as db:
        # A small budget keeps the read to the target's own neighbourhood, which
        # is what "the window containing the message" means.
        seq, page = await store.load_page_around(
            db, THREAD, item_id=target_id, item_byte_budget=1024
        )
    assert seq == target_seq
    loaded = page["core"]["items"]
    assert loaded, "the located page must carry rows"
    # Nothing newer than the target rides along: the page is the target's window.
    assert max(int(item["seq"]) for item in loaded.values()) <= target_seq
    assert page["core"]["_page_has_older_items"] is True

    built = _character_page_snapshot(
        page,
        before_item_id=None,
        before_seq=seq + 1,
        char_limit=200_000,
        turn_limit=2,
        byte_limit=64 * 1024,
        anchor_item_id=target_id,
        anchor_seq=seq,
    )
    history = built["history_page"]
    assert history["anchor_item_id"] == target_id
    assert history["anchor_seq"] == seq
    assert history["page_max_seq"] == seq
    assert history["has_more"] is True
    assert target_id in built["core"]["items"]
    # Store-internal paging hints never reach the wire page.
    assert "_page_total_items" not in built["core"]
    assert "_page_has_older_items" not in built["core"]


@pytest.mark.asyncio
async def test_load_page_around_reports_unknown_items_without_a_page(tmp_path):
    store, factory, _core, _user, _turns = await _store(tmp_path, turns=3, assistants_per_turn=1)
    async with factory() as db:
        seq, page = await store.load_page_around(db, THREAD, item_id="missing-item")
    assert seq is None
    assert (page.get("core") or {}).get("items") in ({}, None)


@pytest.mark.asyncio
async def test_thread_page_around_operation_returns_the_containing_window(tmp_path):
    store, factory, core_items, _user_items, _turns = await _store(tmp_path, turns=20, assistants_per_turn=3)
    target_id = f"{THREAD}:turn-005:a2"
    context = _context(store, factory)
    outcome = await handle_thread_page_around_operation(
        request_id=0,
        params={"thread_id": THREAD, "item_id": target_id, "turn_limit": 2, "page_bytes": 64 * 1024},
        context=context,
    )
    result = outcome.response["result"]
    assert result["found"] is True
    page = result["snapshot_page"]
    assert page["history_page"]["anchor_item_id"] == target_id
    assert target_id in page["core"]["items"]
    assert page["history_page"]["total_items"] == len(core_items) + 20


@pytest.mark.asyncio
async def test_thread_page_around_operation_rejects_unknown_items(tmp_path):
    store, factory, _core, _user, _turns = await _store(tmp_path, turns=2, assistants_per_turn=1)
    context = _context(store, factory)
    outcome = await handle_thread_page_around_operation(
        request_id=1,
        params={"thread_id": THREAD, "item_id": "missing-item"},
        context=context,
    )
    result = outcome.response["result"]
    assert result["found"] is False
    assert result["snapshot_page"] is None
