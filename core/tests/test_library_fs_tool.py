"""Agent 的 library_files 工具装配与动作路由测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.library.tools import LIBRARY_FILES_TOOL_NAME
from lamtools_core.tool import ToolCall, ToolContext
from lamtools_core.tool.default_toolbox import CoreToolbox


@pytest.fixture
def toolbox(tmp_path):
    calls: list[tuple[str, dict]] = []

    async def execute(name, payload, metadata):
        calls.append((name, payload))
        if name == "libraryfs.search":
            return {
                "items": [{
                    "path": "D:\\Art\\miku.png",
                    "name": "miku.png",
                    "size": 2048,
                    "modified_at": "2026-11-20T10:00:00",
                    "kind": "image",
                    "asset": None,
                }],
                "total": 1,
            }
        if name == "libraryfs.collection.create":
            return {"collection": {"collection_id": "col-1", "name": payload.get("name"), "kind": "manual"}}
        if name == "libraryfs.collection.add":
            return {"added": len(payload.get("paths") or []), "assets": len(payload.get("paths") or [])}
        return {"ok": True}

    box = CoreToolbox(
        work_root=Path(tmp_path),
        enable_library_tool=True,
        operation_executor=execute,
    )
    box.test_calls = calls  # type: ignore[attr-defined]
    return box


def _context(box: CoreToolbox) -> ToolContext:
    return ToolContext(session_id="session-test", work_root=box.work_root)


@pytest.mark.asyncio
async def test_library_tool_is_assembled_and_search_routes_to_operation(toolbox):
    specs = {spec.name: spec for spec in toolbox.tool_specs()}
    assert LIBRARY_FILES_TOOL_NAME in specs
    assert specs[LIBRARY_FILES_TOOL_NAME].permission == "auto_allow"

    result = await toolbox.execute(
        ToolCall(id="call-1", name=LIBRARY_FILES_TOOL_NAME, arguments={"action": "search", "query": "miku"}),
        context=_context(toolbox),
    )
    assert result.status == "ok"
    assert "1 shown / 1 total" in (result.content or "")
    assert toolbox.test_calls[-1][0] == "libraryfs.search"  # type: ignore[attr-defined]
    assert toolbox.test_calls[-1][1]["query"] == "miku"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_library_tool_collect_updates_assets_and_collection(toolbox):
    result = await toolbox.execute(
        ToolCall(
            id="call-2",
            name=LIBRARY_FILES_TOOL_NAME,
            arguments={
                "action": "collect",
                "paths": ["D:\\Art\\miku.png", "D:\\Art\\miku-2.png"],
                "rating": 5,
                "tags": ["miku"],
                "new_collection": "海报",
            },
        ),
        context=_context(toolbox),
    )
    assert result.status == "ok"
    names = [name for name, _ in toolbox.test_calls]  # type: ignore[attr-defined]
    assert names.count("libraryfs.asset.update") == 2
    assert "libraryfs.collection.create" in names
    assert "libraryfs.collection.add" in names


@pytest.mark.asyncio
async def test_library_tool_locates_without_file_writes(toolbox):
    result = await toolbox.execute(
        ToolCall(
            id="call-3",
            name=LIBRARY_FILES_TOOL_NAME,
            arguments={"action": "locate", "path": "D:\\Art\\miku.png"},
        ),
        context=_context(toolbox),
    )
    assert result.status == "ok"
    assert toolbox.test_calls[-1][0] == "libraryfs.reveal"  # type: ignore[attr-defined]
    assert all(name != "libraryfs.file.operate" for name, _ in toolbox.test_calls)  # type: ignore[attr-defined]
