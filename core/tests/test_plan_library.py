"""The plan library (资料库): plans are markdown files in 「方案/」.

Covers the scan (frontmatter 状态/摘要, title from the first heading, newest
first, unreadable files degrade instead of hiding) and the two routes the
library UI calls — list and delete (contained to the 方案 folder, .md only).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from lamtools_core.app import open_core_app_db
from lamtools_core.app.plan_library import (
    PLAN_LIBRARY_DIRNAME,
    normalize_plan_status,
    plan_library_root,
    scan_plan_library,
)
from lamtools_core.http import create_core_router

# ------------------------------------------------------------------
# scan_plan_library
# ------------------------------------------------------------------


def _write_plan(work_root: Path, name: str, text: str) -> Path:
    folder = plan_library_root(work_root)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def test_scan_reads_frontmatter_title_and_orders_newest_first(tmp_path):
    older = _write_plan(
        tmp_path,
        "旧方案.md",
        "---\n状态: 完成\n摘要: 已经做完的一份\n---\n# 旧方案\n\n## 需求与边界\n",
    )
    import os

    past = older.stat().st_mtime - 3600
    os.utime(older, (past, past))
    _write_plan(
        tmp_path,
        "新方案.md",
        "---\n状态: 就绪\n摘要: 马上要开工的一份\n---\n# 新方案\n\n## 步骤\n",
    )

    entries = scan_plan_library(tmp_path)

    assert [entry["name"] for entry in entries] == ["新方案.md", "旧方案.md"]
    assert entries[0]["status"] == "ready"
    assert entries[0]["summary"] == "马上要开工的一份"
    assert entries[0]["title"] == "新方案"
    assert entries[0]["path"] == f"{PLAN_LIBRARY_DIRNAME}/新方案.md"
    assert entries[1]["status"] == "done"
    assert all(entry["updated_at"] > 0 for entry in entries)


def test_scan_defaults_and_unreadable_files_degrade(tmp_path):
    plan_library_root(tmp_path).mkdir()
    (plan_library_root(tmp_path) / "无frontmatter.md").write_text(
        "# 只有标题\n\n正文第一行。", encoding="utf-8"
    )
    (plan_library_root(tmp_path) / "损坏.md").write_bytes(b"\xff\xfe\x00broken")
    (plan_library_root(tmp_path) / "被忽略.txt").write_text("不是方案", encoding="utf-8")

    entries = scan_plan_library(tmp_path)

    by_name = {entry["name"]: entry for entry in entries}
    assert "被忽略.txt" not in by_name, "only .md files are plans"
    assert by_name["无frontmatter.md"]["status"] == "draft"
    assert by_name["无frontmatter.md"]["title"] == "只有标题"
    assert by_name["损坏.md"]["status"] == "draft"
    assert by_name["损坏.md"]["title"] == "损坏"


def test_scan_without_the_folder_is_an_empty_list(tmp_path):
    assert scan_plan_library(tmp_path) == []
    assert plan_library_root(tmp_path) == tmp_path / PLAN_LIBRARY_DIRNAME


def test_status_aliases_accept_both_spellings():
    assert normalize_plan_status("草稿") == "draft"
    assert normalize_plan_status("就绪") == "ready"
    assert normalize_plan_status("READY") == "ready"
    assert normalize_plan_status("执行中") == "executing"
    assert normalize_plan_status("完成") == "done"
    assert normalize_plan_status("") == "draft"
    assert normalize_plan_status("谁也看不懂的状态") == "draft"


# ------------------------------------------------------------------
# Routes: GET + DELETE /projects/{id}/plan-library
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_and_delete_routes_round_trip(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        project, _session, _created = await db.project_store.create_with_initial_session(
            tmp_path / "workspace",
            name="Workspace",
        )
        work_root = Path(project.work_root)
        (plan_library_root(work_root)).mkdir(parents=True, exist_ok=True)
        (plan_library_root(work_root) / "方案一.md").write_text(
            "---\n状态: 就绪\n摘要: 第一份\n---\n# 方案一\n", encoding="utf-8"
        )

        app = FastAPI()
        app.include_router(create_core_router(project_store=db.project_store))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            listed = await client.get(f"/projects/{project.id}/plan-library")
            assert listed.status_code == 200
            payload = listed.json()
            assert payload["dir"] == PLAN_LIBRARY_DIRNAME
            assert [entry["title"] for entry in payload["entries"]] == ["方案一"]

            deleted = await client.delete(
                f"/projects/{project.id}/plan-library?path={PLAN_LIBRARY_DIRNAME}/方案一.md"
            )
            assert deleted.status_code == 200
            assert deleted.json() == {"deleted": f"{PLAN_LIBRARY_DIRNAME}/方案一.md"}

            listed_again = await client.get(f"/projects/{project.id}/plan-library")
            assert listed_again.json()["entries"] == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_delete_route_refuses_paths_outside_the_library(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        project, _session, _created = await db.project_store.create_with_initial_session(
            tmp_path / "workspace",
            name="Workspace",
        )
        work_root = Path(project.work_root)
        (work_root / "AGENTS.md").write_text("不是方案，不许删", encoding="utf-8")
        (plan_library_root(work_root)).mkdir(parents=True, exist_ok=True)
        (plan_library_root(work_root) / "方案一.md").write_text("# 方案一\n", encoding="utf-8")

        app = FastAPI()
        app.include_router(create_core_router(project_store=db.project_store))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            outside = await client.delete(
                f"/projects/{project.id}/plan-library?path=AGENTS.md"
            )
            assert outside.status_code == 403

            climbing = await client.delete(
                f"/projects/{project.id}/plan-library?path={PLAN_LIBRARY_DIRNAME}/../AGENTS.md"
            )
            assert climbing.status_code == 403

            not_markdown = await client.delete(
                f"/projects/{project.id}/plan-library?path={PLAN_LIBRARY_DIRNAME}/notes.txt"
            )
            assert not_markdown.status_code == 400

            missing = await client.delete(
                f"/projects/{project.id}/plan-library?path={PLAN_LIBRARY_DIRNAME}/没有.md"
            )
            assert missing.status_code == 404

            # The refused deletes left every file in place.
            assert (work_root / "AGENTS.md").read_text(encoding="utf-8") == "不是方案，不许删"
            assert (plan_library_root(work_root) / "方案一.md").is_file()
    finally:
        await db.close()
