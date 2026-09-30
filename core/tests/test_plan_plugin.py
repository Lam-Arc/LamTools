"""The plan plugin (方案): what it ships — skills only, files as the store.

Plans are markdown documents in the project's 「方案/」 folder: the agent drafts
and edits them with its ordinary file tools, and the library reads the folder.
The plugin's job is the three skills (the conversation-first behaviour) plus the
shared template — no dedicated tool any more.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from lamtools_core.plugins.registry import PluginRegistry, PluginStateStore, bundled_plugins_dir
from lamtools_core.plugins.tools import load_plugin_tools


def _plan_root():
    return bundled_plugins_dir() / "plan"


def _registry(tmp_path) -> PluginRegistry:
    return PluginRegistry(
        plugin_roots=[bundled_plugins_dir()],
        state_store=PluginStateStore(tmp_path / "plugins.jsonc"),
    )


def test_the_plugin_ships_three_skills_and_no_tool(tmp_path):
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
    # Plans are files: the plugin declares no tool of its own any more.
    assert load_plugin_tools(plugin.tool_files, plugin_root=Path(plugin.root)) == []


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


def test_the_skills_teach_the_file_contract_not_a_store():
    """The skills must send the agent to 「方案/」 files — no store, no tool.

    These greps fail if a rewrite drifts back to the retired plan_package flow:
    the skills are the only place the behaviour lives now.
    """
    skills_root = _plan_root() / "skills"
    draft = (skills_root / "draft-plan" / "SKILL.md").read_text(encoding="utf-8")
    refine = (skills_root / "refine-plan" / "SKILL.md").read_text(encoding="utf-8")
    execute = (skills_root / "execute-plan" / "SKILL.md").read_text(encoding="utf-8")

    # The designated folder and the file contract are named.
    assert "方案/" in draft and "方案/" in refine and "方案/" in execute
    # Drafting writes files with the ordinary file tools; nothing mentions the
    # retired tool or its store semantics.
    for name, body in (("draft-plan", draft), ("refine-plan", refine)):
        assert "plan_package" not in body, f"{name} still teaches the retired tool"
        assert "write_file" in body or "edit_file" in body, f"{name} never says how to write"
    assert "plan_package" not in execute, "execute-plan still teaches the retired tool"
    assert "read_file" in execute
    # The status machine lives in the document now; no backend refusal exists.
    assert "状态" in draft and "就绪" in draft and "草稿" in draft


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
