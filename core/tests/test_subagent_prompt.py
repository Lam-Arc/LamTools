from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.app.operation_catalog import OperationCatalog, OperationRequest
from lamtools_core.config.subagent_prompt import (
    DEFAULT_DELEGATION_STRATEGY,
    DEFAULT_SUBAGENT_GUIDE,
    guide_path_for_scope,
    load_effective_delegation_strategy,
    load_effective_role_assignments,
    load_subagent_guide,
    load_subagent_settings,
    merge_role_assignments,
    normalize_role_assignment,
    normalize_delegation_strategy,
    render_delegation_strategy_prompt,
    render_role_assignments_prompt,
    resolve_subagent_guide_path,
    write_subagent_settings,
    write_subagent_guide,
)


@pytest.mark.asyncio
async def test_load_subagent_guide_returns_builtin_when_no_file(tmp_path, isolated_config_root):
    # Isolate from any real ~/.lam config on the test machine.

    guide = load_subagent_guide(tmp_path / "work")

    assert guide == DEFAULT_SUBAGENT_GUIDE
    assert "Delegate" in guide
    assert resolve_subagent_guide_path(tmp_path / "work") is None


@pytest.mark.asyncio
async def test_load_subagent_guide_prefers_project_over_global(tmp_path, isolated_config_root):
    work = tmp_path / "work"
    global_dir = isolated_config_root / "subagent"
    global_dir.mkdir(parents=True)
    (global_dir / "guide.md").write_text("# Global guide\nuse sub_agent wisely", encoding="utf-8")
    project_dir = work / ".lam" / "config" / "subagent"
    project_dir.mkdir(parents=True)
    (project_dir / "guide.md").write_text("# Project guide\nproject-specific rules", encoding="utf-8")

    guide = load_subagent_guide(work)

    assert "Project guide" in guide
    assert "project-specific rules" in guide
    resolved = resolve_subagent_guide_path(work)
    assert resolved is not None and resolved.name == "guide.md"
    assert resolved.parent == project_dir


@pytest.mark.asyncio
async def test_load_subagent_guide_falls_back_to_global(tmp_path, isolated_config_root):
    work = tmp_path / "work"
    global_dir = isolated_config_root / "subagent"
    global_dir.mkdir(parents=True)
    (global_dir / "guide.md").write_text("# Global only\nstandalone guide", encoding="utf-8")

    guide = load_subagent_guide(work)

    assert "Global only" in guide


@pytest.mark.asyncio
async def test_write_subagent_guide_writes_to_requested_scope(tmp_path, isolated_config_root):
    work = tmp_path / "work"

    project_path = write_subagent_guide("# New project guide", scope="project", work_root=work)
    global_path = write_subagent_guide("# New global guide", scope="global", work_root=work)

    assert project_path == work / ".lam" / "config" / "subagent" / "guide.md"
    assert project_path.read_text(encoding="utf-8") == "# New project guide"
    assert global_path == isolated_config_root / "subagent" / "guide.md"
    assert global_path.read_text(encoding="utf-8") == "# New global guide"
    # After writing, the loader returns the project (higher priority) content.
    assert "# New project guide" in load_subagent_guide(work)


def test_guide_path_for_scope_project_without_work_root_falls_to_global(tmp_path, isolated_config_root):
    # Without a work_root, even a "project" scope cannot point at a project dir,
    # so the writer falls back to the global path (home) rather than erroring.
    path = guide_path_for_scope("project", None)
    assert path == isolated_config_root / "subagent" / "guide.md"

    path_with_root = guide_path_for_scope("project", tmp_path / "work")
    assert path_with_root == tmp_path / "work" / ".lam" / "config" / "subagent" / "guide.md"


def _role(
    task_type: str,
    *,
    assignment_type: str = "consider",
    model: str = "model-a",
    reasoning_min: str = "off",
    reasoning_max: str = "max",
) -> dict[str, str]:
    return {
        "task_type": task_type,
        "type": assignment_type,
        "model": model,
        "reasoning_min": reasoning_min,
        "reasoning_max": reasoning_max,
    }


