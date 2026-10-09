"""Tests for the ``library`` tool (tool/library_tools.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.app.core_db import CoreAttachment, open_core_app_db
from lamtools_core.tool import ToolCall
from lamtools_core.tool.default_toolbox import (
    DEFAULT_TOOL_PERMISSIONS,
    LIBRARY_TOOL_NAME,
    build_core_toolbox,
)
from lamtools_core.tool.library_tools import make_library_handler


def _call(**arguments):
    return ToolCall(id="call-1", name=LIBRARY_TOOL_NAME, arguments=arguments)


@pytest.mark.asyncio
async def _library_fixture(tmp_path: Path):
    """一个真实资料库：项目 + 一份用户上传 + 一份代理产出。"""
    work_root = tmp_path / "work"
    work_root.mkdir()
    db = await open_core_app_db(tmp_path / "core.db")
    project, _ = await db.project_store.create(work_root)
    store = db.artifact_store
    uploaded = await store.upload(
        project_id=project.id,
        work_root=work_root,
        name="brief.md",
        content="# brief".encode("utf-8"),
        mime_type="text/markdown",
    )
    (work_root / "result.txt").write_text("done", encoding="utf-8")
    generated = await store.register(
        project_id=project.id,
        work_root=work_root,
        path="result.txt",
        kind="file_change",
        mime_type="text/plain",
        name="result.txt",
        source="agent_generated",
        role="deliverable",
    )
    return db, store, project, work_root, uploaded, generated


def test_library_tool_is_exposed_and_auto_allowed(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path)

    names = [spec["function"]["name"] for spec in toolbox.model_tools()]

    assert LIBRARY_TOOL_NAME in names
    assert DEFAULT_TOOL_PERMISSIONS[LIBRARY_TOOL_NAME] == "auto_allow"


def test_library_tool_needs_no_approval(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path)

    call = toolbox.prepare_call(_call(action="list"))

    assert call.requires_approval is False


@pytest.mark.asyncio
async def test_library_tool_roundtrip_through_the_toolbox(tmp_path):
    _db, store, _project, work_root, uploaded, generated = await _library_fixture(tmp_path)
    toolbox = build_core_toolbox(work_root=work_root, artifact_store=store)

    listed = await toolbox.execute(_call(action="list"))
    assert listed.status == "ok"
    assert uploaded.artifact_id in listed.content
    assert generated.artifact_id in listed.content
    assert "role=deliverable" in listed.content

    favorited = await toolbox.execute(
        _call(action="favorite", artifact_ids=[uploaded.artifact_id], favorite=True)
    )
    assert favorited.status == "ok"
    fresh = await store.get(uploaded.artifact_id)
    assert fresh is not None and fresh.favorite is True

    archived = await toolbox.execute(
        _call(action="folder", artifact_ids=[generated.artifact_id], folder="报告/2026")
    )
    assert archived.status == "ok"
    fresh = await store.get(generated.artifact_id)
    assert fresh is not None and fresh.folder == "报告/2026"

    unarchived = await toolbox.execute(
        _call(action="folder", artifact_ids=[generated.artifact_id], folder="")
    )
    assert unarchived.status == "ok"
    fresh = await store.get(generated.artifact_id)
    assert fresh is not None and fresh.folder == ""

    removed = await toolbox.execute(_call(action="remove", artifact_ids=[generated.artifact_id]))
    assert removed.status == "ok"
    assert await store.get(generated.artifact_id) is not None  # 只是登记移除，记录仍在
    assert generated.artifact_id not in (await toolbox.execute(_call(action="list"))).content

    restored = await toolbox.execute(_call(action="restore", artifact_ids=[generated.artifact_id]))
    assert restored.status == "ok"
    assert generated.artifact_id in (await toolbox.execute(_call(action="list"))).content


@pytest.mark.asyncio
async def test_library_tool_file_itself_is_never_touched(tmp_path):
    _db, store, _project, work_root, _uploaded, generated = await _library_fixture(tmp_path)
    handler = make_library_handler(store, work_root)

    await handler(_call(action="remove", artifact_ids=[generated.artifact_id]))

    assert (work_root / "result.txt").read_text(encoding="utf-8") == "done"


@pytest.mark.asyncio
async def test_library_tool_registers_a_file_deliberately(tmp_path):
    _db, store, _project, work_root, _uploaded, _generated = await _library_fixture(tmp_path)
    (work_root / "报告").mkdir()
    deliverable = work_root / "报告" / "总结.md"
    deliverable.write_text("# 总结", encoding="utf-8")
    handler = make_library_handler(store, work_root)

    # 相对路径登记，同一步归层。
    filed = await handler(_call(action="register", path="报告/总结.md", folder="报告"))
    assert filed.status == "ok"
    artifact_id = filed.metadata["artifact_id"]
    record = await store.get(artifact_id)
    assert record is not None
    assert record.folder == "报告"
    assert record.role == "deliverable"
    assert record.path == "workspace://报告/总结.md"
    assert deliverable.read_text(encoding="utf-8") == "# 总结"  # 文件本身不动

    # 再登记同一路径仍是同一条成果（刷新而不是新增）。
    again = await handler(_call(action="register", path="报告/总结.md"))
    assert again.status == "ok"
    assert again.metadata["artifact_id"] == artifact_id

    # workspace:// 形式与清单可见性。
    via_uri = await handler(_call(action="register", path=f"workspace://报告/总结.md", role="intermediate"))
    assert via_uri.status == "ok"
    assert via_uri.metadata["artifact_id"] == artifact_id
    listed = await handler(_call(action="list"))
    assert artifact_id in listed.content
    assert "role=intermediate" in listed.content

    # 越界与缺文件给明确错误码。
    outside = await handler(_call(action="register", path=str(tmp_path / "elsewhere.md")))
    assert outside.status == "failed"
    assert outside.error_code == "path_outside_root"

    missing = await handler(_call(action="register", path="不存在.md"))
    assert missing.status == "failed"
    assert missing.error_code == "file_not_found"

    bad_role = await handler(_call(action="register", path="报告/总结.md", role="evidence"))
    assert bad_role.status == "failed"
    assert bad_role.error_code == "invalid_argument"


@pytest.mark.asyncio
async def test_library_list_carries_the_real_file_of_every_entry(tmp_path):
    """清单每条都给文件的真实位置：工作区件给项目内路径，聊天附件给附件库路径。

    这是「助手读不到上传图片」的修复：它看得见册子上的名字，也必须看得见
    文件在哪，才能用 read_file 翻它。
    """
    db, store, project, work_root, uploaded, generated = await _library_fixture(tmp_path)

    attachment_dir = tmp_path / "attachments"
    attachment_dir.mkdir()
    blob = attachment_dir / "image.png"
    blob.write_bytes(b"fakepng-bytes")
    async with db.session_factory() as session:
        session.add(CoreAttachment(
            id="att-1",
            session_id="sess-1",
            filename="image.png",
            mime_type="image/png",
            size=blob.stat().st_size,
            storage_path=str(blob),
            preview_type="image",
            metadata_json={},
        ))
        await session.commit()
    pasted = await store.register(
        project_id=project.id,
        work_root=work_root,
        path="attachment://att-1",
        kind="image",
        mime_type="image/png",
        name="image.png",
        source="user_upload",
        role="input",
    )

    handler = make_library_handler(store, work_root)
    listed = await handler(_call(action="list"))

    assert listed.status == "ok"
    assert f"file={work_root / 'result.txt'}" in listed.content
    assert f"file={blob}" in listed.content
    assert generated.artifact_id in listed.content and pasted.artifact_id in listed.content

    # 附件文件不在了：这一条如实报 missing，而不是无声空着。
    blob.unlink()
    listed = await handler(_call(action="list"))
    assert f"file=(missing)" in listed.content
    await db.close()


@pytest.mark.asyncio
async def test_library_tool_errors_are_specific(tmp_path):
    _db, store, _project, work_root, uploaded, _generated = await _library_fixture(tmp_path)
    handler = make_library_handler(store, work_root)

    missing_ids = await handler(_call(action="favorite"))
    assert missing_ids.status == "failed"
    assert missing_ids.error_code == "missing_argument"

    unknown = await handler(_call(action="favorite", artifact_ids=["no-such-id"], favorite=True))
    assert unknown.status == "failed"
    assert unknown.error_code == "entry_not_found"

    bad_folder = await handler(_call(action="folder", artifact_ids=[uploaded.artifact_id], folder="a/../b"))
    assert bad_folder.status == "failed"
    assert bad_folder.error_code == "invalid_argument"

    unknown_action = await handler(_call(action="reorder", artifact_ids=[uploaded.artifact_id]))
    assert unknown_action.status == "failed"
    assert unknown_action.error_code == "invalid_action"


@pytest.mark.asyncio
async def test_library_tool_without_a_bound_project_fails_loudly(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    orphan_root = tmp_path / "orphan"
    orphan_root.mkdir()
    handler = make_library_handler(db.artifact_store, orphan_root)

    listed = await handler(_call(action="list"))

    assert listed.status == "failed"
    assert listed.error_code == "project_not_found"
    await db.close()


@pytest.mark.asyncio
async def test_artifact_store_resolves_project_by_work_root(tmp_path):
    db, store, project, work_root, _uploaded, _generated = await _library_fixture(tmp_path)

    assert await store.resolve_project_id(work_root) == project.id
    assert await store.resolve_project_id(tmp_path / "nowhere") == ""
    await db.close()
