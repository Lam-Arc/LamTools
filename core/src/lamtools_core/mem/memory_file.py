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
import os
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
    line_index: int = -1  # index into MemorySnapshot.raw_lines (-1 => new entry)

    @property
    def is_human(self) -> bool:
        return not self.source


@dataclass
class MemorySnapshot:
    """Parsed representation of MEMORY.md."""

    entries: list[ParsedEntry] = field(default_factory=list)
    raw: str = ""
    # Full original file split into lines. Unrecognised lines (human prose,
    # custom sections, comments) are carried back verbatim on rewrite so a
    # dreaming merge never silently deletes hand-edited content (audit 11).
    raw_lines: list[str] = field(default_factory=list)

    def section(self, name: MemorySection) -> list[ParsedEntry]:
        return [e for e in self.entries if e.section == name]


def parse_memory_md(path: Path | str) -> MemorySnapshot:
    """Parse a MEMORY.md file into a :class:`MemorySnapshot`.

    Returns an empty snapshot if the file does not exist or cannot be read.
    Lines that are not recognised as section headers or list entries are kept
    in ``raw_lines`` (and thus preserved on rewrite); they are only excluded
    from the structured result (human prose lives in AGENTS.md / CONTEXT.md
    but custom sections in MEMORY.md must survive merges).
    """
    p = Path(path)
    if not p.is_file():
        return MemorySnapshot()
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return MemorySnapshot()

    raw_lines = text.splitlines()
    snapshot = MemorySnapshot(raw=text, raw_lines=raw_lines)
    current: MemorySection | None = None

    for index, line in enumerate(raw_lines):
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
                entry.line_index = index
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
    """Write a snapshot back to ``MEMORY.md``.

    Preserves every line that was not parsed as a machine entry — human prose,
    custom sections, comments — verbatim, then replaces the parsed entry lines
    in place and appends new entries at the tail of their section. The write
    is atomic (tmp file + rename) so a crash mid-write cannot corrupt the
    long-term memory file (audit 11).
    """
    text = _render(snapshot)
    _atomic_write(Path(path), text)


def _render(snapshot: MemorySnapshot) -> str:
    text = _render_lines(snapshot)
    if len(text) > MAX_MEMORY_MD_CHARS:
        text = _trim_to_budget(snapshot, text)
    return text


def _render_lines(snapshot: MemorySnapshot) -> str:
    """Render the snapshot without the budget trim."""
    raw_lines = snapshot.raw_lines or []
    if not raw_lines:
        # Brand-new file: emit the standard five sections.
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
        return "\n".join(lines).rstrip() + "\n"

    # Preserve unrecognised lines verbatim; replace only parsed entry lines.
    by_index = {entry.line_index: entry for entry in snapshot.entries if entry.line_index >= 0}
    output: list[str] = []
    for index, line in enumerate(raw_lines):
        entry = by_index.get(index)
        output.append(_format_line(entry) if entry is not None else line)
    _append_new_entries(output, snapshot)
    return "\n".join(output).rstrip() + "\n"


def _append_new_entries(lines: list[str], snapshot: MemorySnapshot) -> None:
    """Insert entries without an original line at the tail of their section."""
    pending: dict[MemorySection, list[ParsedEntry]] = {}
    for entry in snapshot.entries:
        if entry.line_index < 0:
            pending.setdefault(entry.section, []).append(entry)
    if not pending:
        return

    # Locate existing section headers in the output.
    header_index: dict[MemorySection, int] = {}
    for index, line in enumerate(lines):
        match = re.match(r"^#{1,6}\s+(.+)$", line.strip())
        if match:
            section = SECTION_HEADERS.get(match.group(1).strip().lower())
            if section is not None and section not in header_index:
                header_index[section] = index

    for section in SECTION_ORDER:
        entries = pending.get(section)
        if not entries:
            continue
        formatted = [_format_line(entry) for entry in entries]
        if section in header_index:
            insert_at = _section_tail(lines, header_index[section])
            lines[insert_at:insert_at] = ["", *formatted]
        else:
            # No such section in the file yet — append a new one at the end.
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(f"## {section.capitalize()}")
            lines.append("")
            lines.extend(formatted)


def _section_tail(lines: list[str], header_index: int) -> int:
    """Index just after the last non-empty line of the section at header_index."""
    end = len(lines)
    for index in range(header_index + 1, len(lines)):
        if re.match(r"^#{1,6}\s+", lines[index].strip()):
            end = index
            break
    last_content = header_index
    for index in range(header_index + 1, end):
        if lines[index].strip():
            last_content = index
    return last_content + 1


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


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
    Deprecated entries are dropped before anything else. Dropped entries are
    removed from the snapshot's raw lines as well, so unrecognised human
    content is still preserved verbatim.
    """
    # Rank machine entries: deprecated first to drop, then by source recency
    # (older sources dropped first — we approximate with content length as a
    # tiebreak). Human entries are never dropped.
    drop_order = sorted(
        [e for e in snapshot.entries if not e.is_human],
        key=lambda e: (e.is_deprecated, e.date, len(e.content)),
    )
    for entry in drop_order:
        if 0 <= entry.line_index < len(snapshot.raw_lines):
            del snapshot.raw_lines[entry.line_index]
            for other in snapshot.entries:
                if other.line_index > entry.line_index:
                    other.line_index -= 1
        snapshot.entries.remove(entry)
        text = _render_lines(snapshot)
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
