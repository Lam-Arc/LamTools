"""Tests for the short-term memory store (SQLite + in-memory)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.mem import MemoryEntry, MemoryQuery
from lamtools_core.mem.store import InMemoryMemoryStore, SqlAlchemyMemoryStore


# ── fixtures ─────────────────────────────────────────────────────


@pytest.fixture
async def sqlite_store(tmp_path: Path):
    db = await open_core_app_db(tmp_path / "mem_test.db")
    yield db.memory_store
    await db.close()


def _entry(**overrides) -> MemoryEntry:
    defaults = dict(
        id="m1",
        kind="fact",
        content="项目数据库在 data/core.db",
        domain="core",
        source="session#a",
        layer="hot",
        confidence=0.9,
    )
    defaults.update(overrides)
    return MemoryEntry(**defaults)


# ── parametrised over both store implementations ─────────────────

@pytest.fixture(params=["sqlite", "memory"])
async def store(request, sqlite_store):
    if request.param == "sqlite":
        return sqlite_store
    return InMemoryMemoryStore()


# ── tests ────────────────────────────────────────────────────────


class TestMemoryStoreCRUD:
    async def test_add_and_get(self, store):
        entry = _entry()
        await store.add(entry)
        got = await store.get("m1")
        assert got is not None
        assert got.kind == "fact"
        assert got.content == "项目数据库在 data/core.db"
        assert got.confidence == 0.9

    async def test_get_missing_returns_none(self, store):
        assert await store.get("nonexistent") is None

    async def test_add_assigns_id_if_missing(self, store):
        entry = _entry(id="")
        await store.add(entry)
        assert entry.id  # uuid was assigned

    async def test_add_upserts_existing(self, store):
        await store.add(_entry(content="original"))
        await store.add(_entry(content="updated"))
        got = await store.get("m1")
        assert got.content == "updated"

    async def test_delete(self, store):
        await store.add(_entry())
        await store.delete("m1")
        assert await store.get("m1") is None

    async def test_delete_missing_is_noop(self, store):
        await store.delete("nonexistent")  # should not raise


class TestMemoryStoreSearch:
    async def test_search_by_content(self, store):
        await store.add(_entry(id="m1", content="SQLite database location", kind="fact"))
        await store.add(_entry(id="m2", content="PowerShell UTF-8 preference", kind="preference"))
        result = await store.search(MemoryQuery(query="SQLite", limit=5))
        assert result.total == 1
        assert result.hits[0].entry.id == "m1"

    async def test_search_by_kind_filter(self, store):
        await store.add(_entry(id="m1", content="UTF-8", kind="fact"))
        await store.add(_entry(id="m2", content="UTF-8", kind="preference"))
        result = await store.search(MemoryQuery(query="UTF-8", kinds=["preference"], limit=5))
        assert result.total == 1
        assert result.hits[0].entry.kind == "preference"

    async def test_search_by_layer_filter(self, store):
        await store.add(_entry(id="m1", content="data", layer="hot"))
        await store.add(_entry(id="m2", content="data", layer="cold"))
        result = await store.search(MemoryQuery(query="data", layers=["hot"], limit=5))
        assert result.total == 1
        assert result.hits[0].entry.layer == "hot"

    async def test_search_by_min_confidence(self, store):
        await store.add(_entry(id="m1", content="thing", confidence=0.3))
        await store.add(_entry(id="m2", content="thing", confidence=0.9))
        result = await store.search(MemoryQuery(query="thing", min_confidence=0.5, limit=5))
        assert result.total == 1
        assert result.hits[0].entry.confidence == 0.9

    async def test_search_no_match(self, store):
        await store.add(_entry(content="hello world"))
        result = await store.search(MemoryQuery(query="nonexistent_term", limit=5))
        assert result.total == 0

    async def test_search_limit(self, store):
        for i in range(5):
            await store.add(_entry(id=f"m{i}", content="common term", confidence=0.5))
        result = await store.search(MemoryQuery(query="common", limit=3))
        assert result.total == 3

    async def test_search_relevance_score(self, store):
        await store.add(_entry(id="m1", content="the quick brown fox"))
        result = await store.search(MemoryQuery(query="quick brown", limit=5))
        assert result.hits[0].score == pytest.approx(1.0)


class TestMemoryStoreTouch:
    async def test_touch_bumps_access_count(self, store):
        await store.add(_entry())
        await store.touch("m1")
        got = await store.get("m1")
        assert got.access_count == 1

    async def test_touch_missing_is_noop(self, store):
        await store.touch("nonexistent")  # should not raise


class TestSqlAlchemyMemoryStoreSpecific:
    async def test_list_for_work_root(self, sqlite_store):
        e1 = _entry(id="m1", content="a")
        e1.metadata["work_root"] = "/project"
        e2 = _entry(id="m2", content="b")
        e2.metadata["work_root"] = "/other"
        await sqlite_store.add(e1)
        await sqlite_store.add(e2)
        result = await sqlite_store.list_for_work_root("/project")
        assert len(result) == 1
        assert result[0].id == "m1"
