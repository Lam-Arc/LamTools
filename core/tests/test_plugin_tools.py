"""S1 核心链路测试：tools.jsonc 解析 / spec 补全 / jsonc 迁移 /
manifest_version / 工具注入与惰性暴露 / 冲突 / timeout / handler 导入失败 /
skill 禁用检查。
"""
from __future__ import annotations

import json
import sys
import types

import pytest

from lamtools_core.plugins.registry import PluginRegistry, PluginStateStore
from lamtools_core.plugins.tools import complete_plugin_tool_specs, load_plugin_tools
from lamtools_core.tool import ToolCall
from lamtools_core.tool.default_toolbox import build_core_toolbox
from lamtools_core.tool.permission import ASK_USER, AUTO_ALLOW, HARD_BLOCK


# ── 动态导入用的 handler 模块（sys.modules 注入，避免 tests 包导入问题） ──

async def _echo_handler(call: ToolCall):
    args = call.arguments if isinstance(call.arguments, dict) else {}
    return type("R", (), {"call_id": call.id, "name": call.name, "status": "ok",
                          "content": f"echo:{args.get('value', '')}", "error": "",
                          "artifacts": [], "usage": None, "metadata": {}})()


async def _slow_handler(call: ToolCall):
    import asyncio

    await asyncio.sleep(0.2)
    return type("R", (), {"call_id": call.id, "name": call.name, "status": "ok",
                          "content": "slow-done", "error": "", "artifacts": [],
                          "usage": None, "metadata": {}})()


@pytest.fixture(scope="module", autouse=True)
def _register_handler_module():
    mod = types.ModuleType("plugin_test_handlers")
    mod.echo_tool = _echo_handler
    mod.slow_tool = _slow_handler
    sys.modules["plugin_test_handlers"] = mod
    yield
    sys.modules.pop("plugin_test_handlers", None)


def _tool_result(result) -> str:
    return str(getattr(result, "content", "") or "")


def _write_tools(tmp_path, tools_list: list[dict]) -> list:
    """写 tools.jsonc 并返回 tool_files 列表。"""
    tool_file = tmp_path / "tools" / "tools.jsonc"
    tool_file.parent.mkdir(parents=True, exist_ok=True)
    tool_file.write_text(json.dumps({"tools": tools_list}, indent=2), encoding="utf-8")
    return [tool_file]


def _manifest(tmp_path, *, name="demo-plugin", **extra) -> dict:
    data = {"name": name, "version": "0.1.0", **extra}
    manifest_path = tmp_path / name / "plugin.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return manifest_path.parent


# ── tools.jsonc 解析 ──────────────────────────────────────────────

def test_load_plugin_tools_valid(tmp_path):
    files = _write_tools(
        tmp_path,
        [
            {
                "name": "rag_search",
                "description": "search",
                "permission": "auto_allow",
                "visibility": "on_load",
                "skill": "rag-for-agent",
                "handler": "plugin_test_handlers:echo_tool",
                "timeout": 30,
            },
            {"name": "plain_tool", "handler": "plugin_test_handlers:echo_tool"},
        ],
    )
    tools = load_plugin_tools(files, plugin_root=tmp_path)
    assert [t.name for t in tools] == ["rag_search", "plain_tool"]
    assert tools[0].permission == "auto_allow"
    assert tools[0].visibility == "on_load"
    assert tools[0].skill == "rag-for-agent"
    assert tools[0].timeout == 30
    # 缺省：安全默认 ask_user / always
    assert tools[1].permission == "ask_user"
    assert tools[1].visibility == "always"


def test_load_plugin_tools_validation(tmp_path):
    # handler 必填
    with pytest.raises(ValueError, match="handler"):
        load_plugin_tools(_write_tools(tmp_path, [{"name": "x"}]), plugin_root=tmp_path)
    # permission 枚举
    with pytest.raises(ValueError, match="permission"):
        load_plugin_tools(
            _write_tools(tmp_path, [{"name": "x", "handler": "a:b", "permission": "banana"}]),
            plugin_root=tmp_path,
        )
    # visibility 枚举
    with pytest.raises(ValueError, match="visibility"):
        load_plugin_tools(
            _write_tools(tmp_path, [{"name": "x", "handler": "a:b", "visibility": "sometimes"}]),
            plugin_root=tmp_path,
        )
    # on_load 必须带 skill
    with pytest.raises(ValueError, match="skill"):
        load_plugin_tools(
            _write_tools(tmp_path, [{"name": "x", "handler": "a:b", "visibility": "on_load"}]),
            plugin_root=tmp_path,
        )
    # 重复工具名
    with pytest.raises(ValueError, match="duplicate"):
        load_plugin_tools(
            _write_tools(
                tmp_path,
                [{"name": "x", "handler": "a:b"}, {"name": "x", "handler": "a:b"}],
            ),
            plugin_root=tmp_path,
        )
    # timeout 非法
    with pytest.raises(ValueError, match="timeout"):
        load_plugin_tools(
            _write_tools(tmp_path, [{"name": "x", "handler": "a:b", "timeout": -1}]),
            plugin_root=tmp_path,
        )


