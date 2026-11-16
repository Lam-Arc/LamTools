"""Closing question groups without a user message.

user:“跳过等于 done 没问题吧？语义几乎一致。”+(跳过和已答共用同一处关闭逻辑：
组标记 done，只有 closed_reason 不同；跳过不回填任何答案，也不落用户消息。)

The close itself is pure: it mutates the runtime state in place and reports how
many groups it closed, so both the user-message path and the skip path share one
implementation instead of two drifting copies.
"""
from __future__ import annotations

import time
from typing import Any


def close_pending_question_groups(
    state: Any,
    *,
    reason: str,
    answers: dict[str, Any] | None = None,
) -> int:
    """Mark every pending question group done; return how many were closed.

    ``answers`` is keyed by group id and then by question id. When a group has no
    entry there, its questions keep whatever status they already carry — a skip
    must not invent answers.
    """
    metadata = getattr(state, "metadata", None)
    if not isinstance(metadata, dict):
        return 0
    groups = metadata.get("question_groups")
    if not isinstance(groups, list) or not groups:
        return 0

    closed = 0
    now_ms = int(time.time() * 1000)
    for group in groups:
        if not isinstance(group, dict):
            continue
        if str(group.get("status") or "") != "pending":
            continue
        provided = (
            answers.get(str(group.get("group_id") or ""))
            if isinstance(answers, dict)
            else None
        )
        if isinstance(provided, dict):
            for question in group.get("questions") or []:
                if not isinstance(question, dict):
                    continue
                answer = provided.get(str(question.get("id") or ""))
                if isinstance(answer, str) and answer.strip():
                    question["status"] = "answered"
                    question["answer"] = answer.strip()
        group["status"] = "done"
        group["closed_reason"] = reason
        group["closed_at_ms"] = now_ms
        closed += 1
    return closed
