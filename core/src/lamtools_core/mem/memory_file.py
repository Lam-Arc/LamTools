"""Parse and rewrite the project-level ``MEMORY.md`` file.

``MEMORY.md`` is the *long-term* memory layer: human-readable, version-
controlled, and loaded verbatim into the system prompt every turn by
``ProjectContextLoader`` (``app/project_context.py``). Dreaming distils
session content into structured entries and merges them back here.

The file uses fixed Markdown sections so it is both human-editable and
machine-parseable::

    # Memory

    > 由 LamTools dreaming 自动维护。可手动编辑；下次 dreaming 以手动内容为基线归并。

    ## Preferences
    - [2026-08-05] 用户偏好 PowerShell 中文用 UTF-8 — source: session#abc123

    ## Facts
    - [2026-08-05] 项目数据库在 data/core.db — source: session#abc123

    ## Decisions
    ...

    ## Todo
    - [ ] 给 memory.search 接 FTS5

    ## Deprecated
    - ~~考虑用向量检索~~（LIKE 足够，暂不需要）

Each entry is a list item. A leading ``- [ ]`` marks an open todo,
``- [x]`` a done todo, ``- ~~...~~`` a deprecated item, and ``-`` a plain
entry. A trailing ``source: <id>`` marks machine-originated entries; entries
without a source tag are treated as human-authored and are always preserved
on rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re
from typing import Literal

from lamtools_core.mem import MemoryEntry

__all__ = [
    "MemorySection",
    "SECTION_ORDER",
    "SECTION_KIND_MAP",
    "MemorySnapshot",
    "parse_memory_md",
    "write_memory_md",
    "merge_into_memory_md",
]

MemorySection = Literal["preferences", "facts", "decisions", "todo", "deprecated"]

SECTION_ORDER: tuple[MemorySection, ...] = ("preferences", "facts", "decisions", "todo", "deprecated")

# Maps a section to the default ``kind`` for entries parsed from it.
SECTION_KIND_MAP: dict[MemorySection, str] = {
    "preferences": "preference",
    "facts": "fact",
    "decisions": "decision",
    "todo": "todo",
    "deprecated": "deprecated",
}

SECTION_HEADERS: dict[str, MemorySection] = {
    "preferences": "preferences",
    "preference": "preferences",
    "facts": "facts",
    "fact": "facts",
    "decisions": "decisions",
    "decision": "decisions",
    "todo": "todo",
    "todos": "todo",
    "deprecated": "deprecated",
}

_MEMORY_HEADER = """# Memory