# ── spec 补全（半声明式） ─────────────────────────────────────────

def test_complete_plugin_tool_specs_half_declarative():
    from lamtools_core.plugins.models import PluginToolSpec

    declared = [
        PluginToolSpec(name="git_status", handler="a:b", permission="auto_allow"),
    ]
    base = {
        "git_status": types.SimpleNamespace(
            description="Run git status in the workspace.",
            input_schema={"type": "object"},
            output_schema={},
            metadata={"failure_modes": [{"type": "x", "message": "boom"}], "recovery": "try again"},
        )
    }
    specs = complete_plugin_tool_specs(
        declared, plugin_name="git-plugin", plugin_root="C:/x", base_specs_by_name=base
    )
    assert len(specs) == 1
    spec = specs[0]
    assert spec.description == "Run git status in the workspace."
    assert spec.input_schema == {"type": "object"}
    assert spec.permission == "auto_allow"  # 声明优先，不继承 base
    assert spec.metadata["plugin"] == "git-plugin"
    assert spec.metadata["category"] == "plugin"
    assert spec.metadata["visibility"] == "always"
    assert spec.metadata["failure_modes"] == [{"type": "x", "message": "boom"}]
    assert spec.metadata["recovery"] == "try again"


# ── PluginStateStore jsonc 迁移 ───────────────────────────────────

def test_state_store_migrates_legacy_json(tmp_path):
    legacy = tmp_path / "plugins.json"
    legacy.write_text(json.dumps({"plugins": {"old-p": {"enabled": False}}}), encoding="utf-8")
    store = PluginStateStore(tmp_path / "plugins.jsonc")
    assert store.is_enabled("old-p") is False
    # 读旧 json 即触发迁移写 jsonc
    assert (tmp_path / "plugins.jsonc").exists()
    # 写操作落在 jsonc，旧 json 保留
    store.set_enabled("new-p", True)
    data = json.loads((tmp_path / "plugins.jsonc").read_text(encoding="utf-8-sig"))
    assert data["plugins"]["new-p"]["enabled"] is True
    assert legacy.exists()


def test_state_store_jsonc_with_comments(tmp_path):
    target = tmp_path / "plugins.jsonc"
    target.write_text('// 注释\n{"plugins": {"p": {"enabled": true,},}}', encoding="utf-8")
    store = PluginStateStore(target)
    assert store.is_enabled("p") is True


# ── manifest_version / discover 错误可见（E6） ────────────────────

def test_manifest_version_rejected(tmp_path, tmp_path_factory):
    bad = _manifest(tmp_path, name="old-style", manifest_version="2")
    good = _manifest(tmp_path, name="ok-style")
    registry = PluginRegistry(plugin_roots=[tmp_path])
    plugins = registry.discover()
    assert [p.name for p in plugins] == ["ok-style"]
    assert [e["name"] for e in registry.discover_errors] == ["old-style"]
    assert "unsupported manifest_version" in registry.discover_errors[0]["error"]


def test_manifest_new_fields_parsed(tmp_path):
    plugin_root = _manifest(tmp_path, name="rich")
    tools_dir = plugin_root / "tools"
    tools_dir.mkdir()
    (tools_dir / "tools.jsonc").write_text('{"tools": []}', encoding="utf-8")
    schema_dir = plugin_root / "config"
    schema_dir.mkdir()
    (schema_dir / "schema.jsonc").write_text('{}', encoding="utf-8")
    manifest_path = plugin_root / "plugin.json"
    manifest_path.write_text(
        json.dumps(
            {
                "name": "rich",
                "version": "1.0.0",
                "tools": ["./tools/tools.jsonc"],
                "dependencies": ["sqlite-vec>=0.1.9"],
                "configSchema": "./config/schema.jsonc",
            }
        ),
        encoding="utf-8",
    )
    registry = PluginRegistry(plugin_roots=[tmp_path])
    plugin = registry.discover()[0]
    assert [str(p) for p in plugin.tool_files] == [str(tools_dir / "tools.jsonc")]
    assert plugin.dependencies == ["sqlite-vec>=0.1.9"]
    assert plugin.config_schema == schema_dir / "schema.jsonc"


