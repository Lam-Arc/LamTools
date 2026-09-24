from __future__ import annotations

import json
import re
from pathlib import Path

from lamtools_core.plugins._jsonc import load_jsonc_text


STUDY_ROOT = (
    Path(__file__).parents[1]
    / "src"
    / "lamtools_core"
    / "plugins"
    / "bundled"
    / "study"
)
CURATE_ROOT = STUDY_ROOT / "future" / "curate-notes"


def _notes_tool_spec() -> dict:
    manifest = load_jsonc_text(STUDY_ROOT / "tools.jsonc")
    return next(item for item in manifest["tools"] if item["name"] == "notes")


def _curate_text() -> str:
    return "\n".join(
        (CURATE_ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "SKILL.md",
            "references/notes.md",
            "evals/evals.json",
        )
    )


def test_notes_tool_cannot_claim_user_ownership() -> None:
    schema = _notes_tool_spec()["input_schema"]
    assert "user_edit" not in schema["properties"]
    changes = schema["properties"].get("changes")
    if changes:
        assert "user_edit" not in changes["items"]["properties"]


def test_study_cli_exposes_search_and_pin_parity() -> None:
    plugin = json.loads((STUDY_ROOT / "plugin.json").read_text(encoding="utf-8"))
    choices = plugin["cli"]["commands"][0]["arguments"][0]["choices"]
    assert {"search", "pin"} <= set(choices)


def test_study_prompt_routes_notes_and_keeps_first_turn_tool_contract() -> None:
    prompt = (STUDY_ROOT / "prompts" / "study-system.md").read_text(encoding="utf-8")
    assert "curate-notes for organizing study notes" in prompt
    assert "Show the notes tool from the first turn in Study mode" in prompt
    assert all(route in prompt for route in ("build-map", "teach", "answer", "take-exam"))
    assert "Raw → Resource → Note" in prompt
    assert "right sidebar" in prompt
    assert "NOTE_REGION_LOCKED" in prompt


def test_notes_tool_exposes_three_layers_without_legacy_writes() -> None:
    spec = _notes_tool_spec()
    schema = spec["input_schema"]
    actions = set(schema["properties"]["action"]["enum"])

    # Raw is host-captured and read-only for the Agent; Resource and Note are
    # the two Agent-maintained layers.
    assert {"raw_list", "raw_get"} <= actions
    assert {"resource_list", "resource_get", "resource_create", "resource_update"} <= actions
    assert {"list", "tree", "get", "graph", "backlinks", "create", "update"} <= actions
    assert "raw_capture" not in actions

    legacy_actions = {
        "append_blocks",
        "update_block",
        "update_blocks",
        "lock_range",
        "unlock_range",
    }
    assert not actions & legacy_actions
    assert not any("block" in action.casefold() for action in actions)
    assert not any("lock" in action.casefold() for action in actions)

    # A stale property or description can route an Agent back to the retired
    # append/update contract even when the enum is correct.
    assert not {"blocks", "changes", "block_id"} & set(schema["properties"])
    assert "blocks" not in str(spec.get("description", "")).casefold()


def test_three_layer_schema_keeps_lineage_and_revision_fields() -> None:
    properties = _notes_tool_spec()["input_schema"]["properties"]
    assert {"raw_id", "raw_ids"} <= set(properties)
    assert {"resource_id", "resource_ids"} <= set(properties)
    assert {"body_md", "expected_content_hash"} <= set(properties)
    assert "expected_revision" in properties
    assert "parent_id" in properties
    assert "path" in properties


def test_curate_skill_matches_three_layer_contract_and_protects_edits() -> None:
    skill = (CURATE_ROOT / "SKILL.md").read_text(encoding="utf-8")
    notes = (CURATE_ROOT / "references" / "notes.md").read_text(encoding="utf-8")
    combined = skill + "\n" + notes

    assert 'version: "4.0.0"' in skill
    assert all(layer in combined for layer in ("Raw", "Resource", "Note"))
    assert "raw_ids" in combined and "resource_ids" in combined
    assert "Markdown" in combined and "frontmatter" in combined
    assert "parent_id" in combined and "backlinks" in combined and "graph" in combined
    assert "NOTE_REGION_LOCKED" in combined
    assert "reason" in combined and "overlap" in combined
    assert "REVISION_CONFLICT" in combined
    assert "CONTENT_HASH_CONFLICT" in combined
    assert "unsaved draft" in combined
    assert "lock prevents Agent edits" in combined

    # The skill must no longer teach the retired append/update or payload-owned
    # ownership model.  Generic prose may discuss protected ranges, but no
    # retired action or error name may be routable from the skill.
    retired = (
        "append_blocks",
        "update_block",
        "update_blocks",
        "NOTE_BLOCK_LOCKED",
        "user_edit",
        "lock_range",
        "unlock_range",
    )
    assert not any(token in combined for token in retired)


def test_curate_skill_references_are_real_and_fallback_is_source_honest() -> None:
    skill = (CURATE_ROOT / "SKILL.md").read_text(encoding="utf-8")
    linked = re.findall(r"\]\(([^)]+)\)", skill)
    assert linked
    for relative in linked:
        if relative.startswith("references/"):
            target = CURATE_ROOT / relative
            assert target.is_file(), relative
            assert target.read_text(encoding="utf-8").strip(), relative

    evals = json.loads((CURATE_ROOT / "evals" / "evals.json").read_text(encoding="utf-8"))
    unavailable = next(case for case in evals["evals"] if case["id"] == 8)
    assert "不可用" in unavailable["expected_output"]
    assert "尚未开启" not in unavailable["expected_output"]
    fixture = json.loads(
        (CURATE_ROOT / "evals" / "files" / "case-08.json").read_text(encoding="utf-8")
    )
    assert "notes_enabled" not in fixture
    assert fixture["notes_tool_visible"] is True
    assert fixture["notes_service_available"] is False
    assert fixture["service_error"]


def test_eval_cases_do_not_reintroduce_retired_note_contract() -> None:
    text = _curate_text()
    assert not re.search(r"\b(?:append_blocks|update_blocks?|NOTE_BLOCK_LOCKED|user_edit)\b", text)
