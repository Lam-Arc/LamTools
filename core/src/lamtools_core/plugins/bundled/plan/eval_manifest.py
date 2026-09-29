"""Validate the plan plugin's eval wiring without claiming model behavior was tested.

It uses the same bundled-plugin assembly and skill runtime as Core: it checks
that the plan plugin exposes its three skills and the plan_package tool, that
every reference a skill links exists, and that all eval fixtures parse, then
emits one NOT_RUN record per behavioral case. A separate runner with an
explicitly configured production model must replace those records with real
outputs and traces; this module never asserts that a case passed.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from lamtools_core.app.base_agent import assemble_core_agent_plugins
from lamtools_core.skill_runtime import create_skill_runtime


PLUGIN_ID = "plan"
PLAN_MODE = "execute"
ACTIVE_SKILLS = ("draft-plan", "refine-plan", "execute-plan")
# What an executing turn must be able to see: the package itself, the live
# checklist it installs, the skill loader, and file reads for the plan's docs.
REQUIRED_TOOLS = {"plan_package", "write_checklist", "update_checklist", "load_skill", "read_file"}
REFERENCE_LINK = re.compile(r"\]\((references/[^)]+\.md)\)")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _resolve_reference(skill_root: Path, relative: str) -> Path | None:
    """A skill may keep its references beside it or in the shared pool."""

    for candidate in (skill_root / relative, skill_root.parent / relative):
        if candidate.is_file():
            return candidate
    return None


def build_manifest(*, work_root: Path | None = None) -> dict[str, Any]:
    resolved_work_root = (work_root or Path.cwd()).resolve()
    with tempfile.TemporaryDirectory(prefix="lamtools-plan-eval-") as data_dir:
        assembly = assemble_core_agent_plugins(
            data_dir=Path(data_dir),
            work_root=resolved_work_root,
            plugin_roots=[],
        )
        plugin = next((item for item in assembly["plugins"] if item.id == PLUGIN_ID), None)
        if plugin is None:
            raise RuntimeError("the plan plugin is not discovered in the default assembly")
        if not plugin.enabled:
            raise RuntimeError("the plan plugin is disabled in a fresh assembly")

        runtime = create_skill_runtime(
            plugin_skill_roots=assembly["skill_roots"],
            plugin_skill_modes=assembly["skill_modes"],
        )

        skill_locations: dict[str, Path] = {}
        for name in ACTIVE_SKILLS:
            skill = runtime.registry.get(resolved_work_root, name, active_mode=PLAN_MODE)
            if skill is None:
                raise RuntimeError(f"plan skill unavailable in {PLAN_MODE}: {name}")
            skill_locations[name] = skill.location

        tool_names = {
            tool.name
            for group in assembly["plugin_tool_groups"]
            if group["name"] == PLUGIN_ID
            for tool in group["tools"]
        }
        missing_tools = sorted({"plan_package"} - tool_names)
        if missing_tools:
            raise RuntimeError("plan plugin does not declare: " + ", ".join(missing_tools))

        records: list[dict[str, Any]] = []
        reference_count = 0
        for name in ACTIVE_SKILLS:
            location = skill_locations[name]
            raw = location.read_text(encoding="utf-8")
            for relative in REFERENCE_LINK.findall(raw):
                reference = _resolve_reference(location.parent, relative)
                if reference is None:
                    raise FileNotFoundError(f"{name} links a missing reference: {relative}")
                if not reference.read_text(encoding="utf-8").strip():
                    raise ValueError(f"empty reference behind {name}: {relative}")
                reference_count += 1

            eval_manifest = _load_json(location.parent / "evals" / "evals.json")
            if eval_manifest.get("skill_name") != name:
                raise ValueError(f"eval skill_name mismatch: {name}")
            cases = eval_manifest.get("evals")
            if not isinstance(cases, list) or not cases:
                raise ValueError(f"no eval cases for {name}")

            for case in cases:
                fixtures: list[str] = []
                for relative in case.get("files", []):
                    fixture = location.parent / str(relative)
                    payload = _load_json(fixture)
                    if payload.get("case_id") != f"{name}-{int(case['id']):02d}":
                        raise ValueError(f"fixture case_id mismatch: {fixture}")
                    fixtures.append(str(fixture))
                if not fixtures:
                    raise ValueError(f"{name}:{case.get('id')} has no fixture file")
                records.append(
                    {
                        "status": "NOT_RUN",
                        "case_id": f"{name}:{case.get('id')}",
                        "skill": name,
                        "host_registration": "active",
                        "prompt": case.get("prompt"),
                        "fixture_files": fixtures,
                        "assertion_count": len(case.get("assertions", [])),
                        "output": None,
                        "tool_trace": [],
                        "hard_failures": [],
                        "reason": "Production model execution was not performed by the static host adapter.",
                    }
                )

    return {
        "schema_version": 1,
        "host_smoke": {
            "status": "PASS",
            "mode": PLAN_MODE,
            "active_skills": list(ACTIVE_SKILLS),
            "tool_ids": sorted(tool_names),
            "tool_ids_expected_by_mode": sorted(REQUIRED_TOOLS),
            "reference_links_checked": reference_count,
            "behavioral_claim": False,
        },
        "behavioral_summary": {
            "total": len(records),
            "run": 0,
            "not_run": len(records),
        },
        "cases": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = build_manifest()
    payload = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
