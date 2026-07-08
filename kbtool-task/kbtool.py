from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse


HEADING_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)
HASHTAG_RE = re.compile(r"(?<![\w/])#([A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*)")
FRONT_MATTER_TAGS_RE = re.compile(r"^tags:\s*(.+)$", re.MULTILINE)
WIKI_LINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]\n]+)\]\(([^)\n]+)\)")
TODO_RE = re.compile(r"^\s*[-*]\s+\[( |x|X)\]\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class TodoItem:
    text: str
    done: bool
    line: int


@dataclass
class MarkdownLink:
    label: str
    target: str
    kind: str
    line: int


@dataclass
class Note:
    path: Path
    rel_path: Path
    title: str
    tags: set[str] = field(default_factory=set)
    links: list[MarkdownLink] = field(default_factory=list)
    todos: list[TodoItem] = field(default_factory=list)


@dataclass
class BrokenLink:
    source: Path
    line: int
    target: str
    reason: str


@dataclass
class ScanResult:
    root: Path
    notes: list[Note]
    broken_links: list[BrokenLink]

    @property
    def tags(self) -> set[str]:
        result: set[str] = set()
        for note in self.notes:
            result.update(note.tags)
        return result

    @property
    def todo_count(self) -> int:
        return sum(len(note.todos) for note in self.notes)


def line_number(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def parse_front_matter_tags(text: str) -> set[str]:
    if not text.startswith("---"):
        return set()
    end = text.find("\n---", 3)
    if end == -1:
        return set()
    block = text[3:end]
    tags: set[str] = set()
    current_list = False
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = FRONT_MATTER_TAGS_RE.match(line)
        if match:
            current_list = False
            value = match.group(1).strip()
            if value.startswith("[") and value.endswith("]"):
                parts = value[1:-1].split(",")
                tags.update(clean_tag(part) for part in parts if clean_tag(part))
            elif value:
                tags.update(clean_tag(part) for part in value.split() if clean_tag(part))
            else:
                current_list = True
            continue
        if current_list and line.startswith("- "):
            tag = clean_tag(line[2:])
            if tag:
                tags.add(tag)
        elif not line.startswith("- "):
            current_list = False
    return tags


def clean_tag(value: str) -> str:
    return value.strip().strip("'\"").lstrip("#")


def extract_title(path: Path, text: str) -> str:
    match = HEADING_RE.search(text)
    if match:
        return match.group(1).strip()
    return path.stem.replace("-", " ").replace("_", " ").strip() or path.stem


def parse_note(path: Path, root: Path) -> Note:
    text = path.read_text(encoding="utf-8")
    note = Note(path=path, rel_path=path.relative_to(root), title=extract_title(path, text))
    note.tags.update(parse_front_matter_tags(text))
    note.tags.update(clean_tag(match.group(1)) for match in HASHTAG_RE.finditer(text) if clean_tag(match.group(1)))

    for match in WIKI_LINK_RE.finditer(text):
        raw_target = match.group(1).split("|", 1)[0].split("#", 1)[0].strip()
        if raw_target:
            note.links.append(MarkdownLink(
                label=raw_target,
                target=raw_target,
                kind="wiki",
                line=line_number(text, match.start()),
            ))

    for match in MARKDOWN_LINK_RE.finditer(text):
        target = match.group(2).strip()
        note.links.append(MarkdownLink(
            label=match.group(1).strip(),
            target=target,
            kind="markdown",
            line=line_number(text, match.start()),
        ))

    for match in TODO_RE.finditer(text):
        note.todos.append(TodoItem(
            text=match.group(2).strip(),
            done=match.group(1).lower() == "x",
            line=line_number(text, match.start()),
        ))
    return note


def scan_notes(root: Path) -> ScanResult:
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Directory not found: {root}")

    notes = [
        parse_note(path, root)
        for path in sorted(root.rglob("*.md"))
        if path.name.lower() != "index.md"
    ]
    broken_links = detect_broken_links(root, notes)
    return ScanResult(root=root, notes=notes, broken_links=broken_links)


def note_lookup(notes: list[Note]) -> tuple[set[str], set[str]]:
    page_names: set[str] = set()
    rel_files: set[str] = set()
    for note in notes:
        page_names.add(note.path.stem.lower())
        page_names.add(note.title.lower())
        rel_files.add(note.rel_path.as_posix().lower())
        rel_files.add(note.rel_path.with_suffix("").as_posix().lower())
    return page_names, rel_files


def detect_broken_links(root: Path, notes: list[Note]) -> list[BrokenLink]:
    page_names, rel_files = note_lookup(notes)
    broken: list[BrokenLink] = []
    for note in notes:
        for link in note.links:
            if link.kind == "wiki":
                target_key = link.target.replace("\\", "/").strip().lower()
                if target_key not in page_names and target_key not in rel_files:
                    broken.append(BrokenLink(note.rel_path, link.line, link.target, "missing wiki page"))
                continue

            parsed = urlparse(link.target)
            if parsed.scheme or link.target.startswith("#") or link.target.startswith("mailto:"):
                continue
            clean_target = unquote(link.target.split("#", 1)[0].strip())
            if not clean_target:
                continue
            target_path = (note.path.parent / clean_target).resolve()
            try:
                target_path.relative_to(root)
            except ValueError:
                broken.append(BrokenLink(note.rel_path, link.line, link.target, "target outside root"))
                continue
            if not target_path.exists():
                broken.append(BrokenLink(note.rel_path, link.line, link.target, "missing file"))
    return broken


def generate_index(result: ScanResult) -> str:
    lines: list[str] = ["# Knowledge Base Index", ""]
    lines.append("## By Tag")
    lines.append("")
    if result.tags:
        notes_by_tag: dict[str, list[Note]] = {tag: [] for tag in sorted(result.tags)}
        for note in result.notes:
            for tag in note.tags:
                notes_by_tag.setdefault(tag, []).append(note)
        for tag in sorted(notes_by_tag):
            lines.append(f"### #{tag}")
            for note in sorted(notes_by_tag[tag], key=lambda item: item.title.lower()):
                lines.append(f"- [{note.title}]({note.rel_path.as_posix()})")
            lines.append("")
    else:
        lines.append("_No tags found._")
        lines.append("")

    lines.append("## By Title")
    lines.append("")
    for note in sorted(result.notes, key=lambda item: item.title.lower()):
        tag_text = ", ".join(f"#{tag}" for tag in sorted(note.tags)) or "no tags"
        lines.append(f"- [{note.title}]({note.rel_path.as_posix()}) - {tag_text}")
    lines.append("")
    return "\n".join(lines)


def write_index(result: ScanResult) -> Path:
    index_path = result.root / "index.md"
    index_path.write_text(generate_index(result), encoding="utf-8")
    return index_path


def scan_command(root: Path) -> int:
    result = scan_notes(root)
    index_path = write_index(result)
    payload = {
        "root": str(result.root),
        "files": len(result.notes),
        "tags": sorted(result.tags),
        "todos": result.todo_count,
        "broken_links": len(result.broken_links),
        "index": str(index_path),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def report_command(root: Path) -> int:
    result = scan_notes(root)
    print(f"Files: {len(result.notes)}")
    print(f"Tags: {len(result.tags)}")
    print(f"Todos: {result.todo_count}")
    print("Broken links:")
    if not result.broken_links:
        print("- none")
    else:
        for item in result.broken_links:
            print(f"- {item.source.as_posix()}:{item.line} -> {item.target} ({item.reason})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Organize a local Markdown knowledge base.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("scan", "report"):
        sub = subparsers.add_parser(command)
        sub.add_argument("directory", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "scan":
            return scan_command(args.directory)
        if args.command == "report":
            return report_command(args.directory)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
