"""Live wiring: a v2 agent plan replaces the prompt and adds context."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
from lamtools_core.plugin_system.agent import PluginAgentSpec


def make_kit(
    tmp_path: Path,
    *,
    agents: list[PluginAgentSpec] | None = None,
    context_files: list[dict] | None = None,
) -> CoreBaseAgentKit:
    kit = object.__new__(CoreBaseAgentKit)
    kit.work_root = tmp_path.resolve()
    kit.config = CoreBaseAgentConfig(
        instructions="BASE INSTRUCTIONS",
        active_mode="demo:focus",
        model_id="test-model",
        model_display_name="Test Model",
    )
    kit.toolbox = SimpleNamespace(
        skill_index=lambda: "",
        mcp_caller=None,
        agent_tool_whitelist=None,
    )
    kit.plugin_agents = list(agents or [])
    kit.plugin_context_files = list(context_files or [])
    kit._subagent_guide_cache = ""
    kit._subagent_roles_cache = ""
    kit._subagent_strategy_cache = ""
    kit._delegation_strategy = "allowed"
    return kit


def compose(kit: CoreBaseAgentKit) -> tuple[str, list]:
    return kit._compose_system_prompt(
        SimpleNamespace(session_id="s1", metadata={}),
        study_mode=False,
        effective_instructions=kit.config.instructions,
    )


def test_agent_prompt_replaces_the_leading_instructions(tmp_path: Path) -> None:
    agent = PluginAgentSpec(
        plugin="demo",
        scope="mode",
        mode="focus",
        prompt_text="You are the focused writing agent.",
    )
    kit = make_kit(tmp_path, agents=[agent])

    prompt, blocks = compose(kit)

    assert prompt.startswith("You are the focused writing agent.")
    assert "BASE INSTRUCTIONS" not in prompt
    assert any(block.key == "instructions" for block in blocks)


def test_without_an_agent_the_core_instructions_remain(tmp_path: Path) -> None:
    kit = make_kit(tmp_path)

    prompt, _blocks = compose(kit)

    assert prompt.startswith("BASE INSTRUCTIONS")


def test_plugin_context_files_are_appended_to_the_prompt(tmp_path: Path) -> None:
    rules = tmp_path / "rules.md"
    rules.write_text("Write in the user's voice.", encoding="utf-8")
    kit = make_kit(
        tmp_path,
        context_files=[{"plugin": "demo", "file": str(rules), "order": 10}],
    )

    prompt, blocks = compose(kit)

    assert "Instructions from:" in prompt
    assert "Write in the user's voice." in prompt
    assert any(block.key.startswith("plugin_context_") for block in blocks)


def test_agent_tool_whitelist_is_applied_to_the_toolbox(tmp_path: Path) -> None:
    agent = PluginAgentSpec(
        plugin="demo",
        scope="mode",
        mode="focus",
        tools=("read_file", "write_file"),
    )
    kit = make_kit(tmp_path, agents=[agent])

    compose(kit)

    assert kit.toolbox.agent_tool_whitelist == {"read_file", "write_file"}


def test_no_tool_declaration_resets_the_whitelist(tmp_path: Path) -> None:
    agent = PluginAgentSpec(plugin="demo", scope="mode", mode="focus", tools=None)
    kit = make_kit(tmp_path, agents=[agent])
    kit.toolbox.agent_tool_whitelist = {"read_file"}

    compose(kit)

    assert kit.toolbox.agent_tool_whitelist is None


def test_whitelist_filters_the_model_tool_list(tmp_path: Path) -> None:
    from lamtools_core.tool.default_toolbox import build_core_toolbox

    toolbox = build_core_toolbox(work_root=tmp_path)
    toolbox.agent_tool_whitelist = {"read_file"}

    names = [item["function"]["name"] for item in toolbox.model_tools()]

    assert names == ["read_file"]


async def test_whitelist_blocks_execution(tmp_path: Path) -> None:
    from lamtools_core.tool import ToolCall
    from lamtools_core.tool.default_toolbox import build_core_toolbox

    toolbox = build_core_toolbox(work_root=tmp_path)
    toolbox.agent_tool_whitelist = {"read_file"}

    result = await toolbox.execute(ToolCall(id="c1", name="list_dir", arguments={}))

    assert result.status == "blocked"
    assert "not available" in (result.error or "")
