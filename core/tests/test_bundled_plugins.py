"""内置插件化测试：bundled 插件根 / 装配全链（含 Workflow 与 Study）/
禁用即消失 / 不可卸载。

user:“删 v1 成单一系统”+所有断言走统一装配，不再有 assembly 过滤与
半声明合并桥。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.plugin_system.paths import bundled_plugins_dir
from lamtools_core.tool import ToolCall
from lamtools_core.tool.default_toolbox import (
    bundled_core_tool_specs,
    build_core_toolbox,
    default_core_tool_specs,
)
from lamtools_core.tool.loadtools import default_load_tools


def test_bundled_plugins_dir_has_migrated_plugins():
    root = bundled_plugins_dir()
    # user:“git 插件删掉，run_command 就能做”+git 不再是内置插件。
    assert not (root / "git").exists()
    assert (root / "websearch" / "plugin.json").exists()
    assert (root / "imagegen" / "plugin.json").exists()
    assert (root / "plan" / "plugin.json").exists()


def test_plan_skills_load_through_the_v2_assembly(tmp_path):
    from lamtools_core.plugin_system import PluginHost, PluginSystemRuntime

    host = PluginHost(
        roots=[bundled_plugins_dir()],
        state_path=tmp_path / "plugin-system.jsonc",
    )
    artifacts = PluginSystemRuntime(host).assemble(manifests=host.discover())

    names = {skill.name for skill in artifacts.skills}
    assert {"draft-plan", "refine-plan", "execute-plan"} <= names


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

    assembly = assemble_core_agent_plugins(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[],
    )
    # user:“单一插件系统”+内置根永远在扫描链路里，装配直接发现全部插件；
    # 半声明合并桥（plugin_tool_groups）已退役。
    discovered = {item.name for item in assembly["plugins"]}
    assert {"plan", "study", "workflow", "imagegen", "emotion-ball-pet"} <= discovered
    assert assembly["plugin_tool_groups"] == []
    # websearch 默认关闭，启用后才进可用集。
    enabled = {item.name for item in assembly["plugins"] if item.enabled}
    assert "websearch" not in enabled


def test_study_skills_are_scoped_by_the_real_plugin_assembly(tmp_path):
    from lamtools_core.app.base_agent import assemble_core_agent_plugins
    from lamtools_core.plugin_system import PluginHost
    from lamtools_core.plugin_system.ui import assemble_ui
    from lamtools_core.skill_runtime import create_skill_runtime

    assembly = assemble_core_agent_plugins(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[],
    )
    host = PluginHost(
        roots=[bundled_plugins_dir()],
        state_path=tmp_path / "data" / "plugin-system.jsonc",
    )
    manifests = [item for item in host.discover() if item.enabled]
    study_root = next(item.root for item in manifests if item.name == "study")
    study_roots = {(study_root / "skills").resolve(), (study_root / "future").resolve()}
    assert study_roots <= set(assembly["skill_modes"])
    assert all(assembly["skill_modes"][root] == ("study:study",) for root in study_roots)
    study_mode = next(
        mode for mode in assemble_ui(manifests).modes if mode.plugin == "study"
    )
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


def test_study_tools_are_scoped_to_the_study_mode(tmp_path):
    """study 的工具只属于学习模式：主 Agent 模式既看不见也不能执行。

    notes 是 study 的受限工具；资料库的完整能力归主 Agent 的 library 工具。
    对照组：workflow 模式未声明独占，它的工具在普通对话里照旧可用。
    """
    from lamtools_core.app.base_agent import assemble_core_agent_plugins

    assembly = assemble_core_agent_plugins(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[],
    )
    exclusive = assembly["plugin_mode_exclusive_tools"]
    study_tools = {"get_knowledge_net", "build_knowledge_net", "sign", "exam", "notes"}
    assert exclusive["study:study"] == study_tools
    assert exclusive["study"] == study_tools
    # 通用工具（read_file 等）出现在 study 模式的 tools 里，但不该被独占。
    assert "read_file" not in exclusive["study:study"]
    assert "workflow:workflow" not in exclusive

    # user:“换芯声明”+声明工具装配期已补全，直接归并即可。
    plugin_specs: list = list(assembly["plugin_runtime_specs"])

    def build(active_mode=None):
        return build_core_toolbox(
            work_root=tmp_path,
            active_mode=active_mode,
            plugin_tool_specs=plugin_specs,
            plugin_mode_tool_sets=assembly["plugin_mode_tool_sets"],
            plugin_mode_exclusive_tools=assembly["plugin_mode_exclusive_tools"],
        )

    # 注册表完整（配置面可见），但模型可见面按模式收紧。
    assert study_tools <= {spec.name for spec in build().tool_specs()}
    for mode in ("execute", None):
        exposed = {tool["function"]["name"] for tool in build(mode).model_tools(active_mode=mode)}
        assert not (study_tools & exposed), f"study 工具泄漏进 {mode} 模式: {study_tools & exposed}"
    study_exposed = {
        tool["function"]["name"] for tool in build("study:study").model_tools(active_mode="study:study")
    }
    assert study_tools <= study_exposed

    # 执行拦截：主 Agent 模式下即使模型手里有陈旧上下文也不能执行。
    blocked = build("execute").prepare_call(
        ToolCall(id="mode-notes", name="notes", arguments={"action": "list"})
    )
    assert blocked.metadata["approval"]["blocked"] is True
    assert "study:study" in blocked.metadata["approval"]["reason"]

    allowed = build("study:study").prepare_call(
        ToolCall(id="mode-notes", name="notes", arguments={"action": "list"})
    )
    assert allowed.metadata["approval"]["blocked"] is False


def test_default_assembly_toolbox_includes_bundled_plugin_tools(tmp_path):
    """默认装配包含基础工具和所有已启用内置插件的工具。

    websearch 声明默认关闭，这里先在账本里启用。
    """
    from lamtools_core.app.base_agent import assemble_core_agent_plugins
    from lamtools_core.plugin_system.state import PluginStateStore

    state_path = tmp_path / "data" / "plugin-system.jsonc"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    PluginStateStore(state_path).set_enabled("websearch", True)
    assembly = assemble_core_agent_plugins(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[],
    )
    toolbox = build_core_toolbox(
        work_root=tmp_path,
        plugin_tool_specs=list(assembly["plugin_runtime_specs"]),
    )
    names = {spec.name for spec in toolbox.tool_specs()}
    # 20 个基础工具，加 Study、Workflow、管道校验、搜索和生图。
    assert len(names) == 33
    assert "git_status" not in names
    assert "git_diff" not in names
    assert {"get_knowledge_net", "build_knowledge_net", "exam", "sign", "notes"} <= names
    assert {"web_search", "generate_image", "check_exports"} <= names
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
    search_spec = next(spec for spec in toolbox.tool_specs() if spec.name == "web_search")
    assert search_spec.permission == "auto_allow"
    assert search_spec.metadata["plugin"] == "websearch"
    # user:“换芯声明”+web_search 的描述与 schema 从核心工具表补全。
    assert search_spec.description
    assert search_spec.input_schema


def test_disable_bundled_plugin_removes_tools(tmp_path):
    from lamtools_core.plugin_system import PluginHost, PluginSystemRuntime

    host = PluginHost(
        roots=[bundled_plugins_dir()],
        state_path=tmp_path / "data" / "plugin-system.jsonc",
    )
    assert "generate_image" in {spec.name for spec in PluginSystemRuntime(host).assemble().tools}
    host.disable("imagegen")
    names = {spec.name for spec in PluginSystemRuntime(host).assemble().tools}
    assert "generate_image" not in names

async def test_bundled_plugin_executes_via_core_assembly(tmp_path):
    """内置插件 handler 由 core 显式装配（不走动态导入）。"""
    from lamtools_core.plugin_system.capabilities import PluginToolSpec
    from lamtools_core.plugin_system.runtime import _tool_spec

    spec = _tool_spec(
        PluginToolSpec(
            name="git_status",
            permission="auto_allow",
            handler="x:y",
            plugin="git",
            plugin_root=str(tmp_path),
        )
    )
    toolbox = build_core_toolbox(work_root=tmp_path, plugin_tool_specs=[spec])
    # handler 按名由 core 装配（git_status 不依赖动态导入，也不报导入错误）
    assert "git_status" not in toolbox._plugin_handler_errors
    result = await toolbox.execute(ToolCall(id="c1", name="git_status", arguments={}))
    # 非 git 仓库也可能 ok/failed——重点：不是 Unknown tool / 不是导入错误
    assert result.status in {"ok", "failed"}
    assert "Unknown tool" not in (result.error or "")


def test_bundled_plugin_uninstall_rejected(tmp_path):
    from lamtools_core.plugin_system import PluginHost

    host = PluginHost(
        roots=[bundled_plugins_dir()],
        state_path=tmp_path / "data" / "plugin-system.jsonc",
    )
    with pytest.raises(ValueError, match="bundled"):
        host.uninstall("imagegen")


# ── D5 配置迁移（websearch/imagegen 旧位置 → 插件配置） ───────────

def test_imagegen_config_migrates_to_plugin_config(tmp_path):
    from lamtools_core.config.imagegen_store import load_imagegen_config
    from lamtools_core.config.root import core_config_file
    from lamtools_core.plugin_system.plugin_data import read_plugin_config

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
    from lamtools_core.config.root import core_config_file
    from lamtools_core.plugin_system import PluginHost
    from lamtools_core.plugin_system.hooks import HookTrustStore
    from lamtools_core.plugin_system.host_operations import register_host_operations
    from lamtools_core.plugin_system.plugin_data import read_plugin_config
    from lamtools_core.skills import SkillStateStore

    legacy = core_config_file("websearch.jsonc")
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('{"provider": "baidu", "limit": 3}', encoding="utf-8")

    catalog = OperationCatalog()
    register_host_operations(
        catalog,
        PluginHost(roots=[], state_path=tmp_path / "plugin-system.jsonc"),
        work_root=tmp_path,
        data_dir=tmp_path / "data",
        skill_state_store=SkillStateStore(tmp_path / "skill_state.json"),
        skill_registry_factory=lambda: None,
        hook_trust_store=HookTrustStore(tmp_path / "hook_trust.json"),
    )
    result = await catalog.execute("websearch.config.get")
    assert result.status == "ok"
    assert "baidu" in result.payload["content"]
    migrated = read_plugin_config(tmp_path / "data", "websearch")
    assert migrated["provider"] == "baidu"


def test_websearch_plugin_is_disabled_by_default(tmp_path):
    """搜索默认关闭：清单声明 defaultEnabled=false，插件页显式开关优先。"""
    from lamtools_core.plugin_system import PluginHost

    host = PluginHost(
        roots=[bundled_plugins_dir()],
        state_path=tmp_path / "plugin-system.jsonc",
    )

    by_name = {plugin.name: plugin for plugin in host.discover()}
    assert by_name["websearch"].enabled is False
    assert by_name["imagegen"].enabled is True

    host.enable("websearch")
    assert {p.name: p for p in host.discover()}["websearch"].enabled is True

    host.disable("websearch")
    assert {p.name: p for p in host.discover()}["websearch"].enabled is False

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
