from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.checkpoint import CoreCheckpointCoordinator
from lamtools_core.cli import cmd_artifact_preview
from lamtools_core.event import RunItemEvent


@pytest.mark.asyncio
async def test_repeated_writes_keep_one_artifact_and_record_no_history(tmp_path: Path) -> None:
    """一份成果只记"当前是什么"：重复写入不产生历史版本，读到的永远是当前文件。"""
    work_root = tmp_path / "work"
    work_root.mkdir()
    db_path = tmp_path / "core.db"
    db = await open_core_app_db(db_path)
    project, _ = await db.project_store.create(work_root)
    target = work_root / "result.txt"

    ids = []
    item = None
    for index, content in enumerate(("one", "two", "three"), 1):
        target.write_text(content, encoding="utf-8")
        item = RunItemEvent(
            kind="tool_result",
            thread_id="thread-1",
            turn_id=f"turn-{index}",
            item_id=f"item-{index}",
            event_id=f"event-{index}",
            status="completed",
            payload={"tool_name": "write_file"},
            artifacts=[{"kind": "file_change", "uri": "result.txt", "content": "large diff"}],
        )
        await db.artifact_store.ingest_run_item(item, project_id=project.id, work_root=work_root)
        ids.append(item.artifacts[0]["artifact_id"])
        assert "content" not in item.artifacts[0]
        assert "revision_id" not in item.artifacts[0]

    assert len(set(ids)) == 1
    artifact = await db.artifact_store.get(ids[0])
    assert artifact is not None
    assert "latest_revision_id" not in artifact.to_dict()
    assert "revision_count" not in artifact.to_dict()
    # 内容就是磁盘上的当前文件，不是写入过程中的某一版
    assert (await db.artifact_store.content_path(ids[0])).read_text(encoding="utf-8") == "three"

    # 同一条事件重复投递仍然幂等（按路径收敛到同一份成果）。
    await db.artifact_store.ingest_run_item(item, project_id=project.id, work_root=work_root)
    assert len(await db.artifact_store.list(project.id)) == 1
    await db.close()

    reopened = await open_core_app_db(db_path)
    persisted = await reopened.artifact_store.get(ids[0])
    assert persisted is not None
    assert len(await reopened.artifact_store.list(project.id)) == 1
    await reopened.close()


@pytest.mark.asyncio
async def test_content_path_tracks_the_file_on_disk(tmp_path: Path) -> None:
    """文件被改写或删除后，成果读取如实跟随，不做任何历史兜底。"""
    work_root = tmp_path / "work"
    work_root.mkdir()
    db = await open_core_app_db(tmp_path / "core.db")
    project, _ = await db.project_store.create(work_root)
    target = work_root / "note.md"
    target.write_text("v1", encoding="utf-8")
    record = await db.artifact_store.register(
        project_id=project.id, work_root=work_root, path="note.md", kind="file_change",
    )
    assert record.availability == "available"

    target.write_text("v2", encoding="utf-8")
    assert (await db.artifact_store.content_path(record.artifact_id)).read_text(encoding="utf-8") == "v2"

    target.unlink()
    assert await db.artifact_store.content_path(record.artifact_id) is None
    assert (await db.artifact_store.get(record.artifact_id)).availability == "missing"
    await db.close()


@pytest.mark.asyncio
async def test_tool_artifact_outside_the_workspace_is_skipped_not_fatal(tmp_path: Path) -> None:
    """An approved out-of-workspace file must not fail the run that wrote it.

    The write/edit tools name such a file with an absolute path (a path that
    cannot be made relative to the workspace keeps its absolute form).  Artifact
    records only mean something inside the project, so ingestion keeps the
    tool's own entry and moves on instead of raising
    "Artifact path escapes project" — which used to take the whole turn down.
    """
    work_root = tmp_path / "work"
    work_root.mkdir()
    outside = tmp_path / "elsewhere" / "note.txt"
    outside.parent.mkdir()
    outside.write_text("hello", encoding="utf-8")
    db = await open_core_app_db(tmp_path / "core.db")
    project, _ = await db.project_store.create(work_root)

    item = RunItemEvent(
        kind="tool_result",
        thread_id="thread-1",
        turn_id="turn-1",
        item_id="item-outside",
        event_id="event-outside",
        status="completed",
        payload={"tool_name": "write_file"},
        artifacts=[{"kind": "file_change", "uri": outside.as_posix(), "content": "diff"}],
    )
    await db.artifact_store.ingest_run_item(item, project_id=project.id, work_root=work_root)

    assert item.artifacts[0]["uri"] == outside.as_posix()
    assert "artifact_id" not in item.artifacts[0]
    assert await db.artifact_store.list(project.id) == []

    # The skip is narrow: an absolute path *inside* the workspace still registers.
    inside = work_root / "inside.txt"
    inside.write_text("ok", encoding="utf-8")
    inside_item = RunItemEvent(
        kind="tool_result",
        thread_id="thread-1",
        turn_id="turn-2",
        item_id="item-inside",
        event_id="event-inside",
        status="completed",
        payload={"tool_name": "write_file"},
        artifacts=[{"kind": "file_change", "uri": inside.as_posix(), "content": "diff"}],
    )
    await db.artifact_store.ingest_run_item(inside_item, project_id=project.id, work_root=work_root)

    assert inside_item.artifacts[0]["artifact_id"]
    assert [record.path for record in await db.artifact_store.list(project.id)] == [
        "workspace://inside.txt"
    ]
    await db.close()


