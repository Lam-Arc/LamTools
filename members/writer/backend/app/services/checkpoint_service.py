from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.writer.git import WriterGitManager, writer_checkpoint_branch
from app.models.session import WriterSession
from app.services.session_git_operation import (
    SessionGitClaim,
    claim_session_git_operation,
    clear_session_git_claim,
    require_session_git_claim,
)


class WriterCheckpointService:
    def __init__(self, *, git_manager: WriterGitManager, default_work_root: str) -> None:
        self._git = git_manager
        self._default_work_root = default_work_root

    async def ensure_repo(self, work_root: str) -> bool:
        if not work_root:
            return False
        if await self._git.is_repo(work_root):
            return True
        return await self._git.init_repo(work_root)

    async def checkpoint(
        self,
        db: AsyncSession,
        session: WriterSession,
        *,
        reason: str,
        label: str = "checkpoint",
        allow_empty: bool = False,
        turn_id: str | None = None,
        stage: str | None = None,
    ) -> dict[str, Any] | None:
        work_root = session.work_root or self._default_work_root
        if not work_root or not await self.ensure_repo(work_root):
            return None
        checkpoint = await self._git.checkpoint_all_to_branch(
            work_root,
            writer_checkpoint_branch(session.id),
            label=label,
            reason=reason,
            allow_empty=allow_empty,
        )
        if checkpoint is None:
            return None
        record = checkpoint.model_dump(mode="json")
        if turn_id:
            record["turn_id"] = turn_id
        if stage:
            record["stage"] = stage
        runtime_state = _runtime_state_dict(session)
        git_state = _git_state_dict(runtime_state)
        checkpoints = list(git_state.get("checkpoints", []))
        checkpoints.append(record)
        git_state["checkpoints"] = checkpoints[-50:]
        git_state["last_checkpoint"] = record
        runtime_state["git_state"] = git_state
        session.runtime_state = runtime_state
        session.updated_at = datetime.now(timezone.utc)
        return record

    async def checkpoint_if_dirty(
        self,
        db: AsyncSession,
        session: WriterSession,
        *,
        reason: str,
        turn_id: str | None = None,
        stage: str | None = None,
    ) -> dict[str, Any] | None:
        work_root = session.work_root or self._default_work_root
        if not work_root or not await self.ensure_repo(work_root):
            return None
        snapshot = await self._git.status_snapshot(work_root)
        if snapshot is None or not snapshot.dirty_files:
            return None
        return await self.checkpoint(db, session, reason=reason, label="checkpoint", turn_id=turn_id, stage=stage)

    async def create_checkpoint_if_dirty(
        self,
        *,
        session_id: str,
        work_root: str,
        reason: str,
        turn_id: str | None = None,
        stage: str | None = None,
    ) -> dict[str, Any] | None:
        root = work_root or self._default_work_root
        if not root or not await self.ensure_repo(root):
            return None
        snapshot = await self._git.status_snapshot(root)
        if snapshot is None or not snapshot.dirty_files:
            return None
        checkpoint = await self._git.checkpoint_all_to_branch(
            root,
            writer_checkpoint_branch(session_id),
            label="checkpoint",
            reason=reason,
            allow_empty=False,
        )
        if checkpoint is None:
            return None
        record = checkpoint.model_dump(mode="json")
        if turn_id:
            record["turn_id"] = turn_id
        if stage:
            record["stage"] = stage
        return record

    async def persist_checkpoint(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        record: dict[str, Any],
    ) -> None:
        session = await db.get(WriterSession, session_id)
        if session is None:
            raise LookupError("Session not found")
        runtime_state = _runtime_state_dict(session)
        git_state = _git_state_dict(runtime_state)
        checkpoints = list(git_state.get("checkpoints", []))
        checkpoints.append(dict(record))
        git_state["checkpoints"] = checkpoints[-50:]
        git_state["last_checkpoint"] = dict(record)
        runtime_state["git_state"] = git_state
        session.runtime_state = runtime_state
        session.updated_at = datetime.now(timezone.utc)


def _runtime_state_dict(session: WriterSession) -> dict[str, Any]:
    return dict(session.runtime_state or {})


def _git_state_dict(runtime_state: dict[str, Any]) -> dict[str, Any]:
    value = runtime_state.get("git_state")
    return dict(value) if isinstance(value, dict) else {}


_default_git_manager = WriterGitManager()


