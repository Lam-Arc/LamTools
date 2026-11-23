"""资产层、文件操作与统一服务的验收测试。

user:“文件从 D:\\A 移动到 D:\\B 后，只要能够确认是同一文件，原标签、评分和
收藏仍然保留”“删除资产管理记录与删除磁盘原文件必须是两种不同操作”
+(这些测试直接跑真实文件与临时 SQLite，不碰正在使用的 core.db)。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lamtools_core.app.core_db import CoreDbBase
from lamtools_core.app.sqlite_write import SQLiteWriteCoordinator
from lamtools_core.library import file_ops
from lamtools_core.library.everything import FileHit, SearchPage
from lamtools_core.library.service import LibraryFileService
from lamtools_core.library.store import FileAssetStore


class FakeProvider:
    def __init__(self, hits: list[FileHit] | None = None) -> None:
        self.hits = hits or []
        self.status_calls = 0

    def status(self, *, refresh: bool = False):
        self.status_calls += 1
        return {
            "state": "ready",
            "available": True,
            "es_path": "C:\\Everything\\es.exe",
            "everything_version": "1.4.1.1032",
            "message": "ok",
            "indexed_items": 100,
        }

    def search(self, spec):
        hits = [hit for hit in self.hits if not spec.kinds or hit.extension in {
            "png", "jpg", "jpeg", "gif", "webp", "bmp",
        }]
        return SearchPage(
            items=hits,
            total=len(hits),
            offset=spec.offset,
            limit=spec.limit,
            elapsed_ms=3,
            query="fake",
        )


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'library.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(CoreDbBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield FileAssetStore(factory, SQLiteWriteCoordinator(factory))
    await engine.dispose()


def _write(path: Path, payload: bytes = b"x") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return str(path)


@pytest.mark.asyncio
async def test_asset_follows_move_and_keeps_metadata(store, tmp_path):
    source = Path(_write(tmp_path / "A" / "miku.png", b"image"))
    record = await store.update_path(
        str(source),
        favorite=True,
        rating=4,
        tags=["Miku", "miku", " 初音 "],
        note="海报素材",
    )
    assert record is not None
    assert record["tags"] == ["miku", "初音"]

    target = tmp_path / "B" / "miku-renamed.png"
    target.parent.mkdir(parents=True)
    os.rename(source, target)

    moved = await store.touch_path(str(target))
    assert moved is not None
    assert moved["asset_id"] == record["asset_id"]
    assert moved["favorite"] is True
    assert moved["rating"] == 4
    assert moved["tags"] == ["miku", "初音"]
    assert moved["path"] == str(target)
    assert len(await store.list_all()) == 1


@pytest.mark.asyncio
async def test_copy_creates_a_separate_asset(store, tmp_path):
    source = Path(_write(tmp_path / "a.png"))
    first = await store.update_path(str(source), rating=5)
    copied = Path(_write(tmp_path / "a-copy.png"))
    second = await store.touch_path(str(copied))
    assert first is not None and second is not None
    assert first["asset_id"] != second["asset_id"]
    assert second["rating"] == 0
    assert len(await store.list_all()) == 2


@pytest.mark.asyncio
async def test_forget_removes_record_but_not_file(store, tmp_path):
    target = Path(_write(tmp_path / "keep.png"))
    record = await store.update_path(str(target), favorite=True)
    assert record is not None
    deleted = await store.forget([record["asset_id"]])
    assert deleted == 1
    assert target.exists()
    assert await store.get_by_path(str(target)) is None


@pytest.mark.asyncio
async def test_manual_collection_roundtrip(store, tmp_path):
    target = Path(_write(tmp_path / "shot.png"))
    record = await store.update_path(str(target), tags=["poster"])
    collection = await store.create_collection("海报")
    added = await store.add_to_collection(collection["collection_id"], [record["asset_id"]])
    assert added == 1
    items = await store.collection_assets(collection["collection_id"])
    assert [item.asset_id for item in items] == [record["asset_id"]]
    removed = await store.remove_from_collection(collection["collection_id"], [record["asset_id"]])
    assert removed == 1
    assert await store.delete_collection(collection["collection_id"]) is True
    assert target.exists()


@pytest.mark.asyncio
async def test_service_search_merges_asset_and_smart_collection(store, tmp_path):
    target = Path(_write(tmp_path / "miku.png", b"image"))
    hit = FileHit(
        path=str(target),
        name="miku.png",
        directory=str(target.parent),
        extension="png",
        size=5,
        modified_at="2026-11-20T10:00:00",
        created_at="2026-11-01T09:00:00",
        attributes="A",
        is_dir=False,
    )
    service = LibraryFileService(store, FakeProvider([hit]))
    result = await service.search({"query": "miku", "limit": 10})
    assert result["items"][0]["asset"] is None
    await store.update_path(str(target), favorite=True, rating=5, tags=["miku"])

    result = await service.search({"query": "miku", "limit": 10})
    assert result["items"][0]["asset"]["favorite"] is True
    assert result["items"][0]["asset"]["rating"] == 5

    collection = await store.create_collection("五星初音", kind="smart", query={"tags": ["miku"], "rating_min": 5})
    items = await service.collection_items(collection["collection_id"])
    assert items["total"] == 1
    assert items["items"][0]["path"] == str(target)


def test_rename_conflict_does_not_overwrite(tmp_path):
    source = tmp_path / "a.txt"
    other = tmp_path / "b.txt"
    source.write_text("a", encoding="utf-8")
    other.write_text("b", encoding="utf-8")
    result = file_ops.operate("rename", paths=[str(source)], new_name="b.txt", conflict="rename")
    assert result["ok"] == 1
    target = Path(result["items"][0]["target"])
    assert target.name == "b (1).txt"
    assert other.read_text(encoding="utf-8") == "b"


def test_move_across_directories_keeps_content(tmp_path):
    source = tmp_path / "one" / "a.txt"
    source.parent.mkdir()
    source.write_text("hello", encoding="utf-8")
    destination = tmp_path / "two"
    result = file_ops.operate("move", paths=[str(source)], target_dir=str(destination))
    assert result["ok"] == 1
    assert not source.exists()
    assert (destination / "a.txt").read_text(encoding="utf-8") == "hello"


def test_permanent_delete_requires_confirmation(tmp_path):
    target = tmp_path / "gone.txt"
    target.write_text("bye", encoding="utf-8")
    refused = file_ops.operate("delete", paths=[str(target)], confirm=False)
    assert refused["failed"] == 1
    assert target.exists()
    deleted = file_ops.operate("delete", paths=[str(target)], confirm=True)
    assert deleted["ok"] == 1
    assert not target.exists()


@pytest.mark.skipif(os.name != "nt", reason="回收站只有 Windows 有")
def test_trash_moves_file_out_of_place(tmp_path):
    target = tmp_path / "trash-me.txt"
    target.write_text("bye", encoding="utf-8")
    result = file_ops.operate("trash", paths=[str(target)])
    assert result["ok"] == 1
    assert not target.exists()


def test_create_empty_file_does_not_overwrite(tmp_path):
    target = tmp_path / "新文件.txt"
    created = file_ops.operate("touch", paths=[str(target)])
    assert created["ok"] == 1
    assert target.exists()
    assert target.read_bytes() == b""
    target.write_text("已有内容", encoding="utf-8")
    again = file_ops.operate("touch", paths=[str(target)])
    assert again["skipped"] == 1
    assert target.read_text(encoding="utf-8") == "已有内容"


@pytest.mark.asyncio
async def test_preview_text_and_folder(store, tmp_path):
    service = LibraryFileService(store, FakeProvider())
    text_file = tmp_path / "notes.md"
    text_file.write_text("# 标题\n\n正文", encoding="utf-8")
    preview = await service.preview(str(text_file))
    assert preview["kind"] == "document"
    assert "正文" in preview["text"]

    folder = tmp_path / "素材"
    folder.mkdir()
    (folder / "one.png").write_bytes(b"x")
    (folder / "two.txt").write_text("y", encoding="utf-8")
    folder_preview = await service.preview(str(folder))
    assert folder_preview["is_dir"] is True
    assert folder_preview["entry_count"] == 2


