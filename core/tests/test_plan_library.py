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

# ------------------------------------------------------------------
# 能力升级：递归扫描 / 新建 / 文件夹 / 重命名 / 移动 / 收藏
# ------------------------------------------------------------------

from lamtools_core.app.plan_library import (
    PlanLibraryError,
    create_folder,
    create_plan,
    delete_folder,
    list_plan_folders,
    move_plan,
    rename_plan,
    set_plan_favorite,
)


def test_scan_reports_folder_favorite_and_reads_nested_plans(tmp_path):
    nested = plan_library_root(tmp_path) / "迭代计划"
    nested.mkdir(parents=True)
    (nested / "子目录方案.md").write_text(
        "---\n状态: 就绪\n摘要: 在子目录里\n收藏: true\n---\n# 子目录方案\n", encoding="utf-8"
    )
    (plan_library_root(tmp_path)).mkdir(exist_ok=True)
    (plan_library_root(tmp_path) / "根目录方案.md").write_text("# 根目录方案\n", encoding="utf-8")

    entries = scan_plan_library(tmp_path)

    by_name = {entry["name"]: entry for entry in entries}
    assert by_name["子目录方案.md"]["folder"] == "迭代计划"
    assert by_name["子目录方案.md"]["path"] == f"{PLAN_LIBRARY_DIRNAME}/迭代计划/子目录方案.md"
    assert by_name["子目录方案.md"]["favorite"] is True
    assert by_name["根目录方案.md"]["folder"] == ""
    assert by_name["根目录方案.md"]["favorite"] is False


def test_create_plan_writes_skeleton_and_refuses_duplicates(tmp_path):
    entry = create_plan(tmp_path, "新方案")
    assert entry["path"] == f"{PLAN_LIBRARY_DIRNAME}/新方案.md"
    assert entry["status"] == "draft"
    text = (plan_library_root(tmp_path) / "新方案.md").read_text(encoding="utf-8")
    assert text.startswith("---\n状态: 草稿")
    assert "# 新方案" in text

    with pytest.raises(PlanLibraryError):
        create_plan(tmp_path, "新方案")
    with pytest.raises(PlanLibraryError):
        create_plan(tmp_path, "../逃逸")
    # 目标文件夹必须已经在那儿：写错一层不会顺手把一整条目录链造出来。
    with pytest.raises(PlanLibraryError):
        create_plan(tmp_path, "夹内方案", folder="还没建")


def test_create_plan_into_folder_and_folders_listing(tmp_path):
    create_folder(tmp_path, "迭代计划")
    folders = list_plan_folders(tmp_path)
    assert [folder["name"] for folder in folders] == ["迭代计划"]
    assert folders[0]["count"] == 0
    assert folders[0]["dir"] == "迭代计划"
    assert folders[0]["parent"] == ""

    entry = create_plan(tmp_path, "夹内方案", folder="迭代计划")
    assert entry["folder"] == "迭代计划"
    assert list_plan_folders(tmp_path)[0]["count"] == 1

    with pytest.raises(PlanLibraryError):
        create_folder(tmp_path, "迭代计划")
    # 上级不存在时不隐式造父目录。
    with pytest.raises(PlanLibraryError):
        create_folder(tmp_path, "还没建/子目录")
    with pytest.raises(PlanLibraryError):
        create_folder(tmp_path, "../逃逸")


def test_folders_nest_and_each_level_reports_its_parent(tmp_path):
    create_folder(tmp_path, "归档")
    create_folder(tmp_path, "归档/这一期")
    create_folder(tmp_path, "归档/这一期/复盘")

    folders = {folder["dir"]: folder for folder in list_plan_folders(tmp_path)}
    assert set(folders) == {"归档", "归档/这一期", "归档/这一期/复盘"}
    assert folders["归档"]["parent"] == ""
    assert folders["归档/这一期"]["parent"] == "归档"
    assert folders["归档/这一期/复盘"]["parent"] == "归档/这一期"
    assert folders["归档"]["path"] == f"{PLAN_LIBRARY_DIRNAME}/归档"

    entry = create_plan(tmp_path, "深层方案", folder="归档/这一期/复盘")
    assert entry["folder"] == "归档/这一期/复盘"
    assert entry["path"] == f"{PLAN_LIBRARY_DIRNAME}/归档/这一期/复盘/深层方案.md"
    # 父级文件夹的计数把更深处的方案也算进来。
    assert {folder["dir"]: folder["count"] for folder in list_plan_folders(tmp_path)} == {
        "归档": 1,
        "归档/这一期": 1,
        "归档/这一期/复盘": 1,
    }

    # 回到根、再挪到另一条分支上。
    assert move_plan(tmp_path, entry["path"], folder="")["folder"] == ""
    assert move_plan(tmp_path, f"{PLAN_LIBRARY_DIRNAME}/深层方案.md", folder="归档/这一期")["folder"] == "归档/这一期"
    with pytest.raises(PlanLibraryError):
        move_plan(tmp_path, f"{PLAN_LIBRARY_DIRNAME}/归档/这一期/深层方案.md", folder="还没建")

    # 非空的一层删不掉；把最深一层清空后可以删。
    with pytest.raises(PlanLibraryError):
        delete_folder(tmp_path, f"{PLAN_LIBRARY_DIRNAME}/归档/这一期")
    (plan_library_root(tmp_path) / "归档" / "这一期" / "深层方案.md").unlink()
    delete_folder(tmp_path, f"{PLAN_LIBRARY_DIRNAME}/归档/这一期/复盘")
    delete_folder(tmp_path, f"{PLAN_LIBRARY_DIRNAME}/归档/这一期")
    assert [folder["dir"] for folder in list_plan_folders(tmp_path)] == ["归档"]


