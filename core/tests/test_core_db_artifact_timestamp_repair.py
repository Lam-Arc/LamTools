"""旧库的 core_artifacts.last_used_at 是 TEXT NOT NULL DEFAULT ''，模型却是可空 DateTime。

ORM 读到空串会用 fromisoformat 解析并抛 ValueError，导致资料库列表、成果登记和
附件上传全线 500。这里锁住启动时的结构修复：重建这一列、把空串还原成 NULL，
并保证修好之后既能读也能写入新成果。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lamtools_core.app.core_db import CoreArtifact, CoreDbBase, _ensure_late_columns


async def _legacy_artifact_db(path: str) -> None:
    """建一个旧库：模型建完表后，把 last_used_at 換成历史上的 TEXT NOT NULL 形态。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(CoreDbBase.metadata.create_all)
        created = await conn.scalar(
            text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'core_artifacts'")
        )
        legacy = str(created).replace(
            "last_used_at DATETIME", "last_used_at VARCHAR(64) NOT NULL DEFAULT ''"
        ).replace("CREATE TABLE core_artifacts", "CREATE TABLE core_artifacts_legacy")
        await conn.execute(text(legacy))
        columns = [
            row["name"]
            for row in (await conn.execute(text("PRAGMA table_info(core_artifacts)"))).mappings()
        ]
        others = [name for name in columns if name != "last_used_at"]
        values = ", ".join(f'"{name}"' for name in others)
        await conn.execute(text(
            f"INSERT INTO core_artifacts_legacy ({values}, last_used_at) "
            f"SELECT {values}, '' FROM core_artifacts"
        ))
        await conn.execute(text("DROP TABLE core_artifacts"))
        await conn.execute(text("ALTER TABLE core_artifacts_legacy RENAME TO core_artifacts"))
        await conn.execute(text(
            "INSERT INTO core_artifacts (id, project_id, work_root, normalized_path, kind, mime_type, "
            "name, path, source, role, prompt, parent_ids_json, children_ids_json, latest_revision_id, "
            "revision_count, thread_id, turn_id, item_id, tool_name, provenance_json, favorite, folder, "
            "tags_json, rating, usage_json, usage_count, used_in_json, deleted, "
            "created_at, updated_at, last_used_at) VALUES "
            "('legacy1', 'p1', 'E:/work', 'E:/work/a.png', 'image', 'image/png', 'a.png', "
            "'E:/work/a.png', 'user_upload', 'input', '', '[]', '[]', '', 0, 't1', '', '', '', '{}', 0, '', "
            "'[]', 0, '{}', 0, '[]', 0, "
            "'2026-11-01 10:00:00.000000', '2026-11-01 10:00:00.000000', '')"
        ))
    await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_empty_last_used_at_is_repaired_at_boot(tmp_path):
    path = str(tmp_path / "legacy-artifacts.db")
    await _legacy_artifact_db(path)

    legacy_engine = create_async_engine(f"sqlite+aiosqlite:///{path}", future=True)
    # 修复前的症状必须能复现，否则这个测试没有证明力。
    with pytest.raises(ValueError):
        async with async_sessionmaker(legacy_engine, expire_on_commit=False)() as db:
            (await db.execute(select(CoreArtifact))).scalars().all()
    await legacy_engine.dispose()

    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", future=True)
    async with engine.connect() as conn:
        await _ensure_late_columns(conn)
        await conn.commit()

    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        rows = (await db.execute(select(CoreArtifact))).scalars().all()
        assert [row.id for row in rows] == ["legacy1"]
        assert rows[0].last_used_at is None
        # 修好之后新增成果（附件登记那条路）必须写得进去。
        db.add(CoreArtifact(
            id="fresh1", project_id="p1", work_root="E:/work",
            normalized_path="E:/work/b.png", path="E:/work/b.png",
            name="b.png", kind="image", mime_type="image/png",
            source="user_upload", role="input",
        ))
        await db.commit()

    async with engine.connect() as conn:
        declared = {
            row["name"]: row["type"]
            for row in (await conn.execute(text("PRAGMA table_info(core_artifacts)"))).mappings()
        }
    assert "DATE" in str(declared["last_used_at"]).upper()
    await engine.dispose()

    # 第二次启动是空操作，不会重复重建。
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", future=True)
    async with engine.connect() as conn:
        await _ensure_late_columns(conn)
        await conn.commit()
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        assert len((await db.execute(select(CoreArtifact))).scalars().all()) == 2
    await engine.dispose()