@pytest.mark.asyncio
async def test_legacy_manifest_migration_soft_remove_and_exclusions(tmp_path: Path) -> None:
    work_root = tmp_path / "work"
    legacy_root = work_root / ".lam" / "artifact"
    legacy_root.mkdir(parents=True)
    (work_root / "legacy.txt").write_text("legacy", encoding="utf-8")
    (legacy_root / "old-id.json").write_text(json.dumps({
        "kind": "document", "mime_type": "text/plain", "name": "legacy.txt",
        "path": "workspace://legacy.txt", "source": "agent_generated",
    }), encoding="utf-8")
    db = await open_core_app_db(tmp_path / "core.db")
    project, _ = await db.project_store.create(work_root)
    assert await db.artifact_store.migrate_legacy(project_id=project.id, work_root=work_root) == 1
    legacy = await db.artifact_store.get("old-id")
    assert legacy is not None and legacy.path == "workspace://legacy.txt"

    excluded = RunItemEvent(
        kind="tool_result", thread_id="t", event_id="read-event",
        payload={"tool_name": "read_file"}, artifacts=[{"kind": "file_read", "uri": "legacy.txt"}],
    )
    await db.artifact_store.ingest_run_item(excluded, project_id=project.id, work_root=work_root)
    assert len(await db.artifact_store.list(project.id)) == 1

    # 移出资料库只改状态，磁盘文件与内容都不动。
    assert await db.artifact_store.soft_remove([legacy.artifact_id]) == 1
    assert (work_root / "legacy.txt").is_file()
    assert (await db.artifact_store.content_path(legacy.artifact_id)).read_text(encoding="utf-8") == "legacy"
    await db.artifact_store.migrate_legacy(project_id=project.id, work_root=work_root)
    assert (await db.artifact_store.get(legacy.artifact_id)).deleted is True
    assert await db.artifact_store.soft_remove([legacy.artifact_id], deleted=False) == 1

    # 内容仍是磁盘上的当前文件：文件改了，读出来就是新的。
    (work_root / "legacy.txt").write_text("changed", encoding="utf-8")
    assert (await db.artifact_store.content_path(legacy.artifact_id)).read_text(encoding="utf-8") == "changed"
    await db.close()


@pytest.mark.asyncio
async def test_checkpoints_capture_conversation_only(tmp_path: Path) -> None:
    """检查点只保存对话上下文：不再记录文件清单、备份 blob 或成果版本指针。"""
    from sqlalchemy import func as sa_func
    from sqlalchemy import select as sa_select

    from lamtools_core.app.core_db import (
        CoreCheckpointArtifactRef,
        CoreCheckpointBlob,
        CoreWorkspaceManifest,
    )

    work_root = tmp_path / "work"
    work_root.mkdir()
    db = await open_core_app_db(tmp_path / "core.db")
    project, _ = await db.project_store.create(work_root)
    target = work_root / "checkpoint.txt"
    target.write_text("before", encoding="utf-8")
    await db.artifact_store.register(
        project_id=project.id, work_root=work_root, path="checkpoint.txt",
        kind="file_change", provenance={"event_id": "before-event"},
    )
    coordinator = CoreCheckpointCoordinator(
        work_root, db.session_factory, db.persistence.write_coordinator,
    )
    await coordinator.save(session_id="thread", turn_id="turn")

    async with db.session_factory() as session:
        for model in (CoreCheckpointArtifactRef, CoreWorkspaceManifest, CoreCheckpointBlob):
            total = (await session.execute(
                sa_select(sa_func.count()).select_from(model)
            )).scalar_one()
            assert total == 0, model.__tablename__
    await db.close()