@dataclass(frozen=True)
class CheckpointCreateClaim:
    session: SessionGitClaim
    label: str
    reason: str
    allow_empty: bool


@dataclass(frozen=True)
class CheckpointRestoreClaim:
    session: SessionGitClaim
    commit: str


@dataclass(frozen=True)
class CheckpointRestoreExecution:
    auto_checkpoint: dict[str, Any] | None


async def claim_checkpoint_create(
    db: AsyncSession,
    session_id: str,
    *,
    label: str,
    reason: str,
    allow_empty: bool,
) -> CheckpointCreateClaim:
    session = await _get_session(db, session_id)
    if not session.work_root:
        raise ValueError("Session has no work_root set")
    return CheckpointCreateClaim(
        session=claim_session_git_operation(session, "checkpoint.create"),
        label=label,
        reason=reason,
        allow_empty=allow_empty,
    )


async def execute_checkpoint_create(claim: CheckpointCreateClaim) -> dict[str, Any] | None:
    service = WriterCheckpointService(git_manager=_default_git_manager, default_work_root="")
    if not await service.ensure_repo(claim.session.work_root):
        return None
    checkpoint = await _default_git_manager.checkpoint_all_to_branch(
        claim.session.work_root,
        writer_checkpoint_branch(claim.session.session_id),
        label=claim.label,
        reason=claim.reason,
        allow_empty=claim.allow_empty,
    )
    return checkpoint.model_dump(mode="json") if checkpoint is not None else None


async def persist_checkpoint_create(
    db: AsyncSession,
    claim: CheckpointCreateClaim,
    record: dict[str, Any] | None,
) -> dict[str, Any] | None:
    session = await _get_session(db, claim.session.session_id)
    runtime_state = require_session_git_claim(session, claim.session)
    if record is not None:
        git_state = _git_state_dict(runtime_state)
        checkpoints = list(git_state.get("checkpoints", []))
        if not any(item.get("commit") == record.get("commit") for item in checkpoints if isinstance(item, dict)):
            checkpoints.append(dict(record))
        git_state["checkpoints"] = checkpoints[-50:]
        git_state["last_checkpoint"] = dict(record)
        runtime_state["git_state"] = git_state
    clear_session_git_claim(runtime_state, claim.session)
    session.runtime_state = runtime_state
    session.updated_at = datetime.now(timezone.utc)
    return _checkpoint_response(record) if record is not None else None


async def claim_checkpoint_restore(
    db: AsyncSession,
    session_id: str,
    *,
    commit: str,
) -> CheckpointRestoreClaim:
    session = await _get_session(db, session_id)
    if not session.work_root:
        raise ValueError("Session has no work_root set")
    clean_commit = commit.strip()
    checkpoint_commits = {str(item.get("commit")) for item in _checkpoint_records(session)}
    if clean_commit not in checkpoint_commits:
        raise ValueError("Checkpoint is not part of this session")
    return CheckpointRestoreClaim(
        session=claim_session_git_operation(session, "checkpoint.restore"),
        commit=clean_commit,
    )


async def execute_checkpoint_restore(claim: CheckpointRestoreClaim) -> CheckpointRestoreExecution:
    if not await _default_git_manager.is_repo(claim.session.work_root):
        raise ValueError("Not a git repository")
    auto_checkpoint = None
    snapshot = await _default_git_manager.status_snapshot(claim.session.work_root)
    if snapshot and snapshot.dirty_files:
        checkpoint = await _default_git_manager.checkpoint_all_to_branch(
            claim.session.work_root,
            writer_checkpoint_branch(claim.session.session_id),
            label="checkpoint",
            reason="回退前自动存档",
            allow_empty=False,
        )
        auto_checkpoint = checkpoint.model_dump(mode="json") if checkpoint is not None else None
    if not await _default_git_manager.restore_checkpoint(claim.session.work_root, claim.commit):
        raise ValueError("Failed to restore checkpoint")
    return CheckpointRestoreExecution(auto_checkpoint=auto_checkpoint)


