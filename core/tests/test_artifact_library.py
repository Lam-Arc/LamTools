"""资料库（成果库）在库侧新增的四件事：收藏、归档层级、上传新建、占用统计。

对应界面里「资料」那一区的能力，所以断言直接落在磁盘与库上，不经过 UI：
上传必须真的落成文件、重名不许覆盖、收藏/归档只动这两个字段、占用只算最新版本。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.artifact.store import UPLOAD_DIRNAME


@pytest.mark.asyncio
async def test_upload_lands_as_a_real_file_and_a_user_upload_artifact(tmp_path: Path) -> None:
    work_root = tmp_path / "work"
    work_root.mkdir()
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        project, _ = await db.project_store.create(work_root)
        store = db.artifact_store

        record = await store.upload(
            project_id=project.id,
            work_root=work_root,
            name="参考材料.md",
            content="# 参考\n".encode("utf-8"),
            mime_type="text/markdown",
        )

        # 落成真实文件：助手能直接读，用户也能在自己的文件夹里看到。
        written = work_root / UPLOAD_DIRNAME / "参考材料.md"
        assert written.read_text(encoding="utf-8") == "# 参考\n"
        assert record.source == "user_upload"
        assert record.role == "input"
        assert record.name == "参考材料.md"
        assert record.path == f"workspace://{UPLOAD_DIRNAME}/参考材料.md"
        assert record.availability == "available"

        # 再传一个同名文件：加序号，绝不覆盖。
        second = await store.upload(
            project_id=project.id, work_root=work_root, name="参考材料.md", content=b"second",
        )
        assert second.name == "参考材料 (2).md"
        assert written.read_text(encoding="utf-8") == "# 参考\n"
        assert (work_root / UPLOAD_DIRNAME / "参考材料 (2).md").read_bytes() == b"second"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_favorite_and_folder_persist_without_touching_updated_at(tmp_path: Path) -> None:
    work_root = tmp_path / "work"
    work_root.mkdir()
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        project, _ = await db.project_store.create(work_root)
        store = db.artifact_store
        created = await store.upload(
            project_id=project.id, work_root=work_root, name="图.png", content=b"\x89PNG",
        )
        before = (await store.get(created.artifact_id)).updated_at

        starred = await store.set_favorite(created.artifact_id, True)
        assert starred.favorite is True
        filed = await store.set_folder(created.artifact_id, "项目A/这一期")
        assert filed.folder == "项目A/这一期"

        # 整理不是修改：这两下都不该动 updated_at，否则列表会被无谓地重排。
        reloaded = await store.get(created.artifact_id)
        assert reloaded.favorite is True
        assert reloaded.folder == "项目A/这一期"
        assert reloaded.updated_at == before

        # 取消归档与取消收藏都回到空。
        assert (await store.set_folder(created.artifact_id, "")).folder == ""
        assert (await store.set_favorite(created.artifact_id, False)).favorite is False

        with pytest.raises(ValueError):
            await store.set_folder(created.artifact_id, "../逃逸")
        with pytest.raises(LookupError):
            await store.set_favorite("不存在", True)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_stats_counts_artifacts_and_their_current_file_bytes(tmp_path: Path) -> None:
    work_root = tmp_path / "work"
    work_root.mkdir()
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        project, _ = await db.project_store.create(work_root)
        store = db.artifact_store
        assert await store.stats(project.id) == {"count": 0, "bytes": 0}

        await store.upload(project_id=project.id, work_root=work_root, name="a.bin", content=b"12345")
        await store.upload(project_id=project.id, work_root=work_root, name="b.bin", content=b"123")

        stats = await store.stats(project.id)
        assert stats == {"count": 2, "bytes": 8}

        # 占用跟随当前文件：文件改了，字节数就是新的（不保留历史版本）。
        (work_root / "资料" / "a.bin").write_bytes(b"1234567890")
        assert (await store.stats(project.id))["bytes"] == 13

        # 移除只改资料库状态：条数少一个，占用按剩下的算。
        listing = await store.list(project.id)
        await store.soft_remove([listing[0].artifact_id], deleted=True, project_id=project.id)
        stats = await store.stats(project.id)
        assert stats["count"] == 1
    finally:
        await db.close()