def test_role_assignments_merge_global_baseline_with_project_override_and_append(
    tmp_path, isolated_config_root
):
    work = tmp_path / "work"
    write_subagent_settings(
        {"role_assignments": [_role("Research"), _role("Coding")]},
        scope="global",
        work_root=work,
    )
    write_subagent_settings(
        {
            "role_assignments": [
                _role(
                    "  research  ",
                    assignment_type="execute",
                    model="model-b",
                    reasoning_min="medium",
                    reasoning_max="xh",
                ),
                _role("Review", model="model-c"),
            ]
        },
        scope="project",
        work_root=work,
    )

    assert load_effective_role_assignments(work) == [
        _role(
            "research",
            assignment_type="execute",
            model="model-b",
            reasoning_min="medium",
            reasoning_max="xhigh",
        ),
        _role("Coding"),
        _role("Review", model="model-c"),
    ]


def test_project_setting_without_role_assignments_inherits_global_roles(
    tmp_path, isolated_config_root
):
    work = tmp_path / "work"
    write_subagent_settings(
        {"role_assignments": [_role("Research")], "unknown_global": 1},
        scope="global",
        work_root=work,
    )
    path = write_subagent_settings(
        {"default_multimodal_model": "vision-model", "unknown_project": True},
        scope="project",
        work_root=work,
    )

    assert "role_assignments" not in json.loads(path.read_text(encoding="utf-8"))
    settings = load_subagent_settings(work)
    assert settings["role_assignments"] == [_role("Research")]
    assert settings["unknown_global"] == 1
    assert settings["unknown_project"] is True


def test_role_assignment_validation_normalizes_xh_and_rejects_inverted_range():
    assert normalize_role_assignment(
        _role("Research", reasoning_min="medium", reasoning_max="xh")
    )["reasoning_max"] == "xhigh"

    with pytest.raises(ValueError, match="reasoning_min"):
        normalize_role_assignment(
            _role("Research", reasoning_min="max", reasoning_max="off")
        )
    with pytest.raises(ValueError, match="task_type must be a string"):
        normalize_role_assignment({**_role("Research"), "task_type": 123})


def test_merge_role_assignments_rejects_duplicate_normalized_task_types():
    with pytest.raises(ValueError, match="duplicate task_type"):
        merge_role_assignments([_role("Research"), _role(" research ")], [])


def test_role_assignment_prompt_is_stable_and_empty_configuration_is_omitted(
    tmp_path, isolated_config_root
):
    work = tmp_path / "work"
    assert render_role_assignments_prompt(work) == ""
    write_subagent_settings(
        {
            "role_assignments": [
                _role(
                    "Research",
                    model="model-a",
                    reasoning_min="light",
                    reasoning_max="high",
                )
            ]
        },
        scope="global",
        work_root=work,
    )
    assert render_role_assignments_prompt(work) == (
        "## Sub-agent Role Assignments\n"
        "When a task type matches, prefer its assigned type, model, and reasoning level range; otherwise choose according to the task.\n"
        "- Task type: Research; type: consider; suggested model: model-a; suggested reasoning level: light–high"
    )

def test_delegation_strategy_defaults_inherits_overrides_and_unsets(
    tmp_path, isolated_config_root
):
    work = tmp_path / "work"
    assert load_effective_delegation_strategy(work) == DEFAULT_DELEGATION_STRATEGY

    write_subagent_settings(
        {"delegation_strategy": "low", "unknown_global": 1},
        scope="global",
        work_root=work,
    )
    project_path = write_subagent_settings(
        {"unknown_project": True},
        scope="project",
        work_root=work,
    )
    assert load_effective_delegation_strategy(work) == "low"
    assert "delegation_strategy" not in json.loads(
        project_path.read_text(encoding="utf-8")
    )

    write_subagent_settings(
        {"delegation_strategy": "high"},
        scope="project",
        work_root=work,
    )
    assert load_effective_delegation_strategy(work) == "high"
    write_subagent_settings(
        {"delegation_strategy": None},
        scope="project",
        work_root=work,
    )
    saved = json.loads(project_path.read_text(encoding="utf-8"))
    assert "delegation_strategy" not in saved
    assert saved["unknown_project"] is True
    assert load_effective_delegation_strategy(work) == "low"


