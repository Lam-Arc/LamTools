from __future__ import annotations

import pytest

from lamtools_core.app.live_approval import normalize_approval_request


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {"request_id": "request-1", "decision": "approve_once", "guidance": "continue"},
            {"request_id": "request-1", "thread_id": "", "decision": "approve", "guidance": "continue"},
        ),
        (
            {"thread_id": "thread-1", "action": "other_guidance", "response": "use git diff"},
            {"request_id": "request-1", "thread_id": "thread-1", "decision": "guide", "guidance": "use git diff"},
        ),
        (
            {"request_id": "request-1", "decision": "approve_for_session", "response": ""},
            {"request_id": "request-1", "thread_id": "", "decision": "approve", "guidance": ""},
        ),
    ],
)
async def test_normalize_approval_request_canonicalizes_legacy_and_current_payloads(payload, expected) -> None:
    async def resolve_pending_request(thread_id: str) -> str | None:
        assert thread_id == "thread-1"
        return "request-1"

    normalized = await normalize_approval_request(payload, resolve_pending_request=resolve_pending_request)

    assert normalized.to_dict() == expected
