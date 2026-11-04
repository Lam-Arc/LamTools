from __future__ import annotations

import pytest

from lamtools_core.cli import main
from lamtools_core.config import build_config_operation_catalog
from lamtools_core.config.settings_store import set_setting
from lamtools_core.context_compaction import (
    CompactionBudgetExceeded,
    CompactionFitInput,
    CompactionFitter,
    load_retained_steps,
    select_context_compaction_layout,
)
from lamtools_core.context_compaction.formatting import (
    extract_recent_user_messages,
    strip_recent_user_messages,
    extract_recent_user_messages,
    strip_recent_user_messages,
    user_message_text,
)
from lamtools_core.llm import ChatMessage


def _count_tokens(messages: list[ChatMessage]) -> int:
    return sum(10 + len(str(message.content or "")) for message in messages)


def test_layout_default_zero_summarizes_every_assistant_step() -> None:
    messages: list[ChatMessage] = []
    for index in range(8):
        messages.extend(
            [
                ChatMessage(role="assistant", content=f"answer-{index}"),
                ChatMessage(role="tool", content=f"result-{index}"),
            ]
        )

    layout = select_context_compaction_layout(messages, limit_tokens=100_000)

    assert layout is not None
    assert layout.compacted_messages == messages
    assert layout.retained_messages == []


def test_layout_summarizes_users_and_retains_only_explicit_step_override() -> None:
    messages: list[ChatMessage] = []
    for index in range(25):
        messages.append(ChatMessage(role="user", content=f"user-{index}"))
    for index in range(4):
        messages.extend(
            [
                ChatMessage(role="assistant", content=f"answer-{index}"),
                ChatMessage(role="tool", content=f"result-{index}"),
            ]
        )

    layout = select_context_compaction_layout(
        messages,
        limit_tokens=100_000,
        retained_steps=2,
    )

    assert layout is not None
    # The latest user turn is always retained in its own role; the explicit
    # step override only adds the two most recent assistant steps.
    assert [message.content for message in layout.retained_messages] == [
        "user-24",
        "answer-2",
        "result-2",
        "answer-3",
        "result-3",
    ]
    # user-24 is the retained latest turn, so only user-0..user-23 are summarized.
    assert [message.content for message in layout.compacted_messages[:24]] == [
        f"user-{index}" for index in range(24)
    ]
    assert [messages.index(message) for message in layout.retained_messages] == sorted(
        messages.index(message) for message in layout.retained_messages
    )


def test_layout_enters_compaction_when_preferred_union_covers_oversized_history() -> None:
    messages = [
        ChatMessage(role="user", content="old instruction"),
        ChatMessage(role="assistant", content="old answer"),
        ChatMessage(role="tool", content="old tool result"),
        ChatMessage(role="user", content="latest instruction"),
    ]

    layout = select_context_compaction_layout(
        messages,
        limit_tokens=20,
        estimate_tokens=_count_tokens,
    )

    assert layout is not None
    # Everything else is summarized; the latest user instruction stays a user
    # message so the controller can refuse when it alone exceeds the limit.
    assert layout.retained_messages == [messages[-1]]
    assert layout.compacted_messages == messages[:-1]


def test_layout_returns_oversized_latest_user_for_controller_failure() -> None:
    latest = ChatMessage(role="user", content="x" * 100)

    layout = select_context_compaction_layout(
        [latest],
        limit_tokens=20,
        estimate_tokens=_count_tokens,
    )

    assert layout is not None
    # Nothing can be summarized here; keeping the latest user in its own role is
    # what lets the controller report the over-limit turn instead of dropping it.
    assert layout.retained_messages == [latest]
    assert layout.compacted_messages == []


def test_fitter_drops_oldest_selected_units_but_keeps_newest_user() -> None:
    recent = [
        ChatMessage(role="user", content="u0"),
        ChatMessage(role="assistant", content="a0"),
        ChatMessage(role="tool", content="t0"),
        ChatMessage(role="user", content="u1"),
        ChatMessage(role="assistant", content="a1"),
        ChatMessage(role="tool", content="t1"),
        ChatMessage(role="user", content="latest"),
    ]
    fitter = CompactionFitter(_count_tokens)
    target = _count_tokens(
        [ChatMessage(role="system", content=""), *recent[3:]]
    )

    result = fitter.fit(
        CompactionFitInput(
            system_prefix=[],
            summary_message=ChatMessage(role="system", content="summary"),
            recent_messages=recent,
            target_tokens=target,
        )
    )

    assert [message.content for message in result.messages[-4:]] == [
        "u1",
        "a1",
        "t1",
        "latest",
    ]


def test_fitter_fails_when_newest_user_alone_cannot_fit() -> None:
    with pytest.raises(CompactionBudgetExceeded, match="latest turn/user message"):
        CompactionFitter(_count_tokens).fit(
            CompactionFitInput(
                system_prefix=[],
                summary_message=ChatMessage(role="system", content="summary"),
                recent_messages=[ChatMessage(role="user", content="x" * 100)],
                target_tokens=20,
            )
        )


def test_multimodal_user_message_keeps_only_original_text_blocks() -> None:
    content = [
        {"type": "text", "text": "first\n"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
        {"type": "input_text", "text": "second"},
    ]

    assert user_message_text(content) == "first\nsecond"


def test_retained_steps_setting_validation_and_cli(isolated_config_root, capsys) -> None:
    assert load_retained_steps() == 0
    set_setting("core.contextCompaction", {"retained_steps": 101})
    assert load_retained_steps() == 0

    assert main(["context-compaction", "config", "--retained-steps", "0"]) == 0
    assert load_retained_steps() == 0
    assert main(["context-compaction", "show"]) == 0
    assert "retained_steps: 0" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_settings_rpc_accepts_zero_retained_steps(isolated_config_root) -> None:
    result = await build_config_operation_catalog().execute(
        "settings.update",
        {
            "namespace": "core.contextCompaction",
            "value": {"retained_steps": 0},
        },
    )

    assert result.status == "ok"
    assert load_retained_steps() == 0


def test_legacy_recent_user_appendix_is_read_and_stripped() -> None:
    """Old databases still carry the removed appendix.

    The writer is gone, but summaries persisted before the change keep the
    section. Reading must ignore it instead of feeding stale raw user text back
    into the next summary.
    """
    legacy = "model summary\n\n## Recent user messages\n1. 旧指令\n\n2. 又一条"

    assert extract_recent_user_messages(legacy) == ["旧指令", "又一条"]
    assert "## Recent user messages" not in strip_recent_user_messages(legacy)
    assert strip_recent_user_messages(legacy).strip() == "model summary"
