"""Checkpoint inventory baselines and superseded-checkpoint pruning.

Two read/write maintenance passes live here, both using the same scope guard,
file-level backup, single-transaction write and per-session verification as
``maintenance.strip_snapshot_registry_images``:

* :func:`capture_checkpoint_baseline` freezes the *shape and size* of every
  checkpoint (and every session's checkpoint history copies) into one JSON
  document, with a single content digest so a later pass can be compared to it.
  This is the reference the compaction/rollback dialogue-log work is measured
  against.  It mutates nothing.

* :func:`prune_superseded_checkpoints` deletes checkpoints a session no longer
  needs, keeping the newest one per session.  Every checkpoint carries a full
  copy of that session's model-visible history, which is the dominant storage
  consumer; keeping only the newest copy per session is what makes the copy
  budget collapse.  The user has accepted that old data loses rollback depth and
  that these copies may be deleted, on the condition that every session still
  opens cleanly — which is exactly what the per-session verification asserts.

Safety rules (all of them, always applied):

* only the repository's local development data directory may be targeted,
  unless ``allow_non_dev`` is passed explicitly (the CLI never does);
* the newest checkpoint of every session is kept;
* a session with a turn in flight (live runtime owner, or an active turn in its
  snapshot) is skipped entirely;
* a checkpoint referenced by a restore operation is never deleted;
* deletions and parent re-linking happen in one write transaction after a
  file-level backup;
* every affected session is re-loaded through the real readers afterwards
  (snapshot assembly, runtime state, history) and reported;
* repeated runs are idempotent — a second pass finds nothing to delete.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy import text as _text

from .app.core_db import (
    CoreCheckpoint,
    CoreCheckpointV2,
    CoreCheckpointV2Materialized,
    CoreCheckpointV2SessionHistory,
    CoreCheckpointV2SessionMessages,
    CoreDialogueRecord,
    CoreRestoreOperation,
    CoreThreadSnapshot,
    open_core_app_db,
)
from .maintenance import (
    BackupRecord,
    MaintenanceScopeError,
    backup_database_files,
    dev_data_dir,
    is_dev_data_dir,
)
from .runtime_owner import state_row_is_live

BASELINE_FORMAT_VERSION = 1

__all__ = [
    "BASELINE_FORMAT_VERSION",
    "CheckpointBaseline",
    "CheckpointPruneReport",
    "PruneSessionResult",
    "capture_checkpoint_baseline",
    "compare_checkpoint_baseline",
    "prune_superseded_checkpoints",
    "verify_dialogue_records",
]


# --------------------------------------------------------------------------- #
# Baseline
# --------------------------------------------------------------------------- #


@dataclass
class CheckpointBaseline:
    db_path: str
    created_at: str
    format_version: int = BASELINE_FORMAT_VERSION
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    sessions: list[dict[str, Any]] = field(default_factory=list)
    checkpoint_count: int = 0
    session_count: int = 0
    history_bytes: int = 0
    session_messages_bytes: int = 0
    runtime_state_bytes: int = 0
    conversation_bytes: int = 0
    content_digest: str = ""
    db_file_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "db_path": self.db_path,
            "created_at": self.created_at,
            "checkpoint_count": self.checkpoint_count,
            "session_count": self.session_count,
            "history_bytes": self.history_bytes,
            "session_messages_bytes": self.session_messages_bytes,
            "runtime_state_bytes": self.runtime_state_bytes,
            "conversation_bytes": self.conversation_bytes,
            "db_file_bytes": self.db_file_bytes,
            "content_digest": self.content_digest,
            "sessions": self.sessions,
            "checkpoints": self.checkpoints,
        }


def _json_len(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _summary_len(runtime_state_json: Any) -> int:
    if not isinstance(runtime_state_json, dict):
        return 0
    metadata = runtime_state_json.get("metadata")
    if not isinstance(metadata, dict):
        return 0
    compaction = metadata.get("context_compaction")
    if not isinstance(compaction, dict):
        return 0
    return len(str(compaction.get("summary") or ""))


def _compaction_present(runtime_state_json: Any) -> bool:
    if not isinstance(runtime_state_json, dict):
        return False
    metadata = runtime_state_json.get("metadata")
    return isinstance(metadata, dict) and isinstance(metadata.get("context_compaction"), dict)


async def capture_checkpoint_baseline(db_path: Path | str) -> CheckpointBaseline:
    """Read every checkpoint's shape and size.  Mutates nothing."""
    db_path = Path(db_path)
    baseline = CheckpointBaseline(
        db_path=str(db_path),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    db = await open_core_app_db(db_path)
    try:
        async with db.session_factory() as session:
            legacy = {
                str(row.id): row
                for row in (await session.execute(select(CoreCheckpoint))).scalars()
            }
            v2 = {
                str(row.id): row
                for row in (await session.execute(select(CoreCheckpointV2))).scalars()
            }
            history_rows = {
                str(row.checkpoint_id): _json_len(row.history_json)
                for row in (
                    await session.execute(select(CoreCheckpointV2SessionHistory))
                ).scalars()
            }
            message_rows = {
                str(row.checkpoint_id): _json_len(row.messages_json)
                for row in (
                    await session.execute(select(CoreCheckpointV2SessionMessages))
                ).scalars()
            }
            materialized_ids = {
                str(row.checkpoint_id)
                for row in (
                    await session.execute(select(CoreCheckpointV2Materialized))
                ).scalars()
            }

        by_session: dict[str, dict[str, Any]] = {}
        for checkpoint_id, row in sorted(legacy.items()):
            v2_row = v2.get(checkpoint_id)
            runtime_state = v2_row.runtime_state_json if v2_row is not None else None
            entry = {
                "checkpoint_id": checkpoint_id,
                "session_id": str(row.session_id or ""),
                "root_session_id": str(row.root_session_id or ""),
                "reason": str(row.reason or ""),
                "actor_kind": str(row.actor_kind or ""),
                "status": str(row.status or ""),
                "v2_present": v2_row is not None,
                "event_seq": int(getattr(v2_row, "event_seq", 0) or 0),
                "history_seq": int(getattr(v2_row, "history_seq", 0) or 0),
                "created_at": str(getattr(row, "created_at", "") or ""),
                "history_bytes": int(history_rows.get(checkpoint_id, 0)),
                "session_messages_bytes": int(message_rows.get(checkpoint_id, 0)),
                "runtime_state_bytes": _json_len(runtime_state),
                "conversation_bytes": _json_len(getattr(row, "conversation_json", None)),
                "materialized": checkpoint_id in materialized_ids,
                "has_compaction_state": _compaction_present(runtime_state),
                "compaction_summary_chars": _summary_len(runtime_state),
            }
            baseline.checkpoints.append(entry)
            bucket = by_session.setdefault(
                entry["session_id"],
                {
                    "session_id": entry["session_id"],
                    "checkpoint_count": 0,
                    "history_bytes": 0,
                    "session_messages_bytes": 0,
                    "runtime_state_bytes": 0,
                    "conversation_bytes": 0,
                    "reasons": {},
                },
            )
            bucket["checkpoint_count"] += 1
            bucket["history_bytes"] += entry["history_bytes"]
            bucket["session_messages_bytes"] += entry["session_messages_bytes"]
            bucket["runtime_state_bytes"] += entry["runtime_state_bytes"]
            bucket["conversation_bytes"] += entry["conversation_bytes"]
            bucket["reasons"][entry["reason"]] = bucket["reasons"].get(entry["reason"], 0) + 1

        baseline.sessions = [
            {**bucket, "reasons": dict(sorted(bucket["reasons"].items()))}
            for _, bucket in sorted(by_session.items())
        ]
        baseline.checkpoint_count = len(baseline.checkpoints)
        baseline.session_count = len(baseline.sessions)
        baseline.history_bytes = sum(item["history_bytes"] for item in baseline.checkpoints)
        baseline.session_messages_bytes = sum(
            item["session_messages_bytes"] for item in baseline.checkpoints
        )
        baseline.runtime_state_bytes = sum(
            item["runtime_state_bytes"] for item in baseline.checkpoints
        )
        baseline.conversation_bytes = sum(
            item["conversation_bytes"] for item in baseline.checkpoints
        )
        baseline.content_digest = _digest(baseline.checkpoints)
        baseline.db_file_bytes = db_path.stat().st_size if db_path.is_file() else 0
        return baseline
    finally:
        await db.close()


def compare_checkpoint_baseline(
    baseline: dict[str, Any], current: CheckpointBaseline
) -> dict[str, Any]:
    """Diff ``current`` against a previously captured baseline document."""
    previous = {
        str(item.get("checkpoint_id")): item
        for item in (baseline.get("checkpoints") or [])
        if isinstance(item, dict)
    }
    now = {item["checkpoint_id"]: item for item in current.checkpoints}
    added = sorted(set(now) - set(previous))
    removed = sorted(set(previous) - set(now))
    resized = [
        {
            "checkpoint_id": checkpoint_id,
            "history_bytes_before": int(previous[checkpoint_id].get("history_bytes") or 0),
            "history_bytes_after": int(now[checkpoint_id].get("history_bytes") or 0),
        }
        for checkpoint_id in sorted(set(now) & set(previous))
        if int(previous[checkpoint_id].get("history_bytes") or 0)
        != int(now[checkpoint_id].get("history_bytes") or 0)
    ]
    return {
        "checkpoints_added": added,
        "checkpoints_removed": removed,
        "history_bytes_changed": resized,
        "history_bytes_before": int(baseline.get("history_bytes") or 0),
        "history_bytes_after": int(current.history_bytes),
        "history_bytes_saved": max(0, int(baseline.get("history_bytes") or 0) - current.history_bytes),
        "digest_before": str(baseline.get("content_digest") or ""),
        "digest_after": current.content_digest,
        "identical": str(baseline.get("content_digest") or "") == current.content_digest,
    }


# --------------------------------------------------------------------------- #
# Prune
# --------------------------------------------------------------------------- #


@dataclass
class PruneSessionResult:
    session_id: str
    checkpoint_total: int = 0
    kept: int = 0
    planned: int = 0
    deleted: int = 0
    skipped_in_flight: bool = False
    skipped_reason: str = ""
    bytes_before: int = 0
    bytes_after: int = 0
    verified: bool = False
    readable: bool = False
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "checkpoint_total": self.checkpoint_total,
            "kept": self.kept,
            "planned": self.planned,
            "deleted": self.deleted,
            "skipped_in_flight": self.skipped_in_flight,
            "skipped_reason": self.skipped_reason,
            "bytes_before": self.bytes_before,
            "bytes_after": self.bytes_after,
            "bytes_saved": max(0, self.bytes_before - self.bytes_after),
            "verified": self.verified,
            "readable": self.readable,
            "detail": self.detail,
        }


