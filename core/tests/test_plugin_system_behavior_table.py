"""收尾方案步骤 7 验收：行为表条目全部有归属，插件页能按名字查。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.app import OperationCatalog
from lamtools_core.plugin_system import PluginHost
from lamtools_core.plugin_system.behavior_table import (
    build_behavior_table,
    query_behavior_table,
)
from lamtools_core.plugin_system.operations import register_plugin_system_operations


def test_every_backend_entry_is_module_or_kernel():
    table = build_behavior_table()
    assert table["counts"]["backend"] > 100
    for entry in table["backend"]:
        assert entry["ownership"] in {"module", "kernel"}
        assert entry["replaceable"] is (entry["ownership"] == "module")
    # 内核四样在表里且不可替换。
    by_name = {entry["module"]: entry for entry in table["backend"]}
    assert by_name["lamtools_core.plugin_system.host"]["ownership"] == "kernel"
    assert by_name["lamtools_core.plugin_system.host"]["replaceable"] is False
    # 普通模块可替换。
    assert by_name["lamtools_core.prompt"]["replaceable"] is True


def test_frontend_entries_come_from_the_base_map(tmp_path: Path):
    (tmp_path / "importmap.base.json").write_text(
        json.dumps({"imports": {"@/components/A.vue": "/assets/a.js"}}),
        encoding="utf-8",
    )
    table = build_behavior_table(tmp_path)
    assert [entry["module"] for entry in table["frontend"]] == ["@/components/A.vue"]
    assert table["frontend"][0]["replaceable"] is True


def test_query_finds_entries_by_substring():
    table = build_behavior_table()
    hits = query_behavior_table(table, "plugin_system.host")
    assert any(item["module"] == "lamtools_core.plugin_system.host" for item in hits)
    assert query_behavior_table(table, "") == []


@pytest.mark.asyncio
async def test_behavior_operation_serves_searches(tmp_path: Path):
    host = PluginHost(roots=[], state_path=tmp_path / "s.jsonc")
    catalog = OperationCatalog()
    register_plugin_system_operations(catalog, host)

    result = await catalog.execute(
        "plugin.system.behavior", {"query": "plugin_system.host"}
    )
    assert result.status == "ok"
    assert result.payload["total_matches"] >= 1
    assert any(
        entry["module"] == "lamtools_core.plugin_system.host"
        for entry in result.payload["entries"]
    )
    assert result.payload["counts"]["backend"] > 100
