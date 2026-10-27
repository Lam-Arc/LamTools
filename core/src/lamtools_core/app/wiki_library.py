"""内置 Wiki：随版本打包的一组 markdown 文档（只读）。

user:“wiki 内置进 library，作为方案/记忆之外的第四项”+版本锁定——
随包分发，agent 与用户在当前版本里看到的 wiki 与运行版本一致。
最小实现：目录扫描 + 读取，检索复用 library 既有面。
"""

from __future__ import annotations

import posixpath
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote

# user:“wiki中的UI并没有良好的表现层级关系，建议以左侧以窄栏显示文件层级”+
# README 就是随包文档手写的目录：按它的 H2 分类和链接顺序生成左栏层级。
_README_SLUG = "README"
_HEADING_RE = re.compile(r"^(#{2,6})\s+(.+?)\s*$")
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def wiki_root() -> Path:
    """frozen 读 _MEIPASS/resources/wiki；dev 读仓库根 wiki/。"""
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return meipass / "resources" / "wiki"
    # app/wiki_library.py → lamtools_core → src → core → 仓库根
    return Path(__file__).resolve().parents[4] / "wiki"


def _parse_article(text: str) -> tuple[str, str]:
    """返回 (title, summary)：title 取 # 标题，summary 取 frontmatter 摘要。"""
    title = ""
    summary = ""
    lines = text.splitlines()
    in_frontmatter = bool(lines and lines[0].strip() == "---")
    for index, line in enumerate(lines):
        if index == 0 and in_frontmatter:
            continue
        if in_frontmatter:
            if line.strip() == "---":
                in_frontmatter = False
            elif line.strip().startswith("摘要:"):
                summary = line.split(":", 1)[1].strip()
            continue
        if not title and line.strip().startswith("# "):
            title = line.strip()[2:].strip()
            if summary:
                break
    return title or "未命名", summary


def scan_wiki() -> list[dict[str, Any]]:
    root = wiki_root()
    if not root.is_dir():
        return []
    articles: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        title, summary = _parse_article(text)
        relative = path.relative_to(root)
        articles.append(
            {
                "slug": relative.with_suffix("").as_posix(),
                "title": title or relative.stem,
                "summary": summary,
                "section": relative.parent.as_posix() if relative.parent != Path(".") else "",
                "size": path.stat().st_size,
            }
        )
    return articles


def _wiki_slug_from_link(target: str, base_dir: str = "") -> str:
    """README 里的链接 → 文章 slug；不是 wiki 内的 markdown 就返回空串。"""
    path = target.split("#", 1)[0].split("?", 1)[0].strip()
    if not path:
        return ""
    path = unquote(path).replace("\\", "/")
    if path.startswith("/"):
        joined = path.lstrip("/")
    else:
        joined = posixpath.join(base_dir, path) if base_dir else path
    normalized = posixpath.normpath(joined)
    if normalized.startswith("../") or normalized == ".." or not normalized.lower().endswith(".md"):
        return ""
    slug = normalized[:-3]
    return "" if slug == _README_SLUG else slug


def _fallback_groups(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """没有 README 时按所在目录分组，保证左栏仍有层级可看。"""
    buckets: dict[str, list[str]] = {}
    for article in articles:
        slug = str(article.get("slug") or "")
        if not slug or slug == _README_SLUG:
            continue
        section = str(article.get("section") or "")
        buckets.setdefault(section, []).append(slug)
    return [
        {"id": f"group-{index}", "title": section or "文档", "articles": slugs}
        for index, (section, slugs) in enumerate(buckets.items())
    ]


def wiki_tree(articles: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """随包 wiki 的导航树：README 的 H2 分类 → 文章列表。

    返回 ``{"index": <索引 slug 或空串>, "groups": [{"id","title","articles"}]}``。
    README 缺失或不可读时退回「按目录分组」，UI 不因缺少索引而空白。
    """
    root = wiki_root()
    articles = articles if articles is not None else scan_wiki()
    readme = root / f"{_README_SLUG}.md"
    index_slug = _README_SLUG if readme.is_file() else ""
    if not index_slug:
        return {"index": "", "groups": _fallback_groups(articles)}

    try:
        text = readme.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {"index": "", "groups": _fallback_groups(articles)}

    known = {str(article.get("slug") or "") for article in articles}
    groups: list[dict[str, Any]] = []
    seen: set[str] = set()
    current_title = ""
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            if level == 2:
                current_title = heading.group(2).strip()
                groups.append({"id": f"group-{len(groups)}", "title": current_title, "articles": []})
            # 更深的小节（###/####）仍归在当前 H2 分类下，左栏保持两级。
            continue
        if not current_title:
            continue
        for target in _LINK_RE.findall(line):
            slug = _wiki_slug_from_link(target)
            if not slug or slug in seen or slug not in known:
                continue
            seen.add(slug)
            groups[-1]["articles"].append(slug)

    groups = [group for group in groups if group["articles"]]
    # README 里没列到的文章不能丢：补到末尾的「其他文档」。
    leftovers = sorted(known - seen - {_README_SLUG})
    if leftovers:
        groups.append({"id": f"group-{len(groups)}", "title": "其他文档", "articles": leftovers})
    if not groups:
        return {"index": "", "groups": _fallback_groups(articles)}
    return {"index": index_slug, "groups": groups}


def read_wiki_article(slug: str) -> dict[str, str]:
    root = wiki_root().resolve()
    target = (root / f"{str(slug).strip()}.md").resolve()
    # user:“wiki 是只读文档集”+路径必须留在 wiki 目录内，防穿越。
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError(f"wiki 文章不存在: {slug}")
    text = target.read_text(encoding="utf-8")
    title, _summary = _parse_article(text)
    return {"slug": slug, "title": title, "content": text}


__all__ = ["read_wiki_article", "scan_wiki", "wiki_root", "wiki_tree"]
