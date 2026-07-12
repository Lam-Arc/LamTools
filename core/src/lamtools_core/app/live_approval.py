from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


PendingApprovalRequestResolver = Callable[[str], str | None | Awaitable[str | None]]

_DECISION_ALIASES = {
    "approve_once": "approve",
    "approve_for_session": "approve",
    "other_guidance": "guide",
}
_VALID_DECISIONS = {"approve", "deny", "guide"}


@dataclass(frozen=True)
class NormalizedApprovalRequest:
    request_id: str
    thread_id: str
    decision: str
    guidance: str

    def to_dict(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "thread_id": self.thread_id,
            "decision": self.decision,
            "guidance": self.guidance,
        }


async def normalize_approval_request(
    payload: dict[str, Any],
    *,
    resolve_pending_request: PendingApprovalRequestResolver | None = None,
) -> NormalizedApprovalRequest:
    request_id = str(payload.get("request_id") or payload.get("requestId") or "").strip()
    thread_id = str(
        payload.get("thread_id")
        or payload.get("threadId")
        or payload.get("session_id")
        or payload.get("sessionId")
        or ""
    ).strip()
    raw_decision = str(payload.get("decision") or payload.get("action") or "").strip()
    decision = _DECISION_ALIASES.get(raw_decision, raw_decision)
    guidance_value = payload.get("guidance") if isinstance(payload.get("guidance"), str) else payload.get("response")
    guidance = guidance_value if isinstance(guidance_value, str) else ""
    if not request_id and thread_id and resolve_pending_request is not None:
        resolved = resolve_pending_request(thread_id)
        request_id = str(await resolved if isinstance(resolved, Awaitable) else resolved or "").strip()
    if not request_id or decision not in _VALID_DECISIONS:
        raise ValueError("request_id and decision are required")
    return NormalizedApprovalRequest(
        request_id=request_id,
        thread_id=thread_id,
        decision=decision,
        guidance=guidance,
    )


__all__ = ["NormalizedApprovalRequest", "PendingApprovalRequestResolver", "normalize_approval_request"]
