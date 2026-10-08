"""内置插件化测试：bundled 插件根 / 装配全链（含 Workflow 与 Study）/
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
from lamtools_core.tool.loadtools import default_load_tools


def test_bundled_plugins_dir_has_three_plugins():
    root = bundled_plugins_dir()
    assert (root / "git" / "plugin.json").exists()
    assert (root / "websearch" / "plugin.json").exists()
    assert (root / "imagegen" / "plugin.json").exists()


def test_bundled_core_tool_specs_four_tools():
    names = {spec.name for spec in bundled_core_tool_specs()}
    assert names == {"git_status", "git_diff", "web_search", "generate_image"}
    # Includes the existing mcp_activate tool in the current base set.
    base = {spec.name for spec in default_core_tool_specs()}
    assert len(base) == 20
    assert 'mcp_activate' in base
    assert 'memory' in base
    assert 'library' in base
    assert not (base & names)  # 互斥


def test_assemble_discovers_bundled_plugins(tmp_path):
    from lamtools_core.app.base_agent import assemble_core_agent_plugins
    from lamtools_core.plugins.registry import PluginStateStore

    assembly = assemble_core_agent_plugins(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[],
    )
    names = {plugin.name for plugin in assembly["plugins"]}
    # websearch 声明 defaultEnabled=false：默认装配里不出现（要用去插件页启用），
    # 显式启用后回到装配结果里。
    assert {"git", "imagegen"} <= names
    assert "websearch" not in names
    group_names = {group["name"] for group in assembly["plugin_tool_groups"]}
    assert {"git", "imagegen"} <= group_names
    assert "websearch" not in group_names

    PluginStateStore(tmp_path / "data" / "plugins.jsonc").set_enabled("websearch", True)
    enabled = assemble_core_agent_plugins(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[],
    )
    enabled_names = {plugin.name for plugin in enabled["plugins"]}
    assert "websearch" in enabled_names
    assert "websearch" in {group["name"] for group in enabled["plugin_tool_groups"]}


def test_study_skills_are_scoped_by_the_real_plugin_assembly(tmp_path):
    from lamtools_core.app.base_agent import assemble_core_agent_plugins
    from lamtools_core.skill_runtime import create_skill_runtime

    assembly = assemble_core_agent_plugins(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[],
    )
    study = next(plugin for plugin in assembly["plugins"] if plugin.id == "study")
    assert len(study.skill_roots) == 2
    assert all(study.skill_modes[root] == ("study:study",) for root in study.skill_roots)
    study_mode = next(mode for mode in study.ui.modes if mode.id == "study")
    assert "load_skill" in study_mode.tools

    runtime = create_skill_runtime(
        plugin_skill_roots=assembly["skill_roots"],
        plugin_skill_modes=assembly["skill_modes"],
    )
    assert "build-map" not in runtime.registry.prompt_index(tmp_path, active_mode="execute")
    assert runtime.registry.load_prompt_content(
        tmp_path, "teach", active_mode="execute"
    ).startswith('Skill "teach" not found')
    assert "build-map" in runtime.registry.prompt_index(tmp_path, active_mode="study:study")
    assert "curate-notes" in runtime.registry.prompt_index(tmp_path, active_mode="study:study")
    toolbox = build_core_toolbox(
        work_root=tmp_path,
        active_mode="study:study",
        load_tools=default_load_tools(),
        plugin_mode_tool_sets=assembly["plugin_mode_tool_sets"],
        skill_registry=runtime.registry,
    )
    exposed = {
        tool["function"]["name"]
        for tool in toolbox.model_tools(active_mode="study:study")
    }
    assert "load_skill" in exposed


def test_default_assembly_toolbox_includes_bundled_plugin_tools(tmp_path):
    """默认装配包含基础工具和所有已启用 bundled plugin 工具。

    websearch 默认关闭，这里先显式启用，覆盖"启用后工具确实回到工具箱"。
    """
    from lamtools_core.app.base_agent import assemble_core_agent_plugins
    from lamtools_core.plugins.registry import PluginStateStore

    PluginStateStore(tmp_path / "data" / "plugins.jsonc").set_enabled("websearch", True)
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
    # 20 base + 4 bundled + 5 Workflow + 5 Study tools; the plan plugin ships
    # skills only — plans are files in the project's 「方案/」 folder.
    assert len(names) == 34
    assert {'get_knowledge_net', 'build_knowledge_net', 'exam', 'sign', 'notes'} <= names
    assert {"git_status", "git_diff", "web_search", "generate_image"} <= names
    assert "plan_package" not in names
    assert {
        "workflow_graph",
        "workflow_add_node",
        "workflow_connect",
        "workflow_delete_node",
        "workflow_update_node",
    } <= names
    study_build = next(spec for spec in toolbox.tool_specs() if spec.name == "build_knowledge_net")
    operations_schema = study_build.input_schema["properties"]["operations"]
    assert operations_schema["minItems"] == 1
    assert operations_schema["maxItems"] == 100
    assert "build-map" in study_build.description
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


def test_websearch_plugin_is_disabled_by_default(tmp_path):
    """搜索默认关闭：清单声明 defaultEnabled=false，插件页显式开关优先。"""
    from lamtools_core.plugins.registry import PluginRegistry, PluginStateStore

    state_path = tmp_path / "plugins.jsonc"
    store = PluginStateStore(state_path)
    registry = PluginRegistry(plugin_roots=[bundled_plugins_dir()], state_store=store)

    by_name = {plugin.name: plugin for plugin in registry.discover()}
    assert by_name["websearch"].enabled is False
    # 其它内置插件不受影响
    assert by_name["git"].enabled is True
    assert by_name["imagegen"].enabled is True

    store.set_enabled("websearch", True)
    by_name = {plugin.name: plugin for plugin in registry.discover()}
    assert by_name["websearch"].enabled is True

    store.set_enabled("websearch", False)
    by_name = {plugin.name: plugin for plugin in registry.discover()}
    assert by_name["websearch"].enabled is False


def test_unsupported_search_kernel_does_not_break_the_toolbox(tmp_path, monkeypatch):
    """配置里写了不支持的内核名 → 工具箱照常装配（降级到内置默认内核）。

    2026-09-26 事故：websearch.jsonc 里 provider=custom 让 build_core_toolbox
    抛 ValueError，每一轮对话都在启动阶段失败。
    """
    config = tmp_path / "websearch.jsonc"
    config.write_text('{"provider": "custom"}', encoding="utf-8")
    monkeypatch.setenv("WEBSEARCH_CONFIG", str(config))

    toolbox = build_core_toolbox(work_root=tmp_path, data_dir=tmp_path / "data")

    assert "web_search" in toolbox._handlers
