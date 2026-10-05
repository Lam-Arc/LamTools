"""方案 library — plans are markdown files in the project's 「方案/」 folder.

One plan is one document: a small frontmatter (状态 / 摘要 / 收藏) over the
body sections (需求与边界、取舍、步骤、目标与完成判据、风险、未答问题). The
agent drafts and edits these files with its ordinary file tools while it talks
to the user; this module reads the folder and provides the library's file
operations (create / folder / rename / move / favorite) so the UI, the CLI and
the agent all work on the same plain files.
"""

from __future__ import annotations

import os
import re
import shutil
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

#: Frontmatter values meaning "this plan is starred".
_FAVORITE_TRUTHY = {"true", "yes", "1", "是", "y", "on"}

_PLAN_SKELETON = """---
状态: 草稿
摘要:
---

# {title}

（在这里写下方案内容。就绪后对助手说「可以开工了」。）
"""


class PlanLibraryError(ValueError):
    """A library file operation cannot be performed safely."""


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


def _upsert_frontmatter_field(text: str, key: str, value: str | None) -> str:
    """Set ``key: value`` in the document's frontmatter; ``None`` removes it.

    Documents without a frontmatter block get one prepended when a value is
    set. The body is never touched.
    """
    lines = text.splitlines(keepends=True)
    if text.startswith("---"):
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                head, body = lines[: index + 1], lines[index + 1 :]
                kept = [line for line in head[1:-1] if not line.strip().lower().startswith(f"{key.lower()}:")]
                if value is not None:
                    kept.append(f"{key}: {value}\n")
                return "---\n" + "".join(kept) + "---\n" + "".join(body)
    if value is None:
        return text
    return f"---\n{key}: {value}\n---\n{text}"


def normalize_plan_status(raw: str | None) -> str:
    """A frontmatter 状态 value as the library's four states; unknown → draft."""
    return _STATUS_ALIASES.get((raw or "").strip().lower(), "draft")


def _clean_segment(name: str, *, kind: str = "名称") -> str:
    """Validate one on-disk path segment (a file or folder name)."""
    cleaned = (name or "").strip().strip(".")
    if not cleaned:
        raise PlanLibraryError(f"{kind}不能为空")
    if cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned or ":" in cleaned:
        raise PlanLibraryError(f"{kind}不能包含路径分隔符")
    if re.search(r'[*?"<>|\x00-\x1f]', cleaned):
        raise PlanLibraryError(f"{kind}含有不允许的字符")
    return cleaned


def _clean_relative_dir(relative: str, *, kind: str = "文件夹名称") -> str:
    """Validate a folder path inside 「方案/」, one or more segments deep.

    ``归档`` and ``归档/这一期`` are both fine; every segment is checked on its
    own so a nested path can never smuggle in a separator, ``..`` or a reserved
    character.
    """
    cleaned = (relative or "").strip().replace("\\", "/").strip("/")
    segments = [segment for segment in cleaned.split("/") if segment.strip()]
    if not segments:
        raise PlanLibraryError(f"{kind}不能为空")
    return "/".join(_clean_segment(segment, kind=kind) for segment in segments)


def _resolve_library_path(work_root: str | Path, relative: str) -> Path:
    """Resolve a library-relative path (``方案/...``), contained to the folder."""
    root = plan_library_root(work_root).resolve()
    cleaned = (relative or "").strip().replace("\\", "/").strip("/")
    if not cleaned:
        raise PlanLibraryError("路径不能为空")
    target = (Path(work_root).resolve() / cleaned).resolve()
    try:
        target.relative_to(root)
    except ValueError as cause:
        raise PlanLibraryError("路径越出了方案文件夹") from cause
    if target == root:
        raise PlanLibraryError("路径不能是方案文件夹本身")
    return target


def _entry_for(path: Path, work_root: str | Path) -> dict[str, Any]:
    library_root = plan_library_root(work_root).resolve()
    stat = path.stat()
    title = path.stem
    status = "draft"
    summary = ""
    favorite = False
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError, OSError):
        text = ""
    if text:
        fields, body = _parse_frontmatter(text)
        status = normalize_plan_status(fields.get("状态") or fields.get("status"))
        summary = fields.get("摘要") or fields.get("summary") or ""
        favorite = fields.get("收藏", "").strip().lower() in _FAVORITE_TRUTHY
        title = _plan_title(body, path.name)
    folder = path.parent.resolve().relative_to(library_root).as_posix()
    return {
        "name": path.name,
        "path": f"{PLAN_LIBRARY_DIRNAME}/{folder}/{path.name}" if folder != "." else f"{PLAN_LIBRARY_DIRNAME}/{path.name}",
        "folder": "" if folder == "." else folder,
        "title": title,
        "status": status,
        "summary": summary,
        "favorite": favorite,
        "size": stat.st_size,
        "updated_at": int(stat.st_mtime),
    }