@dataclass
class CheckpointPruneReport:
    db_path: str
    data_dir: str
    applied: bool
    already_clean: bool = False
    keep_recent: int = 1
    backup: BackupRecord | None = None
    sessions_total: int = 0
    sessions_skipped_in_flight: int = 0
    checkpoints_total: int = 0
    checkpoints_planned: int = 0
    checkpoints_deleted: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    db_file_bytes_before: int = 0
    db_file_bytes_after: int = 0
    sessions: list[PruneSessionResult] = field(default_factory=list)
    error: str = ""

    @property
    def bytes_saved(self) -> int:
        return max(0, self.bytes_before - self.bytes_after)

    @property
    def ok(self) -> bool:
        if self.error:
            return False
        if not self.applied or self.already_clean:
            return True
        return all(
            item.readable and item.verified
            for item in self.sessions
            if item.deleted or item.planned
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "db_path": self.db_path,
            "data_dir": self.data_dir,
            "applied": self.applied,
            "already_clean": self.already_clean,
            "keep_recent": self.keep_recent,
            "backup": self.backup.to_dict() if self.backup else None,
            "sessions_total": self.sessions_total,
            "sessions_skipped_in_flight": self.sessions_skipped_in_flight,
            "checkpoints_total": self.checkpoints_total,
            "checkpoints_planned": self.checkpoints_planned,
            "checkpoints_deleted": self.checkpoints_deleted,
            "bytes_before": self.bytes_before,
            "bytes_after": self.bytes_after,
            "bytes_saved": self.bytes_saved,
            "db_file_bytes_before": self.db_file_bytes_before,
            "db_file_bytes_after": self.db_file_bytes_after,
            "ok": self.ok,
            "error": self.error,
            "sessions": [item.to_dict() for item in self.sessions],
        }


