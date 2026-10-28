"""Bubble planning: full rendering plus the safe fallback profile."""

from __future__ import annotations

from qqbot.bubbles import BubbleOptions, markdown_blocks, split_bubbles


SAFE = BubbleOptions.for_profile("safe")
FULL = BubbleOptions.for_profile("full")


def test_full_profile_preserves_tables_and_fences() -> None:
    text = "| 名称 | 数量 |\n|---|---:|\n| A | 1 |\n| B | 2 |\n\n```python\nx = 1\ny = 2\n```"

    assert split_bubbles(text, options=FULL) == [
        "| 名称 | 数量 |\n|---|---:|\n| A | 1 |\n| B | 2 |",
        "```python\nx = 1\ny = 2\n```",
    ]


def test_safe_profile_turns_table_rows_into_cards() -> None:
    text = "| 名称 | 数量 | 备注 |\n|---|---:|---|\n| 苹果 | 3 | 红色 |\n| 香蕉 | 5 | 黄色 |"

    assert split_bubbles(text, options=SAFE) == [
        "**表格 · 第 1 行**\n- 名称：苹果\n- 数量：3\n- 备注：红色",
        "**表格 · 第 2 行**\n- 名称：香蕉\n- 数量：5\n- 备注：黄色",
    ]


def test_safe_profile_turns_code_into_quote_block() -> None:
    text = "```python\nx = 1\n\ny = 2\n```"

    assert split_bubbles(text, options=SAFE) == [
        "**代码 · python**\n> x = 1\n>\n> y = 2"
    ]


def test_safe_profile_degrades_inline_code_and_heading() -> None:
    text = "### 小标题\n运行 `npm test` 即可"

    assert split_bubbles(text, options=SAFE) == [
        "**小标题**",
        "运行 「npm test」 即可",
    ]


def test_table_requires_header_and_separator() -> None:
    assert split_bubbles("a | b\nnot a table", options=SAFE) == ["a | b", "not a table"]

    assert split_bubbles("a | b\n--- | ---\n1 | 2", options=SAFE) == [
        "**表格 · 第 1 行**\n- a：1\n- b：2"
    ]


def test_oversized_safe_table_never_splits_a_row() -> None:
    rows = "\n".join(f"| 行 {index} | 值 {index} |" for index in range(12))
    table = f"| 名称 | 值 |\n|---|---|\n{rows}"

    bubbles = split_bubbles(table, limit=70, options=SAFE)

    assert len(bubbles) > 1
    for bubble in bubbles:
        assert bubble.startswith("**表格 · 第 ")
        assert "名称：" in bubble
        assert "值：" in bubble
        assert len(bubble) <= 70


def test_full_table_overflow_repeats_header_without_splitting_rows() -> None:
    rows = "\n".join(f"| 行 {index} | 值 {index} |" for index in range(12))
    table = f"| 名称 | 值 |\n|---|---|\n{rows}"

    bubbles = split_bubbles(table, limit=90, options=FULL)

    assert len(bubbles) > 1
    for bubble in bubbles:
        lines = bubble.split("\n")
        assert lines[0] == "| 名称 | 值 |"
        assert lines[1] == "|---|---|"
        assert all(line.startswith("| 行 ") for line in lines[2:])


def test_safe_profile_keeps_list_and_quote_structures() -> None:
    text = "- 列表一\n  续行\n\n- 列表二\n\n> 引用第一行\n> 引用第二行"

    assert split_bubbles(text, options=SAFE) == [
        "- 列表一\n  续行\n\n- 列表二",
        "> 引用第一行\n> 引用第二行",
    ]


def test_block_parser_distinguishes_table_from_pipe_prose() -> None:
    blocks = markdown_blocks("a | b\nnot a table\n\nc | d\n--- | ---\n1 | 2")

    assert [block.kind for block in blocks] == ["paragraph", "paragraph", "table"]


def test_safe_and_full_never_lose_table_cells() -> None:
    text = "| 名称 | 数量 |\n|---|---:|\n| 苹果 | 3 |\n| 香蕉 | 5 |"

    safe = "\n".join(split_bubbles(text, options=SAFE))
    full = "\n".join(split_bubbles(text, options=FULL))

    for value in ("苹果", "3", "香蕉", "5"):
        assert value in safe
        assert value in full


def test_sunday_style_blocks_degrade_to_plain_content() -> None:
    text = ":::note 提示\n这是 **Sunday** 样式\n第二行\n:::\n\n正常文本"

    expected = [
        "**提示**\n这是 **Sunday** 样式\n第二行",
        "正常文本",
    ]
    assert split_bubbles(text, options=SAFE) == expected
    assert split_bubbles(text, options=FULL) == expected


def test_note_without_title_sends_body_directly() -> None:
    text = ":::note\nSunday 样式块原样透传\n:::"

    assert split_bubbles(text, options=SAFE) == ["Sunday 样式块原样透传"]
    assert split_bubbles(text, options=FULL) == ["Sunday 样式块原样透传"]


def test_oversized_sunday_style_drops_container_markers() -> None:
    body = "\n".join(f"第 {index} 行内容" for index in range(12))
    text = f":::details 详情\n{body}\n:::"

    bubbles = split_bubbles(text, limit=70, options=SAFE)

    assert len(bubbles) > 1
    assert bubbles[0].startswith("**详情**\n")
    assert all(":::" not in bubble for bubble in bubbles)
    assert all(len(bubble) <= 70 for bubble in bubbles)


def test_bubble_profile_defaults_to_full_and_safe_is_explicit() -> None:
    from qqbot.config import normalize

    full = normalize({})["bubbles"]
    assert full["profile"] == "full"
    assert full["table"] == "markdown"
    assert full["code"] == "fence"

    safe = normalize({"bubbles": {"profile": "safe"}})["bubbles"]
    assert safe["profile"] == "safe"
    assert safe["table"] == "cards"
    assert safe["code"] == "quote"
