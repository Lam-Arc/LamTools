"""An answered card must not invent a turn, and a stored one must be repaired.

An approval response used to carry a turn id derived from the resolved state's
run. For a delegated child that produced a turn id nobody owns: nothing ever
closed it, so it stayed `running` forever and the whole session kept reading as
running after all work had finished (reported 2026-10-14 as "a new chat is still
in running").
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lamtools_core.app.approval_resolution import ApprovalResolutionLifecycle
from lamtools_core.app.core_db import CoreThreadSnapshot
from lamtools_core.app.core_session_store import session_record_from_snapshot
from lamtools_core.app.snapshot_store import CoreAppSnapshotProjector, SqlAlchemyThreadSnapshotStore
from lamtools_core.event import RunItemEvent
from lamtools_core.runtime import RuntimeState
from lamtools_core.snapshot import apply_run_item_event_in_place

THREAD = "thread-orphan"
PARENT_TURN = f"{THREAD}:turn:parent-run"
CHILD_RUN = "child-run-1"
ORPHAN_TURN = f"{THREAD}:turn:{CHILD_RUN}"


class Base(DeclarativeBase):
    pass


class ThreadSnapshotRow(Base):
    __tablename__ = "orphan_thread_snapshots"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class SnapshotItemRow(Base):
    __tablename__ = "orphan_thread_snapshot_items"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


def _state(*, status: str = "completed") -> dict:
    return {
        "thread_id": THREAD,
        "snapshot_seq": 10,
        "status": status,
        "items": {},
        "item_order": [],
        "requests": {},
        "turns": {PARENT_TURN: {"turn_id": PARENT_TURN, "status": status, "items": [], "last_seq": 10}},
        "core": {
            "thread_id": THREAD,
            "snapshot_seq": 10,
            "status": status,
            "items": {},
            "item_order": [],
            "requests": {},
            "turns": {PARENT_TURN: {"turn_id": PARENT_TURN, "status": status, "items": [], "last_seq": 10}},
        },
    }


def _approval_response(turn_id: str, *, run_id: str, seq: int = 20) -> RunItemEvent:
    return RunItemEvent.from_dict({
        "kind": "approval_response",
        "thread_id": THREAD,
        "turn_id": turn_id,
        "run_id": run_id,
        "item_id": "call-question",
        "seq": seq,
        "status": "resolved",
        "payload": {"request_id": "call-question", "decision": "guide", "status": "resolved"},
    })


def test_approval_response_for_an_unknown_turn_does_not_create_one():
    state = _state()
    apply_run_item_event_in_place(state, _approval_response(ORPHAN_TURN, run_id=CHILD_RUN))

    assert ORPHAN_TURN not in state["turns"], "an unknown turn must not be invented"
    assert state["status"] == "completed", "the thread must keep the status its own turns earned"
    assert state["requests"]["call-question"]["status"] == "resolved", "the card still resolves"


def test_approval_response_resumes_the_turn_that_owns_the_card():
    state = _state(status="waiting")
    state["turns"][PARENT_TURN]["status"] = "waiting"
    state["core"]["turns"][PARENT_TURN]["status"] = "waiting"
    apply_run_item_event_in_place(state, _approval_response(PARENT_TURN, run_id="parent-run"))

    assert state["turns"][PARENT_TURN]["status"] == "running", "answering resumes its own turn"
    assert state["status"] == "running"


def test_answer_names_the_turn_that_renders_the_card():
    """A delegated child's answer names the parent turn, not the child's run."""
    child_state = RuntimeState(session_id=f"{THREAD}:sub:asker", run_id=CHILD_RUN)
    child_state.metadata = {
        "turn_id": f"{THREAD}:sub:asker:turn:{CHILD_RUN}",
        "actor_kind": "sub_agent",
        "delegated_session": {"parent_thread_id": THREAD, "parent_turn_id": PARENT_TURN},
    }
    lifecycle = ApprovalResolutionLifecycle(
        operation_name="approval.respond",
        thread_id=THREAD,
        state=child_state,
        state_store=None,  # type: ignore[arg-type]
        request_id="call-question",
        tool_call={"id": "call-question", "name": "question"},
        decision="guide",
        guidance="blue",
        persist_run_items=lambda _items: None,  # type: ignore[arg-type]
        run_items_from_events=lambda _events: [],
        snapshot_from_events=lambda _events: {},
    )
    assert lifecycle.approval_response_event().turn_id == PARENT_TURN


@pytest.mark.asyncio
async def test_read_repairs_a_stored_orphan_turn(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'orphan.db'}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = SqlAlchemyThreadSnapshotStore(
        ThreadSnapshotRow, item_model=SnapshotItemRow, projector=CoreAppSnapshotProjector()
    )
    # The poisoned shape as it was actually stored: the top-level copy of the
    # orphan carries no `last_kind` (only the core copy does), so the repair has
    # to merge the two containers before it can see what the turn is.
    stored = _state(status="running")
    stored["turns"][PARENT_TURN]["status"] = "completed"
    stored["core"]["turns"][PARENT_TURN]["status"] = "completed"
    stored["turns"][ORPHAN_TURN] = {
        "turn_id": ORPHAN_TURN, "status": "running", "items": [], "last_seq": 20, "run_id": CHILD_RUN,
    }
    stored["core"]["turns"][ORPHAN_TURN] = {
        "turn_id": ORPHAN_TURN, "status": "running", "items": [],
        "last_kind": "approval_response", "last_seq": 20, "run_id": CHILD_RUN,
    }
    async with factory() as db:
        db.add(ThreadSnapshotRow(thread_id=THREAD, snapshot_seq=20, snapshot_json=stored))
        await db.commit()

    async with factory() as db:
        loaded = await store.load(db, THREAD)
        paged = await store.load_page(db, THREAD)

    for snapshot in (loaded, paged):
        assert ORPHAN_TURN not in snapshot["turns"], snapshot["turns"]
        assert ORPHAN_TURN not in snapshot["core"]["turns"]
        assert snapshot["status"] == "completed", "the session must stop reading as running"
        assert PARENT_TURN in snapshot["turns"], "the real turn stays"


def test_session_list_reads_the_repaired_status():
    """The sidebar reads its status off the stored snapshot, not off a read.

    ``session_record_from_snapshot`` is what ``/sessions`` maps to, so the
    repair has to run there as well or the session list keeps showing a session
    as running while the conversation itself already reads completed.
    """
    stored = _state(status="running")
    stored["session"] = {"member_id": "core", "title": "调子代理提问", "metadata": {}}
    stored["turns"][PARENT_TURN]["status"] = "completed"
    stored["core"]["turns"][PARENT_TURN]["status"] = "completed"
    stored["turns"][ORPHAN_TURN] = {
        "turn_id": ORPHAN_TURN, "status": "running", "items": [], "last_seq": 20, "run_id": CHILD_RUN,
    }
    stored["core"]["turns"][ORPHAN_TURN] = {
        "turn_id": ORPHAN_TURN, "status": "running", "items": [],
        "last_kind": "approval_response", "last_seq": 20, "run_id": CHILD_RUN,
    }

    record = session_record_from_snapshot(
        CoreThreadSnapshot(thread_id=THREAD, snapshot_seq=20, snapshot_json=stored)
    )

    assert record.status == "completed"
    assert record.title == "调子代理提问", "the rest of the record is untouched"