> 由 LamTools dreaming 自动维护。跨会话的长期记忆，每次会话自动加载。
> 可手动编辑；下次 dreaming 以手动内容为基线归并。
"""

MAX_MEMORY_MD_CHARS = 20000  # aligns with ProjectContextLoader._read max_chars_per_file

# - [date] content — source: id
_ENTRY_RE = re.compile(
    r"""^-\s*                # list dash
        (?:(?P<done>\[x\])|(?P<open>\[\s\]))?\s*  # optional [x] / [ ]
        (?:\[(?P<date>\d{4}-\d{2}-\d{2})\]\s*)?    # optional [date]
        (?P<content>.+?)                            # content
        \s*(?:—\s*source:\s*(?P<source>\S+))?\s*$  # optional — source: id
    """,
    re.VERBOSE,
)

_DEPRECATED_RE = re.compile(r"^~~(.+)~~\s*(?:（(.+)）|\((.+)\))?\s*$")


@dataclass
class ParsedEntry:
    """A single parsed line from MEMORY.md."""

    content: str
    section: MemorySection
    source: str = ""  # empty => human-authored
    date: str = ""
    is_todo_open: bool = False
    is_todo_done: bool = False
    is_deprecated: bool = False
    note: str = ""  # parenthetical reason for deprecated entries

    @property
    def is_human(self) -> bool:
        return not self.source


@dataclass
class MemorySnapshot:
    """Parsed representation of MEMORY.md."""

    entries: list[ParsedEntry] = field(default_factory=list)
    raw: str = ""

    def section(self, name: MemorySection) -> list[ParsedEntry]:
        return [e for e in self.entries if e.section == name]


def parse_memory_md(path: Path | str) -> MemorySnapshot:
    """Parse a MEMORY.md file into a :class:`MemorySnapshot`.

    Returns an empty snapshot if the file does not exist or cannot be read.
    Lines that are not recognised as section headers or list entries are
    dropped from the structured result (they are not needed for merging;
    human prose lives in AGENTS.md / CONTEXT.md instead).
    """
    p = Path(path)
    if not p.is_file():
        return MemorySnapshot()
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return MemorySnapshot()

    snapshot = MemorySnapshot(raw=text)
    current: MemorySection | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # Section header: ## Preferences / ## Facts / ...
        header_match = re.match(r"^#{1,6}\s+(.+)$", stripped)
        if header_match:
            title = header_match.group(1).strip().lower()
            current = SECTION_HEADERS.get(title)
            continue

        if current is None:
            # Skip preamble (title, blockquote) and unstructured lines.
            continue

        # List item
        if stripped.startswith("-"):
            entry = _parse_line(stripped, current)
            if entry is not None:
                snapshot.entries.append(entry)

    return snapshot


def _parse_line(line: str, section: MemorySection) -> ParsedEntry | None:
    m = _ENTRY_RE.match(line)
    if not m:
        return None

    content = (m.group("content") or "").strip()
    source = (m.group("source") or "").strip()
    date = (m.group("date") or "").strip()
    is_open = bool(m.group("open"))
    is_done = bool(m.group("done"))

    is_deprecated = False
    note = ""
    dep = _DEPRECATED_RE.match(content)
    if dep:
        is_deprecated = True
        content = dep.group(1).strip()
        note = (dep.group(2) or dep.group(3) or "").strip()

    return ParsedEntry(
        content=content,
        section=section,
        source=source,
        date=date,
        is_todo_open=is_open,
        is_todo_done=is_done,
        is_deprecated=is_deprecated,
        note=note,
    )


def write_memory_md(path: Path | str, snapshot: MemorySnapshot) -> None:
    """Write a snapshot back to ``MEMORY.md`` (full rewrite)."""
    lines: list[str] = [_MEMORY_HEADER.rstrip(), ""]

    for section in SECTION_ORDER:
        entries = snapshot.section(section)
        if not entries:
            continue
        lines.append(f"## {section.capitalize()}")
        lines.append("")
        for entry in entries:
            lines.append(_format_line(entry))
        lines.append("")

    text = "\n".join(lines).rstrip() + "\n"
    if len(text) > MAX_MEMORY_MD_CHARS:
        text = _trim_to_budget(snapshot, text)
    Path(path).write_text(text, encoding="utf-8")


def _format_line(entry: ParsedEntry) -> str:
    prefix = "-"
    if entry.is_todo_done:
        prefix = "- [x]"
    elif entry.is_todo_open:
        prefix = "- [ ]"

    content = entry.content
    if entry.is_deprecated:
        content = f"~~{content}~~"
        if entry.note:
            content = f"{content}（{entry.note}）"

    date_part = f"[{entry.date}] " if entry.date else ""
    source_part = f" — source: {entry.source}" if entry.source else ""
    return f"{prefix} {date_part}{content}{source_part}"


def _trim_to_budget(snapshot: MemorySnapshot, text: str) -> str:
    """When over the char budget, drop lowest-value machine entries first.

    Priority for keeping: human entries > higher confidence machine entries.
    Deprecated entries are dropped before anything else.
    """
    # Rank machine entries: deprecated first to drop, then by source recency
    # (older sources dropped first — we approximate with content length as a
    # tiebreak). Human entries are never dropped.
    drop_order = sorted(
        [e for e in snapshot.entries if not e.is_human],
        key=lambda e: (e.is_deprecated, e.date, len(e.content)),
    )
    for entry in drop_order:
        snapshot.entries.remove(entry)
        lines: list[str] = [_MEMORY_HEADER.rstrip(), ""]
        for section in SECTION_ORDER:
            entries = snapshot.section(section)
            if not entries:
                continue
            lines.append(f"## {section.capitalize()}")
            lines.append("")
            for e in entries:
                lines.append(_format_line(e))
            lines.append("")
        text = "\n".join(lines).rstrip() + "\n"
        if len(text) <= MAX_MEMORY_MD_CHARS:
            break
    return text


# ── merge helper ─────────────────────────────────────────────────


def merge_into_memory_md(
    path: Path | str,
    new_entries: list[MemoryEntry],
    *,
    today: str | None = None,
) -> dict[str, int]:
    """Merge structured memory entries into MEMORY.md and rewrite it.

    - Human-authored entries (no ``source``) are always preserved.
    - Machine entries with a ``source`` already in the file are updated
      in place (content / date refreshed); new sources are appended.
    - Returns a dict with ``added`` / ``updated`` / ``total`` counts.

    ``new_entries`` should already be de-duplicated against the short-term
    store; this function only handles the file-level merge.
    """
    snapshot = parse_memory_md(path)
    date_str = today or datetime.now().strftime("%Y-%m-%d")

    # Index existing machine entries by (source, section) for lookup. Source
    # alone is not unique — one session can contribute entries of different
    # kinds — so we pair it with the section to avoid clobbering.
    by_key: dict[tuple[str, MemorySection], ParsedEntry] = {}
    for entry in snapshot.entries:
        if entry.source:
            by_key[(entry.source, entry.section)] = entry

    added = 0
    updated = 0

    for mem in new_entries:
        section = _kind_to_section(mem.kind)
        source = mem.source or mem.id
        existing = by_key.get((source, section))

        if existing is not None:
            # Update in place.
            existing.content = mem.content
            existing.date = date_str
            existing.source = source
            updated += 1
        else:
            new_entry = ParsedEntry(
                content=mem.content,
                section=section,
                source=source,
                date=date_str,
                is_todo_open=(mem.kind == "todo"),
            )
            snapshot.entries.append(new_entry)
            by_key[(source, section)] = new_entry
            added += 1

    write_memory_md(path, snapshot)
    return {"added": added, "updated": updated, "total": len(snapshot.entries)}


def _kind_to_section(kind: str) -> MemorySection:
    kind_lower = (kind or "").lower()
    for section, sec_kind in SECTION_KIND_MAP.items():
        if kind_lower == sec_kind:
            return section
    # Default unknown kinds to facts.
    return "facts"
