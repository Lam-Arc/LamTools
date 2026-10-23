"""Shared keys and predicate for append-only runtime context updates.

user:“便签问题：不是全量便签重新追加，依旧是改什么加什么”+运行时计划/PID 等只追加变化字段。
"""

from __future__ import annotations

from typing import Any

#: ``RuntimeState.metadata`` key holding the last emitted runtime fields.
RUNTIME_CONTEXT_METADATA_KEY = "runtime_context_reported"

#: Metadata key on the appended runtime update message.
RUNTIME_CONTEXT_DELTA_KEY = "runtime_context_delta"


def is_runtime_context_delta(message: Any) -> bool:
    metadata = getattr(message, "metadata", None)
    return (
        isinstance(metadata, dict)
        and metadata.get("key") == RUNTIME_CONTEXT_DELTA_KEY
    )


__all__ = [
    "RUNTIME_CONTEXT_DELTA_KEY",
    "RUNTIME_CONTEXT_METADATA_KEY",
    "is_runtime_context_delta",
]