async def persist_checkpoint_restore(
    db: AsyncSession,
    claim: CheckpointRestoreClaim,
    execution: CheckpointRestoreExecution,
) -> dict[str, Any]:
    session = await _get_session(db, claim.session.session_id)
    runtime_state = require_session_git_claim(session, claim.session)
    git_state = _git_state_dict(runtime_state)
    if execution.auto_checkpoint is not None:
        checkpoints = list(git_state.get("checkpoints", []))
        if not any(
            item.get("commit") == execution.auto_checkpoint.get("commit")
            for item in checkpoints
            if isinstance(item, dict)
        ):
            checkpoints.append(dict(execution.auto_checkpoint))
        git_state["checkpoints"] = checkpoints[-50:]
        git_state["last_checkpoint"] = dict(execution.auto_checkpoint)
    git_state["last_restore"] = {
        "commit": claim.commit,
        "restored_at": datetime.now(timezone.utc).isoformat(),
    }
    runtime_state["git_state"] = git_state
    clear_session_git_claim(runtime_state, claim.session)
    session.runtime_state = runtime_state
    session.updated_at = datetime.now(timezone.utc)
    return {
        "status": "undone",
        "source": "checkpoint",
        "ref": claim.commit,
        "paths": [],
        "message": "已回退到所选检查点",
    }


async def list_session_checkpoint_responses(db: AsyncSession, session_id: str) -> list[dict[str, Any]]:
    session = await _get_session(db, session_id)
    return [_checkpoint_response(item) for item in reversed(_checkpoint_records(session))]


async def create_session_checkpoint_response(
    db: AsyncSession,
    session_id: str,
    *,
    label: str,
    reason: str,
    allow_empty: bool = False,
) -> dict[str, Any] | None:
    session = await _get_session(db, session_id)
    if not session.work_root:
        raise ValueError("Session has no work_root set")
    service = WriterCheckpointService(git_manager=_default_git_manager, default_work_root="")
    checkpoint = await service.checkpoint(
        db,
        session,
        label=label,
        reason=reason,
        allow_empty=allow_empty,
    )
    return _checkpoint_response(checkpoint) if checkpoint is not None else None


async def restore_session_checkpoint_response(
    db: AsyncSession,
    session_id: str,
    *,
    commit: str,
) -> dict[str, Any]:
    session = await _get_session(db, session_id)
    if not session.work_root:
        raise ValueError("Session has no work_root set")
    if not await _default_git_manager.is_repo(session.work_root):
        raise ValueError("Not a git repository")

    clean_commit = commit.strip()
    checkpoint_commits = {str(item.get("commit")) for item in _checkpoint_records(session)}
    if clean_commit not in checkpoint_commits:
        raise ValueError("Checkpoint is not part of this session")

    service = WriterCheckpointService(git_manager=_default_git_manager, default_work_root="")
    snapshot = await _default_git_manager.status_snapshot(session.work_root)
    if snapshot and snapshot.dirty_files:
        await service.checkpoint(
            db,
            session,
            label="checkpoint",
            reason="回退前自动存档",
            allow_empty=False,
        )
        await db.refresh(session)

    restored = await _default_git_manager.restore_checkpoint(session.work_root, clean_commit)
    if not restored:
        raise ValueError("Failed to restore checkpoint")

    runtime_state = _runtime_state_dict(session)
    git_state = _git_state_dict(runtime_state)
    git_state["last_restore"] = {"commit": clean_commit, "restored_at": datetime.now(timezone.utc).isoformat()}
    runtime_state["git_state"] = git_state
    session.runtime_state = runtime_state
    session.updated_at = datetime.now(timezone.utc)
    return {
        "status": "undone",
        "source": "checkpoint",
        "ref": clean_commit,
        "paths": [],
        "message": "已回退到所选检查点",
    }


async def _get_session(db: AsyncSession, session_id: str) -> WriterSession:
    result = await db.execute(select(WriterSession).where(WriterSession.id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise LookupError("Session not found")
    return session


def _checkpoint_records(session: WriterSession) -> list[dict[str, Any]]:
    git_state = _git_state_dict(_runtime_state_dict(session))
    records = git_state.get("checkpoints")
    if not isinstance(records, list):
        records = []
    normalized: list[dict[str, Any]] = []
    for item in records:
        if isinstance(item, dict) and item.get("commit"):
            normalized.append(dict(item))
    return normalized


def _checkpoint_response(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": str(item.get("label") or "checkpoint"),
        "reason": str(item.get("reason") or ""),
        "branch": item.get("branch"),
        "head": item.get("head"),
        "commit": item.get("commit"),
        "base_head": item.get("base_head"),
        "storage": item.get("storage"),
        "paths": [str(path) for path in item.get("paths", []) if path],
        "allow_empty": bool(item.get("allow_empty", False)),
        "created_at": str(item.get("created_at") or "") or None,
    }
