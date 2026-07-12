from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import execute_writer_write, get_db, get_writer_write
from app.models.base import gen_uuid
from app.models.session import WriterSession
from app.services.session_management import (
    create_writer_session,
    delete_writer_session,
    get_writer_session_response,
    update_writer_session,
)
from app.services.checkpoint_service import (
    claim_checkpoint_create,
    claim_checkpoint_restore,
    execute_checkpoint_create,
    execute_checkpoint_restore,
    list_session_checkpoint_responses,
    persist_checkpoint_create,
    persist_checkpoint_restore,
)
from app.services.agent_branch_service import (
    abandon_agent_branch_response,
    get_agent_branch_diff_response,
    list_agent_branch_responses,
    merge_agent_branch_response,
)
from app.services.commit_review_service import (
    WorktreeChangedError,
    claim_commit_review_approval,
    decide_commit_review_response,
    execute_commit_review_approval,
    get_commit_review_response,
    persist_commit_review_approval,
)
from app.services.session_git_queries import get_git_graph_response, get_session_changes_response
from app.services.session_undo_service import (
    undo_session_changes_response,
    undo_session_file_change_response,
)
from app.services.session_projection import session_response_projected
from app.core.writer.git import WriterGitManager
from app.core.writer.core_kernel_adapter import schedule_writer_startup_prewarm
from app.routers.path_utils import normalize_work_root

logger = logging.getLogger(__name__)

router = APIRouter()

# Service reference — set from main.py lifespan
_service = None


# --- Request/Response Schemas ---

class SessionCreate(BaseModel):
    title: str = "New Session"
    work_root: str = ""
    mode: str = "EXECUTE"
    project_id: str | None = None


class SessionUpdate(BaseModel):
    title: str | None = None
    mode: str | None = None
    work_root: str | None = None
    project_id: str | None = None


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    work_root: str = ""
    branch: str | None = None
    phase: str = "idle"
    mode: str = "EXECUTE"
    status: str = "active"
    lifecycle: dict[str, Any] | None = None
    project_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ChangedFileResponse(BaseModel):
    path: str
    additions: int | None = None
    deletions: int | None = None
    binary: bool = False


class SessionChangesResponse(BaseModel):
    files: list[ChangedFileResponse] = []
    total_additions: int = 0
    total_deletions: int = 0
    diff_stat: str = ""
    diff: str = ""
    source: str = "git"
    ref: str | None = None


class SessionUndoChangesResponse(BaseModel):
    status: str
    source: str = ""
    ref: str | None = None
    paths: list[str] = []
    message: str = ""


class SessionUndoFileRequest(BaseModel):
    path: str


class SessionCheckpointCreate(BaseModel):
    label: str = "checkpoint"
    reason: str = "手动保存检查点"
    allow_empty: bool = False


class SessionCheckpointRestoreRequest(BaseModel):
    commit: str


class SessionCheckpointResponse(BaseModel):
    label: str
    reason: str = ""
    branch: str | None = None
    head: str | None = None
    commit: str | None = None
    base_head: str | None = None
    storage: str | None = None
    paths: list[str] = []
    allow_empty: bool = False
    created_at: str | None = None


class CommitReviewCreate(BaseModel):
    title: str
    summary: str
    how_to_review: str
    self_check: str = ""
    commit_message: str = ""


class CommitReviewDecision(BaseModel):
    action: str
    feedback: str = ""
    commit_message: str | None = None


class CommitReviewResponse(BaseModel):
    id: str = ""
    status: str = "none"
    title: str = ""
    summary: str = ""
    how_to_review: str = ""
    self_check: str = ""
    commit_message: str = ""
    files: list[ChangedFileResponse] = []
    total_additions: int = 0
    total_deletions: int = 0
    source: str = ""
    ref: str | None = None
    commit: str | None = None
    feedback: str = ""
    created_at: str = ""
    updated_at: str = ""


class AgentBranchResponse(BaseModel):
    branch: str
    head: str | None = None
    worktree: str = ""
    dirty: bool = False
    files: list[str] = []


class AgentBranchDiffResponse(BaseModel):
    branch: str
    diff: str = ""


class AgentBranchMergeRequest(BaseModel):
    branch: str


class AgentBranchActionResponse(BaseModel):
    status: str
    branch: str
    message: str = ""
    strategy: str = ""


# --- Session CRUD ---

