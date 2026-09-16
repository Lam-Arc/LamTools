"""Text formatting and parsing helpers for context compaction."""

from __future__ import annotations

import json
import re

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
    raw = strip_recent_user_messages(str(text or "")).strip()
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


RECENT_USER_MESSAGES_HEADING = "## Recent user messages"
RECENT_USER_MESSAGES_SEPARATOR = f"\n\n{RECENT_USER_MESSAGES_HEADING}\n"
RECENT_USER_MESSAGES_METADATA_KEY = "recent_user_messages"
NON_TEXT_USER_MESSAGE_PLACEHOLDER = "[User message contained non-text content]"
_RECENT_USER_ENTRY_RE = re.compile(r"^(\d+)\. (.*)$")
_RECENT_USER_MESSAGES_FOOTER_PREFIX = "<!-- lamtools:recent-user-messages:v1;"
_RECENT_USER_MESSAGES_FOOTER_RE = re.compile(
    r"<!-- lamtools:recent-user-messages:v1;"
    r"total=(?P<total>\d+);lengths=(?P<lengths>\d+(?:,\d+)*) -->\Z"
)
_SPLITLINES_SEPARATORS = (
    "\r",
    "\v",
    "\f",
    "\x1c",
    "\x1d",
    "\x1e",
    "\x85",
    "\u2028",
    "\u2029",
)


def _footer_recent_user_suffix_entries(value: str) -> tuple[int, list[str]] | None:
    """Parse a numbered suffix with its invisible, length-based footer.

    User content is deliberately kept in the normal visible ``1.``/``2.``
    representation.  When that content can look like another suffix heading,
    the writer appends an HTML comment carrying the rendered section length
    and each original entry length.  The parser anchors at the final comment
    and slices by those lengths, so headings or numbered lines inside user
    text cannot be mistaken for framing.
    """
    # ``append_recent_user_messages`` emits the footer last.  Permit a final
    # transport newline while keeping the footer itself anchored at the end.
    end = len(value.rstrip())
    if end <= 0:
        return None
    candidate = value[:end]
    match = _RECENT_USER_MESSAGES_FOOTER_RE.search(candidate)
    if match is None:
        return None

    try:
        total = int(match.group("total"))
        lengths = [int(item) for item in match.group("lengths").split(",")]
    except (TypeError, ValueError):
        return None
    if total < 0 or not lengths or any(length < 0 for length in lengths):
        return None

    footer_start = match.start()
    if footer_start < 2 or candidate[footer_start - 2 : footer_start] != "\n\n":
        return None
    section_end = footer_start - 2
    section_start = section_end - total
    if section_start < 0 or section_start > section_end:
        return None
    section = candidate[section_start:section_end]
    if len(section) != total:
        return None

    cursor = len(RECENT_USER_MESSAGES_HEADING) + 1
    if not section.startswith(f"{RECENT_USER_MESSAGES_HEADING}\n"):
        return None
    entries: list[str] = []
    for index, length in enumerate(lengths, start=1):
        prefix = f"{index}. "
        if not section.startswith(prefix, cursor):
            return None
        cursor += len(prefix)
        end_of_entry = cursor + length
        if end_of_entry > len(section):
            return None
        entries.append(section[cursor:end_of_entry])
        cursor = end_of_entry
        if index < len(lengths):
            if section[cursor : cursor + 2] != "\n\n":
                return None
            cursor += 2
    if cursor != len(section):
        return None
    return section_start, entries


def _recent_user_suffix_entries(value: str) -> tuple[int, list[str]] | None:
    """Find a complete program-owned suffix in ``value``.

    New suffixes that need disambiguation carry a final length footer.  Older
    summaries have no explicit end marker, so the compatibility parser accepts
    only a heading whose tail is a contiguous, one-based numbered sequence
    reaching the end of the string.
    """
    framed = _footer_recent_user_suffix_entries(value)
    if framed is not None:
        return framed
    candidates: list[tuple[int, list[str]]] = []
    starts: list[tuple[int, int]] = []
    offset = 0
    while True:
        marker_index = value.find(RECENT_USER_MESSAGES_SEPARATOR, offset)
        if marker_index < 0:
            break
        starts.append((marker_index, marker_index + len(RECENT_USER_MESSAGES_SEPARATOR)))
        offset = marker_index + 1
    prefix_marker = f"{RECENT_USER_MESSAGES_HEADING}\n"
    if value.startswith(prefix_marker):
        starts.insert(0, (0, len(prefix_marker)))
    for marker_index, start in starts:
        tail = value[start:]
        lines = tail.splitlines()
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            continue
        entry_starts: list[tuple[int, int, str]] = []
        for index, line in enumerate(lines):
            match = _RECENT_USER_ENTRY_RE.match(line)
            if match is None or (index > 0 and lines[index - 1].strip()):
                continue
            entry_starts.append((index, int(match.group(1)), match.group(2)))
        if not entry_starts or entry_starts[0][0] != 0:
            continue
        entries: list[str] = []
        valid = True
        for position, (line_index, number, first_line) in enumerate(entry_starts):
            if number != position + 1:
                valid = False
                break
            end = (
                entry_starts[position + 1][0]
                if position + 1 < len(entry_starts)
                else len(lines)
            )
            continuation = list(lines[line_index + 1 : end])
            # ``append_recent_user_messages`` inserts a blank separator
            # between entries. It is framing, not part of the user content;
            # remove it from the compatibility parse (metadata-backed paths
            # preserve every byte of the original value).
            while continuation and not continuation[-1].strip():
                continuation.pop()
            entries.append("\n".join([first_line, *continuation]))
        if valid:
            candidates.append((marker_index, entries))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate[0])


