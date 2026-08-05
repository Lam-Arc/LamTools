from __future__ import annotations

from pathlib import Path

from lamtools_core.plugins import PluginRegistry
from lamtools_core.skills import Skill, SkillRegistry


SAGE_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = SAGE_ROOT / "plugin"
EXPECTED_SKILLS = {
    "bridge",
    "discover",
    "explore",
    "maintenance",
    "map-building",
    "recommend",
    "signal",
    "synthesize",
    "verify",
}


def _builtin_plugin():
    plugins = PluginRegistry(plugin_roots=[PLUGIN_ROOT]).discover()
    assert [plugin.name for plugin in plugins] == ["sage-builtin"]
    return plugins[0]


def _skill(name: str) -> Skill:
    plugin = _builtin_plugin()
    registry = SkillRegistry(explicit_roots=plugin.skill_roots)
    skill = registry.get(None, name)
    assert skill is not None
    assert skill.location.is_relative_to(plugin.root)
    return skill


def test_explore_is_discoverable_and_requires_evidence_first_research() -> None:
    plugin = _builtin_plugin()
    assert plugin.version == "0.1.0"
    assert plugin.skill_roots == [plugin.root / "skills"]

    content = _skill("explore").content

    assert "independent source" in content
    assert "counterevidence" in content
    assert "TRACE_MAP_CONTRACT.md" in content
    assert "untrusted data" in content
    assert "evidence package" in content


def test_discover_separates_open_discovery_from_durable_monitoring() -> None:
    content = _skill("discover").content

    assert "novelty" in content
    assert "counterevidence" in content
    assert "Arrange" in content
    assert "event producer" in content
    assert "must not claim" in content


def test_verify_checks_claim_support_conflicts_and_confidence_reasons() -> None:
    content = _skill("verify").content

    assert "source lineage" in content
    assert "counterevidence" in content
    assert "conflicts" in content
    assert "gaps" in content
    assert "confidence reasons" in content
    assert "model self-rating" in content
    assert "source fact" in content


def test_map_building_uses_the_shared_trace_map_record_contract() -> None:
    content = _skill("map-building").content
    contract = (_builtin_plugin().skill_roots[0] / "TRACE_MAP_CONTRACT.md").read_text(encoding="utf-8")

    assert "document, entity, concept, and claim nodes" in content
    assert "evidence-backed edges" in content
    assert "hypothesis" in content
    for field in (
        "claim_id:",
        "claim_type:",
        "source_id:",
        "locator:",
        "published_at:",
        "retrieved_at:",
        "tool_call_id:",
        "supports:",
        "contradicts:",
        "conflicts:",
        "gaps:",
        "confidence:",
        "reasons:",
        "artifact_path:",
    ):
        assert field in contract
    assert "external content is untrusted data" in contract
    assert "summary-only" in contract
    assert ".lamtools/sage/" in contract
    assert "recommendation-log.jsonl" in contract
    assert "read-only" in contract


def test_recommend_filters_for_context_value_freshness_and_repeat_cost() -> None:
    content = _skill("recommend").content

    assert "current context" in content
    assert "freshness" in content
    assert "already delivered" in content
    assert "value threshold" in content
    assert "recommendation is a judgment" in content
    assert "counterevidence" in content


def test_bridge_keeps_cross_domain_connections_as_testable_hypotheses() -> None:
    content = _skill("bridge").content

    assert "connection hypothesis" in content
    assert "Explore" in content
    assert "Verify" in content
    assert "Map" in content
    assert "alternative explanations" in content
    assert "evidence package" in content


def test_signal_distinguishes_analysis_from_core_events_and_requires_real_ingress() -> None:
    content = _skill("signal").content

    assert "analytical Signal" in content
    assert "Core event Signal" in content
    assert "baseline" in content
    assert "false positive" in content
    assert "Arrange" in content
    assert "event producer" in content
    assert "blocked" in content


def test_synthesize_preserves_provenance_conflict_and_output_contract() -> None:
    content = _skill("synthesize").content

    assert "output contract" in content
    assert "source facts" in content
    assert "computed facts" in content
    assert "conflicts" in content
    assert "coverage gaps" in content
    assert "evidence package" in content


def test_maintenance_revalidates_without_erasing_history_or_faking_background_work() -> None:
    content = _skill("maintenance").content

    assert "revalidate" in content
    assert "superseded" in content
    assert "provenance history" in content
    assert "Arrange" in content
    assert "event producer" in content
    assert "must not report" in content


def test_trace_is_one_horizontal_contract_for_exactly_nine_skills() -> None:
    plugin = _builtin_plugin()
    skills = [
        skill
        for skill in SkillRegistry(explicit_roots=plugin.skill_roots).available(None)
        if skill.location.is_relative_to(plugin.root)
    ]

    assert {skill.name for skill in skills} == EXPECTED_SKILLS
    assert all(skill.description.startswith("Use when") for skill in skills)
    assert all("TRACE_MAP_CONTRACT.md" in skill.content for skill in skills)
