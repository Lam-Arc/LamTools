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
    append_recent_user_messages,
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
    assert [message.content for message in layout.retained_messages] == [
        "answer-2",
        "result-2",
        "answer-3",
        "result-3",
    ]
    assert [message.content for message in layout.compacted_messages[:25]] == [
        f"user-{index}" for index in range(25)
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
    assert layout.compacted_messages == messages
    assert layout.retained_messages == []


def test_layout_returns_oversized_latest_user_for_controller_failure() -> None:
    latest = ChatMessage(role="user", content="x" * 100)

    layout = select_context_compaction_layout(
        [latest],
        limit_tokens=20,
        estimate_tokens=_count_tokens,
    )

    assert layout is not None
    assert layout.compacted_messages == [latest]
    assert layout.retained_messages == []


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


def test_fitter_appends_numbered_recent_users_verbatim() -> None:
    original = ["first line\nsecond line", " keep surrounding spaces "]
    result = CompactionFitter(_count_tokens).fit(
        CompactionFitInput(
            system_prefix=[],
            summary_message=ChatMessage(role="system", content="model summary"),
            recent_messages=[],
            recent_user_messages=original,
            target_tokens=1_000,
        )
    )

    assert result.messages[0].content == (
        "model summary\n\n## Recent user messages\n"
        "1. first line\nsecond line\n\n2.  keep surrounding spaces "
    )


def test_fitter_silently_drops_oldest_recent_user_when_suffix_is_over_budget() -> None:
    users = ["old" * 20, "middle", "latest"]
    target = _count_tokens(
        [ChatMessage(role="system", content=append_recent_user_messages("", users[1:]))]
    )
    result = CompactionFitter(_count_tokens).fit(
        CompactionFitInput(
            system_prefix=[],
            summary_message=ChatMessage(role="system", content="model summary"),
            recent_messages=[],
            recent_user_messages=users,
            target_tokens=target,
        )
    )

    content = str(result.messages[0].content)
    assert "oldold" not in content
    assert content.endswith("1. middle\n\n2. latest")
    assert result.estimated_tokens <= target


def test_prior_program_owned_recent_user_suffix_is_replaced() -> None:
    previous = append_recent_user_messages("model summary", ["old instruction"])

    assert strip_recent_user_messages(previous) == "model summary"
    assert append_recent_user_messages(previous, ["new instruction"]).count(
        "## Recent user messages"
    ) == 1


def test_recent_user_marker_collision_keeps_visible_numbered_text_and_round_trips() -> None:
    # A user message can contain the legacy heading plus a numbered line.  The
    # new collision-safe framing must keep that content intact when a later
    # recursive compaction strips and appends the suffix again.
    user_content = "prefix\n\n## Recent user messages\n1. quoted"
    summary = append_recent_user_messages("summary", [user_content])

    assert extract_recent_user_messages(summary) == [user_content]
    assert strip_recent_user_messages(summary) == "summary"
    assert (
        "## Recent user messages\n"
        "1. prefix\n\n"
        "## Recent user messages\n"
        "1. quoted"
    ) in summary
    assert "<!-- lamtools:recent-user-messages:v1;" in summary
    assert "(framed)" not in summary


@pytest.mark.parametrize(
    "user_content",
    [
        "a\r\nb",
        "a\r\n\r\n1. b",
        "a\n",
        "a\n   ",
        "a\vb",
        "a\fb",
        "a\x1cb",
        "a\x1db",
        "a\x1eb",
        "a\x85b",
        "a\u2028b",
        "a\u2029b",
    ],
)
def test_recent_user_splitlines_sensitive_content_round_trips_verbatim(
    user_content: str,
) -> None:
    summary = append_recent_user_messages("summary", [user_content])

    assert extract_recent_user_messages(summary) == [user_content]
    assert strip_recent_user_messages(summary) == "summary"
    assert "<!-- lamtools:recent-user-messages:v1;" in summary


def test_legacy_recent_user_marker_collision_without_numbered_tail_is_preserved() -> None:
    # Model prose may quote the program-owned heading.  Without a contiguous
    # one-based numbered tail, the compatibility parser must leave that prose
    # untouched so a later suffix append cannot erase it.
    summary = (
        "The model quoted this heading as an example:\n\n"
        "## Recent user messages\n"
        "(not a numbered suffix; keep this text verbatim)"
    )

    assert extract_recent_user_messages(summary) == []
    assert strip_recent_user_messages(summary) == summary
    appended = append_recent_user_messages(summary, ["new instruction"])
    assert "(not a numbered suffix; keep this text verbatim)" in appended
    assert appended.endswith("## Recent user messages\n1. new instruction")


def test_multimodal_user_message_keeps_only_original_text_blocks() -> None:
    content = [
        {"type": "text", "text": "first\n"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
        {"type": "input_text", "text": "second"},
    ]

    assert user_message_text(content) == "first\nsecond"


def test_fitter_drops_retained_step_before_recent_user_original() -> None:
    latest_only = append_recent_user_messages("", ["latest instruction"])
    target = _count_tokens([ChatMessage(role="system", content=latest_only)])
    result = CompactionFitter(_count_tokens).fit(
        CompactionFitInput(
            system_prefix=[],
            summary_message=ChatMessage(role="system", content="model summary"),
            recent_messages=[ChatMessage(role="assistant", content="x" * 100)],
            recent_user_messages=["latest instruction"],
            target_tokens=target,
        )
    )

    assert len(result.messages) == 1
    assert result.messages[0].content == latest_only


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
