"""方案 library — plans are markdown files in the project's 「方案/」 folder.

One plan is one document: a small frontmatter (状态 / 摘要) over the body
sections (需求与边界、取舍、步骤、目标与完成判据、风险、未答问题). The agent
drafts and edits these files with its ordinary file tools while it talks to the
user; this module only reads the folder so the library can list what is there.
Nothing here parses the body into structures — the executing turn reads the
document the way a person would.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: The designated folder inside every project workspace.
PLAN_LIBRARY_DIRNAME = "方案"

#: Frontmatter values seen in the wild, mapped onto the four library states.
_STATUS_ALIASES = {
    "草稿": "draft",
    "draft": "draft",
    "就绪": "ready",
    "ready": "ready",
    "执行中": "executing",
    "executing": "executing",
    "完成": "done",
    "done": "done",
}


def plan_library_root(work_root: str | Path) -> Path:
    return Path(work_root) / PLAN_LIBRARY_DIRNAME


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Simple ``key: value`` lines between the first two ``---`` lines.

    A document without frontmatter (or with an unterminated block) comes back
    with empty fields and the text intact — the body is still readable.
    """
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            fields: dict[str, str] = {}
            for line in lines[1:index]:
                key, sep, value = line.partition(":")
                if sep and key.strip():
                    fields[key.strip().lower()] = value.strip()
            return fields, "\n".join(lines[index + 1:])
    return {}, text


def normalize_plan_status(raw: str | None) -> str:
    """A frontmatter 状态 value as the library's four states; unknown → draft."""
    return _STATUS_ALIASES.get((raw or "").strip().lower(), "draft")


def _plan_title(body: str, filename: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return filename.removesuffix(".md")


def scan_plan_library(work_root: str | Path) -> list[dict[str, Any]]:
    """Every markdown file in 「方案/」, newest first.

    A file that cannot be read degrades to a title-only draft entry rather than
    hiding from the list — the library shows what is on disk.
    """
    root = plan_library_root(work_root)
    if not root.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.md")):
        if not path.is_file():
            continue
        stat = path.stat()
        title = path.stem
        status = "draft"
        summary = ""
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError, OSError):
            text = ""
        if text:
            fields, body = _parse_frontmatter(text)
            status = normalize_plan_status(fields.get("状态") or fields.get("status"))
            summary = fields.get("摘要") or fields.get("summary") or ""
            title = _plan_title(body, path.name)
        entries.append(
            {
                "name": path.name,
                "path": f"{PLAN_LIBRARY_DIRNAME}/{path.name}",
                "title": title,
                "status": status,
                "summary": summary,
                "size": stat.st_size,
                "updated_at": int(stat.st_mtime),
            }
        )
    entries.sort(key=lambda entry: (entry["updated_at"], entry["name"]), reverse=True)
    return entries
