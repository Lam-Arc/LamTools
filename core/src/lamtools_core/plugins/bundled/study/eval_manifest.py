"""Validate Study skill eval wiring without claiming model behavior was tested.

This module uses the same bundled-plugin assembly and SkillRegistry as Core. It
checks mode isolation, skill-group membership, tool declarations, relative
references, and all eval fixtures, then emits one NOT_RUN record per behavioral
case. A separate runner with an explicitly configured production model must
replace those records with real outputs and traces.
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


STUDY_MODE = "study:study"
ACTIVE_SKILLS = (
    "build-map",
    "teach",
    "teach-humanities",
    "teach-science",
    "answer",
    "take-exam",
    "curate-notes",
)
FUTURE_SKILLS: tuple[str, ...] = ()
# A group entry owns the shared protocol and names its members; a member adds
# subject rules and is reachable only through the entry, so it must stay out of
# the implicit index.
SKILL_GROUPS: dict[str, tuple[str, ...]] = {
    "teach": ("teach-humanities", "teach-science"),
}
REQUIRED_TOOLS = {
    "build_knowledge_net",
    "get_knowledge_net",
    "exam",
    "sign",
    "notes",
    "load_skill",
    "read_file",
    "web_search",
    "web_fetch",
}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def build_manifest(*, work_root: Path | None = None) -> dict[str, Any]:
    resolved_work_root = (work_root or Path.cwd()).resolve()
    with tempfile.TemporaryDirectory(prefix="lamtools-study-eval-") as data_dir:
        assembly = assemble_core_agent_plugins(
            data_dir=Path(data_dir),
            work_root=resolved_work_root,
            plugin_roots=[],
        )
        study = next(plugin for plugin in assembly["plugins"] if plugin.id == "study")
        runtime = create_skill_runtime(
            plugin_skill_roots=assembly["skill_roots"],
            plugin_skill_modes=assembly["skill_modes"],
        )

        study_mode = next(mode for mode in study.ui.modes if mode.id == "study")
        mode_tools = set(study_mode.tools)
        missing_tools = sorted(REQUIRED_TOOLS - mode_tools)
        if missing_tools:
            raise RuntimeError(f"Study mode misses required tools: {', '.join(missing_tools)}")

        records: list[dict[str, Any]] = []
        reference_count = 0
        skill_locations: dict[str, Path] = {}
        for name in ACTIVE_SKILLS:
            if runtime.registry.get(resolved_work_root, name, active_mode="execute") is not None:
                raise RuntimeError(f"Study skill leaked into execute mode: {name}")
            skill = runtime.registry.get(resolved_work_root, name, active_mode=STUDY_MODE)
            if skill is None:
                raise RuntimeError(f"Study skill unavailable in {STUDY_MODE}: {name}")
            skill_locations[name] = skill.location

        mode_index = runtime.registry.prompt_index(resolved_work_root, active_mode=STUDY_MODE)
        for entry, members in SKILL_GROUPS.items():
            entry_skill = runtime.registry.get(resolved_work_root, entry, active_mode=STUDY_MODE)
            if entry_skill is None:
                raise RuntimeError(f"Skill group entry unavailable in {STUDY_MODE}: {entry}")
            if not entry_skill.allow_implicit_invocation or f"- {entry}:" not in mode_index:
                raise RuntimeError(f"Skill group entry must stay implicitly invocable: {entry}")
            for member in members:
                member_skill = runtime.registry.get(resolved_work_root, member, active_mode=STUDY_MODE)
                if member_skill is None:
                    raise RuntimeError(f"Skill group member unavailable in {STUDY_MODE}: {member}")
                if member_skill.allow_implicit_invocation:
                    raise RuntimeError(f"Skill group member must not be implicitly invocable: {member}")
                if f"- {member}:" in mode_index:
                    raise RuntimeError(f"Skill group member leaked into the mode index: {member}")
                if member not in entry_skill.content:
                    raise RuntimeError(f"Skill group entry {entry} does not name its member: {member}")

        for name in FUTURE_SKILLS:
            if runtime.registry.get(resolved_work_root, name, active_mode=STUDY_MODE) is not None:
                raise RuntimeError(f"Future Study skill registered without a capability gate: {name}")
            location = study.root / "future" / name / "SKILL.md"
            if not location.is_file():
                raise FileNotFoundError(location)
            skill_locations[name] = location

        for name, location in skill_locations.items():
            raw = location.read_text(encoding="utf-8")
            for relative in re.findall(r"\]\((references/[^)]+\.md)\)", raw):
                reference = location.parent / relative
                if not reference.is_file():
                    raise FileNotFoundError(reference)
                reference.read_text(encoding="utf-8")
                reference_count += 1

            eval_manifest = _load_json(location.parent / "evals" / "evals.json")
            if eval_manifest.get("skill_name") != name:
                raise ValueError(f"eval skill_name mismatch: {name}")
            cases = eval_manifest.get("evals")
            if not isinstance(cases, list) or len(cases) != 8:
                raise ValueError(f"expected 8 eval cases for {name}")

            for case in cases:
                fixtures: list[str] = []
                for relative in case.get("files", []):
                    fixture = location.parent / str(relative)
                    _load_json(fixture)
                    fixtures.append(str(fixture))
                records.append(
                    {
                        "status": "NOT_RUN",
                        "case_id": f"{name}:{case.get('id')}",
                        "skill": name,
                        "host_registration": "active" if name in ACTIVE_SKILLS else "future_gated",
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
            "mode": STUDY_MODE,
            "active_skills": list(ACTIVE_SKILLS),
            "future_gated_skills": list(FUTURE_SKILLS),
            "skill_groups": {entry: list(members) for entry, members in SKILL_GROUPS.items()},
            "tool_ids": sorted(mode_tools),
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