@dataclass
class _Plan:
    session_id: str
    keep: list[str]
    delete: list[str]
    bytes_before: int
    referenced: list[str]
    in_flight: bool = False
    detail: str = ""


async def _session_in_flight(session: Any, session_id: str) -> tuple[bool, str]:
    state_row = (
        await session.execute(
            _text("SELECT runtime_state_json FROM core_runtime_sessions WHERE thread_id = :tid"),
            {"tid": session_id},
        )
    ).first()
    if state_row is not None and isinstance(state_row[0], (dict, str)):
        payload = state_row[0]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                payload = {}
        if state_row_is_live(payload):
            return True, "runtime state belongs to a live run"
    active = (
        await session.execute(
            select(CoreThreadSnapshot.active_turn_id).where(
                CoreThreadSnapshot.thread_id == session_id
            )
        )
    ).scalar_one_or_none()
    if active:
        return True, f"snapshot has an active turn ({active})"
    return False, ""


async def _plan_prune(db: Any, *, keep_recent: int) -> list[_Plan]:
    plans: list[_Plan] = []
    async with db.session_factory() as session:
        rows = list((await session.execute(select(CoreCheckpoint))).scalars())
        if not rows:
            return plans
        history_bytes = {
            str(row.checkpoint_id): _json_len(row.history_json)
            for row in (
                await session.execute(select(CoreCheckpointV2SessionHistory))
            ).scalars()
        }
        messages_bytes = {
            str(row.checkpoint_id): _json_len(row.messages_json)
            for row in (
                await session.execute(select(CoreCheckpointV2SessionMessages))
            ).scalars()
        }
        v2_runtime_bytes = {
            str(row.id): _json_len(row.runtime_state_json)
            for row in (await session.execute(select(CoreCheckpointV2))).scalars()
        }
        referenced = {
            str(value)
            for row in (await session.execute(select(CoreRestoreOperation))).scalars()
            for value in (
                row.target_checkpoint_id,
                row.undo_checkpoint_id,
                row.derived_checkpoint_id,
            )
            if value
        }

        by_session: dict[str, list[Any]] = {}
        for row in rows:
            by_session.setdefault(str(row.session_id or ""), []).append(row)

        for session_id, group in sorted(by_session.items()):
            ordered = sorted(
                group,
                key=lambda item: (
                    getattr(item, "created_at", None) or datetime.min,
                    str(item.id),
                ),
                reverse=True,
            )
            keep = [str(item.id) for item in ordered[: max(1, int(keep_recent))]]
            candidates = [str(item.id) for item in ordered[max(1, int(keep_recent)) :]]
            # A checkpoint referenced by a restore operation is never deleted.
            delete_ids = [cid for cid in candidates if cid not in referenced]
            referenced_here = [cid for cid in candidates if cid in referenced]
            bytes_before = sum(
                history_bytes.get(cid, 0)
                + messages_bytes.get(cid, 0)
                + v2_runtime_bytes.get(cid, 0)
                for cid in delete_ids
            )
            in_flight, detail = await _session_in_flight(session, session_id)
            plans.append(
                _Plan(
                    session_id=session_id,
                    keep=keep,
                    delete=delete_ids,
                    bytes_before=bytes_before,
                    referenced=referenced_here,
                    in_flight=in_flight,
                    detail=detail,
                )
            )
    return plans


