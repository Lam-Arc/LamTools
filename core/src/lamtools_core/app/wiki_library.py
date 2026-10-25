"""内置 Wiki：随版本打包的一组 markdown 文档（只读）。

user:“wiki 内置进 library，作为方案/记忆之外的第四项”+版本锁定——
随包分发，agent 与用户在当前版本里看到的 wiki 与运行版本一致。
最小实现：目录扫描 + 读取，检索复用 library 既有面。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


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


def read_wiki_article(slug: str) -> dict[str, str]:
    root = wiki_root().resolve()
    target = (root / f"{str(slug).strip()}.md").resolve()
    # user:“wiki 是只读文档集”+路径必须留在 wiki 目录内，防穿越。
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError(f"wiki 文章不存在: {slug}")
    text = target.read_text(encoding="utf-8")
    title, _summary = _parse_article(text)
    return {"slug": slug, "title": title, "content": text}


__all__ = ["read_wiki_article", "scan_wiki", "wiki_root"]
