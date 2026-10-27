"""Host contracts added for the QQ bot port: agent presets + prompt waterfall."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import lamtools_core.app.base_agent as base_agent
from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent
from lamtools_core.plugin_system.agent_presets import (
    AgentPreset,
    AgentPresetRegistry,
    build_agent_preset_registry,
)
from lamtools_core.plugin_system.prompt_waterfall import (
    PromptAssembly,
    PromptContext,
    PromptSection,
    SystemPromptWaterfall,
)
from lamtools_core.runtime import RuntimeState


# ── Preset registry ────────────────────────────────────────────────────────

def test_preset_compose_fills_only_unset_values() -> None:
    registry = AgentPresetRegistry(
        [
            AgentPreset(
                id="readonly",
                mode="low",
                tools=("read_file", "search_content"),
                model="preset-model",
                prompt="只读模式",
            )
        ]
    )

    composed = registry.compose("readonly", mode="", allowed_tools=None, model="", prompt="额外")
    assert composed.preset_id == "readonly"
    assert composed.mode == "low"
    assert composed.allowed_tools == ["read_file", "search_content"]
    assert composed.model == "preset-model"
    assert composed.prompt == "额外"
    assert composed.preset_prompt == "只读模式"

    explicit = registry.compose(
        "readonly",
        mode="high",
        allowed_tools=["write_file"],
        model="explicit-model",
        prompt="",
    )
    assert explicit.mode == "high"
    assert explicit.allowed_tools == ["write_file"]
    assert explicit.model == "explicit-model"


def test_preset_registry_rejects_unknown_and_defaults() -> None:
    registry = AgentPresetRegistry([AgentPreset(id="default"), AgentPreset(id="other")])
    assert registry.default_id == "default"
    assert registry.resolve().id == "default"
    with pytest.raises(KeyError):
        registry.resolve("missing")


def test_build_preset_registry_reads_manifests_and_config(tmp_path: Path) -> None:
    enabled = SimpleNamespace(
        name="demo",
        enabled=True,
        raw={
            "agentPresets": [
                {"id": "from-plugin", "title": "Plugin preset", "mode": "low"},
                {"id": "default", "title": "Plugin default", "metadata": {"default": True}},
            ]
        },
    )
    disabled = SimpleNamespace(
        name="off",
        enabled=False,
        raw={"agentPresets": [{"id": "disabled-preset"}]},
    )
    config_dir = tmp_path / ".lam" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "agent-presets.jsonc").write_text(
        '{"presets": [{"id": "from-config", "mode": "high"}]}',
        encoding="utf-8",
    )

    registry = build_agent_preset_registry(
        [enabled, disabled],
        data_dir=tmp_path / "data",
        work_root=tmp_path,
    )

    ids = {preset.id for preset in registry.list()}
    assert ids == {"from-plugin", "default", "from-config"}
    assert registry.default_id == "default"
    assert registry.resolve("from-config").mode == "high"


# ── Prompt waterfall ───────────────────────────────────────────────────────

def test_waterfall_orders_appends_and_unregisters() -> None:
    waterfall = SystemPromptWaterfall()
    calls: list[str] = []

    def late(_context: PromptContext, assembly: PromptAssembly) -> PromptAssembly:
        calls.append("late")
        assembly.append_section("late", "LATE", order=200)
        return assembly

    def early(_context: PromptContext, assembly: PromptAssembly) -> PromptAssembly:
        calls.append("early")
        assembly.append_section("early", "EARLY", order=10)
        return assembly

    unregister = waterfall.register(late, plugin="demo", order=200)
    waterfall.register(early, plugin="demo", order=10)
    assembly = waterfall.assemble(PromptContext(), PromptAssembly(text="BASE", sections=[]))

    assert calls == ["early", "late"]
    assert assembly.text == "BASE\n\nEARLY\n\nLATE"
    assert [section.name for section in assembly.sections] == ["early", "late"]

    unregister()
    second = waterfall.assemble(PromptContext(), PromptAssembly(text="BASE", sections=[]))
    assert second.text == "BASE\n\nEARLY"
    assert waterfall.handler_count == 1


def test_waterfall_replaces_section_text() -> None:
    waterfall = SystemPromptWaterfall()

    def replace(_context: PromptContext, assembly: PromptAssembly) -> PromptAssembly:
        assembly.replace_section("identity", "NEW IDENTITY")
        return assembly

    waterfall.register(replace)
    assembly = PromptAssembly(
        text="BASE\n\nOLD IDENTITY",
        sections=[PromptSection(name="identity", order=1, text="OLD IDENTITY")],
    )
    result = waterfall.assemble(PromptContext(), assembly)
    assert result.text == "BASE\n\nNEW IDENTITY"
    assert result.sections[0].text == "NEW IDENTITY"


def test_waterfall_rejects_async_handlers() -> None:
    waterfall = SystemPromptWaterfall()

    async def handler(_context: PromptContext, assembly: PromptAssembly) -> PromptAssembly:
        return assembly

    waterfall.register(handler, plugin="bad")
    with pytest.raises(TypeError, match="synchronous"):
        waterfall.assemble(PromptContext(), PromptAssembly(text="BASE"))


# ── CoreBaseAgentKit integration ───────────────────────────────────────────

class _Toolbox:
    load_tools = None

    def tool_specs(self):
        return []

    def model_tools(self, active_mode=None):
        return []

    def skill_index(self):
        return ""


def _kit(tmp_path: Path, waterfall: SystemPromptWaterfall | None) -> CoreBaseAgentKit:
    kit = CoreBaseAgentKit(
        work_root=tmp_path,
        config=CoreBaseAgentConfig(instructions="BASE INSTRUCTIONS"),
        toolbox=_Toolbox(),  # type: ignore[arg-type]
        prompt_waterfall=waterfall,
    )
    kit._cached_subagent_guide = lambda: ""  # type: ignore[method-assign]
    kit._cached_subagent_roles = lambda: ""  # type: ignore[method-assign]
    kit._cached_subagent_strategy = lambda: ""  # type: ignore[method-assign]
    kit._build_project_context_parts = lambda: []  # type: ignore[method-assign]
    return kit


def test_kit_runs_prompt_waterfall_and_tracks_section(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(base_agent, "command_shell_prompt", lambda: "[Shell]")
    waterfall = SystemPromptWaterfall()

    def handler(context: PromptContext, assembly: PromptAssembly) -> PromptAssembly:
        assert context.agent_name == "qq_demo"
        assembly.append_section("qqbot:scope-prompt", "GROUP PROMPT", order=90)
        return assembly

    waterfall.register(handler, plugin="qq-bot")
    kit = _kit(tmp_path, waterfall)
    state = RuntimeState(
        session_id="plugin-sub-agent:sub:qq_demo",
        metadata={
            "work_root": str(tmp_path),
            "turn_id": "turn-1",
            "actor_kind": "sub_agent",
            "delegated_session": {"agent": "qq_demo"},
        },
    )

    system_prompt, blocks = kit._compose_system_prompt(
        state,
        study_mode=False,
        effective_instructions="BASE INSTRUCTIONS",
    )

    assert "BASE INSTRUCTIONS" in system_prompt
    assert "GROUP PROMPT" in system_prompt
    assert any(block.key == "qqbot:scope-prompt" for block in blocks)


def test_kit_without_waterfall_is_unchanged(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(base_agent, "command_shell_prompt", lambda: "[Shell]")
    kit = _kit(tmp_path, None)
    state = RuntimeState(session_id="s", metadata={"work_root": str(tmp_path), "turn_id": "t"})
    system_prompt, blocks = kit._compose_system_prompt(
        state,
        study_mode=False,
        effective_instructions="BASE INSTRUCTIONS",
    )
    assert "BASE INSTRUCTIONS" in system_prompt
    assert all(block.key != "qqbot:scope-prompt" for block in blocks)


# ── Runner preset application ──────────────────────────────────────────────

class _ScriptedLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("runner should stream")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        yield LLMStreamEvent(kind="content_delta", content="done")
        yield LLMStreamEvent(kind="done")


async def test_runner_applies_agent_preset(tmp_path: Path) -> None:
    from lamtools_core.runtime import InMemoryRuntimeStateStore
    from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner

    llm = _ScriptedLLM()
    registry = AgentPresetRegistry(
        [
            AgentPreset(
                id="readonly",
                mode="low",
                tools=("read_file",),
                model="preset-model",
                prompt="PRESET PROMPT",
            )
        ]
    )
    runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=llm,
        model_id="base-model",
        state_store=InMemoryRuntimeStateStore(),
        agent_presets=registry,
    )

    result = await runner.run(task="inspect", agent="demo", preset="readonly")

    assert result.decision == "done"
    assert llm.requests
    request = llm.requests[0]
    assert request.model == "preset-model"
    assert "PRESET PROMPT" in str(request.messages[0].content)
    tool_names = {tool.get("function", {}).get("name") or tool.get("name") for tool in request.tools}
    assert "read_file" in tool_names
    assert "write_file" not in tool_names
    state = await runner.state_store.get(result.session_id)
    assert state is not None
    assert state.metadata.get("agent_preset") == "readonly"


async def test_runner_rejects_unknown_preset(tmp_path: Path) -> None:
    from lamtools_core.runtime import InMemoryRuntimeStateStore
    from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner

    runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=_ScriptedLLM(),
        model_id="base-model",
        state_store=InMemoryRuntimeStateStore(),
        agent_presets=AgentPresetRegistry([]),
    )
    with pytest.raises(ValueError, match="unknown agent preset"):
        await runner.run(task="inspect", agent="demo", preset="missing")


async def test_preset_list_operation_exposes_host_registry(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from lamtools_core.app import OperationCatalog
    from lamtools_core.plugin_system import PluginContext, PluginHost
    from lamtools_core.plugin_system.operations import register_plugin_system_operations

    host = PluginHost(roots=[tmp_path / "plugins"], state_path=tmp_path / "state.json")
    context = PluginContext(work_root=tmp_path, data_dir=tmp_path)
    context.set_service(
        "agent_presets",
        AgentPresetRegistry(
            [
                AgentPreset(id="readonly", title="Read only", mode="low", tools=("read_file",), plugin="demo"),
                AgentPreset(id="default", title="Default", metadata={"default": True}),
            ]
        ),
    )
    host.backend_manager = SimpleNamespace(context=context)
    catalog = OperationCatalog()
    register_plugin_system_operations(catalog, host)

    result = await catalog.execute("plugin.system.presets.list", {})

    assert result.status == "ok"
    assert result.payload["default"] == "default"
    assert [item["id"] for item in result.payload["presets"]] == ["default", "readonly"]
    assert result.payload["presets"][1]["tools"] == ["read_file"]
