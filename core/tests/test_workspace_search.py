"""文件检索入口的边界：命中数、扫描预算、截断，都必须如实交出去。

对应 Easy Tools 第一批的第二件事。检索本身复用 `WorkspaceReadOnlyTools`，
这里验的是「界面拿到的那份结果诚不诚实」：搜全了没有、有多少是被上限截掉的、
内容命中能不能定位到行——这些决定用户敢不敢把结果当全部。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.tool.workspace_search import (
    DEFAULT_UI_SEARCH_LIMIT,
    MAX_UI_SEARCH_LIMIT,
    search_workspace,
)


def _make_tree(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.ts").write_text("const answer = 42\n", encoding="utf-8")
    (root / "src" / "helper.ts").write_text("export const x = 1\n", encoding="utf-8")
    (root / "README.md").write_text("# 说明\nanswer 在 main.ts 里\n", encoding="utf-8")
    return root


@pytest.mark.asyncio
async def test_finds_files_by_name_and_reports_the_scan_size(tmp_path: Path) -> None:
    root = _make_tree(tmp_path)

    report = await search_workspace(work_root=root, query="*.ts")

    paths = [hit["path"] for hit in report["matches"]]
    assert "src/main.ts" in paths
    assert "src/helper.ts" in paths
    assert report["match_count"] == 2
    # 「扫了多少」必须交出去，界面才能说清这份结果是从多大的树里找出来的。
    assert report["scanned_entries"] > 0
    assert report["scan_exhausted"] is False
    assert report["truncated"] is False


@pytest.mark.asyncio
async def test_content_search_returns_the_matching_line(tmp_path: Path) -> None:
    # user:“按文件名/内容检索并打开结果”+(内容命中要能定位到第几行)。
    root = _make_tree(tmp_path)

    report = await search_workspace(work_root=root, query="answer", mode="content")

    assert report["mode"] == "content"
    assert report["match_count"] >= 1
    main_hit = next(hit for hit in report["matches"] if hit["path"].endswith("main.ts"))
    assert main_hit["line"] == 1
    assert "answer" in main_hit["text"]


@pytest.mark.asyncio
async def test_hitting_the_result_cap_says_results_were_withheld(tmp_path: Path) -> None:
    # user:“结果过多要分页/截断并明示”+(顶部上限就是截断，不能装作找全了)。
    root = tmp_path / "project"
    root.mkdir()
    for index in range(12):
        (root / f"note{index}.md").write_text("payload\n", encoding="utf-8")

    report = await search_workspace(work_root=root, query="*.md", limit=5)

    assert len(report["matches"]) == 5
    assert report["truncated"] is True


@pytest.mark.asyncio
async def test_an_exhausted_scan_budget_is_never_reported_as_complete(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    for index in range(30):
        (root / f"file{index}.txt").write_text("payload\n", encoding="utf-8")

    # 界面可以比后台默认更保守：给一个必然耗尽的条目预算。
    report = await search_workspace(
        work_root=root, query="*.nomatch", limit=50, max_scan_entries=5,
    )

    assert report["matches"] == []
    assert report["scan_exhausted"] is True
    assert report["match_count"] == 0


@pytest.mark.asyncio
async def test_an_empty_query_asks_for_nothing_instead_of_scanning(tmp_path: Path) -> None:
    root = _make_tree(tmp_path)

    report = await search_workspace(work_root=root, query="   ")

    assert report["matches"] == []
    assert report["scanned_entries"] == 0
    assert report["scan_exhausted"] is False


@pytest.mark.asyncio
async def test_the_limit_is_clamped_to_a_sane_range(tmp_path: Path) -> None:
    root = _make_tree(tmp_path)

    # 0 是「只要 1 条」的合法请求，不能退化成「没给 limit」。
    small = await search_workspace(work_root=root, query="*.ts", limit=0)
    huge = await search_workspace(work_root=root, query="*.ts", limit=10_000)

    # 下限 1：只要一条，而且还有别的命中没回来，就必须说被截断了。
    assert len(small["matches"]) == 1
    assert small["truncated"] is True
    # 上限 MAX_UI_SEARCH_LIMIT：界面不该能把后台拖进无界扫描。
    assert len(huge["matches"]) <= MAX_UI_SEARCH_LIMIT
    assert DEFAULT_UI_SEARCH_LIMIT <= MAX_UI_SEARCH_LIMIT


@pytest.mark.asyncio
async def test_a_missing_work_root_fails_clearly(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as failure:
        await search_workspace(work_root=tmp_path / "nope", query="*.ts")
    assert "项目目录不存在" in str(failure.value)
