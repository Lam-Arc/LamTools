"""Provider-side conversation affinity for prompt-cache routing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Metadata keys that already name the conversation a request belongs to.
#: ``_provider_session_affinity`` is the explicit host override; the other two
#: are set by the runtime for auxiliary and workflow child sessions.
_AFFINITY_METADATA_KEYS = (
    "_provider_session_affinity",
    "auxiliary_parent_session_id",
    "parent_session_id",
)


def provider_session_affinity(
    session_id: str,
    metadata: Mapping[str, Any] | None = None,
) -> str:
    """Return the session id that groups this request with its conversation.

    OpenCode routes inference requests and prompt caches by
    ``x-opencode-session``, and its own client makes every child session reuse
    the parent's id (``parentID ?? fork ?? own id``).  A LamTools sub-agent has
    its own runtime session id (``parent:sub:agent``), so the raw id would land
    on a different route than the main agent and lose cache locality.
    """
    values = metadata if isinstance(metadata, Mapping) else {}
    for key in _AFFINITY_METADATA_KEYS:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    delegated = values.get("delegated_session")
    if isinstance(delegated, Mapping):
        value = delegated.get("parent_thread_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    raw = str(session_id or "").strip()
    # Child session ids are ``<parent>:sub:<agent>``; nested children append
    # another segment.  The root before the first marker is the conversation
    # every level of the tree belongs to.
    return raw.split(":sub:", 1)[0]


__all__ = ["provider_session_affinity"]
