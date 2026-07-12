from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.writer.git import GitCommandResult, WriterGitManager
from app.models.message import WriterMessage
from app.models.session import WriterSession
from app.services.session_git_operation import (
    SessionGitClaim,
    claim_session_git_operation,
    clear_session_git_claim,
    require_session_git_claim,
)


EnsureRepo = Callable[[str], Awaitable[bool]]


class WorktreeChangedError(RuntimeError):
    pass


class WriterCommitReviewService:
    def __init__(
        self,
        *,
        git_manager: WriterGitManager,
        default_work_root: str,
        ensure_repo: EnsureRepo,
    ) -> None:
        self._git = git_manager
        self._default_work_root = default_work_root
        self._ensure_repo = ensure_repo

    @staticmethod
    def latest_request(summary: dict[str, Any]) -> dict[str, Any] | None:
        latest: dict[str, Any] | None = None
        for item in summary.get("tool_results_summary", []):
            if not isinstance(item, dict) or item.get("tool_name") != "request_commit_review":
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            request = metadata.get("commit_review_request") if isinstance(metadata, dict) else None
            if isinstance(request, dict):
                latest = dict(request)
        return latest

    async def persist_request(
        self,
        db: AsyncSession,
        session: WriterSession,
        request: dict[str, Any],
    ) -> dict[str, Any] | None:
        changes = await self._collect_changes(session)
        files = [item for item in changes["files"] if isinstance(item, dict)]
        if not files:
            return None
        work_root = session.work_root or self._default_work_root
        snapshot = await self._git.status_snapshot(work_root) if work_root else None
        file_paths = {str(item.get("path") or "") for item in files}
        dirty_hashes = {
            path: value
            for path, value in ((snapshot.dirty_hashes if snapshot else {}) or {}).items()
            if path in file_paths
        }
        now = datetime.now(timezone.utc).isoformat()
        title = str(request.get("title") or "请验收本阶段改动").strip()
        review = {
            "id": f"review-{session.id[:8]}-{int(datetime.now(timezone.utc).timestamp())}",
            "status": "pending",
            "title": title[:120],
            "summary": str(request.get("summary") or "").strip()[:1200],
            "how_to_review": str(request.get("how_to_review") or "").strip()[:800],
            "self_check": str(request.get("self_check") or "").strip()[:800],
            "commit_message": str(request.get("commit_message") or "").strip()[:160] or f"chore: {title[:48]}",
            "files": files,
            "total_additions": int(changes["total_additions"] or 0),
            "total_deletions": int(changes["total_deletions"] or 0),
            "source": str(changes["source"] or ""),
            "ref": changes["ref"],
            "head": snapshot.head if snapshot else None,
            "dirty_hashes": dirty_hashes,
            "created_at": now,
            "updated_at": now,
        }
        runtime_state = _runtime_state_dict(session)
        runtime_state["pending_commit_review"] = review
        session.runtime_state = runtime_state
        session.updated_at = datetime.now(timezone.utc)
        return review

    async def _collect_changes(self, session: WriterSession) -> dict[str, Any]:
        work_root = session.work_root or self._default_work_root
        if not work_root or not await self._ensure_repo(work_root):
            return {"files": [], "total_additions": 0, "total_deletions": 0, "source": "none", "ref": None}

        source = "working_tree"
        ref: str | None = None
        numstat = await self._git.run(work_root, ["diff", "--numstat", "--"], max_output_chars=30000)
        if numstat.code != 0:
            numstat = GitCommandResult(code=0, stdout="", stderr="")
        if not numstat.stdout.strip():
            git_state = _git_state_dict(_runtime_state_dict(session))
            checkpoint = git_state.get("last_checkpoint") if isinstance(git_state.get("last_checkpoint"), dict) else {}
            commit = str((checkpoint or {}).get("commit") or "")
            if commit and checkpoint.get("storage") != "checkpoint_branch":
                source = "checkpoint"
                ref = commit
                base_ref = str(checkpoint.get("base_head") or "")
                if base_ref:
                    numstat = await self._git.run(
                        work_root,
                        ["diff", "--numstat", base_ref, commit, "--"],
                        max_output_chars=30000,
                    )
                else:
                    numstat = await self._git.run(
                        work_root,
                        ["show", "--numstat", "--format=", commit],
                        max_output_chars=30000,
                    )
                if numstat.code != 0:
                    numstat = GitCommandResult(code=0, stdout="", stderr="")

        files: list[dict[str, Any]] = []
        total_additions = 0
        total_deletions = 0
        for line in numstat.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            add_raw, del_raw, path = parts[0], parts[1], parts[2]
            binary = add_raw == "-" or del_raw == "-"
            additions = None if binary else int(add_raw or 0)
            deletions = None if binary else int(del_raw or 0)
            if additions is not None:
                total_additions += additions
            if deletions is not None:
                total_deletions += deletions
            files.append({
                "path": path,
                "additions": additions,
                "deletions": deletions,
                "binary": binary,
            })

        if source == "working_tree":
            untracked = await self._git.run(
                work_root,
                ["ls-files", "--others", "--exclude-standard"],
                max_output_chars=30000,
            )
            tracked = {item["path"] for item in files}
            untracked_paths = (
                [line.strip() for line in untracked.stdout.splitlines() if line.strip()]
                if untracked.code == 0
                else []
            )
            for path in untracked_paths:
                if path in tracked:
                    continue
                additions, binary = _untracked_stats(work_root, path)
                if additions is not None:
                    total_additions += additions
                files.append({
                    "path": path,
                    "additions": additions,
                    "deletions": 0 if additions is not None else None,
                    "binary": binary,
                })

        return {
            "files": files,
            "total_additions": total_additions,
            "total_deletions": total_deletions,
            "source": source,
            "ref": ref,
        }


