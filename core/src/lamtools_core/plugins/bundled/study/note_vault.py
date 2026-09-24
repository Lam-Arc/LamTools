"""Filesystem-backed Study note vault."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
SOURCE_FOOTER_RE = re.compile(
    r"(?:\n|\A)<!-- lamtools:sources-begin -->\n.*?\n<!-- lamtools:sources ([^\n]*) -->\s*\Z",
    re.DOTALL,
)
INVALID_SEGMENT_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))}

@dataclass(frozen=True)
class NoteDocument:
    metadata: dict[str, Any]
    content: str
    content_hash: str

def content_hash(content: str) -> str:
    """Hash the editable body, excluding host-owned frontmatter/footer."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

def vault_root(database_path: Path, scope_key: str) -> Path:
    digest = hashlib.sha256(scope_key.encode('utf-8')).hexdigest()[:24]
    return database_path.parent / 'study-notes' / digest

def _safe_segment(value: str, fallback: str) -> str:
    segment = INVALID_SEGMENT_RE.sub('-', value.strip()).strip(' .-')
    segment = re.sub(r'\s+', ' ', segment)[:96].strip()
    if not segment or segment.casefold() in WINDOWS_RESERVED:
        segment = fallback
    return segment

def normalize_relative_path(requested: str | None, *, title: str, note_id: str,
                            existing: set[str] | None = None) -> str:
    """Normalize a safe POSIX path and reject Windows case collisions."""
    existing = existing or set()
    folded = {item.casefold() for item in existing}
    raw = str(requested or '').replace('\\', '/').strip()
    if raw:
        path = PurePosixPath(raw)
        if path.is_absolute() or any(part in ('', '.', '..') for part in path.parts):
            raise ValueError('INVALID_NOTE_PATH')
        parts = [_safe_segment(part, f'folder-{i + 1}') for i, part in enumerate(path.parts)]
        if not parts[-1].casefold().endswith('.md'):
            parts[-1] += '.md'
        relative = PurePosixPath(*parts).as_posix()
    else:
        relative = f"{_safe_segment(title, 'note')}.md"
    if relative.casefold() not in folded:
        return relative
    path = PurePosixPath(relative)
    suffix = hashlib.sha256(note_id.encode('utf-8')).hexdigest()[:8]
    candidate = path.with_name(f'{path.stem}-{suffix}.md').as_posix()
    if candidate.casefold() in folded:
        raise ValueError('NOTE_PATH_EXISTS')
    return candidate

def _footer(metadata: dict[str, Any]) -> str:
    resource_ids = list(metadata.get('resource_ids') or [])
    references = metadata.get('resource_refs') or [{'id': value, 'title': value} for value in resource_ids]
    links = ' · '.join(
        f"[{_markdown_label(item.get('title') or item.get('id'))}]"
        f"(lamtools-resource://{quote(str(item.get('id')), safe='')})"
        for item in references if item.get('id')
    )
    sentinel = '<!-- lamtools:sources ' + json.dumps(resource_ids, ensure_ascii=False, separators=(',', ':')) + ' -->'
    return f'<!-- lamtools:sources-begin -->\n> 来源：{links}\n{sentinel}'


def _markdown_label(value: Any) -> str:
    """Keep host-owned source lines single-line and Markdown-safe."""
    label = ' '.join(str(value).split())
    return label.replace('\\', '\\\\').replace('[', '\\[').replace(']', '\\]')

def serialize_document(metadata: dict[str, Any], content: str) -> str:
    lines = ['---']
    for key in ('id', 'title', 'parent_id', 'resource_ids', 'revision'):
        lines.append(f'{key}: {json.dumps(metadata.get(key), ensure_ascii=False, separators=(",", ":"))}')
    lines.extend(('---', content.rstrip('\n'), '', _footer(metadata)))
    return '\n'.join(lines)

def parse_document(raw: str) -> NoteDocument:
    metadata: dict[str, Any] = {}
    match = FRONTMATTER_RE.match(raw)
    content = raw[match.end():] if match else raw
    if match:
        for line in match.group(1).splitlines():
            if ':' not in line:
                continue
            key, encoded = line.split(':', 1)
            try:
                metadata[key.strip()] = json.loads(encoded.strip())
            except json.JSONDecodeError:
                metadata[key.strip()] = encoded.strip().strip('"').strip("'")
    footer = SOURCE_FOOTER_RE.search(content)
    if footer:
        content = content[:footer.start()].rstrip('\n')
    return NoteDocument(metadata, content, content_hash(content))

def resolve_document_path(root: Path, relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or any(part in ('', '.', '..') for part in relative.parts):
        raise ValueError('INVALID_NOTE_PATH')
    # The vault is host-owned storage next to the Study database.  Resolving
    # the supplied root as the trust anchor would accept a symlink to anywhere.
    container = root.parent
    if container.is_symlink() or root.is_symlink():
        raise ValueError('INVALID_NOTE_PATH')
    expected_root = container.parent.resolve() / container.name / root.name
    if root.resolve() != expected_root:
        raise ValueError('INVALID_NOTE_PATH')
    target, resolved_root = root.joinpath(*relative.parts).resolve(), root.resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError('INVALID_NOTE_PATH') from exc
    if target.suffix.casefold() != '.md':
        raise ValueError('INVALID_NOTE_PATH')
    return target

def read_document(root: Path, relative_path: str) -> NoteDocument:
    try:
        return parse_document(resolve_document_path(root, relative_path).read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise ValueError('NOTE_FILE_MISSING') from exc
    except UnicodeDecodeError as exc:
        raise ValueError('NOTE_FILE_NOT_UTF8') from exc

def write_document(root: Path, relative_path: str, metadata: dict[str, Any], content: str,
                   *, replace: bool = True) -> NoteDocument:
    target = resolve_document_path(root, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f'.{target.name}.', suffix='.tmp', dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(serialize_document(metadata, content))
            handle.flush()
            os.fsync(handle.fileno())
        if replace:
            os.replace(temporary, target)
        else:
            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                raise ValueError('NOTE_PATH_EXISTS') from exc
    finally:
        if temporary.exists():
            temporary.unlink()
    return NoteDocument(dict(metadata), content, content_hash(content))
