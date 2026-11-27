"""方案体系：类型分类、设计／实施双状态、专题与关联、元数据写回、导入。

覆盖本次改造新增的读侧（scan 报告哪些字段）与写侧（创建带类型骨架、
只改 frontmatter 的元数据写回、从现有文件导入），并核对旧文档向后兼容：
旧四值 状态（草稿／就绪／执行中／完成）仍映射到同一套读模型，历史文件
不改一个字节也能继续被列出和打开。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from lamtools_core.app import open_core_app_db
from lamtools_core.app.plan_library import (
    PLAN_LIBRARY_DIRNAME,
    PlanLibraryError,
    create_plan,
    import_plan,
    normalize_design_status,
    normalize_impl_status,
    normalize_plan_type,
    plan_library_root,
    scan_plan_library,
    set_plan_meta,
)
from lamtools_core.http import create_core_router


def _write(work_root: Path, name: str, text: str) -> Path:
    folder = plan_library_root(work_root)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _entry(work_root: Path, name: str) -> dict:
    for entry in scan_plan_library(work_root):
        if entry["name"] == name:
            return entry
    raise AssertionError(f"没有扫描到 {name}")


# ------------------------------------------------------------------
# 类型
# ------------------------------------------------------------------


def test_type_from_frontmatter_wins_over_filename(tmp_path):
    _write(tmp_path, "随便叫.md", "---\n类型: 技术规范\n---\n# 随便叫\n")

    entry = _entry(tmp_path, "随便叫.md")

    assert entry["type"] == "SPEC"
    assert entry["type_label"] == "技术规范"


def test_type_inferred_from_filename_and_title(tmp_path):
    cases = {
        "Sunday-X-PRD-V1.0.md": "PRD",
        "接口-SPEC.md": "SPEC",
        "安装-EXP-01.md": "EXP",
        "Rust核心迁移-01-源码审计报告.md": "AUDIT",
        "Rust核心迁移-09-M1M2验收报告.md": "REPORT",
        "Rust核心迁移-02-架构与实施计划.md": "PLAN",
        "界面-设计说明.md": "DESIGN",
        "总体方案.md": "",
    }
    for name in cases:
        _write(tmp_path, name, f"---\n状态: 草稿\n---\n# {name.removesuffix('.md')}\n")

    for name, expected in cases.items():
        assert _entry(tmp_path, name)["type"] == expected, name


def test_type_aliases_accept_chinese_and_lowercase():
    assert normalize_plan_type("产品需求文档") == "PRD"
    assert normalize_plan_type("prd") == "PRD"
    assert normalize_plan_type("结果报告") == "REPORT"
    assert normalize_plan_type("架构设计") == "ARCH"
    assert normalize_plan_type("") == ""
    assert normalize_plan_type("谁也不认识的类型") == ""


def test_unknown_type_is_reported_not_hidden(tmp_path):
    _write(tmp_path, "旧文档.md", "---\n状态: 完成\n---\n# 旧文档\n")

    entry = _entry(tmp_path, "旧文档.md")

    assert entry["type"] == ""
    assert entry["type_label"] == "未分类"
    assert entry["title"] == "旧文档"


# ------------------------------------------------------------------
# 双状态
# ------------------------------------------------------------------


def test_legacy_status_maps_onto_design_and_impl_axes(tmp_path):
    cases = {
        "草稿.md": ("draft", "none", "draft"),
        "就绪.md": ("active", "none", "ready"),
        "执行中.md": ("active", "doing", "executing"),
        "完成.md": ("active", "accepted", "done"),
    }
    for name, (_design, _impl, _status) in cases.items():
        _write(tmp_path, name, f"---\n状态: {name.removesuffix('.md')}\n---\n# {name}\n")

    for name, (design, impl, status) in cases.items():
        entry = _entry(tmp_path, name)
        assert (entry["design_status"], entry["impl_status"]) == (design, impl), name
        # status 是旧客户端用的兼容值，语义不变。
        assert entry["status"] == status, name


def test_new_status_words_read_as_two_independent_axes(tmp_path):
    _write(
        tmp_path,
        "归档.md",
        "---\n状态: 已归档\n---\n# 归档\n",
    )
    _write(
        tmp_path,
        "待验收.md",
        "---\n状态: 生效\n实施: 待验收\n---\n# 待验收\n",
    )

    archived = _entry(tmp_path, "归档.md")
    assert (archived["design_status"], archived["impl_status"]) == ("archived", "none")
    assert archived["status"] == "archived"

    waiting = _entry(tmp_path, "待验收.md")
    assert (waiting["design_status"], waiting["impl_status"]) == ("active", "review")
    assert waiting["status"] == "executing"

    assert normalize_design_status("废弃") == "deprecated"
    assert normalize_design_status("生效") == "active"
    assert normalize_impl_status("未开始") == "none"
    assert normalize_impl_status("已验收") == "accepted"


def test_topic_and_related_are_read_from_frontmatter(tmp_path):
    _write(
        tmp_path,
        "记忆检索.md",
        "---\n类型: SPEC\n专题: Sunday Memory\n"
        "关联: 方案/记忆PRD.md, 会话:s-123\n---\n# 记忆检索机制\n",
    )

    entry = _entry(tmp_path, "记忆检索.md")

    assert entry["topic"] == "Sunday Memory"
    assert entry["related"] == ["方案/记忆PRD.md", "会话:s-123"]


# ------------------------------------------------------------------
# 创建：类型骨架
# ------------------------------------------------------------------


def test_create_plan_writes_the_type_skeleton(tmp_path):
    entry = create_plan(tmp_path, "支付流程重构", plan_type="PRD")
    text = (plan_library_root(tmp_path) / "支付流程重构.md").read_text(encoding="utf-8")

    assert entry["type"] == "PRD"
    assert entry["design_status"] == "draft"
    assert "类型: PRD" in text
    assert "状态: 草稿" in text
    # PRD 的核心内容由骨架提示，正文仍是一篇普通文档。
    assert "## 背景" in text
    assert "## 验收标准" in text


def test_create_plan_for_spec_uses_its_own_skeleton(tmp_path):
    create_plan(tmp_path, "检索协议", plan_type="SPEC")
    text = (plan_library_root(tmp_path) / "检索协议.md").read_text(encoding="utf-8")

    assert "类型: SPEC" in text
    assert "## 机制" in text
    assert "## 背景" not in text


# ------------------------------------------------------------------
# 元数据写回
# ------------------------------------------------------------------


def test_set_plan_meta_touches_frontmatter_and_keeps_the_body(tmp_path):
    body = "# 记忆检索机制\n\n正文第一段，一个字都不该动。\n"
    _write(tmp_path, "记忆检索.md", f"---\n作者: 二两\n状态: 就绪\n---\n{body}")

    entry = set_plan_meta(
        tmp_path,
        f"{PLAN_LIBRARY_DIRNAME}/记忆检索.md",
        plan_type="SPEC",
        design_status="archived",
        impl_status="review",
        topic="Sunday Memory",
        summary="检索协议与边界",
    )

    text = (plan_library_root(tmp_path) / "记忆检索.md").read_text(encoding="utf-8")
    assert body in text
    assert "作者: 二两" in text
    assert "类型: SPEC" in text
    assert "状态: 已归档" in text
    assert "实施: 待验收" in text
    assert "专题: Sunday Memory" in text
    assert entry["type"] == "SPEC"
    assert (entry["design_status"], entry["impl_status"]) == ("archived", "review")
    assert entry["topic"] == "Sunday Memory"


def test_set_plan_meta_records_related_sessions(tmp_path):
    _write(tmp_path, "方案.md", "---\n状态: 草案\n---\n# 方案\n")

    set_plan_meta(
        tmp_path,
        f"{PLAN_LIBRARY_DIRNAME}/方案.md",
        related_sessions=["s-1"],
    )
    entry = set_plan_meta(
        tmp_path,
        f"{PLAN_LIBRARY_DIRNAME}/方案.md",
        related_sessions=["s-1", "s-2"],
    )

    assert "会话:s-1" in entry["related"]
    assert "会话:s-2" in entry["related"]
    # 不去重地重复写同一会话，会把关联列表变成一串噪音。
    assert entry["related"].count("会话:s-1") == 1


def test_set_plan_meta_rejects_values_outside_the_vocabulary(tmp_path):
    _write(tmp_path, "方案.md", "---\n状态: 草案\n---\n# 方案\n")
    path = f"{PLAN_LIBRARY_DIRNAME}/方案.md"

    with pytest.raises(PlanLibraryError):
        set_plan_meta(tmp_path, path, plan_type="NOT-A-TYPE")
    with pytest.raises(PlanLibraryError):
        set_plan_meta(tmp_path, path, design_status="进行中")
    with pytest.raises(PlanLibraryError):
        set_plan_meta(tmp_path, path, impl_status="差不多了")


# ------------------------------------------------------------------
# 导入
# ------------------------------------------------------------------


def test_import_plan_copies_and_never_overwrites(tmp_path):
    source = tmp_path / "外部" / "想法.md"
    source.parent.mkdir(parents=True)
    source.write_text("# 想法\n", encoding="utf-8")

    first = import_plan(tmp_path, source)
    second = import_plan(tmp_path, source)

    assert first["name"] == "想法.md"
    assert second["name"] != "想法.md"
    assert (plan_library_root(tmp_path) / first["name"]).is_file()
    # 源文件属于用户，不是搬走也不是删掉。
    assert source.is_file()


def test_import_plan_refuses_non_markdown_and_missing_files(tmp_path):
    note = tmp_path / "笔记.txt"
    note.write_text("不是方案", encoding="utf-8")

    with pytest.raises(PlanLibraryError):
        import_plan(tmp_path, note)
    with pytest.raises(PlanLibraryError):
        import_plan(tmp_path, tmp_path / "不存在.md")


# ------------------------------------------------------------------
# 路由：meta / import
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_meta_and_import_routes_round_trip(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        project, _session, _created = await db.project_store.create_with_initial_session(
            tmp_path / "workspace",
            name="Workspace",
        )
        work_root = Path(project.work_root)
        (plan_library_root(work_root)).mkdir(parents=True, exist_ok=True)
        (plan_library_root(work_root) / "方案一.md").write_text(
            "---\n状态: 草稿\n---\n# 方案一\n\n正文。\n", encoding="utf-8"
        )
        outside = tmp_path / "外部想法.md"
        outside.write_text("# 外部想法\n", encoding="utf-8")

        app = FastAPI()
        app.include_router(create_core_router(project_store=db.project_store))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            updated = await client.post(
                f"/projects/{project.id}/plan-library/meta",
                json={
                    "path": f"{PLAN_LIBRARY_DIRNAME}/方案一.md",
                    "type": "PRD",
                    "design_status": "active",
                    "impl_status": "doing",
                    "topic": "记忆",
                },
            )
            assert updated.status_code == 200
            entry = updated.json()["entry"]
            assert entry["type"] == "PRD"
            assert (entry["design_status"], entry["impl_status"]) == ("active", "doing")
            assert entry["topic"] == "记忆"

            imported = await client.post(
                f"/projects/{project.id}/plan-library/import",
                json={"path": str(outside)},
            )
            assert imported.status_code == 200
            assert imported.json()["entry"]["name"] == "外部想法.md"

            refused = await client.post(
                f"/projects/{project.id}/plan-library/meta",
                json={"path": f"{PLAN_LIBRARY_DIRNAME}/方案一.md", "type": "胡写"},
            )
            assert refused.status_code == 400

            escaping = await client.post(
                f"/projects/{project.id}/plan-library/meta",
                json={"path": "AGENTS.md", "topic": "越界"},
            )
            assert escaping.status_code == 400
    finally:
        await db.close()