@pytest.mark.asyncio
async def test_project_scoped_mutations_reject_artifacts_from_another_project(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    db = await open_core_app_db(tmp_path / "core.db")
    first, _ = await db.project_store.create(first_root)
    second, _ = await db.project_store.create(second_root)
    target = first_root / "private.txt"
    target.write_text("private", encoding="utf-8")
    artifact = await db.artifact_store.register(
        project_id=first.id,
        work_root=first_root,
        path="private.txt",
        kind="file_change",
    )

    assert await db.artifact_store.soft_remove(
        [artifact.artifact_id],
        project_id=second.id,
    ) == 0
    assert (await db.artifact_store.get(artifact.artifact_id)).deleted is False
    await db.close()


@pytest.mark.asyncio
async def test_upload_is_input_and_generated_image_is_durable_output(tmp_path: Path) -> None:
    work_root = tmp_path / "work"
    work_root.mkdir()
    db = await open_core_app_db(tmp_path / "core.db")
    project, _ = await db.project_store.create(work_root)
    upload = await db.artifact_store.register(
        project_id=project.id,
        work_root=work_root,
        path="attachment://upload-1",
        kind="image",
        mime_type="image/png",
        name="reference.png",
        source="user_upload",
        role="input",
        preferred_id="upload-1",
    )
    assert upload.role == "input"

    image_path = work_root / "generated.png"
    image_path.write_bytes(b"generated-image")
    item = RunItemEvent(
        kind="tool_result", thread_id="thread-image", turn_id="turn-image",
        item_id="item-image", event_id="event-image", payload={"tool_name": "generate_image"},
        artifacts=[{"kind": "image", "uri": "generated.png", "metadata": {"mime_type": "image/png"}}],
    )
    await db.artifact_store.ingest_run_item(item, project_id=project.id, work_root=work_root)
    generated = await db.artifact_store.get(item.artifacts[0]["artifact_id"])
    assert generated is not None and generated.kind == "image" and generated.role == "deliverable"
    assert (await db.artifact_store.content_path(generated.artifact_id)) == image_path
    await db.close()


@pytest.mark.asyncio
async def test_completed_agent_message_registers_existing_workspace_paths(tmp_path: Path) -> None:
    work_root = tmp_path / "work"
    output = work_root / "gui-run-01" / "financial-model.xlsx"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"xlsx")
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    db = await open_core_app_db(tmp_path / "core.db")
    project, _ = await db.project_store.create(work_root)
    item = RunItemEvent(
        kind="message",
        thread_id="thread-final",
        turn_id="turn-final",
        item_id="turn-final:model_text",
        event_id="event-final",
        status="completed",
        payload={
            "type": "agentMessage",
            "content": (
                "交付：`gui-run-01/financial-model.xlsx`，重复链接 "
                "[模型](gui-run-01/financial-model.xlsx)。\n"
                f"不要挂载项目外文件 `{outside}` 或不存在的 `missing.pdf`。"
            ),
        },
    )

    await db.artifact_store.ingest_run_item(item, project_id=project.id, work_root=work_root)

    assert len(item.artifacts) == 1
    assert item.artifacts[0]["uri"] == "gui-run-01/financial-model.xlsx"
    assert item.artifacts[0]["role"] == "deliverable"
    record = await db.artifact_store.get(item.artifacts[0]["artifact_id"])
    assert record is not None
    assert record.path == "workspace://gui-run-01/financial-model.xlsx"
    assert record.thread_id == "thread-final"
    assert record.turn_id == "turn-final"
    assert record.item_id == "turn-final:model_text"
    assert record.provenance["discovered_from"] == "final_response_path"
    await db.close()


@pytest.mark.asyncio
async def test_incomplete_or_child_agent_message_does_not_discover_paths(tmp_path: Path) -> None:
    work_root = tmp_path / "work"
    work_root.mkdir()
    (work_root / "draft.txt").write_text("draft", encoding="utf-8")
    db = await open_core_app_db(tmp_path / "core.db")
    project, _ = await db.project_store.create(work_root)
    for item in (
        RunItemEvent(
            kind="message", thread_id="t", event_id="running", status="running",
            payload={"type": "agentMessage", "content": "`draft.txt`"},
        ),
        RunItemEvent(
            kind="message", thread_id="t", event_id="child", status="completed",
            payload={"type": "agentMessage", "content": "`draft.txt`", "sub_agent_terminal": True},
        ),
    ):
        await db.artifact_store.ingest_run_item(item, project_id=project.id, work_root=work_root)
        assert item.artifacts == []
    assert await db.artifact_store.list(project.id) == []
    await db.close()


@pytest.mark.asyncio
async def test_artifact_preview_cli_prints_plain_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    work_root = tmp_path / "work"
    work_root.mkdir()
    target = work_root / "report.py"
    target.write_text("print('hello')\n", encoding="utf-8")
    db_path = tmp_path / "core.db"
    db = await open_core_app_db(db_path)
    project, _ = await db.project_store.create(work_root)
    artifact = await db.artifact_store.register(
        project_id=project.id,
        work_root=work_root,
        path="report.py",
        kind="file_change",
        mime_type="text/x-python",
    )
    await db.close()

    result = await cmd_artifact_preview(Namespace(
        artifact_id=artifact.artifact_id,
        work_root=str(work_root),
        core_db=str(db_path),
        max_chars=200000,
    ))

    assert result == 0
    assert capsys.readouterr().out == "print('hello')\n"
