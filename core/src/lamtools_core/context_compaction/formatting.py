"""Text formatting and parsing helpers for context compaction."""

from __future__ import annotations

import json

from lamtools_core.llm import ChatMessage
from lamtools_core.tokens import estimate_text_tokens

from .models import (
    COMPACTION_PREFIX,
    _COMPACTION_SUMMARY_FIELDS,
    _COMPACTION_SUMMARY_TITLES,
    _LEGACY_SUMMARY_TITLES,
    CompactionSummary,
)


def parse_compaction_summary(text: str) -> CompactionSummary | None:
    """Parse only the exact ordered nine-section summary contract."""
    raw = str(text or "").strip()
    if not raw:
        return None
    lines = raw.splitlines()
    if lines and lines[0].strip() == COMPACTION_PREFIX:
        lines = lines[1:]

    headings = [
        (index, line.strip())
        for index, line in enumerate(lines)
        if numbered_section_number(line) is not None
    ]
    if [title for _, title in headings] != list(_COMPACTION_SUMMARY_TITLES):
        return None

    values: dict[str, str] = {}
    for position, (start, _) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        values[_COMPACTION_SUMMARY_FIELDS[position]] = "\n".join(
            lines[start + 1 : end]
        ).strip()
    return CompactionSummary(**values)


def normalize_legacy_compaction_summary(text: str) -> str:
    """Canonicalize the pre-contract fixture format during migration."""
    lines = str(text or "").strip().splitlines()
    headings = [
        line.strip()
        for line in lines
        if numbered_section_number(line) is not None
    ]
    if headings != list(_LEGACY_SUMMARY_TITLES):
        return text
    replacements = dict(zip(_LEGACY_SUMMARY_TITLES, _COMPACTION_SUMMARY_TITLES))
    return "\n".join(replacements.get(line.strip(), line) for line in lines)


def with_compaction_prefix(content: str) -> str:
    text = str(content or "").strip()
    if text.startswith(COMPACTION_PREFIX):
        return text
    return f"{COMPACTION_PREFIX}\n{text}".strip()


def has_structured_sections(content: str) -> bool:
    """Return whether the content contains all nine numbered sections."""
    return parse_compaction_summary(content) is not None


def inherit_prior_protected_context(summary: str, prior_summaries: list[str]) -> str:
    protected_sections = (
        (
            2,
            "2. Active User Instructions",
            ("2. Active User Instructions", "2. User History, Instructions, And Decisions"),
            denies_user_instructions,
        ),
        (
            3,
            "3. External Action Authorization",
            ("3. External Action Authorization",),
            denies_external_action_authorization,
        ),
    )
    result = summary
    for number, title, accepted_titles, denies_content in protected_sections:
        inherited: list[str] = []
        for prior_summary in prior_summaries:
            if numbered_summary_section_title(prior_summary, number) not in accepted_titles:
                continue
            for line in numbered_summary_section(prior_summary, number):
                normalized = " ".join(line.split())
                if normalized and normalized not in inherited:
                    inherited.append(normalized)
        if not inherited:
            continue

        current = []
        if numbered_summary_section_title(result, number) in accepted_titles:
            current = [
                line
                for line in numbered_summary_section(result, number)
                if not denies_content(line)
            ]
        merged = [*inherited, *(line for line in current if " ".join(line.split()) not in inherited)]
        lines = result.splitlines()
        start, end = numbered_summary_section_bounds(lines, number)
        section = [title, *merged]
        if start is None:
            result = "\n".join([*lines, "", *section]).strip()
        else:
            result = "\n".join([*lines[:start], *section, "", *lines[end:]]).strip()
    return result


def numbered_summary_section(text: str, number: int) -> list[str]:
    lines = str(text or "").splitlines()
    start, end = numbered_summary_section_bounds(lines, number)
    if start is None:
        return []
    return [line.strip() for line in lines[start + 1 : end] if line.strip()]


def numbered_summary_section_title(text: str, number: int) -> str:
    lines = str(text or "").splitlines()
    start, _ = numbered_summary_section_bounds(lines, number)
    return lines[start].strip() if start is not None else ""


def numbered_summary_section_bounds(lines: list[str], number: int) -> tuple[int | None, int]:
    prefix = f"{number}. "
    start = next((index for index, line in enumerate(lines) if line.strip().startswith(prefix)), None)
    if start is None:
        return None, len(lines)
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].strip()
            and lines[index].strip()[0].isdigit()
            and ". " in lines[index].strip()[:4]
        ),
        len(lines),
    )
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return start, end


def denies_user_instructions(line: str) -> bool:
    normalized = " ".join(line.lower().split())
    return any(
        marker in normalized
        for marker in (
            "no explicit user instruction",
            "no prior user instruction",
            "no user instruction",
            "无明确用户指令",
            "没有明确用户指令",
            "无用户指令",
        )
    )


def denies_external_action_authorization(line: str) -> bool:
    normalized = " ".join(line.lower().split())
    return any(
        marker in normalized
        for marker in (
            "none confirmed",
            "no external action authorization",
            "no action authorization",
            "no authorization confirmed",
            "无外部操作授权",
            "未确认外部操作授权",
            "未获得外部操作授权",
        )
    )


def format_messages_for_compaction(
    messages: list[ChatMessage],
    *,
    existing_summary: str = "",
) -> str:
    lines: list[str] = []
    if existing_summary.strip():
        lines.extend(["## Existing Compacted Summary", existing_summary.strip(), ""])
    for index, message in enumerate(messages, start=1):
        content = message.content
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        lines.append(f"## Message {index}: {message.role}")
        if message.name:
            lines.append(f"name: {message.name}")
        if message.tool_call_id:
            lines.append(f"tool_call_id: {message.tool_call_id}")
        if message.tool_calls:
            lines.append("tool_calls:")
            for tool_call in message.tool_calls:
                lines.append(f"- {tool_call.name}: {tool_call.arguments}")
        lines.append(content)
        lines.append("")
    return "\n".join(lines).strip()


def numbered_section_number(line: str) -> int | None:
    stripped = line.strip()
    if not stripped or not stripped[0].isdigit() or ". " not in stripped[:4]:
        return None
    return int(stripped.split(".", 1)[0])


def line_is_in_numbered_sections(lines: list[str], index: int, numbers: set[int]) -> bool:
    for line in reversed(lines[:index]):
        number = numbered_section_number(line)
        if number is not None:
            return number in numbers
    return False


def truncate_text_to_tokens(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    if estimate_text_tokens(text) <= max_tokens:
        return text

    marker = "\n...[compaction summary truncated to fit budget]"
    marker_tokens = estimate_text_tokens(marker)
    if marker_tokens >= max_tokens:
        marker = ""
        marker_tokens = 0

    available_tokens = max_tokens - marker_tokens
    low = 0
    high = len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_text_tokens(text[:middle]) <= available_tokens:
            low = middle
        else:
            high = middle - 1

    return f"{text[:low]}{marker}"


__all__ = [
    "format_messages_for_compaction",
    "has_structured_sections",
    "inherit_prior_protected_context",
    "normalize_legacy_compaction_summary",
    "parse_compaction_summary",
    "truncate_text_to_tokens",
    "with_compaction_prefix",
]
