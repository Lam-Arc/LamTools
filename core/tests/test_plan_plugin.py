"""The plan plugin (方案): what it ships, and the tool doing real work.

The plugin is the desktop half of "the phone authors a plan, a desktop executes
it": the manifest declares the skills and the tool, and core assembles the tool's
handler over the operation catalog the plan store already backs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.app.plan_operations import register_plan_operations
from lamtools_core.plugins.registry import PluginRegistry, PluginStateStore, bundled_plugins_dir
from lamtools_core.plugins.tools import complete_plugin_tool_specs, load_plugin_tools
from lamtools_core.runtime.plan_package import InMemoryPlanStore, PlanManager
from lamtools_core.tool import ToolCall
from lamtools_core.tool.default_toolbox import build_core_toolbox, bundled_core_tool_specs, core_model_tools


def _plan_root():
    return bundled_plugins_dir() / "plan"


class _Projects:
    """Just enough project store for the workspace → project lookup."""

    def __init__(self, work_root) -> None:
        self._projects = [SimpleNamespace(id="proj-1", work_root=str(work_root))]

    async def list(self):
        return list(self._projects)


def _registry(tmp_path) -> PluginRegistry:
    return PluginRegistry(
        plugin_roots=[bundled_plugins_dir()],
        state_store=PluginStateStore(tmp_path / "plugins.jsonc"),
    )


def test_the_plugin_ships_three_skills_and_one_tool(tmp_path):
    registry = _registry(tmp_path)
    plugin = next((item for item in registry.discover() if item.name == "plan"), None)

    assert plugin is not None, "the plan plugin is not discovered"
    # On by default: the capability the user asked for has to be there on a fresh
    # install, not behind a switch they have to find.
    assert plugin.enabled is True
    assert plugin.platforms == "universal"
    assert [Path(root).name for root in plugin.skill_roots] == ["skills"]
    assert sorted(path.parent.name for path in Path(plugin.skill_roots[0]).glob("*/SKILL.md")) == [
        "draft-plan",
        "execute-plan",
        "refine-plan",
    ]
    declared = load_plugin_tools(plugin.tool_files, plugin_root=Path(plugin.root))
    assert [tool.name for tool in declared] == ["plan_package"]
    assert declared[0].permission == "auto_allow"


def test_every_plan_skill_parses_and_declares_its_platform(tmp_path):
    modules: dict[str, str] = {}
    for path in sorted((_plan_root() / "skills").glob("*/SKILL.md")):
        body = path.read_text(encoding="utf-8")
        assert body.startswith("---"), f"{path} has no frontmatter"
        modules[path.parent.name] = body

    assert set(modules) == {"draft-plan", "refine-plan", "execute-plan"}
    # Executing needs the repository, so the phone must not offer that one.
    assert "platforms: universal" in modules["draft-plan"].split("---")[1]
    assert "platforms: universal" in modules["refine-plan"].split("---")[1]
    assert "platforms: desktop" in modules["execute-plan"].split("---")[1]
    # A description is the whole trigger: an empty one means the skill never fires.
    for name, body in modules.items():
        description = next(
            line for line in body.split("---")[1].splitlines() if line.startswith("description:")
        )
        assert len(description) > 120, f"{name} has a description too thin to trigger on"


def test_every_plan_skill_ships_a_complete_eval_suite(tmp_path):
    """Each plan skill ships evals in the same shape the Study suite uses.

    No other check covers the plan evals: the Study manifest is built from a
    hard-coded skill list, so a plan suite could rot unread. These keys
    (skill_name, prompt, expected_output, assertions, files) are kept identical
    to the Study format so a single checker could read either.
    """
    skills_root = _plan_root() / "skills"
    template = skills_root / "references" / "plan-template.md"
    assert template.is_file()
    draft_body = (skills_root / "draft-plan" / "SKILL.md").read_text(encoding="utf-8")
    # The document shapes only reach the model if drafting links the reference.
    assert "](references/plan-template.md)" in draft_body

    seen: set[str] = set()
    case_count = 0
    for skill_file in sorted(skills_root.glob("*/SKILL.md")):
        name = skill_file.parent.name
        seen.add(name)
        body = skill_file.read_text(encoding="utf-8")

        # A reference may sit beside the skill or in the shared references pool.
        for relative in re.findall(r"\]\((references/[^)]+\.md)\)", body):
            candidates = (skill_file.parent / relative, skills_root / relative)
            assert any(path.is_file() for path in candidates), (
                f"{name} links a missing reference: {relative}"
            )

        manifest = json.loads(
            (skill_file.parent / "evals" / "evals.json").read_text(encoding="utf-8")
        )
        assert manifest["skill_name"] == name
        cases = manifest["evals"]
        assert len(cases) == 8, f"{name} must ship 8 eval cases"
        for case in cases:
            assert str(case["prompt"]).strip()
            assert str(case["expected_output"]).strip()
            assertions = case["assertions"]
            assert assertions and all(str(item).strip() for item in assertions)
            assert len(assertions) >= 3, f"{name}:{case['id']} asserts too little"
            files = case["files"]
            assert files, f"{name}:{case['id']} has no fixture"
            for relative in files:
                fixture = skill_file.parent / relative
                assert fixture.is_file()
                payload = json.loads(fixture.read_text(encoding="utf-8"))
                assert payload["case_id"] == f"{name}-{int(case['id']):02d}"
            case_count += 1

    assert seen == {"draft-plan", "refine-plan", "execute-plan"}
    assert case_count == 24


def test_plan_eval_manifest_reports_wiring_not_behavior(tmp_path):
    """The plan eval runner validates wiring and claims no behavior."""
    from lamtools_core.plugins.bundled.plan.eval_manifest import build_manifest

    report = build_manifest(work_root=tmp_path)

    assert report["host_smoke"]["status"] == "PASS"
    assert report["host_smoke"]["mode"] == "execute"
    assert report["host_smoke"]["active_skills"] == [
        "draft-plan",
        "refine-plan",
        "execute-plan",
    ]
    assert report["host_smoke"]["behavioral_claim"] is False
    assert report["host_smoke"]["reference_links_checked"] >= 1
    assert report["behavioral_summary"] == {"total": 24, "run": 0, "not_run": 24}
    assert [case["case_id"] for case in report["cases"]][:2] == [
        "draft-plan:1",
        "draft-plan:2",
    ]
    assert all(case["status"] == "NOT_RUN" and case["output"] is None for case in report["cases"])
    assert all(case["fixture_files"] for case in report["cases"])


def _toolbox(tmp_path, *, operation_executor: Any = None):
    root = _plan_root()
    declared = load_plugin_tools([root / "tools" / "tools.jsonc"], plugin_root=root)
    base_specs = {spec.name: spec for spec in bundled_core_tool_specs()}
    specs = complete_plugin_tool_specs(
        declared,
        plugin_name="plan",
        plugin_root=root,
        base_specs_by_name=base_specs,
    )
    assert [spec.name for spec in specs] == ["plan_package"]
    definitions = {
        item["function"]["name"]: item["function"] for item in core_model_tools(specs)
    }
    assert definitions["plan_package"]["parameters"]["additionalProperties"] is False
    return build_core_toolbox(
        work_root=tmp_path,
        plugin_tool_specs=specs,
        operation_executor=operation_executor,
    )


@pytest.mark.asyncio
async def test_the_tool_saves_and_reads_a_plan_through_the_catalog(tmp_path):
    catalog = OperationCatalog()
    store = InMemoryPlanStore()
    register_plan_operations(
        catalog,
        plan_manager=PlanManager(store),
        project_store=_Projects(tmp_path),
    )

    async def executor(operation: str, payload: dict, meta: dict) -> Any:
        return await catalog.execute(operation, payload, metadata=meta)

    toolbox = _toolbox(tmp_path, operation_executor=executor)

    saved = await toolbox.execute(
        ToolCall(
            id="call-1",
            name="plan_package",
            arguments={
                "action": "save",
                # No project_id: a running turn fills it in from its workspace.
                "title": "手机做方案，电脑执行",
                "requirement": {"restatement": "把需求变成方案"},
                "approach": {"chosen": "共享插件"},
            },
        )
    )
    assert saved.status == "ok", saved.error
    plan = saved.metadata["operation_payload"]["plan"]
    assert plan["project_id"] == "proj-1"
    assert plan["revision"] == 1
    plan_id = plan["plan_id"]

    read_back = await toolbox.execute(
        ToolCall(id="call-2", name="plan_package", arguments={"action": "get", "plan_id": plan_id})
    )
    assert read_back.status == "ok", read_back.error
    assert read_back.metadata["operation_payload"]["plan"]["title"] == "手机做方案，电脑执行"

    # A save is a patch, and it spends a revision.
    revised = await toolbox.execute(
        ToolCall(
            id="call-3",
            name="plan_package",
            arguments={"action": "save", "plan_id": plan_id, "expected_revision": 1, "summary": "一句话"},
        )
    )
    assert revised.status == "ok", revised.error
    revised_plan = revised.metadata["operation_payload"]["plan"]
    assert revised_plan["revision"] == 2
    assert revised_plan["summary"] == "一句话"
    assert revised_plan["title"] == "手机做方案，电脑执行"

    listed = await toolbox.execute(
        ToolCall(id="call-4", name="plan_package", arguments={"action": "list", "project_id": "proj-1"})
    )
    assert [item["plan_id"] for item in listed.metadata["operation_payload"]["plans"]] == [plan_id]


@pytest.mark.asyncio
async def test_the_tool_says_so_when_there_is_no_catalog(tmp_path):
    """A host without an operation catalog must not look like it can save plans."""

    toolbox = _toolbox(tmp_path)
    result = await toolbox.execute(
        ToolCall(id="call-1", name="plan_package", arguments={"action": "list"})
    )

    assert result.status == "failed"
    assert "no operation catalog" in (result.error or "")
    assert "Unknown tool" not in (result.error or "")
    assert "plan_package" not in toolbox._plugin_handler_errors