# ── 工具注入集成（注入 → 模型可见 → 执行 → 权限） ─────────────────

def _make_toolbox(tmp_path, declared_tools, *, approval_policy="require", **kwargs):
    from lamtools_core.plugins.tools import complete_plugin_tool_specs

    specs = complete_plugin_tool_specs(
        declared_tools, plugin_name="demo", plugin_root=tmp_path
    )
    return build_core_toolbox(
        work_root=tmp_path,
        approval_policy=approval_policy,
        plugin_tool_specs=specs,
        **kwargs,
    )


async def test_plugin_tool_injected_and_executed(tmp_path):
    from lamtools_core.plugins.models import PluginToolSpec

    toolbox = _make_toolbox(
        tmp_path,
        [
            PluginToolSpec(
                name="echo_tool",
                description="echo a value",
                input_schema={"type": "object", "properties": {"value": {"type": "string"}}},
                permission="auto_allow",
                handler="plugin_test_handlers:echo_tool",
            )
        ],
    )
    names = {item["function"]["name"] for item in toolbox.model_tools()}
    assert "echo_tool" in names
    result = await toolbox.execute(ToolCall(id="c1", name="echo_tool", arguments={"value": "hello"}))
    assert result.status == "ok"
    assert _tool_result(result) == "echo:hello"


def test_plugin_tool_permission_ask_user_requires_approval(tmp_path):
    from lamtools_core.plugins.models import PluginToolSpec

    toolbox = _make_toolbox(
        tmp_path,
        [PluginToolSpec(name="echo_tool", permission="ask_user", handler="plugin_test_handlers:echo_tool")],
        approval_policy="require",
    )
    call = ToolCall(id="c1", name="echo_tool", arguments={"value": "x"})
    call = toolbox.prepare_call(call)
    assert call.requires_approval is True


def test_plugin_tool_hard_block_skipped(tmp_path):
    from lamtools_core.plugins.models import PluginToolSpec

    toolbox = _make_toolbox(
        tmp_path,
        [PluginToolSpec(name="evil_tool", permission="hard_block", handler="plugin_test_handlers:echo_tool")],
    )
    assert "evil_tool" not in {item["function"]["name"] for item in toolbox.model_tools()}
    # 注册进 tool_permissions 但 ApprovalGate 对 hard_block 直接拦
    call = toolbox.prepare_call(ToolCall(id="c1", name="evil_tool", arguments={}))
    assert call.requires_approval is False
    decision = toolbox.approval_gate.check("evil_tool", {})
    assert decision.blocked is True
    assert decision.permission_tier == HARD_BLOCK


# ── 惰性暴露（visibility=on_load） ────────────────────────────────

async def test_on_load_tool_hidden_until_skill_loaded(tmp_path):
    from lamtools_core.plugins.models import PluginToolSpec

    # 构造一个真实可加载的 skill（SKILL.md）
    skills_root = tmp_path / "skills" / "rag-for-agent"
    skills_root.mkdir(parents=True)
    (skills_root / "SKILL.md").write_text(
        "---\nname: rag-for-agent\ndescription: RAG 查询\n---\n检索协议",
        encoding="utf-8",
    )
    from lamtools_core.skills import SkillRegistry

    registry = SkillRegistry(explicit_roots=[tmp_path / "skills"])
    toolbox = build_core_toolbox(
        work_root=tmp_path,
        skill_registry=registry,
        plugin_tool_specs=complete_plugin_tool_specs(
            [
                PluginToolSpec(
                    name="rag_search",
                    permission="auto_allow",
                    visibility="on_load",
                    skill="rag-for-agent",
                    handler="plugin_test_handlers:echo_tool",
                )
            ],
            plugin_name="demo",
            plugin_root=tmp_path,
        ),
    )
    visible = {item["function"]["name"] for item in toolbox.model_tools()}
    assert "rag_search" not in visible  # 加载前不可见

    result = await toolbox.execute(ToolCall(id="c1", name="load_skill", arguments={"name": "rag-for-agent"}))
    assert result.status == "ok"
    visible_after = {item["function"]["name"] for item in toolbox.model_tools()}
    assert "rag_search" in visible_after  # 加载后可见


# ── 冲突 / timeout / handler 导入失败 ─────────────────────────────

