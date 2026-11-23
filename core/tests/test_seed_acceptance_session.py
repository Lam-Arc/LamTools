"""铺验收会话的脚本必须真的符合 items 端点契约。

user:“一次离线自证：在不启动真实应用的前提下，用测试方式证明脚本构造的请求体
符合端点契约”+(不联网、不起应用：直接把脚本产出的十条 item 交给后端自己的
``normalize_session_items`` / ``build_item_plan``，验证 kind、part 形状、字符上限
以及重跑时的 id 稳定性，另外核对内容与 ``方案/验收-交互与显示.md`` 的十项对齐。)
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from lamtools_core.app.session_items import (
    DISPLAY_ITEM_KINDS,
    build_item_plan,
    normalize_session_items,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "seed-acceptance-session.py"


def _load_script() -> ModuleType:
    """按路径加载带连字符文件名的脚本（它不是包的一部分）。"""
    assert _SCRIPT_PATH.is_file(), f"missing script: {_SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("seed_acceptance_session", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def seed() -> ModuleType:
    return _load_script()


@pytest.fixture(scope="module")
def items(seed: ModuleType) -> list[dict]:
    return seed.build_acceptance_items(_REPO_ROOT)


def test_ten_items_one_per_section(seed: ModuleType, items: list[dict]) -> None:
    """十项十气泡：每条都是 kind=text + role=assistant，幂等键固定为 acceptance-<序号>。"""
    assert len(items) == 10
    for index, item in enumerate(items, start=1):
        assert item["kind"] == "text"
        assert item["role"] == "assistant"
        assert item["client_item_id"] == f"acceptance-{index}"
        assert item["kind"] in DISPLAY_ITEM_KINDS
        assert item["parts"], f"item {index} 没有内容"


def test_server_accepts_every_payload(seed: ModuleType, items: list[dict]) -> None:
    """后端校验器原样接受：这是「请求体合契约」最硬的证明。"""
    normalized = normalize_session_items(items)
    assert len(normalized) == 10
    for entry in normalized:
        assert entry["markdown"].strip(), "规范化后的 Markdown 不能为空"
        assert entry["kind"] == "text"


def test_request_body_shape_matches_route_model(seed: ModuleType, items: list[dict]) -> None:
    """请求体字段与 SessionItemsCreateRequest 对齐：items / client_item_id。"""
    for item in items:
        body = seed.build_request_body(item)
        assert set(body) == {"client_item_id", "items"}
        assert body["client_item_id"] == seed.SUITE_KEY
        assert len(body["items"]) == 1
        wire = body["items"][0]
        assert {"kind", "role", "parts", "client_item_id"} <= set(wire)


def test_rerun_derives_identical_ids(seed: ModuleType, items: list[dict]) -> None:
    """幂等：同一组 client_item_id 重跑，turn_id 与 item_id 全部不变。"""
    normalized = normalize_session_items(items)
    first = build_item_plan("thread-1", normalized, client_item_id=seed.SUITE_KEY)
    second = build_item_plan("thread-1", normalized, client_item_id=seed.SUITE_KEY)
    assert first["turn_id"] == second["turn_id"]
    assert [i["item_id"] for i in first["items"]] == [i["item_id"] for i in second["items"]]
    ids = [i["item_id"] for i in first["items"]]
    assert len(set(ids)) == 10, "十条 item 必须各自独立"

    # 换一个 suite key 才是新的一批（证明幂等靠 key，不是靠内容哈希撞巧）。
    other = build_item_plan("thread-1", normalized, client_item_id="acceptance-suite-v2")
    assert other["turn_id"] != first["turn_id"]


def test_chart_parts_render_three_chart_blocks(seed: ModuleType, items: list[dict]) -> None:
    """第三项：三张图分别是柱状/折线/饼图，且 source 是合法 JSON。"""
    chart_item = items[2]
    charts = [p for p in chart_item["parts"] if p["type"] == "chart"]
    assert len(charts) == 3
    assert [c["source"]["type"] for c in charts] == ["bar", "line", "pie"]
    for chart in charts:
        json.dumps(chart["source"], ensure_ascii=False)  # 必须可序列化

    markdown = normalize_session_items([chart_item])[0]["markdown"]
    assert markdown.count("```chart") == 3
    assert "图表数据不是合法 JSON" in markdown  # 验收关注点写进了正文


def test_mermaid_has_enough_branches(seed: ModuleType, items: list[dict]) -> None:
    """第四项：四节点以上的流程图，含菱形判定与分支文字。"""
    diagram = [p for p in items[3]["parts"] if p["type"] == "mermaid"][0]["source"]
    nodes = [line for line in diagram.splitlines() if "-->" in line]
    assert len(nodes) >= 4
    assert "{" in diagram and "}" in diagram, "需要菱形判定节点"
    assert "是" in diagram and "否" in diagram, "连线上要有分支文字"


def test_interactive_part_is_really_interactive(seed: ModuleType, items: list[dict]) -> None:
    """第五项：控件必须真能拖、真能调参数（不是静态图）。"""
    html = [p for p in items[4]["parts"] if p["type"] == "interactive-html"][0]["source"]
    assert 'type="range"' in html, "需要滑块"
    assert "addEventListener('pointermove'" in html, "需要拖动"
    assert "setPointerCapture" in html
    assert "<script>" in html and "</script>" in html
    # 样式只用主题变量，避免深色主题下看不见
    assert "var(--foreground" in html and "var(--background" in html


def test_writing_part_carries_card_attrs(seed: ModuleType, items: list[dict]) -> None:
    """第六项：写作稿是卡片，带 variant 与 title 属性。"""
    part = [p for p in items[5]["parts"] if p["type"] == "writing"][0]
    assert part["variant"] == "social_post"
    assert part["title"]
    markdown = normalize_session_items([items[5]])[0]["markdown"]
    fence = [line for line in markdown.splitlines() if line.startswith("```writing")]
    assert len(fence) == 1, "写作稿应当渲染成一个 writing 围栏"
    assert 'variant="social_post"' in fence[0]
    assert 'title="一发就懂的更新说明"' in fence[0]
    # 卡片内的正文就是草稿本身，不带「编辑/复制」这类 UI 按钮文案。
    body = markdown.split("```writing", 1)[1].split("```", 1)[0]
    assert "周末把会话里的三个小毛病一起修了" in body
    assert "编辑" not in body and "复制" not in body


def test_file_references_point_at_real_files(seed: ModuleType, items: list[dict]) -> None:
    """第七项：引用的文件在磁盘上真实存在，且路径整条写进正文。"""
    required = [
        _REPO_ROOT / "方案" / "内置浏览器-01-总体方案.md",
        _REPO_ROOT / "core" / "ui" / "src" / "preview" / "resolve.ts",
        _REPO_ROOT / "core" / "desktop" / "src-tauri" / "tests" / "fixtures" / "ocr-known-text.png",
    ]
    markdown = normalize_session_items([items[6]])[0]["markdown"]
    for path in required:
        assert path.is_file(), f"引用的文件不存在: {path}"
        assert str(path).replace("\\", "/") in markdown


def test_unpreviewable_section_degrades_honestly(seed: ModuleType, items: list[dict]) -> None:
    """第九项：docx/pptx 在仓库里就列出来，不在就明说跳过（不伪造路径）。"""
    markdown = normalize_session_items([items[8]])[0]["markdown"]
    assert "不支持直接预览" in markdown
    samples = [
        _REPO_ROOT / "lam_projects" / "attachment-preview-lab" / "05-示例文档.docx",
        _REPO_ROOT / "lam_projects" / "attachment-preview-lab" / "07-示例演示.pptx",
    ]
    if not any(path.is_file() for path in samples):
        assert "本项无真人可点" in markdown or "跳过" in markdown


def test_urls_are_real_links(seed: ModuleType, items: list[dict]) -> None:
    """第八项：两个真实地址，既能自动识别也能点。"""
    markdown = normalize_session_items([items[7]])[0]["markdown"]
    assert "https://www.baidu.com" in markdown
    assert "https://www.bilibili.com" in markdown
    assert "[百度](https://www.baidu.com)" in markdown


def test_guide_has_ten_row_verdict_table(seed: ModuleType, items: list[dict]) -> None:
    """第十项：操作指引 + 十条判定标准表。"""
    markdown = normalize_session_items([items[9]])[0]["markdown"]
    rows = [line for line in markdown.splitlines() if line.startswith("| ") and "☐" in line]
    assert len(rows) == 10
    assert "操作指引" in markdown or "怎么用" in markdown


def test_total_size_within_endpoint_limits(seed: ModuleType, items: list[dict]) -> None:
    """字符上限：单项、单 part、总量都在端点允许范围内。"""
    assert seed.local_contract_errors(items) == []
    normalized = normalize_session_items(items)
    total = sum(len(entry["markdown"]) for entry in normalized)
    assert total < seed.MAX_TOTAL_CHARS


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (405, "旧后端"),
        (404, "不存在"),
        (409, "回合"),
        (422, "契约"),
        (503, "item 写入通道"),
    ],
)
def test_failure_hints_are_actionable(seed: ModuleType, status: int, expected: str) -> None:
    """失败可读：每个状态码给出中文原因与下一步。"""
    error = seed.ApiError(status=status, payload={"detail": {"code": "X", "message": ""}}, path="/p")
    hint = seed.explain_failure(error)
    assert expected in hint
    assert "下一步" in hint or "重跑" in hint


def test_no_secret_or_db_access(seed: ModuleType) -> None:
    """脚本只走 HTTP：不 import 数据库驱动、不打印 token。"""
    source = _SCRIPT_PATH.read_text(encoding="utf-8")
    for forbidden in ("sqlite3", "import psycopg", "Bearer ", "Secret-"):
        assert forbidden not in source, f"脚本不应出现 {forbidden}"