async def _apply_prune(db: Any, plans: list[_Plan]) -> None:
    all_deleted = sorted({cid for plan in plans if not plan.in_flight for cid in plan.delete})
    if not all_deleted:
        return

    async def action(session: Any) -> None:
        # Re-link surviving children to the nearest surviving parent before the
        # rows disappear, so the checkpoint graph never points at a dead node.
        survivors = list(
            (
                await session.execute(
                    select(CoreCheckpoint).where(
                        CoreCheckpoint.parent_checkpoint_id.in_(all_deleted)
                    )
                )
            ).scalars()
        )
        for row in survivors:
            cursor = row.parent_checkpoint_id
            guard = 0
            while cursor and cursor in all_deleted and guard < 1024:
                guard += 1
                parent = await session.get(CoreCheckpoint, cursor)
                cursor = str(getattr(parent, "parent_checkpoint_id", "") or "")
            row.parent_checkpoint_id = cursor or ""
        await session.execute(
            delete(CoreCheckpointV2SessionHistory).where(
                CoreCheckpointV2SessionHistory.checkpoint_id.in_(all_deleted)
            )
        )
        await session.execute(
            delete(CoreCheckpointV2SessionMessages).where(
                CoreCheckpointV2SessionMessages.checkpoint_id.in_(all_deleted)
            )
        )
        await session.execute(
            delete(CoreCheckpointV2Materialized).where(
                CoreCheckpointV2Materialized.checkpoint_id.in_(all_deleted)
            )
        )
        await session.execute(
            delete(CoreCheckpointV2).where(CoreCheckpointV2.id.in_(all_deleted))
        )
        await session.execute(
            delete(CoreCheckpoint).where(CoreCheckpoint.id.in_(all_deleted))
        )
        # Any restore operation that still references a deleted checkpoint (a
        # defensive sweep; referenced candidates are skipped in planning) cannot
        # be satisfied any more.
        await session.execute(
            delete(CoreRestoreOperation).where(
                CoreRestoreOperation.target_checkpoint_id.in_(all_deleted)
                | CoreRestoreOperation.undo_checkpoint_id.in_(all_deleted)
                | CoreRestoreOperation.derived_checkpoint_id.in_(all_deleted)
            )
        )

    await db.persistence.write(action)