def test_delegation_strategy_validation_and_prompt_copy(tmp_path, isolated_config_root):
    work = tmp_path / "work"
    with pytest.raises(ValueError, match="delegation_strategy"):
        normalize_delegation_strategy("aggressive")
    write_subagent_settings(
        {"delegation_strategy": "high"},
        scope="global",
        work_root=work,
    )
    assert render_delegation_strategy_prompt(work) == (
        "## Sub-agent Delegation Strategy\n"
        "This strategy takes precedence over the general delegation guide and role suggestions.\n"
        "Current sub-agent delegation strategy: first make a plan and obtain user confirmation. "
        "After confirmation, immediately create a highly centralized Checklist and use multiple "
        "sub-agents in parallel wherever possible. The main Agent remains responsible for decisions, "
        "direction, task assignment, dependency coordination, conflict resolution, integration, and final acceptance."
    )

# --- RPC operations -------------------------------------------------------


def _guide_catalog(work_root: Path | str | None) -> OperationCatalog:
    from lamtools_core.app.http_agent_app import _register_subagent_guide_operations

    catalog = OperationCatalog()
    _register_subagent_guide_operations(catalog, work_root=work_root)
    return catalog


@pytest.mark.asyncio
async def test_rpc_guide_get_returns_builtin_when_unset(tmp_path, isolated_config_root):
    catalog = _guide_catalog(tmp_path / "work")

    result = await catalog.execute(
        "config.subagent.guide.get", {"work_root": str(tmp_path / "work")}
    )

    assert result.status == "ok"
    assert result.payload["is_builtin"] is True
    assert result.payload["scope"] == "builtin"
    assert result.payload["content"] == DEFAULT_SUBAGENT_GUIDE


@pytest.mark.asyncio
async def test_rpc_guide_set_then_get_roundtrips_project_scope(tmp_path, isolated_config_root):
    work = tmp_path / "work"
    catalog = _guide_catalog(work)

    written = await catalog.execute(
        "config.subagent.guide.set",
        {"scope": "project", "work_root": str(work), "content": "# Project RPC guide"},
    )
    assert written.status == "ok"
    assert written.payload["scope"] == "project"

    fetched = await catalog.execute(
        "config.subagent.guide.get", {"work_root": str(work)}
    )
    assert fetched.status == "ok"
    assert fetched.payload["is_builtin"] is False
    assert fetched.payload["scope"] == "project"
    assert fetched.payload["content"] == "# Project RPC guide"


