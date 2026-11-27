"""RPC-level acceptance for the core-cognition and dream operations.

The memory view and any client reach these through the operation catalog, so the
operations must be registered and behave from the outside — not only through the
library functions the other tests use directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core import mem as memory
from lamtools_core.app.http_agent_app import _register_memory_operations
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.mem import dreaming


@pytest.fixture()
def project_work(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    return work


@pytest.fixture()
def catalog() -> OperationCatalog:
    instance = OperationCatalog()
    _register_memory_operations(instance)
    return instance


def _params(work: Path, **extra: object) -> dict[str, object]:
    return {"scope": "project", "work_root": str(work), **extra}


@pytest.mark.asyncio
async def test_operations_are_registered(catalog):
    for name in (
        "memory.core.get",
        "memory.core.set",
        "memory.core.clear",
        "memory.core.versions",
        "memory.core.restore",
        "memory.dream.status",
        "memory.dream.run",
    ):
        assert catalog.has(name), name


@pytest.mark.asyncio
async def test_core_set_then_get_returns_the_document_and_dream_state(catalog, project_work):
    written = await catalog.execute(
        "memory.core.set",
        _params(project_work, content="# 项目认知\n用户偏好方案先行。\n"),
    )
    assert written.status == "ok", written.payload

    got = await catalog.execute("memory.core.get", _params(project_work))

    assert got.status == "ok", got.payload
    payload = got.payload
    assert payload["scope"] == "project"
    assert payload["path"].endswith(memory.CORE_FILENAME)
    assert payload["content"].startswith("# 项目认知")
    assert payload["versions"] == []
    assert payload["dream"]["enabled"] is True
    assert payload["dream"]["last_dream_at"] == ""


@pytest.mark.asyncio
async def test_versions_are_listed_and_restorable(catalog, project_work):
    await catalog.execute("memory.core.set", _params(project_work, content="# 第一版\n"))
    await catalog.execute("memory.core.set", _params(project_work, content="# 第二版\n"))

    listed = await catalog.execute("memory.core.versions", _params(project_work))
    versions = listed.payload["versions"]
    assert versions, "the previous content must be listed"

    restored = await catalog.execute(
        "memory.core.restore", _params(project_work, version=versions[0]["id"])
    )
    assert restored.status == "ok", restored.payload
    assert "第一版" in memory.read_core_document(memory.SCOPE_PROJECT, project_work)


@pytest.mark.asyncio
async def test_clear_empties_the_document_but_keeps_history(catalog, project_work):
    await catalog.execute("memory.core.set", _params(project_work, content="# 认知\n内容。\n"))

    cleared = await catalog.execute("memory.core.clear", _params(project_work))

    assert cleared.status == "ok", cleared.payload
    assert memory.read_core_document(memory.SCOPE_PROJECT, project_work) == ""
    listed = await catalog.execute("memory.core.versions", _params(project_work))
    assert listed.payload["versions"]


@pytest.mark.asyncio
async def test_deleting_from_the_client_records_a_tombstone(catalog, project_work):
    memory.write_memory(
        memory.SCOPE_PROJECT, project_work, "notes/old.md", "when X, read this"
    )

    deleted = await catalog.execute(
        "memory.delete", _params(project_work, path="notes/old.md")
    )

    assert deleted.status == "ok", deleted.payload
    state = dreaming.load_state(memory.SCOPE_PROJECT, project_work)
    assert state["forgotten"][0]["path"] == "notes/old.md"
    assert state["forgotten"][0]["title"] == "when X, read this"


@pytest.mark.asyncio
async def test_dream_status_reports_both_tiers(catalog, project_work):
    result = await catalog.execute("memory.dream.status", {"work_root": str(project_work)})

    assert result.status == "ok", result.payload
    payload = result.payload
    assert payload["enabled"] is True
    assert payload["global"]["last_dream_at"] == ""
    assert payload["project"]["last_dream_at"] == ""


@pytest.mark.asyncio
async def test_project_core_requires_a_workspace(catalog):
    result = await catalog.execute(
        "memory.core.get", {"scope": "project", "work_root": ""}
    )
    # A project tier without a workspace is a caller error, surfaced as one.
    assert result.status == "error"
    assert result.payload.get("error_code") == "invalid_path"