async def _verify_sessions(db: Any, report: CheckpointPruneReport) -> None:
    for result in report.sessions:
        if not result.planned and not result.deleted:
            result.readable = True
            result.verified = True
            continue
        try:
            async with db.session_factory() as session:
                state = await db.snapshot_store.load(session, result.session_id)
            if not isinstance(state, dict):
                raise RuntimeError("snapshot reader returned a non-object state")
            state_row = await db.runtime_state_store.get(result.session_id)
            history = await db.runtime_state_store.get_history(result.session_id)
            result.readable = True
            remaining = (
                await _count_checkpoints(db, result.session_id)
            )
            result.bytes_after = int(remaining["bytes"])
            result.detail = (
                f"loaded snapshot with {len(state.get('core', {}).get('items', {}) if isinstance(state.get('core'), dict) else {})} items; "
                f"runtime={'present' if state_row is not None else 'absent'}; "
                f"history_rows={len(history)}; checkpoints_remaining={remaining['count']}"
            )
            result.verified = True
        except Exception as exc:  # noqa: BLE001 — a broken session must be reported, not hidden
            result.readable = False
            result.verified = False
            result.detail = f"session load failed: {exc}"
            report.error = report.error or f"session '{result.session_id}' failed verification"


async def _count_checkpoints(db: Any, session_id: str) -> dict[str, int]:
    async with db.session_factory() as session:
        count = int(
            (
                await session.execute(
                    select(func.count()).select_from(CoreCheckpoint).where(
                        CoreCheckpoint.session_id == session_id
                    )
                )
            ).scalar_one()
        )
        checkpoint_ids = [
            str(value)
            for value in (
                await session.execute(
                    select(CoreCheckpoint.id).where(CoreCheckpoint.session_id == session_id)
                )
            ).scalars()
        ]
        bytes_total = 0
        if checkpoint_ids:
            history_bytes = int(
                (
                    await session.execute(
                        select(
                            func.coalesce(
                                func.sum(func.length(CoreCheckpointV2SessionHistory.history_json)), 0
                            )
                        ).where(
                            CoreCheckpointV2SessionHistory.checkpoint_id.in_(checkpoint_ids)
                        )
                    )
                ).scalar_one()
            )
            messages_bytes = int(
                (
                    await session.execute(
                        select(
                            func.coalesce(
                                func.sum(func.length(CoreCheckpointV2SessionMessages.messages_json)), 0
                            )
                        ).where(
                            CoreCheckpointV2SessionMessages.checkpoint_id.in_(checkpoint_ids)
                        )
                    )
                ).scalar_one()
            )
            bytes_total = history_bytes + messages_bytes
            runtime_bytes = int(
                (
                    await session.execute(
                        select(
                            func.coalesce(
                                func.sum(func.length(CoreCheckpointV2.runtime_state_json)), 0
                            )
                        ).where(CoreCheckpointV2.id.in_(checkpoint_ids))
                    )
                ).scalar_one()
            )
            bytes_total += runtime_bytes
    return {"count": count, "bytes": bytes_total}


