"""Movable system-context blocks with an epoch-frozen leading prompt.

The leading system prompt is the first bytes of every request, so changing any
part of it invalidates the provider's prefix cache for the whole conversation.
This module implements the rule that the leading prompt is frozen for an epoch
(one session span between context compactions), and any later change is emitted
as an append-only notice at the request tail instead.

Only informational blocks live here. A functional capability change (the tool
array itself) cannot be expressed as text and is intentionally out of scope.

user:“任何属于系统提示词，在上下文压缩之前绝不变动，如有变动 把它作为一条更新信息追加到尾部”+系统提示词按块冻结，变化只追加尾部通知，压缩时重建为新版。
user:“严格延续，但是每次压缩的时候重建为新态”+压缩周期随会话状态持久化，重启后沿用同一份冻结文本；压缩成功时用最新内容重新冻结。
user:“或者统一为 system message are changed，now：（新内容）”+通知只写变化后的内容，不回写原文。
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

#: ``RuntimeState.metadata`` key holding the frozen epoch.
MOVABLE_CONTEXT_METADATA_KEY = "movable_system_context"

#: Metadata key on the appended notice message.
MOVABLE_CONTEXT_NOTICE_KEY = "movable_context_notice"

MOVABLE_CONTEXT_VERSION = 1


@dataclass(frozen=True)
class MovableBlock:
    """One independently tracked block of the leading system prompt."""

    key: str
    label: str
    content: str


@dataclass(frozen=True)
class MovableContextPlan:
    """Result of comparing the current blocks with the frozen epoch."""

    epoch: dict[str, Any]
    system_prompt: str
    notices: list[dict[str, Any]]
    changed: bool
    seeded: bool = False


def block_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


def new_movable_epoch(
    system_prompt: str,
    blocks: Sequence[MovableBlock],
    *,
    turn_id: str = "",
) -> dict[str, Any]:
    """Return a fresh epoch whose baseline is the supplied blocks."""
    reported = {block.key: block_digest(block.content) for block in blocks}
    labels = {block.key: block.label for block in blocks}
    return {
        "version": MOVABLE_CONTEXT_VERSION,
        "epoch_id": uuid.uuid4().hex,
        "system_prompt": system_prompt,
        "block_labels": labels,
        "reported": reported,
        "created_turn_id": turn_id,
    }


def _valid_epoch(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    if value.get("version") != MOVABLE_CONTEXT_VERSION:
        return None
    if not isinstance(value.get("system_prompt"), str) or not value["system_prompt"]:
        return None
    if not isinstance(value.get("reported"), Mapping):
        return None
    labels = value.get("block_labels")
    if labels is not None and not isinstance(labels, Mapping):
        # A corrupted label map must not crash request construction; re-seed
        # instead. The frozen prompt itself is still valid, but a fresh epoch
        # is the only safe interpretation.
        return None
    return dict(value)


def plan_movable_context(
    previous: Any,
    *,
    system_prompt: str,
    blocks: Sequence[MovableBlock],
    turn_id: str = "",
) -> MovableContextPlan:
    """Freeze the first prompt of an epoch and report later block changes.

    The returned ``system_prompt`` is always what must be sent. On an existing
    epoch it is the frozen text, never the freshly composed one. ``notices``
    contains one entry per block whose provider-visible content differs from
    what the model was last told about it. Only two states exist: changed and
    deleted; a block that returns to an earlier value is simply changed again.
    """
    epoch = _valid_epoch(previous)
    current = {block.key: block for block in blocks}
    if epoch is None:
        epoch = new_movable_epoch(system_prompt, blocks, turn_id=turn_id)
        return MovableContextPlan(
            epoch=epoch,
            system_prompt=system_prompt,
            notices=[],
            changed=True,
            seeded=True,
        )

    labels = {
        str(key): str(value)
        for key, value in dict(epoch.get("block_labels") or {}).items()
    }
    reported = {
        str(key): (None if value is None else str(value))
        for key, value in dict(epoch.get("reported") or {}).items()
    }

    notices: list[dict[str, Any]] = []
    changed = False
    for key in sorted(set(current) | set(reported)):
        block = current.get(key)
        label = block.label if block is not None else labels.get(key, key)
        new_digest = block_digest(block.content) if block is not None else None
        if new_digest == reported.get(key):
            continue
        status = "deleted" if new_digest is None else "changed"
        notices.append({
            "key": key,
            "label": label,
            "status": status,
            "content": "" if new_digest is None else block.content,
        })
        reported[key] = new_digest
        labels[key] = label
        changed = True

    if not changed:
        return MovableContextPlan(
            epoch=epoch,
            system_prompt=str(epoch["system_prompt"]),
            notices=[],
            changed=False,
        )

    updated = {
        **epoch,
        "block_labels": labels,
        "reported": reported,
        "updated_turn_id": turn_id,
    }
    return MovableContextPlan(
        epoch=updated,
        system_prompt=str(epoch["system_prompt"]),
        notices=notices,
        changed=True,
    )


def format_movable_context_notice(notices: Sequence[Mapping[str, Any]]) -> str:
    """Render the append-only notice message.

    Only the new content is included; the stale copy still sits in the leading
    prompt, so deleted blocks must explicitly say that the old copy no longer
    applies.
    """
    lines = ["[System context update]"]
    for notice in notices:
        label = str(notice.get("label") or notice.get("key") or "system message")
        status = str(notice.get("status") or "changed")
        if status == "deleted":
            lines.append(
                f'System message "{label}" are deleted; '
                "the copy in the leading system prompt no longer applies."
            )
        else:
            lines.append(f'System message "{label}" are changed, now:')
            content = str(notice.get("content") or "")
            if content:
                lines.append(content)
        lines.append("")
    return "\n".join(lines).rstrip()


def is_movable_context_notice(message: Any) -> bool:
    metadata = getattr(message, "metadata", None)
    return (
        isinstance(metadata, dict)
        and metadata.get("key") == MOVABLE_CONTEXT_NOTICE_KEY
    )


__all__ = [
    "MOVABLE_CONTEXT_METADATA_KEY",
    "MOVABLE_CONTEXT_NOTICE_KEY",
    "MOVABLE_CONTEXT_VERSION",
    "MovableBlock",
    "MovableContextPlan",
    "block_digest",
    "format_movable_context_notice",
    "is_movable_context_notice",
    "new_movable_epoch",
    "plan_movable_context",
]