def test_rename_plan_moves_name_within_folder(tmp_path):
    create_plan(tmp_path, "旧名")
    entry = rename_plan(tmp_path, f"{PLAN_LIBRARY_DIRNAME}/旧名.md", "新名")
    assert entry["path"] == f"{PLAN_LIBRARY_DIRNAME}/新名.md"
    assert not (plan_library_root(tmp_path) / "旧名.md").exists()

    with pytest.raises(PlanLibraryError):
        rename_plan(tmp_path, f"{PLAN_LIBRARY_DIRNAME}/新名.md", "新名")  # 同名已存在（自身）
    with pytest.raises(PlanLibraryError):
        rename_plan(tmp_path, f"{PLAN_LIBRARY_DIRNAME}/../AGENTS.md", "x")


def test_move_plan_between_root_and_folder(tmp_path):
    create_plan(tmp_path, "要移动的方案")
    create_folder(tmp_path, "归档")

    moved = move_plan(tmp_path, f"{PLAN_LIBRARY_DIRNAME}/要移动的方案.md", folder="归档")
    assert moved["folder"] == "归档"
    assert (plan_library_root(tmp_path) / "归档" / "要移动的方案.md").is_file()

    moved_back = move_plan(tmp_path, f"{PLAN_LIBRARY_DIRNAME}/归档/要移动的方案.md", folder="")
    assert moved_back["folder"] == ""

    with pytest.raises(PlanLibraryError):
        move_plan(tmp_path, f"{PLAN_LIBRARY_DIRNAME}/要移动的方案.md", folder="不存在")


def test_favorite_writes_frontmatter_and_unstar_removes_it(tmp_path):
    create_plan(tmp_path, "会被收藏的方案")
    path = f"{PLAN_LIBRARY_DIRNAME}/会被收藏的方案.md"

    entry = set_plan_favorite(tmp_path, path, favorite=True)
    assert entry["favorite"] is True
    text = (plan_library_root(tmp_path) / "会被收藏的方案.md").read_text(encoding="utf-8")
    assert "收藏: true" in text

    entry = set_plan_favorite(tmp_path, path, favorite=False)
    assert entry["favorite"] is False
    text = (plan_library_root(tmp_path) / "会被收藏的方案.md").read_text(encoding="utf-8")
    assert "收藏" not in text.split("---\n")[1]


def test_delete_folder_requires_empty_and_never_leaves_the_library(tmp_path):
    create_folder(tmp_path, "空文件夹")
    delete_folder(tmp_path, f"{PLAN_LIBRARY_DIRNAME}/空文件夹")
    assert list_plan_folders(tmp_path) == []

    create_folder(tmp_path, "非空")
    create_plan(tmp_path, "里面的方案", folder="非空")
    with pytest.raises(PlanLibraryError):
        delete_folder(tmp_path, f"{PLAN_LIBRARY_DIRNAME}/非空")
    with pytest.raises(PlanLibraryError):
        delete_folder(tmp_path, f"{PLAN_LIBRARY_DIRNAME}/../逃逸")
    with pytest.raises(PlanLibraryError):
        delete_folder(tmp_path, f"{PLAN_LIBRARY_DIRNAME}/没有这个夹")


# ------------------------------------------------------------------
# 新路由：POST files / folders、DELETE folders、rename / move / favorite
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_library_capability_routes_round_trip(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        project, _session, _created = await db.project_store.create_with_initial_session(
            tmp_path / "workspace",
            name="Workspace",
        )
        app = FastAPI()
        app.include_router(create_core_router(project_store=db.project_store))
        base = f"/projects/{project.id}/plan-library"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            folder = (await client.post(f"{base}/folders", json={"path": "归档"})).json()["folder"]
            assert folder["name"] == "归档"
            nested = (await client.post(f"{base}/folders", json={"path": "归档/这一期"})).json()["folder"]
            assert nested["dir"] == "归档/这一期"
            assert nested["parent"] == "归档"

            created = (await client.post(f"{base}/files", json={"name": "路由方案", "folder": "归档/这一期"})).json()["entry"]
            assert created["folder"] == "归档/这一期"

            renamed = (await client.post(f"{base}/rename", json={"path": created["path"], "name": "改名后"})).json()["entry"]
            assert renamed["path"] == f"{PLAN_LIBRARY_DIRNAME}/归档/这一期/改名后.md"

            moved = (await client.post(f"{base}/move", json={"path": renamed["path"], "folder": ""})).json()["entry"]
            assert moved["folder"] == ""

            starred = (await client.post(f"{base}/favorite", json={"path": moved["path"], "favorite": True})).json()["entry"]
            assert starred["favorite"] is True

            listing = (await client.get(base)).json()
            assert [folder["dir"] for folder in listing["folders"]] == ["归档", "归档/这一期"]
            assert listing["entries"][0]["favorite"] is True

            duplicate = await client.post(f"{base}/files", json={"name": "改名后"})
            assert duplicate.status_code == 400

            # 非空的那一层删不掉；最深的一层是空的，可以先删。
            refused = await client.delete(f"{base}/folders?path={PLAN_LIBRARY_DIRNAME}/归档")
            assert refused.status_code == 400
            emptied = await client.delete(f"{base}/folders?path={PLAN_LIBRARY_DIRNAME}/归档/这一期")
            assert emptied.status_code == 200
    finally:
        await db.close()
