"""Bounded conversation reads: one page of items, never the whole thread.

Opening a session used to materialize every item row of the thread. On a long
thread that is thousands of rows of conversation content, which made the first
screen cost as much as reading the entire session — the failure mode was a
61-second open that exceeded the client's timeout and left the transcript blank.
These tests pin the bounded read: the newest page only, with a metadata-derived
paging envelope so older turns stay reachable.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lamtools_core.app.live_operations import (
    handle_thread_history_operation,
    handle_thread_outline_operation,
    handle_thread_read_operation,
)
from lamtools_core.app.snapshot_store import (
    CoreAppSnapshotProjector,
    SqlAlchemyThreadSnapshotStore,
)

THREAD = "thread-big"


class Base(DeclarativeBase):
    pass


class ThreadSnapshotRow(Base):
    __tablename__ = "page_thread_snapshots"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class SnapshotItemRow(Base):
    __tablename__ = "page_thread_snapshot_items"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


def _snapshot_doc(user_items: dict[str, dict]) -> dict:
    """Metadata row: turns + orders + the top-level user items.

    Real threads keep user messages in the top-level map (inside this row) and
    assistant process items as one row each in the item table; the fixture keeps
    that split so the outline and the bounded read are exercised the same way.
    """
    return {
        "thread_id": THREAD,
        "snapshot_seq": 10_000,
        "seen_event_ids": [],
        "turns": {},
        "items": dict(user_items),
        "item_order": list(user_items),
        "requests": {},
        "queue": [],
        "artifacts": {},
        "status": "completed",
        "core": {
            "thread_id": THREAD,
            "snapshot_seq": 10_000,
            "items": {},
            "item_order": [],
            "turns": {},
            "requests": {},
            "artifacts": {},
            "status": "completed",
            "resource_usage_version": 1,
        },
    }


async def _store(tmp_path, *, turns: int = 20, assistants_per_turn: int = 10, body_chars: int = 4_000):
    """A thread with `turns` turns: one top-level user item + N assistant rows each."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'page.db'}", future=True)
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
        turn_id = f"turn-{turn_index}"
        seq += 1
        user_id = f"{THREAD}:turn:{turn_id}:user"
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
            item_id = f"{THREAD}:turn:{turn_id}:a{assistant_index}"
            core_items[item_id] = {
                "item_id": item_id,
                "turn_id": turn_id,
                "type": "agentMessage",
                "seq": seq,
                "payload": {"type": "agentMessage", "text": "x" * body_chars},
            }
            turn_items[turn_id].append(item_id)
    doc = _snapshot_doc(user_items)
    doc["core"]["item_order"] = list(core_items)
    doc["core"]["turns"] = {
        turn_id: {"turn_id": turn_id, "status": "completed", "items": list(ids)}
        for turn_id, ids in turn_items.items()
    }
    async with factory() as db:
        db.add(ThreadSnapshotRow(
            thread_id=THREAD, snapshot_seq=10_000, snapshot_json=doc
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


@pytest.mark.asyncio
async def test_page_load_reads_only_the_newest_items(tmp_path):
    store, factory, items, _user_items, _turns = await _store(
        tmp_path, turns=40, assistants_per_turn=10, body_chars=4_000
    )
    total = len(items)
    async with factory() as db:
        page = await store.load_page(db, THREAD, item_byte_budget=64 * 1024)

    loaded = page["core"]["items"]
    assert 0 < len(loaded) < total, "the read must be bounded by the byte budget"
    # The loaded rows are the newest prefix of the thread's item rows.
    all_seqs = sorted(int(item["seq"]) for item in items.values())
    loaded_seqs = sorted(int(item["seq"]) for item in loaded.values())
    assert loaded_seqs == all_seqs[-len(loaded):]
    # The envelope still describes the whole thread.
    assert len(page["core"]["item_order"]) == total
    assert page["core"]["_page_has_older_items"] is True


@pytest.mark.asyncio
async def test_page_load_walks_backwards_with_the_cursor_and_then_stops(tmp_path):
    store, factory, items, _user_items, _turns = await _store(
        tmp_path, turns=6, assistants_per_turn=10, body_chars=4_000
    )
    total = len(items)
    seen: list[str] = []
    before_seq: int | None = None
    async with factory() as db:
        for _ in range(20):
            page = await store.load_page(
                db, THREAD, before_seq=before_seq, item_byte_budget=32 * 1024
            )
            loaded = page["core"]["items"]
            if not loaded:
                break
            seen.extend(loaded)
            before_seq = min(int(item["seq"]) for item in loaded.values())
            if not page["core"]["_page_has_older_items"]:
                break
    assert len(seen) == total, f"cursor walk must cover every item, got {len(seen)}"
    assert len(set(seen)) == total, "no item may be delivered twice"


class _HostPersistence:
    """`AppPersistenceHost`'s bounded-read surface over the test store."""

    def __init__(self, store) -> None:
        self.store = store

    async def load(self, db, thread_id: str):
        return await self.store.load(db, thread_id)

    async def load_page(
        self, db, thread_id: str, *, before_seq=None, before_item_id=None, item_byte_budget=None
    ):
        kwargs: dict = {"before_seq": before_seq, "before_item_id": before_item_id}
        if item_byte_budget is not None:
            kwargs["item_byte_budget"] = item_byte_budget
        return await self.store.load_page(db, thread_id, **kwargs)

    async def load_turn_tails(self, db, thread_id: str, *, per_turn_items: int = 3):
        return await self.store.load_turn_tails(db, thread_id, per_turn_items=per_turn_items)


class _SessionFactory:
    def __init__(self, factory) -> None:
        self._factory = factory

    def __call__(self):
        return self._factory()


class _MemberHooks:
    async def augment_thread_read(self, *, db, thread_id, result):
        return {}


def _context(store, factory) -> SimpleNamespace:
    return SimpleNamespace(
        session_factory=_SessionFactory(factory),
        persistence=_HostPersistence(store),
        host=SimpleNamespace(session_store=None, member_hooks=_MemberHooks()),
    )


@pytest.mark.asyncio
async def test_thread_read_serves_a_bounded_first_page_and_history_reassembles(tmp_path):
    store, factory, items, user_items, _turns = await _store(
        tmp_path, turns=20, assistants_per_turn=10, body_chars=4_000
    )
    total = len(items) + len(user_items)
    context = _context(store, factory)

    outcome = await handle_thread_read_operation(
        request_id=0, params={"thread_id": THREAD, "page_bytes": 64 * 1024}, context=context
    )
    page = outcome.response["result"]["snapshot"]
    history = page["history_page"]
    assert history["total_items"] == total
    assert history["has_more"] is True
    assert history["item_count"] < total, "the first page must not carry the whole thread"
    assert history["byte_count"] <= 64 * 1024

    seen = set(page["core"]["items"])
    cursor_id = history["next_before_item_id"]
    cursor_seq = history["next_before_seq"]
    for _ in range(60):
        if not history["has_more"]:
            break
        follow = await handle_thread_history_operation(
            request_id=1,
            params={
                "thread_id": THREAD,
                "before_item_id": cursor_id,
                "before_seq": cursor_seq,
                "page_bytes": 64 * 1024,
            },
            context=context,
        )
        older = follow.response["result"]["snapshot_page"]
        history = older["history_page"]
        seen.update(older["core"]["items"])
        cursor_id = history["next_before_item_id"]
        cursor_seq = history["next_before_seq"]
    assert seen == set(items), "paging must reassemble every item exactly"
    assert history["has_more"] is False


@pytest.mark.asyncio
async def test_thread_outline_keeps_every_turn_with_a_bounded_read(tmp_path):
    store, factory, _items, _user_items, turns = await _store(
        tmp_path, turns=20, assistants_per_turn=10, body_chars=400
    )
    context = _context(store, factory)
    outcome = await handle_thread_outline_operation(
        request_id=0, params={"thread_id": THREAD}, context=context
    )
    outlines = outcome.response["result"]["items"]
    assert len(outlines) == len(turns)
    assert all(item["prompt"] or item["response_excerpt"] for item in outlines)
