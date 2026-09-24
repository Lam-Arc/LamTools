"""Auto-generate a short session title from the first user message.

Called from the live turn-start handler when a session has no prior items.
Uses the same LLM client already wired into the agent app, and persists the
result through the existing session store + broadcasts ``session/updated`` so
frontends refresh their sidebar.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from lamtools_core.llm import ChatMessage, LLMRequest
from lamtools_core.llm.retry import complete_with_retry

if TYPE_CHECKING:
    from lamtools_core.llm import LLMClient, LLMResponse

_logger = logging.getLogger(__name__)

#: Titles longer than this are truncated (the prompt asks for ≤20 chars, but we
#: enforce a hard ceiling defensively).
MAX_TITLE_LEN = 20

#: Limit how much of the first message is sent to the title model.
MAX_MESSAGE_CHARS = 2000

TITLE_CALL_TIMEOUT_SECONDS = 30.0

#: Session titles that count as "untouched defaults" and may be overwritten.
_DEFAULT_TITLES = frozenset({"", "new session", "新会话", "新的研究", "untitled", "core"})


def _clean_title(raw: str) -> str:
    """Strip surrounding quotes/whitespace and clamp to the length limit."""
    title = raw.strip().strip("\"'""''「」“”").strip()
    # Collapse internal newlines into spaces — a title must be single-line.
    title = " ".join(title.split())
    if len(title) > MAX_TITLE_LEN:
        title = title[:MAX_TITLE_LEN].rstrip()
    return title


async def generate_session_title(
    llm_client: "LLMClient",
    model_id: str,
    first_message_text: str,
) -> str | None:
    """Generate a ≤20-char title without reasoning or an output-token cap."""
    text = (first_message_text or "").strip()
    if not text:
        return None
    text = text[:MAX_MESSAGE_CHARS]

    request = LLMRequest(
        messages=[
            ChatMessage(
                role="system",
                content=(
                    "Condense the following user message into a short title of no more than 20 characters. "
                    "Output only the title text, without quotation marks, explanation, or a final period. "
                    "Use the same language as the user message."
                ),
            ),
            ChatMessage(role="user", content=text),
        ],
        model=model_id,
        temperature=0,
        metadata={
            "thinking_enabled": False,
            "reasoning_level": "off",
        },
    )
    try:
        response: "LLMResponse" = await complete_with_retry(
            llm_client,
            request,
            max_attempts=2,
            timeout_seconds=TITLE_CALL_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001
        _logger.warning("[autotitle] llm complete failed", exc_info=True)
        return None

    title = _clean_title(response.content or "")
    return title or None


def is_default_title(title: str | None, session_id: str = "") -> bool:
    """True when ``title`` is an untouched default that may be overwritten."""
    if not title:
        return True
    normalized = title.strip().lower()
    if normalized in _DEFAULT_TITLES:
        return True
    # A session whose title was never set is often the bare id.
    return normalized == (session_id or "").strip().lower()


__all__ = ["generate_session_title", "is_default_title"]