def extract_recent_user_messages(summary: str) -> list[str]:
    """Extract the legacy numbered recent-user suffix, if one is present."""
    found = _recent_user_suffix_entries(str(summary or ""))
    return list(found[1]) if found is not None else []


def _standard_suffix_for_recent_user_messages(messages: list[str]) -> str:
    entries = "\n\n".join(
        f"{index}. {content}" for index, content in enumerate(messages, start=1)
    )
    return f"{RECENT_USER_MESSAGES_HEADING}\n{entries}"


def _recent_user_suffix_needs_footer(messages: list[str]) -> bool:
    """Return whether visible numbered text could confuse the fallback parser."""
    for content in messages:
        text = str(content)
        if RECENT_USER_MESSAGES_HEADING in text:
            return True
        # A blank-line-prefixed numbered line inside an entry looks exactly
        # like the next program-owned entry to the legacy parser.
        if re.search(r"\n\n\d+\. ", text):
            return True
        # Keep a user-quoted footer from being mistaken for our final footer.
        if _RECENT_USER_MESSAGES_FOOTER_PREFIX in text:
            return True
        # ``str.splitlines()`` normalizes these separators (and the fallback
        # parser drops a trailing line boundary), so use the exact-length
        # footer whenever they occur in user-authored text.
        if text.endswith("\n") or any(
            separator in text for separator in _SPLITLINES_SEPARATORS
        ):
            return True
        # The compatibility parser trims blank lines at the end of the whole
        # suffix. Preserve an LF followed by spaces/tabs with the footer too.
        if "\n" in text and not text.rsplit("\n", 1)[-1].strip():
            return True
    return False


def _suffix_for_recent_user_messages(messages: list[str]) -> str:
    """Render the visible numbered suffix, adding an invisible footer if needed."""
    normalized = [str(content) for content in messages]
    section = _standard_suffix_for_recent_user_messages(normalized)
    if not _recent_user_suffix_needs_footer(normalized):
        return section
    lengths = ",".join(str(len(content)) for content in normalized)
    footer = (
        f"{_RECENT_USER_MESSAGES_FOOTER_PREFIX}"
        f"total={len(section)};lengths={lengths} -->"
    )
    return f"{section}\n\n{footer}"


def strip_recent_user_messages(
    summary: str,
    recent_user_messages: list[str] | None = None,
) -> str:
    """Remove the program-owned recent-user suffix from a prior summary."""
    value = str(summary or "")
    if recent_user_messages is not None:
        suffixes = [_suffix_for_recent_user_messages(list(recent_user_messages))]
        # Metadata from an older writer may describe a standard suffix even
        # when the current renderer would choose collision-safe framing.
        standard_suffix = _standard_suffix_for_recent_user_messages(list(recent_user_messages))
        if standard_suffix not in suffixes:
            suffixes.append(standard_suffix)
        for suffix in suffixes:
            if value.endswith(suffix):
                body = value[: -len(suffix)] if suffix else value
                if body.endswith("\n\n"):
                    body = body[:-2]
                return body.rstrip()
    found = _recent_user_suffix_entries(value)
    if found is not None:
        return value[: found[0]].rstrip()
    if value.startswith(f"{RECENT_USER_MESSAGES_HEADING}\n"):
        return ""
    return value


def append_recent_user_messages(summary: str, messages: list[str]) -> str:
    """Append verbatim user messages as a deterministic numbered suffix."""
    body = strip_recent_user_messages(summary).rstrip()
    if not messages:
        return body
    section = _suffix_for_recent_user_messages(list(messages))
    return f"{body}\n\n{section}" if body else section


def user_message_text(content: object) -> str:
    """Return user-authored text without serializing non-text media blocks."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else str(content)
    chunks: list[str] = []
    for part in content:
        if isinstance(part, str):
            chunks.append(part)
        elif isinstance(part, dict):
            part_type = str(part.get("type") or "").strip().lower()
            if part_type and part_type not in {
                "text",
                "input_text",
                "output_text",
            }:
                continue
            value = part.get("text")
            if not isinstance(value, str):
                value = part.get("content")
            if isinstance(value, str):
                chunks.append(value)
    return "".join(chunks)


def recent_user_message_text(content: object) -> str:
    """Return a suffix-safe representation for any user content.

    Text is preserved verbatim, including empty/whitespace-only strings. A
    media-only block gets a stable marker rather than leaking image/tool
    payload fields into the summary.
    """
    text = user_message_text(content)
    if text or not isinstance(content, list) or not content:
        return text
    return NON_TEXT_USER_MESSAGE_PLACEHOLDER


__all__ = [
    "RECENT_USER_MESSAGES_HEADING",
    "RECENT_USER_MESSAGES_METADATA_KEY",
    "NON_TEXT_USER_MESSAGE_PLACEHOLDER",
    "append_recent_user_messages",
    "extract_recent_user_messages",
    "format_messages_for_compaction",
    "has_structured_sections",
    "inherit_prior_protected_context",
    "normalize_legacy_compaction_summary",
    "parse_compaction_summary",
    "strip_recent_user_messages",
    "truncate_text_to_tokens",
    "recent_user_message_text",
    "user_message_text",
    "with_compaction_prefix",
]