async def prune_superseded_checkpoints(
    db_path: Path | str,
    *,
    apply: bool = False,
    keep_recent: int = 1,
    backup_root: Path | str | None = None,
    allow_non_dev: bool = False,
) -> CheckpointPruneReport:
    """Delete superseded checkpoints, keeping the newest per session.

    ``apply=False`` (the default) is a dry run: it plans and reports, and writes
    nothing.  ``apply=True`` backs the database files up first, performs all
    deletions in one transaction, then reloads every affected session through
    the real readers.  A second run is idempotent.
    """
    db_path = Path(db_path)
    if not allow_non_dev and not is_dev_data_dir(db_path.parent):
        raise MaintenanceScopeError(
            "checkpoint pruning runs only against the local development data "
            f"directory ({dev_data_dir()}); refusing '{db_path.parent}'. Installed "
            "user data directories are never touched."
        )
    keep_recent = max(1, int(keep_recent))
    report = CheckpointPruneReport(
        db_path=str(db_path),
        data_dir=str(db_path.parent),
        applied=bool(apply),
        keep_recent=keep_recent,
        db_file_bytes_before=db_path.stat().st_size if db_path.is_file() else 0,
    )
    db = await open_core_app_db(db_path)
    try:
        plans = await _plan_prune(db, keep_recent=keep_recent)
        report.sessions_total = len(plans)
        report.checkpoints_total = sum(len(plan.keep) + len(plan.delete) for plan in plans)
        for plan in plans:
            result = PruneSessionResult(
                session_id=plan.session_id,
                checkpoint_total=len(plan.keep) + len(plan.delete),
                kept=len(plan.keep),
                planned=len(plan.delete),
                skipped_in_flight=plan.in_flight,
                skipped_reason=plan.detail if plan.in_flight else "",
                bytes_before=plan.bytes_before,
                bytes_after=plan.bytes_before,
                verified=not plan.delete,
                readable=True,
            )
            report.sessions.append(result)
        report.checkpoints_planned = sum(
            0 if plan.in_flight else len(plan.delete) for plan in plans
        )
        report.sessions_skipped_in_flight = sum(1 for plan in plans if plan.in_flight)
        report.bytes_before = sum(
            0 if plan.in_flight else plan.bytes_before for plan in plans
        )

        if report.checkpoints_planned == 0:
            report.already_clean = True
            await _verify_sessions(db, report)
            report.checkpoints_deleted = 0
            report.db_file_bytes_after = report.db_file_bytes_before
            return report

        if not apply:
            report.checkpoints_deleted = 0
            report.bytes_after = report.bytes_before
            report.db_file_bytes_after = report.db_file_bytes_before
            return report

        report.backup = backup_database_files(
            db_path,
            backup_root=backup_root,
            label="prune-checkpoints",
            purpose="prune-checkpoints: file-level backup taken before deleting superseded checkpoints",
        )
        await _apply_prune(db, plans)
        for result, plan in zip(report.sessions, plans):
            if plan.in_flight:
                continue
            result.deleted = len(plan.delete)
        report.checkpoints_deleted = sum(item.deleted for item in report.sessions)
        await _verify_sessions(db, report)
        report.bytes_after = sum(item.bytes_after for item in report.sessions)
        try:
            async with db.session_factory() as session:
                await session.execute(_text("PRAGMA wal_checkpoint(TRUNCATE)"))
        except Exception:  # noqa: BLE001 — informational only
            pass
        report.db_file_bytes_after = db_path.stat().st_size if db_path.is_file() else 0
        return report
    finally:
        await db.close()