def test_plugin_tool_name_conflict(tmp_path):
    from lamtools_core.plugins.models import PluginToolSpec

    toolbox = _make_toolbox(
        tmp_path,
        [PluginToolSpec(name="read_file", permission="auto_allow", handler="plugin_test_handlers:echo_tool")],
    )
    assert "read_file" not in {s.name for s in toolbox.plugin_tool_specs}
    assert "read_file" in toolbox._plugin_conflicts
    # 冲突工具不进模型可见列表（core 自己的 read_file 仍在）
    names = {item["function"]["name"] for item in toolbox.model_tools()}
    assert "read_file" in names  # core 工具不受影响


async def test_plugin_tool_timeout(tmp_path):
    from lamtools_core.plugins.models import PluginToolSpec

    toolbox = _make_toolbox(
        tmp_path,
        [
            PluginToolSpec(
                name="slow_tool",
                permission="auto_allow",
                handler="plugin_test_handlers:slow_tool",
                timeout=0.05,
            )
        ],
    )
    result = await toolbox.execute(ToolCall(id="c1", name="slow_tool", arguments={}))
    assert result.status == "failed"
    assert "timed out" in (result.error or "")


async def test_plugin_handler_import_failure(tmp_path):
    from lamtools_core.plugins.models import PluginToolSpec

    toolbox = _make_toolbox(
        tmp_path,
        [
            PluginToolSpec(
                name="broken_tool",
                permission="auto_allow",
                handler="no_such_module:no_such_fn",
            )
        ],
    )
    assert "broken_tool" in toolbox._plugin_handler_errors
    result = await toolbox.execute(ToolCall(id="c1", name="broken_tool", arguments={}))
    assert result.status == "blocked"
    assert "Unknown tool" in (result.error or "")


# ── skill 禁用检查（缺口 #1） ─────────────────────────────────────

async def test_load_skill_disabled_rejected(tmp_path):
    from lamtools_core.skills import SkillRegistry, SkillStateStore

    skills_root = tmp_path / "skills" / "demo-skill"
    skills_root.mkdir(parents=True)
    (skills_root / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: demo\n---\ncontent",
        encoding="utf-8",
    )
    state_store = SkillStateStore(tmp_path / "skill_state.json")
    state_store.set_enabled("demo-skill", False)
    toolbox = build_core_toolbox(
        work_root=tmp_path,
        skill_registry=SkillRegistry(explicit_roots=[tmp_path / "skills"]),
        skill_state_store=state_store,
    )
    result = await toolbox.execute(ToolCall(id="c1", name="load_skill", arguments={"name": "demo-skill"}))
    assert result.status == "failed"
    assert "disabled" in (result.error or "")


# ── 用户权限覆盖（E3） ────────────────────────────────────────────

def test_permission_overrides_win(tmp_path):
    from lamtools_core.plugins.models import PluginToolSpec

    toolbox = _make_toolbox(
        tmp_path,
        [PluginToolSpec(name="echo_tool", permission="auto_allow", handler="plugin_test_handlers:echo_tool")],
        permission_overrides={"echo_tool": "ask_user"},
    )
    call = toolbox.prepare_call(ToolCall(id="c1", name="echo_tool", arguments={}))
    assert call.requires_approval is True




# ── 验收 #2：access_tools 档位对插件工具生效 ─────────────────────

def test_plugin_tool_respects_access_tier(tmp_path):
    """read_only 档位：不在 access 列表的插件工具需审批；在列表的免审。"""
    from lamtools_core.plugins.models import PluginToolSpec

    tier_tools = {"read_only": {"echo_tool"}, "limited_edit": set(), "full_edit": set()}
    toolbox = build_core_toolbox(
        work_root=tmp_path,
        approval_policy="require",
        active_tier="read_only",
        tier_tools=tier_tools,
        plugin_tool_specs=complete_plugin_tool_specs(
            [
                PluginToolSpec(name="echo_tool", permission="ask_user", handler="plugin_test_handlers:echo_tool"),
                PluginToolSpec(name="other_tool", permission="ask_user", handler="plugin_test_handlers:echo_tool"),
            ],
            plugin_name="demo",
            plugin_root=tmp_path,
        ),
    )
    # 在 read_only access 列表 → 免审
    call = toolbox.prepare_call(ToolCall(id="c1", name="echo_tool", arguments={}))
    assert call.requires_approval is False
    # 不在列表 → 需审批
    call2 = toolbox.prepare_call(ToolCall(id="c2", name="other_tool", arguments={}))
    assert call2.requires_approval is True
