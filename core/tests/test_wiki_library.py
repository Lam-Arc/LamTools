"""Bundled wiki navigation: README is the outline of the shipped manual.

The wiki ships as version-locked markdown (wiki/ at the repo root). README.md
is the hand-written table of contents; the library UI renders that structure
as its left rail, so every article must appear exactly once under the category
the README gives it, and a wiki without a README must still be browsable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.app import wiki_library
from lamtools_core.app.wiki_library import (
    read_wiki_article,
    scan_wiki,
    wiki_root,
    wiki_tree,
)


def test_tree_groups_every_article_once_in_readme_order() -> None:
    articles = scan_wiki()
    tree = wiki_tree()

    assert tree["index"] == "README"
    groups = tree["groups"]
    assert [group["title"] for group in groups][:2] == ["一、开始使用", "二、任务与规划"]
    assert groups[0]["articles"][0] == "articles/welcome"
    assert groups[-1]["title"] == "十二、帮助与参考"

    listed = [slug for group in groups for slug in group["articles"]]
    expected = {article["slug"] for article in articles if article["slug"] != tree["index"]}
    assert len(listed) == len(set(listed)), "同一篇文章在目录里出现了不止一次"
    assert set(listed) == expected


def test_tree_titles_come_from_readme_category_headings() -> None:
    tree = wiki_tree()
    ids = [group["id"] for group in tree["groups"]]
    assert len(ids) == len(set(ids))
    assert all(group["title"] for group in tree["groups"])


def test_tree_falls_back_to_sections_without_readme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "wiki"
    (root / "articles").mkdir(parents=True)
    (root / "articles" / "one.md").write_text("# 第一篇\n\n正文\n", encoding="utf-8")
    (root / "articles" / "two.md").write_text("# 第二篇\n\n正文\n", encoding="utf-8")
    monkeypatch.setattr(wiki_library, "wiki_root", lambda: root)

    tree = wiki_tree()

    assert tree["index"] == ""
    assert [group["title"] for group in tree["groups"]] == ["articles"]
    assert tree["groups"][0]["articles"] == ["articles/one", "articles/two"]


def test_tree_ignores_links_that_point_outside_the_wiki(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "wiki"
    root.mkdir()
    (root / "README.md").write_text(
        "# 目录\n\n## 一、开始\n\n- [第一篇](articles/one.md)\n- [源码](../../core/app.py)\n",
        encoding="utf-8",
    )
    (root / "articles").mkdir()
    (root / "articles" / "one.md").write_text("# 第一篇\n", encoding="utf-8")
    monkeypatch.setattr(wiki_library, "wiki_root", lambda: root)

    tree = wiki_tree()

    assert tree["groups"] == [{"id": "group-0", "title": "一、开始", "articles": ["articles/one"]}]


def test_read_article_stays_inside_the_wiki(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = wiki_root()
    with pytest.raises(ValueError):
        read_wiki_article("../AGENTS.md")
    assert root.is_dir()