_default_git_manager = WriterGitManager()


@dataclass(frozen=True)
class CommitReviewClaim:
    session: SessionGitClaim
    review_id: str
    expected_head: str
    expected_hashes: dict[str, str]
    paths: list[str]
    commit_message: str
    feedback: str


async def claim_commit_review_approval(
    db: AsyncSession,
    session_id: str,
    *,
    feedback: str = "",
    commit_message: str | None = None,
) -> CommitReviewClaim:
    session = await _get_session(db, session_id)
    runtime_state = _runtime_state_dict(session)
    review = runtime_state.get("pending_commit_review")
    if not isinstance(review, dict) or review.get("status") not in {"pending", "changes_requested", "postponed"}:
        raise ValueError("No pending commit review")
    return CommitReviewClaim(
        session=claim_session_git_operation(session, "commit_review.approve"),
        review_id=str(review.get("id") or ""),
        expected_head=str(review.get("head") or ""),
        expected_hashes=dict(review.get("dirty_hashes") or {}),
        paths=[
            str(item.get("path"))
            for item in review.get("files", [])
            if isinstance(item, dict) and item.get("path")
        ],
        commit_message=(commit_message or review.get("commit_message") or "").strip(),
        feedback=feedback.strip(),
    )


async def execute_commit_review_approval(claim: CommitReviewClaim):
    if not await _default_git_manager.is_repo(claim.session.work_root):
        raise ValueError("Not a git repository")
    snapshot = await _default_git_manager.status_snapshot(claim.session.work_root)
    if snapshot is None:
        raise ValueError("Could not read git status")
    current_hashes = {path: snapshot.dirty_hashes.get(path, "") for path in claim.expected_hashes}
    if claim.expected_head != str(snapshot.head or ""):
        raise WorktreeChangedError("Worktree changed after review request; request review again")
    if claim.expected_hashes and current_hashes != claim.expected_hashes:
        raise WorktreeChangedError("Worktree changed after review request; request review again")
    if snapshot.dirty_files:
        committed = await _default_git_manager.commit_paths(
            claim.session.work_root,
            claim.paths,
            message=claim.commit_message,
        )
    else:
        committed = await _default_git_manager.checkpoint_all(
            claim.session.work_root,
            label="commit",
            reason=claim.commit_message,
            allow_empty=True,
        )
    if committed is None:
        raise ValueError("Git commit failed")
    return committed


async def persist_commit_review_approval(db: AsyncSession, claim: CommitReviewClaim, committed) -> dict[str, Any]:
    session = await _get_session(db, claim.session.session_id)
    runtime_state = require_session_git_claim(session, claim.session)
    review = runtime_state.get("pending_commit_review")
    if not isinstance(review, dict) or str(review.get("id") or "") != claim.review_id:
        raise RuntimeError("Commit review changed while Git operation was running")
    review = dict(review)
    review["status"] = "approved"
    review["commit"] = committed.commit
    review["commit_message"] = claim.commit_message
    review["feedback"] = claim.feedback
    review["updated_at"] = datetime.now(timezone.utc).isoformat()
    runtime_state["pending_commit_review"] = review
    git_state = _git_state_dict(runtime_state)
    git_state["last_formal_commit"] = committed.model_dump(mode="json")
    runtime_state["git_state"] = git_state
    clear_session_git_claim(runtime_state, claim.session)
    session.runtime_state = runtime_state
    session.branch = committed.branch
    session.updated_at = datetime.now(timezone.utc)
    return _commit_review_response(review)


async def get_commit_review_response(db: AsyncSession, session_id: str) -> dict[str, Any]:
    session = await _get_session(db, session_id)
    review = _runtime_state_dict(session).get("pending_commit_review")
    return _commit_review_response(review if isinstance(review, dict) else None)