@pytest.mark.asyncio
async def test_rpc_guide_set_rejects_invalid_scope(tmp_path, isolated_config_root):
    catalog = _guide_catalog(tmp_path / "work")

    result = await catalog.execute(
        "config.subagent.guide.set",
        {"scope": "weird", "content": "nope"},
    )

    assert result.status == "error"
    assert "scope" in result.payload["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("blank_root", [None, "   "])
async def test_rpc_guide_set_project_requires_work_root(
    tmp_path, isolated_config_root, blank_root
):
    # Catalog constructed without a work_root; payload also omits it.
    catalog = _guide_catalog(blank_root)

    result = await catalog.execute(
        "config.subagent.guide.set",
        {"scope": "project", "content": "no root", "work_root": blank_root},
    )
    settings = await catalog.execute(
        "config.subagent.settings.set",
        {
            "scope": "project",
            "settings": {"delegation_strategy": "high"},
            "work_root": blank_root,
        },
    )

    assert result.status == "error"
    assert "work_root" in result.payload["error"]
    assert settings.status == "error"
    assert "work_root" in settings.payload["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("configured_root", [None, "   "])
async def test_rpc_project_scoped_reads_require_work_root(
    isolated_config_root, configured_root
):
    catalog = _guide_catalog(configured_root)

    guide = await catalog.execute(
        "config.subagent.guide.get",
        {"scope": "project"},
    )
    settings = await catalog.execute(
        "config.subagent.settings.get",
        {"scope": "project"},
    )

    assert guide.status == "error"
    assert "work_root" in guide.payload["error"]
    assert settings.status == "error"
    assert "work_root" in settings.payload["error"]


@pytest.mark.asyncio
async def test_rpc_settings_get_returns_scoped_local_and_effective_roles(
    tmp_path, isolated_config_root
):
    work = tmp_path / "work"
    write_subagent_settings(
        {"role_assignments": [_role("Research")], "unknown_global": "kept"},
        scope="global",
        work_root=work,
    )
    write_subagent_settings(
        {"default_multimodal_model": "vision-model"},
        scope="project",
        work_root=work,
    )
    catalog = _guide_catalog(work)

    project = await catalog.execute(
        "config.subagent.settings.get",
        {"scope": "project", "work_root": str(work)},
    )
    global_result = await catalog.execute(
        "config.subagent.settings.get",
        {"scope": "global", "work_root": str(work)},
    )

    assert project.status == "ok"
    assert project.payload["scope"] == "project"
    assert project.payload["settings"]["role_assignments"] == []
    assert project.payload["role_assignments_inherited"] is True
    assert project.payload["effective_role_assignments"] == [_role("Research")]
    assert global_result.payload["settings"]["role_assignments"] == [_role("Research")]
    assert global_result.payload["settings"]["unknown_global"] == "kept"
    assert global_result.payload["role_assignments_inherited"] is False


@pytest.mark.asyncio
async def test_rpc_settings_set_validates_roles_and_preserves_unknown_settings(
    tmp_path, isolated_config_root
):
    work = tmp_path / "work"
    write_subagent_settings(
        {"plugin_setting": {"enabled": True}},
        scope="project",
        work_root=work,
    )
    catalog = _guide_catalog(work)

    invalid = await catalog.execute(
        "config.subagent.settings.set",
        {
            "scope": "project",
            "work_root": str(work),
            "settings": {
                "role_assignments": [
                    _role("Research", reasoning_min="max", reasoning_max="off")
                ]
            },
        },
    )
    assert invalid.status == "error"
    assert "reasoning_min" in invalid.payload["error"]

    valid = await catalog.execute(
        "config.subagent.settings.set",
        {
            "scope": "project",
            "work_root": str(work),
            "settings": {
                "role_assignments": [
                    _role("Research", reasoning_min="medium", reasoning_max="xh")
                ]
            },
        },
    )
    assert valid.status == "ok"
    saved = json.loads(
        (work / ".lam" / "config" / "subagent" / "settings.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved["plugin_setting"] == {"enabled": True}
    assert saved["role_assignments"][0]["reasoning_max"] == "xhigh"


@pytest.mark.asyncio
async def test_rpc_delegation_strategy_scoped_effective_validation_and_unset(
    tmp_path, isolated_config_root
):
    work = tmp_path / "work"
    write_subagent_settings(
        {"delegation_strategy": "low"},
        scope="global",
        work_root=work,
    )
    write_subagent_settings(
        {"plugin_setting": "kept"},
        scope="project",
        work_root=work,
    )
    catalog = _guide_catalog(work)

    inherited = await catalog.execute(
        "config.subagent.settings.get",
        {"scope": "project", "work_root": str(work)},
    )
    assert inherited.payload["settings"]["delegation_strategy"] is None
    assert inherited.payload["effective_delegation_strategy"] == "low"
    assert inherited.payload["global_delegation_strategy"] == "low"
    assert inherited.payload["delegation_strategy_inherited"] is True

    invalid = await catalog.execute(
        "config.subagent.settings.set",
        {
            "scope": "project",
            "work_root": str(work),
            "settings": {"delegation_strategy": "aggressive"},
        },
    )
    assert invalid.status == "error"
    assert "delegation_strategy" in invalid.payload["error"]

    overridden = await catalog.execute(
        "config.subagent.settings.set",
        {
            "scope": "project",
            "work_root": str(work),
            "settings": {"delegation_strategy": "high"},
        },
    )
    assert overridden.status == "ok"
    fetched = await catalog.execute(
        "config.subagent.settings.get",
        {"scope": "project", "work_root": str(work)},
    )
    assert fetched.payload["settings"]["delegation_strategy"] == "high"
    assert fetched.payload["effective_delegation_strategy"] == "high"
    assert fetched.payload["global_delegation_strategy"] == "low"
    assert fetched.payload["delegation_strategy_inherited"] is False

    unset = await catalog.execute(
        "config.subagent.settings.set",
        {
            "scope": "project",
            "work_root": str(work),
            "settings": {"delegation_strategy": None},
        },
    )
    assert unset.status == "ok"
    saved = json.loads(
        (work / ".lam" / "config" / "subagent" / "settings.json").read_text(
            encoding="utf-8"
        )
    )
    assert "delegation_strategy" not in saved
    assert saved["plugin_setting"] == "kept"
    inherited_again = await catalog.execute(
        "config.subagent.settings.get",
        {"scope": "project", "work_root": str(work)},
    )
    assert inherited_again.payload["effective_delegation_strategy"] == "low"
    assert inherited_again.payload["delegation_strategy_inherited"] is True


# --- Prompt injection -----------------------------------------------------


@pytest.mark.asyncio
async def test_base_agent_injects_custom_subagent_guide_into_system_prompt(tmp_path, isolated_config_root):
    from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
    from lamtools_core.kernel.state import RuntimeState
    from lamtools_core.prompt import PromptContext

    project_dir = tmp_path / "work" / ".lam" / "config" / "subagent"
    project_dir.mkdir(parents=True)
    (project_dir / "guide.md").write_text(
        "CUSTOM SUBAGENT GUIDE: always specify model + mode when delegating.",
        encoding="utf-8",
    )

    kit = CoreBaseAgentKit(work_root=tmp_path / "work", config=CoreBaseAgentConfig())
    request = await kit.build_model_request(
        RuntimeState(session_id="guide-inject"),
        PromptContext(session_id="guide-inject"),
    )

    system_prompt = str(request.messages[0].content)
    assert "CUSTOM SUBAGENT GUIDE" in system_prompt
    # The old hard-coded delegation line is replaced by the guide.
    assert "互不依赖的任务应委派 sub-agent 并行执行。其 prompt 至少明确" not in system_prompt


@pytest.mark.asyncio
async def test_base_agent_injects_builtin_guide_when_no_file(tmp_path, isolated_config_root):
    from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
    from lamtools_core.kernel.state import RuntimeState
    from lamtools_core.prompt import PromptContext


    kit = CoreBaseAgentKit(work_root=tmp_path / "work", config=CoreBaseAgentConfig())
    request = await kit.build_model_request(
        RuntimeState(session_id="builtin-guide"),
        PromptContext(session_id="builtin-guide"),
    )

    system_prompt = str(request.messages[0].content)
    assert DEFAULT_SUBAGENT_GUIDE in system_prompt


@pytest.mark.asyncio
async def test_base_agent_appends_role_assignments_immediately_after_subagent_guide(
    tmp_path, isolated_config_root
):
    from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
    from lamtools_core.kernel.state import RuntimeState
    from lamtools_core.prompt import PromptContext

    work = tmp_path / "work"
    write_subagent_settings(
        {"role_assignments": [_role("Research")]},
        scope="global",
        work_root=work,
    )
    kit = CoreBaseAgentKit(work_root=work, config=CoreBaseAgentConfig())
    request = await kit.build_model_request(
        RuntimeState(session_id="role-prompt"),
        PromptContext(session_id="role-prompt"),
    )

    system_prompt = str(request.messages[0].content)
    expected = (
        f"{DEFAULT_SUBAGENT_GUIDE}\n\n"
        "## Sub-agent Delegation Strategy\n"
        "This strategy takes precedence over the general delegation guide and role suggestions.\n"
        "Current sub-agent delegation strategy: keep the current default delegation strategy.\n\n"
        "## Sub-agent Role Assignments\n"
        "When a task type matches, prefer its assigned type, model, and reasoning level range; otherwise choose according to the task.\n"
        "- Task type: Research; type: consider; suggested model: model-a; suggested reasoning level: off–max"
    )
    assert expected in system_prompt


@pytest.mark.asyncio
async def test_forbidden_strategy_keeps_guide_but_has_priority_and_runtime_blocks_tools(
    tmp_path, isolated_config_root
):
    from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
    from lamtools_core.kernel.state import RuntimeState
    from lamtools_core.prompt import PromptContext
    from lamtools_core.tool import ToolCall
    from lamtools_core.tool.default_toolbox import build_core_toolbox

    work = tmp_path / "work"
    write_subagent_guide("CUSTOM GUIDE: delegate broadly", scope="project", work_root=work)
    write_subagent_settings(
        {
            "delegation_strategy": "forbidden",
            "role_assignments": [_role("Research")],
        },
        scope="project",
        work_root=work,
    )
    # Production assembles the toolbox before constructing the kit; exercise
    # that injected-toolbox path so a previously serialized approval cannot
    # retain access after the strategy changes to forbidden.
    toolbox = build_core_toolbox(work_root=work)
    kit = CoreBaseAgentKit(
        work_root=work,
        config=CoreBaseAgentConfig(capability="text"),
        toolbox=toolbox,
    )
    request = await kit.build_model_request(
        RuntimeState(session_id="forbidden-strategy"),
        PromptContext(session_id="forbidden-strategy"),
    )
    system_prompt = str(request.messages[0].content)
    guide_index = system_prompt.index("CUSTOM GUIDE: delegate broadly")
    strategy_index = system_prompt.index("## Sub-agent Delegation Strategy")
    roles_index = system_prompt.index("## Sub-agent Role Assignments")
    assert guide_index < strategy_index < roles_index
    assert "takes precedence over the general delegation guide" in system_prompt
    assert "do not delegate to sub-agents" in system_prompt
    assert "ask the user for a text description" in system_prompt

    visible = {spec.name for spec in kit.toolbox.tool_specs()}
    assert "sub_agent" not in visible
    assert "sub_agent_message" not in visible
    for tool_name in ("sub_agent", "sub_agent_message"):
        direct = ToolCall(id=f"direct-{tool_name}", name=tool_name, arguments={})
        direct_result = await kit.toolbox.execute(direct)
        assert direct_result.status == "blocked"
        assert direct_result.error == f"Tool disabled: {tool_name}"

        resumed = kit.toolbox.prepare_approved_call(
            ToolCall(id=f"resumed-{tool_name}", name=tool_name, arguments={})
        )
        resumed_result = await kit.toolbox.execute(resumed)
        assert resumed_result.status == "blocked"


def test_non_forbidden_strategy_keeps_subagent_tools_visible(tmp_path, isolated_config_root):
    from lamtools_core.app.base_agent import CoreBaseAgentKit

    write_subagent_settings(
        {"delegation_strategy": "low"},
        scope="global",
        work_root=tmp_path / "work",
    )
    kit = CoreBaseAgentKit(work_root=tmp_path / "work")
    visible = {spec.name for spec in kit.toolbox.tool_specs()}
    assert {"sub_agent", "sub_agent_message"} <= visible


@pytest.mark.asyncio
async def test_base_agent_injects_capability_prompt_for_text_model(tmp_path, isolated_config_root):
    from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
    from lamtools_core.kernel.state import RuntimeState
    from lamtools_core.prompt import PromptContext

    kit = CoreBaseAgentKit(
        work_root=tmp_path / "work",
        config=CoreBaseAgentConfig(capability="text"),
    )

    request = await kit.build_model_request(
        RuntimeState(session_id="cap-text"),
        PromptContext(session_id="cap-text"),
    )

    system_prompt = str(request.messages[0].content)
    assert "Current model capability" in system_prompt
    assert "text only" in system_prompt
    assert "image, video, and audio input are unsupported" in system_prompt
    assert "sub_agent" in system_prompt
    assert "multimodal model" in system_prompt


@pytest.mark.asyncio
async def test_base_agent_injects_capability_prompt_for_multimodal_model(tmp_path, isolated_config_root):
    from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
    from lamtools_core.kernel.state import RuntimeState
    from lamtools_core.prompt import PromptContext

    kit = CoreBaseAgentKit(
        work_root=tmp_path / "work",
        config=CoreBaseAgentConfig(capability="multimodal"),
    )

    request = await kit.build_model_request(
        RuntimeState(session_id="cap-mm"),
        PromptContext(session_id="cap-mm"),
    )

    system_prompt = str(request.messages[0].content)
    assert "Current model capability" in system_prompt
    assert "multimodal" in system_prompt


@pytest.mark.asyncio
async def test_base_agent_omits_capability_line_when_capability_unknown(tmp_path, isolated_config_root):
    from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
    from lamtools_core.kernel.state import RuntimeState
    from lamtools_core.prompt import PromptContext

    kit = CoreBaseAgentKit(
        work_root=tmp_path / "work",
        config=CoreBaseAgentConfig(capability=""),  # unknown
    )

    request = await kit.build_model_request(
        RuntimeState(session_id="cap-none"),
        PromptContext(session_id="cap-none"),
    )

    system_prompt = str(request.messages[0].content)
    assert "Current model capability" not in system_prompt


# --- Default multimodal model resolution -----------------------------------


def _write_model(config_dir: Path, model_id: str, *, capability: str) -> None:
    """Write a minimal model jsonc into a config-root models dir."""
    models_dir = config_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / f"{model_id}.jsonc").write_text(
        json.dumps({"model_id": model_id, "capability": capability}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_resolve_default_multimodal_model_prefers_settings(tmp_path, isolated_config_root):
    from lamtools_core.config.subagent_prompt import resolve_default_multimodal_model

    _write_model(isolated_config_root, "alpha-mm", capability="multimodal")
    settings_dir = isolated_config_root / "subagent"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "settings.json").write_text(
        json.dumps({"default_multimodal_model": "alpha-mm"}), encoding="utf-8"
    )

    assert resolve_default_multimodal_model(tmp_path / "work") == "alpha-mm"


def test_resolve_default_multimodal_model_picks_first_multimodal_from_store(tmp_path, isolated_config_root):
    from lamtools_core.config.subagent_prompt import resolve_default_multimodal_model

    # Two multimodal models: "model-a" sorts before "model-b" by model_id.
    _write_model(isolated_config_root, "model-b", capability="multimodal")
    _write_model(isolated_config_root, "model-a", capability="multimodal")
    # A text model must never be picked.
    _write_model(isolated_config_root, "text-only", capability="text")

    assert resolve_default_multimodal_model(tmp_path / "work") == "model-a"


def test_resolve_default_multimodal_model_returns_none_without_multimodal(tmp_path, isolated_config_root):
    from lamtools_core.config.subagent_prompt import resolve_default_multimodal_model

    _write_model(isolated_config_root, "text-only", capability="text")

    assert resolve_default_multimodal_model(tmp_path / "work") is None


@pytest.mark.asyncio
async def test_text_model_capability_prompt_uses_first_multimodal_model(tmp_path, isolated_config_root):
    from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
    from lamtools_core.kernel.state import RuntimeState
    from lamtools_core.prompt import PromptContext

    _write_model(isolated_config_root, "alpha-mm", capability="multimodal")

    kit = CoreBaseAgentKit(
        work_root=tmp_path / "work",
        config=CoreBaseAgentConfig(capability="text"),
    )
    request = await kit.build_model_request(
        RuntimeState(session_id="cap-dynamic"),
        PromptContext(session_id="cap-dynamic"),
    )

    system_prompt = str(request.messages[0].content)
    assert 'set model to "alpha-mm"' in system_prompt
    assert "Kimi-K2.6" not in system_prompt


@pytest.mark.asyncio
async def test_text_model_capability_prompt_omits_concrete_model_when_none(tmp_path, isolated_config_root):
    from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
    from lamtools_core.kernel.state import RuntimeState
    from lamtools_core.prompt import PromptContext

    kit = CoreBaseAgentKit(
        work_root=tmp_path / "work",
        config=CoreBaseAgentConfig(capability="text"),
    )
    request = await kit.build_model_request(
        RuntimeState(session_id="cap-no-mm"),
        PromptContext(session_id="cap-no-mm"),
    )

    system_prompt = str(request.messages[0].content)
    assert "set model to a model that supports images" in system_prompt
    assert 'model="' not in system_prompt
    assert "Kimi-K2.6" not in system_prompt
