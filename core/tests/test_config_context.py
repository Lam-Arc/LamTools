"""Tests for the global context config RPCs (loadtools / memory / load_context)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from lamtools_core.app.operation_catalog import OperationCatalog


def _context_catalog() -> OperationCatalog:
    from lamtools_core.app.http_agent_app import (
        _register_load_context_operations,
        _register_loadtools_operations,
        _register_memory_operations,
    )

    catalog = OperationCatalog()
    _register_loadtools_operations(catalog)
    _register_memory_operations(catalog)
    _register_load_context_operations(catalog)
    return catalog


# --- loadtools -------------------------------------------------------------


@pytest.mark.asyncio
async def test_loadtools_get_returns_builtin_modes_and_catalog(isolated_config_root):
    catalog = _context_catalog()

    result = await catalog.execute("config.loadtools.get")

    assert result.status == "ok"
    assert result.payload["source"] == "builtin"
    modes = result.payload["modes"]
    assert set(modes) == {"consider", "execute", "workflow"}
    assert modes["execute"]["tools"] == []  # full access
    assert "read_file" in modes["consider"]["tools"]
    catalog_names = {item["name"] for item in result.payload["catalog"]}
    assert "write_file" in catalog_names
    assert "edit_file" in catalog_names
    categories = {item["category"] for item in result.payload["catalog"]}
    assert "file_write" in categories and "command" in categories


@pytest.mark.asyncio
async def test_loadtools_set_writes_file_and_get_reads_it_back(isolated_config_root):
    catalog = _context_catalog()

    set_result = await catalog.execute("config.loadtools.set", {
        "modes": {
            "consider": {
                "description": "只读",
                "tools": ["read_file", "list_dir"],
            },
            "execute": {"description": "全量", "tools": []},
        },
    })

    assert set_result.status == "ok"
    assert set_result.payload["source"] == "config"
    # The file is written into the unified config dir and parses back cleanly.
    path = isolated_config_root / "loadtools.jsonc"
    assert path.is_file()
    from lamtools_core.tool.loadtools import load_loadtools

    loaded = load_loadtools(path)
    assert set(loaded) == {"consider", "execute"}
    assert loaded["consider"].tool_set == {"read_file", "list_dir"}
    assert loaded["execute"].is_full_access

    get_result = await catalog.execute("config.loadtools.get")
    assert get_result.payload["source"] == "config"
    assert get_result.payload["modes"]["consider"]["tools"] == ["read_file", "list_dir"]


@pytest.mark.asyncio
async def test_loadtools_set_rejects_invalid_payload(isolated_config_root):
    catalog = _context_catalog()

    result = await catalog.execute("config.loadtools.set", {"modes": "nope"})

    assert result.status == "error"
    assert "modes" in result.payload["error"]


# --- memory -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_get_returns_empty_when_missing(isolated_config_root):
    catalog = _context_catalog()

    result = await catalog.execute("config.memory.get")

    assert result.status == "ok"
    assert result.payload == {"content": "", "exists": False}


@pytest.mark.asyncio
async def test_memory_set_then_get_roundtrips(isolated_config_root):
    catalog = _context_catalog()

    set_result = await catalog.execute("config.memory.set", {"content": "# Global memory\n跨项目事实"})
    assert set_result.status == "ok"
    assert (isolated_config_root / "memory.md").read_text(encoding="utf-8") == "# Global memory\n跨项目事实"

    get_result = await catalog.execute("config.memory.get")
    assert get_result.status == "ok"
    assert get_result.payload["content"] == "# Global memory\n跨项目事实"
    assert get_result.payload["exists"] is True


# --- load_context -----------------------------------------------------------


@pytest.mark.asyncio
async def test_load_context_get_returns_empty_when_missing(isolated_config_root):
    catalog = _context_catalog()

    result = await catalog.execute("config.load_context.get")

    assert result.status == "ok"
    assert result.payload == {"addition": [], "except": [], "exists": False}


@pytest.mark.asyncio
async def test_load_context_set_then_get_roundtrips(isolated_config_root):
    catalog = _context_catalog()

    set_result = await catalog.execute("config.load_context.set", {
        "addition": [{"name": "GLOBAL_RULES.md", "priority": 30, "kind": "system"}],
        "except": ["CONTEXT.md"],
    })
    assert set_result.status == "ok"

    # The written file must be parseable by the actual context loader.
    from lamtools_core.app.project_context import ContextConfig

    config = ContextConfig.from_file(isolated_config_root / "load_context.jsonc")
    assert config is not None
    assert [item["name"] for item in config.addition] == ["GLOBAL_RULES.md"]
    assert config.except_files == ["CONTEXT.md"]

    get_result = await catalog.execute("config.load_context.get")
    assert get_result.status == "ok"
    assert get_result.payload["exists"] is True
    assert get_result.payload["addition"][0]["name"] == "GLOBAL_RULES.md"
    assert get_result.payload["except"] == ["CONTEXT.md"]


@pytest.mark.asyncio
async def test_load_context_set_rejects_malformed_addition(isolated_config_root):
    catalog = _context_catalog()

    result = await catalog.execute("config.load_context.set", {
        "addition": [{"priority": 10}],  # missing name
        "except": [],
    })

    assert result.status == "error"
    assert "name" in result.payload["error"]


# --- CLI --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cli_loadtools_show_edit_delete(isolated_config_root, capsys):
    from lamtools_core.cli import cmd_loadtools_delete_mode, cmd_loadtools_edit_mode, cmd_loadtools_show

    assert await cmd_loadtools_edit_mode(argparse.Namespace(
        mode="plan", description="计划模式", tools="read_file,list_dir", no_limit=False,
    )) == 0
    assert await cmd_loadtools_show(argparse.Namespace()) == 0
    out = capsys.readouterr().out
    assert "plan" in out and "计划模式" in out

    # --no-limit clears the whitelist (full access).
    assert await cmd_loadtools_edit_mode(argparse.Namespace(
        mode="plan", description="", tools="", no_limit=True,
    )) == 0
    from lamtools_core.tool.loadtools import load_loadtools

    loaded = load_loadtools(isolated_config_root / "loadtools.jsonc")
    assert loaded["plan"].is_full_access

    assert await cmd_loadtools_delete_mode(argparse.Namespace(mode="plan")) == 0
    assert "plan" not in load_loadtools(isolated_config_root / "loadtools.jsonc")


@pytest.mark.asyncio
async def test_cli_memory_and_load_context_set_get(isolated_config_root, capsys):
    from lamtools_core.cli import cmd_load_context_get, cmd_load_context_set, cmd_memory_get, cmd_memory_set

    import io
    import sys

    monkey_stdin = io.StringIO("# cli memory\n")
    original = sys.stdin
    sys.stdin = monkey_stdin
    try:
        assert await cmd_memory_set(argparse.Namespace(source_file="-")) == 0
    finally:
        sys.stdin = original
    assert await cmd_memory_get(argparse.Namespace()) == 0
    assert "# cli memory" in capsys.readouterr().out

    monkey_stdin = io.StringIO('{"addition":[{"name":"X.md","priority":20}],"except":[]}')
    original = sys.stdin
    sys.stdin = monkey_stdin
    try:
        assert await cmd_load_context_set(argparse.Namespace(source_file="-")) == 0
    finally:
        sys.stdin = original
    assert await cmd_load_context_get(argparse.Namespace()) == 0
    out = capsys.readouterr().out
    assert "X.md" in out