async def decide_commit_review_response(
    db: AsyncSession,
    session_id: str,
    *,
    action: str,
    feedback: str = "",
    commit_message: str | None = None,
) -> dict[str, Any]:
    session = await _get_session(db, session_id)
    runtime_state = _runtime_state_dict(session)
    review = runtime_state.get("pending_commit_review")
    if not isinstance(review, dict) or review.get("status") not in {"pending", "changes_requested", "postponed"}:
        raise ValueError("No pending commit review")

    decision = action.strip().lower()
    now = datetime.now(timezone.utc).isoformat()
    if decision in {"request_changes", "needs_changes", "adjust"}:
        clean_feedback = feedback.strip()
        review["status"] = "changes_requested"
        review["feedback"] = clean_feedback
        review["updated_at"] = now
        runtime_state["pending_commit_review"] = review
        session.runtime_state = runtime_state
        if clean_feedback:
            db.add(WriterMessage(
                session_id=session_id,
                role="user",
                content=f"验收反馈：{clean_feedback}",
                parts={"commit_review_feedback": {"review_id": review.get("id"), "feedback": clean_feedback}},
            ))
        return _commit_review_response(review)

    if decision in {"postpone", "skip", "archive_only"}:
        review["status"] = "postponed"
        review["feedback"] = feedback.strip()
        review["updated_at"] = now
        runtime_state["pending_commit_review"] = review
        session.runtime_state = runtime_state
        return _commit_review_response(review)

    if decision != "approve":
        raise ValueError("Unsupported review decision")

    if not await _default_git_manager.is_repo(session.work_root):
        raise ValueError("Not a git repository")
    snapshot = await _default_git_manager.status_snapshot(session.work_root)
    if snapshot is None:
        raise ValueError("Could not read git status")

    expected_hashes = dict(review.get("dirty_hashes") or {})
    current_hashes = {
        path: snapshot.dirty_hashes.get(path, "")
        for path in expected_hashes
    }
    if str(review.get("head") or "") != str(snapshot.head or ""):
        raise WorktreeChangedError("Worktree changed after review request; request review again")
    if expected_hashes and current_hashes != expected_hashes:
        raise WorktreeChangedError("Worktree changed after review request; request review again")

    clean_commit_message = (commit_message or review.get("commit_message") or "").strip()
    paths = [
        str(item.get("path"))
        for item in review.get("files", [])
        if isinstance(item, dict) and item.get("path")
    ]
    committed = None
    if snapshot.dirty_files:
        committed = await _default_git_manager.commit_paths(
            session.work_root,
            paths,
            message=clean_commit_message,
        )
    else:
        committed = await _default_git_manager.checkpoint_all(
            session.work_root,
            label="commit",
            reason=clean_commit_message,
            allow_empty=True,
        )
    if committed is None:
        raise ValueError("Git commit failed")

    review["status"] = "approved"
    review["commit"] = committed.commit
    review["commit_message"] = clean_commit_message
    review["feedback"] = feedback.strip()
    review["updated_at"] = now
    runtime_state["pending_commit_review"] = review
    git_state = _git_state_dict(runtime_state)
    git_state["last_formal_commit"] = committed.model_dump(mode="json")
    runtime_state["git_state"] = git_state
    session.runtime_state = runtime_state
    session.branch = committed.branch
    session.updated_at = datetime.now(timezone.utc)
    return _commit_review_response(review)


async def _get_session(db: AsyncSession, session_id: str) -> WriterSession:
    result = await db.execute(select(WriterSession).where(WriterSession.id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise LookupError("Session not found")
    return session


def _commit_review_response(review: dict[str, Any] | None) -> dict[str, Any]:
    if not review:
        return {
            "id": "",
            "status": "none",
            "title": "",
            "summary": "",
            "how_to_review": "",
            "self_check": "",
            "commit_message": "",
            "files": [],
            "total_additions": 0,
            "total_deletions": 0,
            "source": "",
            "ref": None,
            "commit": None,
            "feedback": "",
            "created_at": "",
            "updated_at": "",
        }
    return {
        "id": str(review.get("id") or ""),
        "status": str(review.get("status") or "none"),
        "title": str(review.get("title") or ""),
        "summary": str(review.get("summary") or ""),
        "how_to_review": str(review.get("how_to_review") or ""),
        "self_check": str(review.get("self_check") or ""),
        "commit_message": str(review.get("commit_message") or ""),
        "files": [
            {
                "path": str(item.get("path") or ""),
                "additions": item.get("additions"),
                "deletions": item.get("deletions"),
                "binary": bool(item.get("binary", False)),
            }
            for item in review.get("files", [])
            if isinstance(item, dict)
        ],
        "total_additions": int(review.get("total_additions") or 0),
        "total_deletions": int(review.get("total_deletions") or 0),
        "source": str(review.get("source") or ""),
        "ref": review.get("ref"),
        "commit": review.get("commit"),
        "feedback": str(review.get("feedback") or ""),
        "created_at": str(review.get("created_at") or ""),
        "updated_at": str(review.get("updated_at") or ""),
    }


def _runtime_state_dict(session: WriterSession) -> dict[str, Any]:
    return dict(session.runtime_state or {})


def _git_state_dict(runtime_state: dict[str, Any]) -> dict[str, Any]:
    value = runtime_state.get("git_state")
    return dict(value) if isinstance(value, dict) else {}


def _untracked_stats(work_root: str, rel_path: str) -> tuple[int | None, bool]:
    root = Path(work_root).resolve()
    target = (root / rel_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None, True
    if not target.exists() or not target.is_file():
        return None, True
    try:
        raw = target.read_bytes()
    except OSError:
        return None, True
    if b"\x00" in raw:
        return None, True
    text = raw.decode("utf-8", errors="replace")
    return len(text.splitlines()), False