# --------------------------------------------------------------------------- #
# Dialogue-record verification
# --------------------------------------------------------------------------- #


async def verify_dialogue_records(
    db_path: Path | str, *, thread_id: str = ""
) -> dict[str, Any]:
    """Re-check every compaction control record's fidelity.  Read-only.

    For each compaction record the stored fields are re-hashed and compared to
    the ``sent_digest`` captured from the actual model request, which is the
    "the record rebuilds exactly what was sent" contract.  Rollback records are
    reported structurally (target watermark, detached range, branch epoch).
    """
    from .dialogue_records import (
        COMPACTION_RECORD,
        ROLLBACK_RECORD,
        verify_compaction_record,
    )

    db_path = Path(db_path)
    db = await open_core_app_db(db_path)
    try:
        async with db.session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(CoreDialogueRecord)
                        .order_by(CoreDialogueRecord.thread_id.asc(), CoreDialogueRecord.seq.asc())
                    )
                ).scalars()
            )
        records: list[dict[str, Any]] = []
        compaction_total = 0
        compaction_ok = 0
        max_record_bytes = 0
        max_record_ref: dict[str, Any] = {}
        for row in rows:
            if thread_id and str(row.thread_id) != thread_id:
                continue
            record = dict(row.record_json or {})
            kind = str(row.kind or record.get("kind") or "")
            record_bytes = len(
                json.dumps(record, ensure_ascii=False, default=str).encode("utf-8")
            )
            entry: dict[str, Any] = {
                "thread_id": str(row.thread_id),
                "seq": int(row.seq or 0),
                "kind": kind,
                "branch_epoch": int(row.branch_epoch or 0),
                "watermark": int(row.watermark or 0),
                # Inline retained messages make the record self-verifiable; the
                # byte size is reported so the cost stays observable until step 3
                # removes the inline copy.
                "record_bytes": record_bytes,
            }
            if record_bytes > max_record_bytes:
                max_record_bytes = record_bytes
                max_record_ref = {"thread_id": str(row.thread_id), "seq": int(row.seq or 0), "kind": kind}
            if kind == COMPACTION_RECORD:
                compaction_total += 1
                check = verify_compaction_record(record)
                entry.update(check)
                entry["trigger"] = str(record.get("trigger") or "")
                entry["summary_chars"] = len(str(record.get("summary") or ""))
                entry["folded"] = int((record.get("folded") or {}).get("count") or 0)
                entry["retained"] = len(record.get("retained") or [])
                entry["ok"] = bool(check.get("integrity") and check.get("fidelity"))
                if entry["ok"]:
                    compaction_ok += 1
            elif kind == ROLLBACK_RECORD:
                detached = record.get("detached") or {}
                entry.update(
                    {
                        "target_event_seq": int(record.get("target_event_seq") or 0),
                        "target_history_seq": int(record.get("target_history_seq") or 0),
                        "detached_events": int((detached.get("events") or {}).get("count") or 0),
                        "detached_history": int((detached.get("history") or {}).get("count") or 0),
                        "ok": True,
                    }
                )
            else:
                entry["ok"] = False
            records.append(entry)
    finally:
        await db.close()
    return {
        "db_path": str(db_path),
        "thread_id": thread_id,
        "records_total": len(records),
        "compaction_total": compaction_total,
        "compaction_ok": compaction_ok,
        "max_record_bytes": max_record_bytes,
        "max_record": max_record_ref,
        "records_bytes_total": sum(item["record_bytes"] for item in records),
        "ok": compaction_total == compaction_ok,
        "records": records,
    }
