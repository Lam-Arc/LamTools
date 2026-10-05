"""Tests for the ``memory`` tool (tool/memory_tools.py)."""

from __future__ import annotations

import pytest

from lamtools_core.tool import ToolCall
from lamtools_core.tool.default_toolbox import (
    DEFAULT_TOOL_PERMISSIONS,
    build_core_toolbox,
)
from lamtools_core.tool.memory_tools import MEMORY_TOOL_NAME, make_memory_handler


def _call(**arguments):
    return ToolCall(id="call-1", name=MEMORY_TOOL_NAME, arguments=arguments)


def test_memory_tool_is_exposed_and_auto_allowed(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path)

    names = [spec["function"]["name"] for spec in toolbox.model_tools()]

    assert MEMORY_TOOL_NAME in names
    assert DEFAULT_TOOL_PERMISSIONS[MEMORY_TOOL_NAME] == "auto_allow"


def test_memory_tool_needs_no_approval(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path)

    call = toolbox.prepare_call(
        _call(action="write", path="a.md", content="A")
    )

    assert call.requires_approval is False


@pytest.mark.asyncio
async def test_memory_tool_roundtrip_through_the_toolbox(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path)

    written = await toolbox.execute(_call(action="write", path="notes/a.md", content="# A\n"))
    assert written.status == "ok"
    assert (tmp_path / ".lam" / "memory" / "notes" / "a.md").is_file()

    read = await toolbox.execute(_call(action="read", path="notes/a.md"))
    assert read.status == "ok"
    assert read.content == "# A\n"

    listed = await toolbox.execute(_call(action="list"))
    assert listed.status == "ok"
    assert "notes/a.md" in listed.content

    deleted = await toolbox.execute(_call(action="delete", path="notes/a.md"))
    assert deleted.status == "ok"


@pytest.mark.asyncio
async def test_memory_tool_refreshes_the_index_on_write(tmp_path):
    handler = make_memory_handler(tmp_path)

    await handler(_call(action="write", path="facts.md", content="# Facts\n\nUse UTF-8.\n"))

    index = (tmp_path / ".lam" / "memory" / "INDEX.md").read_text(encoding="utf-8")
    assert "`facts.md`" in index
    assert "Facts" in index


@pytest.mark.asyncio
async def test_memory_tool_rejects_missing_action_and_unknown_action(tmp_path):
    handler = make_memory_handler(tmp_path)

    assert (await handler(_call())).error_code == "missing_argument"
    assert (await handler(_call(action="nope"))).error_code == "invalid_action"
    assert (await handler(_call(action="read"))).error_code == "missing_argument"


@pytest.mark.asyncio
async def test_memory_tool_surfaces_library_errors(tmp_path):
    handler = make_memory_handler(tmp_path)

    escape = await handler(_call(action="read", path="../escape.md"))
    assert escape.status == "failed"
    assert escape.error_code == "invalid_path"

    reserved = await handler(_call(action="write", path="INDEX.md", content="x"))
    assert reserved.status == "failed"
    assert reserved.error_code == "reserved_name"

    missing = await handler(_call(action="read", path="nope.md"))
    assert missing.status == "failed"
    assert missing.error_code == "not_found"


@pytest.mark.asyncio
async def test_memory_tool_global_scope_uses_the_config_tier(tmp_path, isolated_config_root):
    handler = make_memory_handler(tmp_path)

    result = await handler(_call(action="write", scope="global", path="facts.md", content="shared"))

    assert result.status == "ok"
    assert (isolated_config_root / "memory" / "facts.md").read_text(encoding="utf-8") == "shared"
