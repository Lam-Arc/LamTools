"""Tests for library seeding (artifact/seed.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.artifact.seed import SeedError, load_manifest, seed_library, verify_asset


def _manifest(**overrides) -> dict:
    manifest = {
        "version": 1,
        "aliases": {"@": "ui"},
        "assets": [
            {
                "file": "ui/glass.css",
                "name": "光学玻璃材质",
                "folder": "样式/材质",
                "tags": ["material", "glass", "low-trans"],
                "rating": 5,
                "usage": {
                    "entry": ".optical-glass--low-trans",
                    "requires": "--glass-tint",
                    "example": '<div class="optical-glass"></div>',
                },
            }
        ],
        "retag": [{"file": "ui/Ring.vue", "tags": ["control", "ring"]}],
    }
    manifest.update(overrides)
    return manifest


async def _fixture(tmp_path: Path, manifest: dict):
    work_root = tmp_path / "work"
    (work_root / "ui").mkdir(parents=True)
    (work_root / "ui" / "glass.css").write_text(
        ".optical-glass { color: red; }\n.optical-glass--low-trans { opacity: 0.6; }\n",
        encoding="utf-8",
    )
    (work_root / "ui" / "Ring.vue").write_text(
        '<template><div class="ping-ring"></div></template>',
        encoding="utf-8",
    )
    manifest_path = tmp_path / "seed.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    db = await open_core_app_db(tmp_path / "core.db")
    project, _session = await db.project_store.create(work_root)
    return db, project, work_root, manifest_path


@pytest.mark.asyncio
async def test_seed_files_materials_with_usage_and_retags_the_rest(tmp_path):
    """带用法的素材入库；其余文件只换标签，两层都落在同一个库里。"""
    db, project, work_root, manifest_path = await _fixture(tmp_path, _manifest())

    report = await seed_library(
        db.artifact_store,
        project_id=project.id,
        work_root=work_root,
        manifest_path=manifest_path,
    )

    assert report["failed"] == []
    assert len(report["assets"]) == 1
    assert len(report["retagged"]) == 1

    record = await db.artifact_store.get(report["assets"][0]["artifact_id"])
    assert record is not None
    assert record.name == "光学玻璃材质"
    assert record.folder == "样式/材质"
    assert record.tags == ["material", "glass", "low-trans"]
    assert record.rating == 5
    assert record.usage["entry"] == ".optical-glass--low-trans"
    assert record.usage["requires"] == "--glass-tint"

    ring = await db.artifact_store.get(report["retagged"][0]["artifact_id"])
    assert ring is not None
    assert ring.tags == ["control", "ring"]
    assert ring.usage == {}
    await db.close()


@pytest.mark.asyncio
async def test_seed_refuses_an_entry_that_is_not_in_the_file(tmp_path):
    """entry 在文件里不存在就不入库：宁可失败，也不留一条骗人的用法。"""
    manifest = _manifest()
    manifest["assets"][0]["usage"]["entry"] = ".optical-glass--solid"
    db, project, work_root, manifest_path = await _fixture(tmp_path, manifest)

    report = await seed_library(
        db.artifact_store,
        project_id=project.id,
        work_root=work_root,
        manifest_path=manifest_path,
    )

    assert report["assets"] == []
    assert report["failed"][0]["file"] == "ui/glass.css"
    assert ".optical-glass--solid" in report["failed"][0]["problems"][0]
    listed = await db.artifact_store.list(project.id)
    assert [item.name for item in listed] == ["Ring.vue"]  # 只剩重打标签的那份
    await db.close()


@pytest.mark.asyncio
async def test_seed_verifies_import_entries_through_aliases(tmp_path):
    """import 形式的 entry 必须能落到真实文件；落不到就失败。"""
    manifest = _manifest()
    manifest["assets"][0]["file"] = "ui/Ring.vue"
    manifest["assets"][0]["usage"]["entry"] = "import PingRing from '@/Ring.vue'"
    db, project, work_root, manifest_path = await _fixture(tmp_path, manifest)

    report = await seed_library(
        db.artifact_store,
        project_id=project.id,
        work_root=work_root,
        manifest_path=manifest_path,
    )
    assert report["failed"] == []

    manifest["assets"][0]["usage"]["entry"] = "import Ghost from '@/Ghost.vue'"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    report = await seed_library(
        db.artifact_store,
        project_id=project.id,
        work_root=work_root,
        manifest_path=manifest_path,
    )
    assert report["failed"][0]["problems"][0].startswith("entry 指向的文件不存在")
    await db.close()


@pytest.mark.asyncio
async def test_seed_fills_gaps_and_never_overwrites_by_default(tmp_path):
    """播种是补空：人改过的评分与用法不会被清单盖掉，标签只做并集。"""
    db, project, work_root, manifest_path = await _fixture(tmp_path, _manifest())
    first = await seed_library(
        db.artifact_store,
        project_id=project.id,
        work_root=work_root,
        manifest_path=manifest_path,
    )
    artifact_id = first["assets"][0]["artifact_id"]
    await db.artifact_store.set_rating(artifact_id, 2)
    await db.artifact_store.set_usage(artifact_id, {"entry": ".custom-entry"})

    again = await seed_library(
        db.artifact_store,
        project_id=project.id,
        work_root=work_root,
        manifest_path=manifest_path,
    )
    assert again["failed"] == []
    record = await db.artifact_store.get(artifact_id)
    assert record.rating == 2
    assert record.usage == {"entry": ".custom-entry"}
    assert record.tags == ["material", "glass", "low-trans"]  # 没有重复

    forced = await seed_library(
        db.artifact_store,
        project_id=project.id,
        work_root=work_root,
        manifest_path=manifest_path,
        overwrite=True,
    )
    assert forced["assets"][0]["changed"]
    record = await db.artifact_store.get(artifact_id)
    assert record.rating == 5
    assert record.usage["entry"] == ".optical-glass--low-trans"
    await db.close()


@pytest.mark.asyncio
async def test_seed_does_not_resurrect_a_removed_entry(tmp_path):
    """人从资料库移除过的素材，播种不会把它悄悄放回来。"""
    db, project, work_root, manifest_path = await _fixture(tmp_path, _manifest())
    first = await seed_library(
        db.artifact_store,
        project_id=project.id,
        work_root=work_root,
        manifest_path=manifest_path,
    )
    artifact_id = first["assets"][0]["artifact_id"]
    await db.artifact_store.soft_remove([artifact_id], project_id=project.id)

    again = await seed_library(
        db.artifact_store,
        project_id=project.id,
        work_root=work_root,
        manifest_path=manifest_path,
    )
    assert again["assets"] == []
    assert again["skipped"][0]["reason"] == "已从资料库移除"
    record = await db.artifact_store.get(artifact_id)
    assert record.deleted is True
    await db.close()


def test_manifest_shape_is_validated(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_manifest()), encoding="utf-8")
    assert load_manifest(good)["aliases"] == {"@": "ui"}

    bad_version = tmp_path / "bad-version.json"
    bad_version.write_text(json.dumps(_manifest(version=99)), encoding="utf-8")
    with pytest.raises(SeedError):
        load_manifest(bad_version)

    not_json = tmp_path / "bad.json"
    not_json.write_text("{", encoding="utf-8")
    with pytest.raises(SeedError):
        load_manifest(not_json)


def test_verify_asset_rejects_escaping_paths(tmp_path):
    work_root = tmp_path / "work"
    work_root.mkdir()
    (tmp_path / "outside.css").write_text(".x {}", encoding="utf-8")

    _path, problems = verify_asset(
        work_root.resolve(),
        {"file": "../outside.css", "name": "越界", "tags": ["x"], "usage": {"entry": ".x"}},
        {},
    )

    assert problems and "越出工作区" in problems[0]


def test_verify_asset_accepts_a_design_token_entry(tmp_path):
    """令牌也是取用抓手：--radius 必须在这份文件里真的定义过。"""
    root = tmp_path / "work"
    root.mkdir()
    (root / "vars.css").write_text(":root { --radius: 12px; }", encoding="utf-8")
    asset = {"file": "vars.css", "name": "设计令牌", "tags": ["token"], "usage": {"entry": "--radius"}}

    path, problems = verify_asset(root.resolve(), asset, {})
    assert path is not None and problems == []

    asset["usage"]["entry"] = "--missing"
    _path, problems = verify_asset(root.resolve(), asset, {})
    assert problems and "--missing" in problems[0]