@router.post("/sessions", response_model=SessionResponse)
async def create_session(body: SessionCreate, db: AsyncSession = Depends(get_db)):
    return await create_writer_session(
        db,
        title=body.title,
        work_root=body.work_root,
        mode=body.mode,
        project_id=body.project_id,
    )


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WriterSession)
        .order_by(WriterSession.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    sessions = result.scalars().all()
    return [await session_response_projected(db, session) for session in sessions]


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await get_writer_session_response(db, session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc


@router.patch("/sessions/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str, body: SessionUpdate, db: AsyncSession = Depends(get_db)
):
    try:
        return await update_writer_session(
            db,
            session_id,
            body.model_dump(exclude_unset=True),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await delete_writer_session(db, session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc


# --- Git Version Graph ---

_git_manager = WriterGitManager()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runtime_state(session: WriterSession) -> dict[str, Any]:
    return dict(session.runtime_state or {})


def _commit_review_response(review: dict[str, Any] | None) -> CommitReviewResponse:
    if not review:
        return CommitReviewResponse()
    files = [
        ChangedFileResponse.model_validate(item)
        for item in review.get("files", [])
        if isinstance(item, dict)
    ]
    return CommitReviewResponse(
        id=str(review.get("id") or ""),
        status=str(review.get("status") or "none"),
        title=str(review.get("title") or ""),
        summary=str(review.get("summary") or ""),
        how_to_review=str(review.get("how_to_review") or ""),
        self_check=str(review.get("self_check") or ""),
        commit_message=str(review.get("commit_message") or ""),
        files=files,
        total_additions=int(review.get("total_additions") or 0),
        total_deletions=int(review.get("total_deletions") or 0),
        source=str(review.get("source") or ""),
        ref=review.get("ref"),
        commit=review.get("commit"),
        feedback=str(review.get("feedback") or ""),
        created_at=str(review.get("created_at") or ""),
        updated_at=str(review.get("updated_at") or ""),
    )


def _review_dirty_hashes(snapshot: Any, files: list[ChangedFileResponse]) -> dict[str, str]:
    if snapshot is None:
        return {}
    file_paths = {item.path for item in files}
    return {
        path: value
        for path, value in snapshot.dirty_hashes.items()
        if path in file_paths
    }


async def _ensure_work_root_repo(work_root: str) -> bool:
    if not work_root:
        return False
    if await _git_manager.is_repo(work_root):
        return True
    return await _git_manager.init_repo(work_root)


@router.get("/sessions/{session_id}/git-graph")
async def get_git_graph(session_id: str, db: AsyncSession = Depends(get_db)):
    """Get the git version graph for the session's work root.

    Returns a branch-linear timeline (horizontal lanes per branch)
    that normal users can understand — not a full DAG.
    """
    try:
        return await get_git_graph_response(db, session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/changes", response_model=SessionChangesResponse)
async def get_session_changes(session_id: str, db: AsyncSession = Depends(get_db)):
    """Return real Git change stats for the session work root."""
    try:
        return SessionChangesResponse.model_validate(await get_session_changes_response(db, session_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/agent-branches", response_model=list[AgentBranchResponse])
async def list_session_agent_branches(session_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return [
            AgentBranchResponse.model_validate(item)
            for item in await list_agent_branch_responses(db, session_id)
        ]
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/agent-branches/diff", response_model=AgentBranchDiffResponse)
async def get_session_agent_branch_diff(
    session_id: str,
    branch: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        return AgentBranchDiffResponse.model_validate(
            await get_agent_branch_diff_response(db, session_id, branch)
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/agent-branches/merge", response_model=AgentBranchActionResponse)
async def merge_session_agent_branch(
    session_id: str,
    request: AgentBranchMergeRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return AgentBranchActionResponse.model_validate(
            await merge_agent_branch_response(db, session_id, request.branch)
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/agent-branches/abandon", response_model=AgentBranchActionResponse)
async def abandon_session_agent_branch(
    session_id: str,
    request: AgentBranchMergeRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return AgentBranchActionResponse.model_validate(
            await abandon_agent_branch_response(db, session_id, request.branch)
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/checkpoints", response_model=list[SessionCheckpointResponse])
async def list_session_checkpoints(session_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return [
            SessionCheckpointResponse.model_validate(item)
            for item in await list_session_checkpoint_responses(db, session_id)
        ]
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/checkpoints", response_model=SessionCheckpointResponse)
async def create_session_checkpoint(
    session_id: str,
    body: SessionCheckpointCreate,
    db: AsyncSession = Depends(get_db),
    write_transaction=Depends(get_writer_write),
):
    try:
        claim = await execute_writer_write(db, lambda write_db: claim_checkpoint_create(
            write_db, session_id,
            label=body.label or "checkpoint",
            reason=body.reason or "手动保存检查点",
            allow_empty=body.allow_empty,
        ), write_transaction)
        record = await execute_checkpoint_create(claim)
        checkpoint = await execute_writer_write(
            db, lambda write_db: persist_checkpoint_create(write_db, claim, record), write_transaction
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if checkpoint is None:
        raise HTTPException(status_code=400, detail="No checkpoint was created")
    return SessionCheckpointResponse.model_validate(checkpoint)


@router.post("/sessions/{session_id}/checkpoints/restore", response_model=SessionUndoChangesResponse)
async def restore_session_checkpoint(
    session_id: str,
    body: SessionCheckpointRestoreRequest,
    db: AsyncSession = Depends(get_db),
    write_transaction=Depends(get_writer_write),
):
    try:
        claim = await execute_writer_write(
            db, lambda write_db: claim_checkpoint_restore(write_db, session_id, commit=body.commit), write_transaction
        )
        execution = await execute_checkpoint_restore(claim)
        return SessionUndoChangesResponse.model_validate(
            await execute_writer_write(
                db, lambda write_db: persist_checkpoint_restore(write_db, claim, execution), write_transaction
            )
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/commit-review", response_model=CommitReviewResponse)
async def get_commit_review(session_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return CommitReviewResponse.model_validate(await get_commit_review_response(db, session_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/commit-review/request", response_model=CommitReviewResponse)
async def request_commit_review(
    session_id: str,
    body: CommitReviewCreate,
    db: AsyncSession = Depends(get_db),
    write_transaction=Depends(get_writer_write),
):
    result = await db.execute(
        select(WriterSession).where(WriterSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.work_root:
        raise HTTPException(status_code=400, detail="Session has no work_root set")
    if not await _ensure_work_root_repo(session.work_root):
        raise HTTPException(status_code=400, detail="Git is not available for this work_root")

    changes = await get_session_changes(session_id, db)
    if not changes.files:
        raise HTTPException(status_code=400, detail="No changes to review")
    snapshot = await _git_manager.status_snapshot(session.work_root)
    now = _utc_now_iso()
    review = {
        "id": f"review-{int(datetime.now(timezone.utc).timestamp())}",
        "status": "pending",
        "title": body.title.strip() or "请验收本阶段改动",
        "summary": body.summary.strip(),
        "how_to_review": body.how_to_review.strip(),
        "self_check": body.self_check.strip(),
        "commit_message": body.commit_message.strip() or f"chore: {body.title.strip()[:48]}",
        "files": [item.model_dump() for item in changes.files],
        "total_additions": changes.total_additions,
        "total_deletions": changes.total_deletions,
        "source": changes.source,
        "ref": changes.ref,
        "head": snapshot.head if snapshot else None,
        "dirty_hashes": _review_dirty_hashes(snapshot, changes.files),
        "created_at": now,
        "updated_at": now,
    }
    async def write(write_db):
        persisted = await write_db.get(WriterSession, session_id)
        if persisted is None:
            raise HTTPException(status_code=404, detail="Session not found")
        runtime_state = _runtime_state(persisted)
        runtime_state["pending_commit_review"] = review
        persisted.runtime_state = runtime_state
        persisted.updated_at = datetime.now(timezone.utc)
    await execute_writer_write(db, write, write_transaction)
    return _commit_review_response(review)


@router.post("/sessions/{session_id}/commit-review/decision", response_model=CommitReviewResponse)
async def decide_commit_review(
    session_id: str,
    body: CommitReviewDecision,
    db: AsyncSession = Depends(get_db),
    write_transaction=Depends(get_writer_write),
):
    try:
        if body.action.strip().lower() in {"approve", "accept", "commit"}:
            claim = await execute_writer_write(
                db,
                lambda write_db: claim_commit_review_approval(
                    write_db,
                    session_id,
                    feedback=body.feedback,
                    commit_message=body.commit_message,
                ),
                write_transaction,
            )
            committed = await execute_commit_review_approval(claim)
            result = await execute_writer_write(
                db,
                lambda write_db: persist_commit_review_approval(write_db, claim, committed),
                write_transaction,
            )
        else:
            result = await execute_writer_write(
                db,
                lambda write_db: decide_commit_review_response(
                    write_db,
                    session_id,
                    action=body.action,
                    feedback=body.feedback,
                    commit_message=body.commit_message,
                ),
                write_transaction,
            )
        return CommitReviewResponse.model_validate(
            result
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorktreeChangedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/changes/undo", response_model=SessionUndoChangesResponse)
async def undo_session_changes(session_id: str, db: AsyncSession = Depends(get_db)):
    """Undo the changes currently shown by the session review panel."""
    try:
        return SessionUndoChangesResponse.model_validate(await undo_session_changes_response(db, session_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/changes/undo-file", response_model=SessionUndoChangesResponse)
async def undo_session_file_change(
    session_id: str,
    request: SessionUndoFileRequest,
    db: AsyncSession = Depends(get_db),
):
    """Undo one file from the session review panel."""
    try:
        return SessionUndoChangesResponse.model_validate(
            await undo_session_file_change_response(db, session_id, request.path)
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
