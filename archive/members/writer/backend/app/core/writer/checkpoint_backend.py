from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable
from typing import Any

from sqlalchemy import delete, select

from lamtools_core.app.snapshot_store import CoreAppSnapshotProjector
from lamtools_core.checkpoint import CoreCheckpointCoordinator, ForkConversationResult

from app.config import settings
from app.database import writer_write_coordinator
from app.models.app_server import WriterAppEvent, WriterThreadSnapshot
from app.models.message import WriterMessage
from app.models.session import WriterSession
from app.models.transcript import WriterTranscriptBlock, WriterTranscriptTurn
from app.services.session_fork_service import fork_session_response
from app.services.session_rollback_markers import with_rolled_back_metadata


_SESSION_FIELDS = (
    "phase", "mode", "status", "loop_position", "task_complexity", "planning_depth",
    "turn_count", "error_count", "transcript_revision", "todos", "open_loops",
    "context_summary", "task_plan", "runtime_state", "metadata_",
)
_TURN_FIELDS = (
    "status_cache", "final_reply_block_id", "started_at", "last_state_changed_at",
    "terminal_at", "terminal_reason", "error", "metadata_",
)


class WriterCheckpointConversationBackend:
    """Maps the Core checkpoint contract onto Writer-owned conversation tables."""

    def __init__(
        self,
        session_factory: Any,
        *,
        state_store: Any | None = None,
        state_invalidator: Callable[[str], None] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.state_store = state_store
        self.state_invalidator = state_invalidator

    async def capture(self, session_id: str, *, exclude_turn_id: str = "") -> dict[str, Any]:
        async with self.session_factory() as db:
            return await self._capture(db, session_id, exclude_turn_id=exclude_turn_id)

    async def _capture(self, db: Any, session_id: str, *, exclude_turn_id: str = "") -> dict[str, Any]:
        root_session_id = _root_session_id(session_id)
        session = await db.get(WriterSession, root_session_id)
        if session is None:
            raise LookupError("Session not found")
        turns = list((await db.execute(
            select(WriterTranscriptTurn)
            .where(WriterTranscriptTurn.session_id == root_session_id)
            .order_by(WriterTranscriptTurn.sequence.asc())
        )).scalars())
        excluded_message_ids = {
            str(turn.user_message_id) for turn in turns
            if turn.id == exclude_turn_id and turn.user_message_id
        }
        kept_turns = [turn for turn in turns if turn.id != exclude_turn_id]
        messages = list((await db.execute(
            select(WriterMessage)
            .where(WriterMessage.session_id == root_session_id)
            .order_by(WriterMessage.created_at.asc())
        )).scalars())
        events = list((await db.execute(
            select(WriterAppEvent)
            .where(WriterAppEvent.thread_id == root_session_id)
            .order_by(WriterAppEvent.seq.asc())
        )).scalars())
        kept_events = [event for event in events if str(event.turn_id or "") != exclude_turn_id]
        snapshot = await db.get(WriterThreadSnapshot, root_session_id)
        projection = deepcopy(dict(snapshot.snapshot_json or {})) if snapshot is not None else {}
        if exclude_turn_id and projection:
            CoreAppSnapshotProjector().remove_turns(projection, {exclude_turn_id})
        return {
            "session_id": session_id,
            "root_session_id": root_session_id,
            "last_visible_turn_id": kept_turns[-1].id if kept_turns else "",
            "session": {field: _json_value(getattr(session, field)) for field in _SESSION_FIELDS},
            "turns": [
                {
                    "id": turn.id,
                    "sequence": turn.sequence,
                    "user_message_id": turn.user_message_id,
                    **{field: _json_value(getattr(turn, field)) for field in _TURN_FIELDS},
                }
                for turn in kept_turns
            ],
            "messages": [
                {"id": message.id, "metadata_": _json_value(message.metadata_)}
                for message in messages
                if message.id not in excluded_message_ids
            ],
            "projection": (
                {
                    "snapshot_seq": int(snapshot.snapshot_seq or 0),
                    "snapshot_json": projection,
                }
                if snapshot is not None else None
            ),
            "events": [_event_payload(event) for event in kept_events],
        }

    async def restore(self, db: Any, session_id: str, payload: dict[str, Any]) -> None:
        root_session_id = str(payload.get("root_session_id") or _root_session_id(session_id))
        session = await db.get(WriterSession, root_session_id)
        if session is None:
            raise LookupError("Session not found")
        session_payload = payload.get("session")
        if not isinstance(session_payload, dict):
            raise ValueError("Writer checkpoint conversation is incomplete")
        for field in _SESSION_FIELDS:
            if field in session_payload:
                setattr(session, field, _restore_value(field, session_payload[field]))

        saved_turns = {
            str(item.get("id") or ""): item
            for item in list(payload.get("turns") or [])
            if isinstance(item, dict) and item.get("id")
        }
        current_turns = list((await db.execute(
            select(WriterTranscriptTurn)
            .where(WriterTranscriptTurn.session_id == root_session_id)
            .order_by(WriterTranscriptTurn.sequence.asc())
        )).scalars())
        marker = {
            "reason": "checkpoint_restore",
            "rolled_back_at": datetime.now(timezone.utc).isoformat(),
            "checkpoint_session_id": session_id,
        }
        extra_turns: list[WriterTranscriptTurn] = []
        for turn in current_turns:
            saved = saved_turns.get(turn.id)
            if saved is None:
                turn.metadata_ = with_rolled_back_metadata(turn.metadata_, marker)
                extra_turns.append(turn)
                continue
            for field in _TURN_FIELDS:
                if field in saved:
                    setattr(turn, field, _restore_value(field, saved[field]))

        saved_messages = {
            str(item.get("id") or ""): item
            for item in list(payload.get("messages") or [])
            if isinstance(item, dict) and item.get("id")
        }
        messages = list((await db.execute(
            select(WriterMessage).where(WriterMessage.session_id == root_session_id)
        )).scalars())
        for message in messages:
            saved = saved_messages.get(message.id)
            if saved is not None:
                message.metadata_ = deepcopy(saved.get("metadata_"))
        await _mark_extra_messages(db, messages=messages, turns=extra_turns, marker=marker)

        projection_payload = payload.get("projection")
        projection = await db.get(WriterThreadSnapshot, root_session_id)
        if isinstance(projection_payload, dict):
            if projection is None:
                projection = WriterThreadSnapshot(thread_id=root_session_id)
                db.add(projection)
            projection.snapshot_seq = int(projection_payload.get("snapshot_seq") or 0)
            projection.snapshot_json = deepcopy(dict(projection_payload.get("snapshot_json") or {}))
            projection.updated_at = datetime.now()
        elif projection is not None:
            await db.delete(projection)

        await db.execute(delete(WriterAppEvent).where(WriterAppEvent.thread_id == root_session_id))
        for event_payload in list(payload.get("events") or []):
            if isinstance(event_payload, dict):
                db.add(_event_row(event_payload, root_session_id))
        session.transcript_revision = int(session.transcript_revision or 0) + 1
        session.updated_at = datetime.now()
        invalidate = getattr(self.state_store, "invalidate", None)
        if callable(invalidate):
            invalidate(root_session_id)
        if self.state_invalidator is not None:
            self.state_invalidator(root_session_id)

    async def require_inactive(self, session_id: str) -> None:
        root_session_id = _root_session_id(session_id)
        async with self.session_factory() as db:
            session = await db.get(WriterSession, root_session_id)
            snapshot = await db.get(WriterThreadSnapshot, root_session_id)
        if session is None:
            raise LookupError("Session not found")
        session_status = str(session.status or "").lower()
        projection_status = str((snapshot.snapshot_json or {}).get("status") or "").lower() if snapshot else ""
        if session_status in {"running", "waiting", "interrupting"} or projection_status in {
            "running", "waiting", "interrupting",
        }:
            raise ValueError("Session has an active turn; cancel or finish it before rollback")

    async def fork(
        self,
        db: Any,
        *,
        source_session_id: str,
        new_session_id: str,
        payload: dict[str, Any],
        title: str,
        options: dict[str, Any],
    ) -> ForkConversationResult:
        response = await fork_session_response(
            db,
            source_session_id,
            fork_id=new_session_id,
            after_turn_id=str(payload.get("last_visible_turn_id") or "") or None,
            title=title or None,
            isolated_worktree=bool(options.get("isolated_worktree") or options.get("isolatedWorktree")),
        )
        conversation = await self._capture(db, new_session_id)
        return ForkConversationResult(conversation=conversation, session_payload=response)


def writer_checkpoint_coordinator(
    work_root: str | Path,
    *,
    session_factory: Any,
    state_store: Any | None = None,
) -> CoreCheckpointCoordinator:
    return CoreCheckpointCoordinator(
        work_root=work_root,
        session_factory=session_factory,
        write_coordinator=writer_write_coordinator(session_factory),
        storage_root=Path(settings.data_dir) / "checkpoints",
        conversation_backend=WriterCheckpointConversationBackend(session_factory, state_store=state_store),
    )


async def writer_session_work_root(session_factory: Any, session_id: str) -> str:
    async with session_factory() as db:
        session = await db.get(WriterSession, _root_session_id(session_id))
    if session is None:
        raise LookupError("Session not found")
    return str(Path(session.work_root or settings.writer_work_root).resolve())


async def _mark_extra_messages(
    db: Any,
    *,
    messages: list[WriterMessage],
    turns: list[WriterTranscriptTurn],
    marker: dict[str, Any],
) -> None:
    if not turns:
        return
    user_ids = {str(turn.user_message_id) for turn in turns if turn.user_message_id}
    final_ids = {str(turn.final_reply_block_id) for turn in turns if turn.final_reply_block_id}
    final_texts: set[str] = set()
    if final_ids:
        blocks = list((await db.execute(
            select(WriterTranscriptBlock).where(WriterTranscriptBlock.id.in_(final_ids))
        )).scalars())
        final_texts = {str(block.content or "") for block in blocks if str(block.content or "")}
    for message in messages:
        if message.id in user_ids or (message.role == "assistant" and str(message.content or "") in final_texts):
            message.metadata_ = with_rolled_back_metadata(message.metadata_, marker)


def _event_payload(event: WriterAppEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "seq": int(event.seq or 0),
        "turn_id": event.turn_id,
        "item_id": event.item_id,
        "parent_item_id": event.parent_item_id,
        "client_message_id": event.client_message_id,
        "method": event.method,
        "payload_json": deepcopy(dict(event.payload_json or {})),
        "created_at": _json_value(event.created_at),
        "persisted_at": _json_value(event.persisted_at),
    }


def _event_row(payload: dict[str, Any], thread_id: str) -> WriterAppEvent:
    return WriterAppEvent(
        event_id=str(payload.get("event_id") or ""),
        thread_id=thread_id,
        seq=int(payload.get("seq") or 0),
        turn_id=str(payload.get("turn_id") or "") or None,
        item_id=str(payload.get("item_id") or "") or None,
        parent_item_id=str(payload.get("parent_item_id") or "") or None,
        client_message_id=str(payload.get("client_message_id") or "") or None,
        method=str(payload.get("method") or ""),
        payload_json=deepcopy(dict(payload.get("payload_json") or {})),
        created_at=_datetime_value(payload.get("created_at")) or datetime.now(),
        persisted_at=_datetime_value(payload.get("persisted_at")) or datetime.now(),
    )


def _restore_value(field: str, value: Any) -> Any:
    if field in {"started_at", "last_state_changed_at", "terminal_at"}:
        return _datetime_value(value)
    return deepcopy(value)


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return deepcopy(value)


def _datetime_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _root_session_id(session_id: str) -> str:
    return str(session_id).split(":sub:", 1)[0]


__all__ = [
    "WriterCheckpointConversationBackend",
    "writer_checkpoint_coordinator",
    "writer_session_work_root",
]
