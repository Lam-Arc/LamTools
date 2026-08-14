"""S3 内置插件化测试：bundled 插件根 / 装配全链（基础 15 + 内置 4）/
禁用即消失 / 不可卸载。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.plugins.registry import bundled_plugins_dir
from lamtools_core.plugins.tools import complete_plugin_tool_specs
from lamtools_core.tool import ToolCall
from lamtools_core.tool.default_toolbox import (
    bundled_core_tool_specs,
    build_core_toolbox,
    default_core_tool_specs,
)


def test_bundled_plugins_dir_has_three_plugins():
    root = bundled_plugins_dir()
    assert (root / "git" / "plugin.json").exists()
    assert (root / "websearch" / "plugin.json").exists()
    assert (root / "imagegen" / "plugin.json").exists()


def test_bundled_core_tool_specs_four_tools():
    names = {spec.name for spec in bundled_core_tool_specs()}
    assert names == {"git_status", "git_diff", "web_search", "generate_image"}
    # 基础集 15（D1 共识定界）
    base = {spec.name for spec in default_core_tool_specs()}
    assert len(base) == 15
    assert not (base & names)  # 互斥


def test_assemble_discovers_bundled_plugins(tmp_path):
    from lamtools_core.app.base_agent import assemble_core_agent_plugins

    assembly = assemble_core_agent_plugins(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[],
    )
    names = {plugin.name for plugin in assembly["plugins"]}
    assert {"git", "websearch", "imagegen"} <= names
    group_names = {group["name"] for group in assembly["plugin_tool_groups"]}
    assert {"git", "websearch", "imagegen"} <= group_names


def test_default_assembly_toolbox_19_tools(tmp_path):
    """默认装配 = 基础 15 + 内置插件 4（D6 验收）。"""
    from lamtools_core.app.base_agent import assemble_core_agent_plugins

    assembly = assemble_core_agent_plugins(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[],
    )
    base_specs = {spec.name: spec for spec in [*default_core_tool_specs(), *bundled_core_tool_specs()]}
    plugin_specs: list = []
    for group in assembly["plugin_tool_groups"]:
        plugin_specs.extend(
            complete_plugin_tool_specs(
                group["tools"],
                plugin_name=group["name"],
                plugin_root=group["root"],
                base_specs_by_name=base_specs,
            )
        )
    toolbox = build_core_toolbox(work_root=tmp_path, plugin_tool_specs=plugin_specs)
    names = {spec.name for spec in toolbox.tool_specs()}
    assert len(names) == 19
    assert {"git_status", "git_diff", "web_search", "generate_image"} <= names
    # 半声明式补全：内置插件工具描述从 core 常量来
    git_spec = next(spec for spec in toolbox.tool_specs() if spec.name == "git_status")
    assert "git status" in git_spec.description.lower()
    assert git_spec.permission == "auto_allow"
    assert git_spec.metadata["plugin"] == "git"


def test_disable_bundled_plugin_removes_tools(tmp_path):
    from lamtools_core.app.base_agent import assemble_core_agent_plugins
    from lamtools_core.plugins.registry import PluginStateStore

    state = PluginStateStore(tmp_path / "data" / "plugins.jsonc")
    state.set_enabled("git", False)
    assembly = assemble_core_agent_plugins(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[],
    )
    names = {plugin.name for plugin in assembly["plugins"]}
    assert "git" not in names
    group_names = {group["name"] for group in assembly["plugin_tool_groups"]}
    assert "git" not in group_names


async def test_bundled_plugin_executes_via_core_assembly(tmp_path):
    """内置插件 handler 由 core 显式装配（不走动态导入）。"""
    from lamtools_core.plugins.models import PluginToolSpec

    base_specs = {spec.name: spec for spec in bundled_core_tool_specs()}
    specs = complete_plugin_tool_specs(
        [PluginToolSpec(name="git_status", permission="auto_allow", handler="x:y")],
        plugin_name="git",
        plugin_root=tmp_path,
        base_specs_by_name=base_specs,
    )
    toolbox = build_core_toolbox(work_root=tmp_path, plugin_tool_specs=specs)
    # handler 按名由 core 装配（git_status 不依赖动态导入，也不报导入错误）
    assert "git_status" not in toolbox._plugin_handler_errors
    result = await toolbox.execute(ToolCall(id="c1", name="git_status", arguments={}))
    # 非 git 仓库也可能 ok/failed——重点：不是 Unknown tool / 不是导入错误
    assert result.status in {"ok", "failed"}
    assert "Unknown tool" not in (result.error or "")


async def test_bundled_plugin_uninstall_rejected(tmp_path):
    from lamtools_core.app.base_agent import build_core_plugin_operation_catalog

    catalog = build_core_plugin_operation_catalog(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[],
    )
    result = await catalog.execute("plugin.uninstall", {"name": "git"})
    assert result.status == "error"
    assert "bundled" in result.payload["error"]


# ── D5 配置迁移（websearch/imagegen 旧位置 → 插件配置） ───────────

def test_imagegen_config_migrates_to_plugin_config(tmp_path):
    from lamtools_core.config.imagegen_store import load_imagegen_config
    from lamtools_core.config.root import core_config_file
    from lamtools_core.plugins.config_store import read_plugin_config

    legacy = core_config_file("imagegen.jsonc")
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('{"enabled": true, "api_url": "https://img.example.com"}', encoding="utf-8")

    loaded = load_imagegen_config(data_dir=tmp_path / "data")
    assert loaded == {"enabled": True, "api_url": "https://img.example.com"}
    # 迁移写新位置
    migrated = read_plugin_config(tmp_path / "data", "imagegen")
    assert migrated["enabled"] is True
    # 旧文件保留（不删）
    assert legacy.exists()
    # 二次读取走新位置（幂等）
    loaded_again = load_imagegen_config(data_dir=tmp_path / "data")
    assert loaded_again["api_url"] == "https://img.example.com"


async def test_websearch_config_get_migrates_legacy(tmp_path):
    from lamtools_core.app import OperationCatalog
    from lamtools_core.plugins.config_store import read_plugin_config
    from lamtools_core.plugins.operations import build_plugin_operation_catalog
    from lamtools_core.plugins.registry import PluginRegistry, PluginStateStore

    legacy = __import__("lamtools_core.config.root", fromlist=["core_config_file"]).core_config_file("websearch.jsonc")
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('{"provider": "baidu", "limit": 3}', encoding="utf-8")

    catalog = build_plugin_operation_catalog(
        plugin_registry=PluginRegistry(plugin_roots=[]),
        plugin_state_store=PluginStateStore(tmp_path / "plugin-state.json"),
        hook_registry_factory=lambda: None,
        hook_trust_store=type("T", (), {"untrust": lambda self, h: None})(),
        data_dir=tmp_path / "data",
    )
    result = await catalog.execute("websearch.config.get")
    assert result.status == "ok"
    assert "baidu" in result.payload["content"]
    migrated = read_plugin_config(tmp_path / "data", "websearch")
    assert migrated["provider"] == "baidu"
