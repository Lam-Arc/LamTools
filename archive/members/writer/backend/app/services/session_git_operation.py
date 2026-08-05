from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.models.session import WriterSession


@dataclass(frozen=True)
class SessionGitClaim:
    token: str
    operation: str
    session_id: str
    work_root: str


def claim_session_git_operation(session: WriterSession, operation: str) -> SessionGitClaim:
    runtime_state = dict(session.runtime_state or {})
    claims = dict(runtime_state.get("git_operation_claims") or {})
    if operation in claims:
        raise ValueError(f"Git operation already in progress: {operation}")
    claim = SessionGitClaim(
        token=uuid4().hex,
        operation=operation,
        session_id=session.id,
        work_root=session.work_root or "",
    )
    claims[operation] = claim.token
    runtime_state["git_operation_claims"] = claims
    session.runtime_state = runtime_state
    return claim


def require_session_git_claim(session: WriterSession, claim: SessionGitClaim) -> dict[str, Any]:
    runtime_state = dict(session.runtime_state or {})
    claims = dict(runtime_state.get("git_operation_claims") or {})
    if claims.get(claim.operation) != claim.token:
        raise RuntimeError("Session changed while Git operation was running")
    if (session.work_root or "") != claim.work_root:
        raise RuntimeError("Session work_root changed while Git operation was running")
    return runtime_state


def clear_session_git_claim(runtime_state: dict[str, Any], claim: SessionGitClaim) -> None:
    claims = dict(runtime_state.get("git_operation_claims") or {})
    if claims.get(claim.operation) == claim.token:
        claims.pop(claim.operation, None)
    if claims:
        runtime_state["git_operation_claims"] = claims
    else:
        runtime_state.pop("git_operation_claims", None)


__all__ = [
    "SessionGitClaim",
    "claim_session_git_operation",
    "clear_session_git_claim",
    "require_session_git_claim",
]