def _plan_title(body: str, filename: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return filename.removesuffix(".md")


def scan_plan_library(work_root: str | Path) -> list[dict[str, Any]]:
    """Every markdown file in 「方案/」 (recursively), newest first.

    A file that cannot be read degrades to a title-only draft entry rather than
    hiding from the list — the library shows what is on disk. ``folder`` is the
    file's directory inside 「方案/」 (empty for the top level).
    """
    root = plan_library_root(work_root)
    if not root.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
            continue
        try:
            entries.append(_entry_for(path, work_root))
        except (OSError, ValueError):
            continue  # a file vanishing or escaping mid-scan must not break the list
    entries.sort(key=lambda entry: (entry["updated_at"], entry["name"]), reverse=True)
    return entries


def _folder_entry(path: Path, work_root: str | Path) -> dict[str, Any]:
    """One folder as the library reports it, with its depth in 「方案/」."""
    library_root = plan_library_root(work_root).resolve()
    relative = path.resolve().relative_to(library_root).as_posix()
    count = sum(1 for _ in path.rglob("*.md"))
    return {
        "name": path.name,
        "path": f"{PLAN_LIBRARY_DIRNAME}/{relative}",
        # 与 entry.folder 同一口径：库内相对目录，根为 ""。
        "dir": relative,
        "parent": relative.rsplit("/", 1)[0] if "/" in relative else "",
        "count": count,
    }


def list_plan_folders(work_root: str | Path) -> list[dict[str, Any]]:
    """Every folder inside 「方案/」 at any depth, sorted by path.

    The flat list carries each folder's own ``dir`` and ``parent`` so any
    consumer can render one level at a time without a second round trip.
    """
    root = plan_library_root(work_root)
    if not root.is_dir():
        return []
    folders: list[dict[str, Any]] = []
    for current, dirnames, _ in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
        for name in dirnames:
            folders.append(_folder_entry(Path(current) / name, work_root))
    folders.sort(key=lambda folder: folder["dir"])
    return folders


def _resolve_folder(work_root: str | Path, folder: str, *, must_exist: bool = True) -> Path:
    """Resolve a (possibly nested) folder inside 「方案/」, refusing escapes."""
    relative = _clean_relative_dir(folder)
    target = _resolve_library_path(work_root, f"{PLAN_LIBRARY_DIRNAME}/{relative}")
    if must_exist and not target.is_dir():
        raise PlanLibraryError("目标文件夹不存在")
    return target


def create_plan(work_root: str | Path, name: str, *, folder: str = "") -> dict[str, Any]:
    """Create one skeleton plan document; refuses to overwrite."""
    cleaned = _clean_segment(name, kind="方案名称")
    stem = cleaned if cleaned.lower().endswith(".md") else f"{cleaned}.md"
    title = stem[:-3]
    if folder:
        # 文件夹可以是任意深度，但必须是已经在那儿的一层；先校验再动盘。
        target = _resolve_folder(work_root, folder) / stem
    else:
        target = plan_library_root(work_root) / stem
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise PlanLibraryError("同名方案已存在")
    target.write_text(_PLAN_SKELETON.format(title=title), encoding="utf-8")
    return _entry_for(target, work_root)


def create_folder(work_root: str | Path, path: str) -> dict[str, Any]:
    """Create one folder inside 「方案/」; nested paths build one level deeper."""
    root = plan_library_root(work_root).resolve()
    target = _resolve_library_path(work_root, f"{PLAN_LIBRARY_DIRNAME}/{_clean_relative_dir(path)}")
    if target.exists():
        raise PlanLibraryError("同名文件夹已存在")
    if target.parent == root:
        root.mkdir(parents=True, exist_ok=True)  # 「方案/」随第一次建夹产生
    elif not target.parent.is_dir():
        raise PlanLibraryError("上级文件夹不存在")
    target.mkdir()
    return _folder_entry(target, work_root)


def delete_folder(work_root: str | Path, path: str) -> dict[str, str]:
    """Delete one empty folder at any depth inside 「方案/」."""
    target = _resolve_library_path(work_root, path)
    if not target.is_dir():
        raise PlanLibraryError("文件夹不存在")
    if any(target.iterdir()):
        raise PlanLibraryError("文件夹不是空的，先移走或删除里面的内容")
    target.rmdir()
    return {"deleted": path}


def rename_plan(work_root: str | Path, path: str, new_name: str) -> dict[str, Any]:
    """Rename one plan document in place (same folder)."""
    target = _resolve_library_path(work_root, path)
    if not target.is_file() or target.suffix.lower() != ".md":
        raise PlanLibraryError("只有方案文档可以重命名")
    cleaned = _clean_segment(new_name, kind="方案名称")
    stem = cleaned if cleaned.lower().endswith(".md") else f"{cleaned}.md"
    renamed = target.with_name(stem)
    if renamed.exists():
        raise PlanLibraryError("同名方案已存在")
    renamed = renamed.resolve()
    renamed.relative_to(plan_library_root(work_root).resolve())
    target.rename(renamed)
    return _entry_for(renamed, work_root)


def move_plan(work_root: str | Path, path: str, folder: str = "") -> dict[str, Any]:
    """Move one plan document to the library root ('') or any existing folder."""
    target = _resolve_library_path(work_root, path)
    if not target.is_file() or target.suffix.lower() != ".md":
        raise PlanLibraryError("只有方案文档可以移动")
    destination_dir = _resolve_folder(work_root, folder) if folder else plan_library_root(work_root).resolve()
    destination = destination_dir / target.name
    if destination.exists():
        raise PlanLibraryError("目标文件夹里有同名方案")
    shutil.move(str(target), str(destination))
    return _entry_for(destination, work_root)


def set_plan_favorite(work_root: str | Path, path: str, *, favorite: bool) -> dict[str, Any]:
    """Star (or unstar) one plan by writing the 收藏 frontmatter field."""
    target = _resolve_library_path(work_root, path)
    if not target.is_file() or target.suffix.lower() != ".md":
        raise PlanLibraryError("只有方案文档可以收藏")
    text = target.read_text(encoding="utf-8")
    updated = _upsert_frontmatter_field(text, "收藏", "true" if favorite else None)
    if updated != text:
        target.write_text(updated, encoding="utf-8")
    return _entry_for(target, work_root)
