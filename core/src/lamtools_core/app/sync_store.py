"""Desktop change journal and snapshot builder for Local-First clients."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid
from types import SimpleNamespace
from typing import Any

from sqlalchemy import delete, func, select

from .core_db import (
    CoreProject,
    CoreSyncChange,
    CoreThreadSnapshot,
)
from .project_visuals import DEFAULT_PROJECT_COLOR_KEY, DEFAULT_PROJECT_ICON_KEY


SYNC_CURSOR_EXPIRED = "SYNC_CURSOR_EXPIRED"

# user:“Unexpected error: QueuePool limit of size 8 overflow 8 reached”+(同步日志是派生数据：
# 每条事件都复制一份完整 payload，实测涨到 3.3GB / 21 万行。保留最近这些行就够补差，
# 更早的让客户端改用一次全量快照，库不再无限膨胀)。
SYNC_JOURNAL_MAX_ROWS = 20000


class CoreSyncJournal:
    """Append-only global journal shared by all mobile sync connections."""

    def __init__(self, session_factory: Any, write_coordinator: Any, *, workspace_id: str = "") -> None:
        self.session_factory = session_factory
        self.write_coordinator = write_coordinator
        self.workspace_id = str(workspace_id or "").strip()

    def append(
        self,
        db: Any,
        *,
        entity_type: str,
        operation: str,
        entity_id: str,
        entity: dict[str, Any] | None = None,
        thread_id: str = "",
        change_id: str | None = None,
        event_type: str | None = None,
        revision: int = 0,
    ) -> CoreSyncChange:
        row = CoreSyncChange(
            change_id=change_id or f"sync_{uuid.uuid4().hex}",
            workspace_id=self.workspace_id,
            entity_type=str(entity_type),
            event_type=str(event_type or f"{entity_type}.{operation}"),
            operation=str(operation),
            entity_id=str(entity_id),
            thread_id=str(thread_id or ""),
            revision=max(0, int(revision or 0)),
            entity_json=dict(entity or {}),
        )
        db.add(row)
        return row

    async def prune(self, *, keep: int | None = None) -> int:
        """Drop the oldest journal rows, keeping a bounded replay window.

        Clients whose cursor falls behind the window get
        ``SYNC_CURSOR_EXPIRED`` and rebuild from one snapshot, which is the
        existing contract; the journal was never the durable source of truth.
        """
        limit = max(1, int(keep if keep is not None else SYNC_JOURNAL_MAX_ROWS))

        async def action(db: Any) -> int:
            newest = await db.scalar(select(func.coalesce(func.max(CoreSyncChange.seq), 0)))
            cutoff = int(newest or 0) - limit
            if cutoff <= 0:
                return 0
            result = await db.execute(
                delete(CoreSyncChange)
                .where(CoreSyncChange.seq <= cutoff)
                .execution_options(synchronize_session=False)
            )
            return int(result.rowcount or 0)

        return await self.write_coordinator.run(action)

    async def current_cursor(self, db: Any | None = None) -> int:
        statement = select(func.coalesce(func.max(CoreSyncChange.seq), 0))
        if self.workspace_id:
            statement = statement.where(CoreSyncChange.workspace_id == self.workspace_id)
        if db is not None:
            value = await db.scalar(statement)
            return int(value or 0)
        async with self.session_factory() as connection:
            value = await connection.scalar(statement)
            return int(value or 0)

    async def oldest_cursor(self, db: Any | None = None) -> int | None:
        statement = select(func.min(CoreSyncChange.seq))
        if self.workspace_id:
            statement = statement.where(CoreSyncChange.workspace_id == self.workspace_id)
        if db is not None:
            value = await db.scalar(statement)
            return int(value) if value is not None else None
        async with self.session_factory() as connection:
            value = await connection.scalar(statement)
            return int(value) if value is not None else None

    async def current_snapshot_revision(self, db: Any) -> int:
        """Return the highest durable thread snapshot revision in this scope."""

        value = await db.scalar(select(func.coalesce(func.max(CoreThreadSnapshot.revision), 0)))
        return int(value or 0)

    async def list_after(self, db: Any, cursor: int, *, limit: int = 500) -> list[dict[str, Any]]:
        statement = select(CoreSyncChange).where(CoreSyncChange.seq > int(cursor))
        if self.workspace_id:
            statement = statement.where(CoreSyncChange.workspace_id == self.workspace_id)
        result = await db.execute(
            statement
            .order_by(CoreSyncChange.seq.asc())
            .limit(max(1, min(int(limit), 2_000)))
        )
        return [self._to_dict(row) for row in result.scalars().all()]

    async def get_change(self, change_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as db:
            row = await db.scalar(select(CoreSyncChange).where(CoreSyncChange.change_id == change_id))
            return self._to_dict(row) if row is not None else None

    async def get_change_header(self, change_id: str) -> dict[str, Any] | None:
        # user:“调查并检修 constant 内 sunday 出现过的所有报错，整理并给出方案，然后修复，不要出错”+(实时事件已传正文，同步通知只需版本与游标，读取时也不装载大字段)。
        columns = [c for c in CoreSyncChange.__table__.columns if c.name != "entity_json"]
        async with self.session_factory() as db:
            row = (await db.execute(select(*columns).where(
                CoreSyncChange.change_id == change_id))).mappings().one_or_none()
        if row is None:
            return None
        if row["entity_type"] != "thread.event":
            return await self.get_change(change_id)
        header = self._to_dict(SimpleNamespace(**row, entity_json={}))
        header.pop("payload", None)
        header.pop("entity", None)
        return header

    async def build_snapshot(self, db: Any) -> dict[str, Any]:
        projects = (await db.execute(
            select(CoreProject).order_by(CoreProject.created_at.asc(), CoreProject.id.asc())
        )).scalars().all()
        thread_rows = (await db.execute(
            select(CoreThreadSnapshot).order_by(CoreThreadSnapshot.updated_at.desc())
        )).scalars().all()
        project_ids_by_root = {str(row.work_root): str(row.id) for row in projects}
        threads: list[dict[str, Any]] = []
        snapshot_revision = 0
        for row in thread_rows:
            state = dict(row.snapshot_json or {})
            row_revision = _snapshot_revision(row, state)
            snapshot_revision = max(snapshot_revision, row_revision)
            state["revision"] = row_revision
            state["snapshot_seq"] = int(row.snapshot_seq or state.get("snapshot_seq") or 0)
            session = state.get("session") if isinstance(state.get("session"), dict) else {}
            metadata = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
            project_id = metadata.get("project_id") or project_ids_by_root.get(str(metadata.get("work_root") or ""))
            threads.append({
                "id": row.thread_id,
                "project_id": project_id,
                "title": str(session.get("title") or row.thread_id),
                "status": str(state.get("status") or "idle"),
                "created_at": str(session.get("created_at") or ""),
                "updated_at": row.updated_at.isoformat() if row.updated_at else "",
                "metadata": dict(metadata),
                "revision": row_revision,
                "deleted": False,
            })
        return {
            "workspace_id": self.workspace_id,
            "workspace_revision": await self.current_cursor(db),
            "snapshot_revision": snapshot_revision,
            "projects": [
                {
                    "id": row.id,
                    "name": row.name,
                    "path": row.work_root,
                    "work_root": row.work_root,
                    "icon_key": str(getattr(row, "icon_key", DEFAULT_PROJECT_ICON_KEY) or DEFAULT_PROJECT_ICON_KEY),
                    "color_key": str(getattr(row, "color_key", DEFAULT_PROJECT_COLOR_KEY) or DEFAULT_PROJECT_COLOR_KEY),
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                    "updated_at": row.updated_at.isoformat() if row.updated_at else "",
                    "revision": max(1, int(row.revision or 1)),
                    "deleted": False,
                }
                for row in projects
            ],
            "threads": threads,
            # Conversation bodies are intentionally excluded from bootstrap.
            # A client fetches the selected thread through the character-
            # bounded thread.resume/thread.history flow instead.
            "snapshots": [],
            "messages": [],
        }

    async def sync(self, *, cursor: int | None, limit: int = 500) -> dict[str, Any]:
        async with self.session_factory() as db:
            current = await self.current_cursor(db)
            oldest = await self.oldest_cursor(db)
            snapshot_revision = await self.current_snapshot_revision(db)
            if cursor is not None and oldest is not None and int(cursor) < oldest - 1:
                return {
                    "ok": False,
                    "error": SYNC_CURSOR_EXPIRED,
                    "workspace_id": self.workspace_id,
                    "workspace_revision": current,
                    "snapshot_revision": snapshot_revision,
                    "cursor": current,
                    "oldest_cursor": oldest,
                }
            if cursor is None:
                snapshot = await self.build_snapshot(db)
                return {
                    "ok": True,
                    "mode": "snapshot",
                    "workspace_id": self.workspace_id,
                    "workspace_revision": current,
                    "snapshot_revision": snapshot_revision,
                    "snapshotVersion": current,
                    "cursor": current,
                    **snapshot,
                }
            changes = await self.list_after(db, int(cursor), limit=limit)
            next_cursor = int(changes[-1]["seq"]) if changes else current
            return {
                "ok": True,
                "mode": "delta",
                "workspace_id": self.workspace_id,
                "workspace_revision": current,
                "snapshot_revision": snapshot_revision,
                "snapshotVersion": current,
                "cursor": next_cursor,
                "has_more": next_cursor < current,
                "changes": changes,
            }

    def _to_dict(self, row: CoreSyncChange) -> dict[str, Any]:
        revision = int(row.revision or 0)
        entity = dict(row.entity_json or {})
        payload = {
            "seq": int(row.seq),
            "change_id": row.change_id,
            "workspace_id": row.workspace_id or self.workspace_id,
            "type": row.entity_type,
            "entity_type": row.entity_type,
            "event_type": row.event_type or f"{row.entity_type}.{row.operation}",
            "operation": row.operation,
            "entity_id": row.entity_id,
            "thread_id": row.thread_id,
            "revision": revision,
            # ``seq`` is the workspace-wide ordering anchor. Keep the explicit
            # field in the wire contract so clients never infer whether a
            # cursor is per-thread or global.
            "workspace_revision": int(row.seq),
            "snapshot_revision": revision,
            "payload": entity,
            "entity": entity,
            "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat()
            if row.created_at and row.created_at.tzinfo is None
            else (row.created_at.isoformat() if row.created_at else datetime.now(timezone.utc).isoformat()),
        }
        if entity.get("snapshot_required") is True:
            payload["snapshot_required"] = True
        return payload
def _snapshot_revision(row: Any, state: dict[str, Any] | None = None) -> int:
    value = getattr(row, "revision", None)
    if value is None and isinstance(state, dict):
        value = state.get("revision")
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


__all__ = ["CoreSyncJournal", "SYNC_CURSOR_EXPIRED"]
