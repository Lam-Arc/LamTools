"""user:“我希望能够在插件界面中看见 skill 的调用统计”+技能调用统计的验收测试：
使用账本的记录/汇总/重置、load_skill 成功后计数、skill.list 与 skill.usage
RPC 的载荷，以及 GUI 能力的 CLI 对应命令。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from lamtools_core.app import OperationCatalog
from lamtools_core.plugin_system.host import PluginHost
from lamtools_core.plugin_system.hooks import HookTrustStore
from lamtools_core.plugin_system.host_operations import register_host_operations
from lamtools_core.skills import Skill, SkillRegistry, SkillStateStore, SkillUsageStore
from lamtools_core.tool import ToolCall
from lamtools_core.tool.default_toolbox import build_core_toolbox


@pytest.fixture()
def env(tmp_path: Path):
    host = PluginHost(roots=[tmp_path / "plugins"], state_path=tmp_path / "plugin-system.jsonc")
    state = SkillStateStore(tmp_path / "skill_state.json")
    usage = SkillUsageStore(tmp_path / "skill_usage.json")
    registry = SkillRegistry(
        explicit_roots=(),
        runtime_skills=lambda: [
            Skill(name="alpha", description="Alpha skill", location=None, content="A"),
            Skill(name="beta", description="Beta skill", location=None, content="B"),
        ],
    )
    catalog = OperationCatalog()
    register_host_operations(
        catalog,
        host,
        work_root=tmp_path,
        data_dir=tmp_path / "data",
        skill_state_store=state,
        skill_usage_store=usage,
        skill_registry_factory=lambda: registry,
        hook_trust_store=HookTrustStore(tmp_path / "hook_trust.json"),
    )
    return catalog, state, usage


# ── 使用账本 ──────────────────────────────────────────────────────────────


def test_usage_store_counts_and_timestamps(tmp_path: Path) -> None:
    store = SkillUsageStore(tmp_path / "skill_usage.json")
    assert store.snapshot() == {}

    first = store.record("alpha")
    second = store.record("alpha")

    entry = store.snapshot()["alpha"]
    assert entry["count"] == 2
    assert entry["first_used_at"] == first["first_used_at"]
    assert entry["last_used_at"] == second["last_used_at"]
    # 时间戳可被前端 Date 解析（UTC ISO 8601）。
    assert entry["first_used_at"].endswith("Z")
    assert store.snapshot()["alpha"]["model_count"] == 2


def test_usage_store_tracks_model_and_user_sources(tmp_path: Path) -> None:
    store = SkillUsageStore(tmp_path / "skill_usage.json")
    store.record("alpha", source="model")
    store.record("alpha", source="user")
    entry = store.snapshot()["alpha"]
    assert entry["count"] == 2
    assert entry["model_count"] == 1
    assert entry["user_count"] == 1


def test_usage_store_summary_and_reset(tmp_path: Path) -> None:
    store = SkillUsageStore(tmp_path / "skill_usage.json")
    store.record("alpha")
    store.record("alpha")
    store.record("beta")

    summary = store.summary()
    assert summary["total_calls"] == 3
    assert summary["skills_used"] == 2

    store.reset("alpha")
    assert "alpha" not in store.snapshot()
    assert store.summary()["total_calls"] == 1

    store.reset()
    assert store.snapshot() == {}
    assert store.summary()["total_calls"] == 0


def test_usage_store_ignores_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "skill_usage.json"
    path.write_text("{not json", encoding="utf-8")
    store = SkillUsageStore(path)
    assert store.snapshot() == {}
    # 坏账本不应阻止新的调用被记下来。
    assert store.record("alpha")["count"] == 1


def test_usage_store_ignores_blank_name(tmp_path: Path) -> None:
    store = SkillUsageStore(tmp_path / "skill_usage.json")
    assert store.record("   ") == {}
    assert store.snapshot() == {}


# ── load_skill 记账 ───────────────────────────────────────────────────────


async def test_load_skill_records_usage(tmp_path: Path) -> None:
    skill_dir = tmp_path / ".lam" / "skills" / "alpha"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: demo\n---\nbody\n", encoding="utf-8"
    )
    state = SkillStateStore(tmp_path / "data" / "skill_state.json")
    usage_path = tmp_path / "data" / "skill_usage.json"
    toolbox = build_core_toolbox(
        work_root=tmp_path,
        skill_state_store=state,
        permission_preset="full_access",
        approval_policy="auto_approve",
    )

    result = await toolbox.execute(
        ToolCall(id="call-1", name="load_skill", arguments={"name": "alpha"})
    )
    assert result.status == "ok", result.error

    recorded = SkillUsageStore(usage_path).snapshot()
    assert recorded["alpha"]["count"] == 1


async def test_failed_load_skill_is_not_counted(tmp_path: Path) -> None:
    state = SkillStateStore(tmp_path / "data" / "skill_state.json")
    toolbox = build_core_toolbox(
        work_root=tmp_path,
        skill_state_store=state,
        permission_preset="full_access",
        approval_policy="auto_approve",
    )
    result = await toolbox.execute(
        ToolCall(id="call-1", name="load_skill", arguments={"name": "missing"})
    )
    assert result.status == "failed"
    assert not (tmp_path / "data" / "skill_usage.json").exists()


# ── 宿主 RPC ──────────────────────────────────────────────────────────────


async def test_skill_list_carries_usage_and_summary(env) -> None:
    catalog, _, usage = env
    usage.record("alpha")
    usage.record("alpha")
    usage.record("beta")

    result = await catalog.execute("skill.list", {})
    assert result.status == "ok", result.payload

    by_name = {item["name"]: item for item in result.payload["skills"]}
    assert by_name["alpha"]["usage"]["count"] == 2
    assert by_name["beta"]["usage"]["count"] == 1
    assert result.payload["usage_summary"]["total_calls"] == 3
    assert result.payload["usage_summary"]["skills_used"] == 2


async def test_skill_list_reports_zero_for_never_used(env) -> None:
    catalog, _, _ = env
    result = await catalog.execute("skill.list", {})
    by_name = {item["name"]: item for item in result.payload["skills"]}
    assert by_name["alpha"]["usage"]["count"] == 0
    assert by_name["alpha"]["usage"]["last_used_at"] == ""


async def test_skill_usage_rpc_returns_every_record(env) -> None:
    catalog, _, usage = env
    usage.record("alpha")
    # 已删除技能的历史记录仍应可见（统计是历史，不是列表的投影）。
    usage.record("old-skill")

    result = await catalog.execute("skill.usage", {})
    assert result.status == "ok", result.payload
    assert set(result.payload["skills"]) == {"alpha", "old-skill"}
    assert result.payload["summary"]["total_calls"] == 2


async def test_skill_delete_clears_usage_record(tmp_path: Path) -> None:
    host = PluginHost(roots=[tmp_path / "plugins"], state_path=tmp_path / "plugin-system.jsonc")
    state = SkillStateStore(tmp_path / "skill_state.json")
    usage = SkillUsageStore(tmp_path / "skill_usage.json")
    skill_dir = tmp_path / ".lam" / "skills" / "alpha"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("---\nname: alpha\ndescription: demo\n---\nbody\n", encoding="utf-8")
    registry = SkillRegistry(
        explicit_roots=(),
        runtime_skills=lambda: [
            Skill(name="alpha", description="demo", location=skill_file, content="body"),
        ],
    )
    catalog = OperationCatalog()
    register_host_operations(
        catalog,
        host,
        work_root=tmp_path,
        data_dir=tmp_path / "data",
        skill_state_store=state,
        skill_usage_store=usage,
        skill_registry_factory=lambda: registry,
        hook_trust_store=HookTrustStore(tmp_path / "hook_trust.json"),
    )
    usage.record("alpha")

    deleted = await catalog.execute("skill.delete", {"name": "alpha"})
    assert deleted.status == "ok", deleted.payload
    assert "alpha" not in usage.snapshot()


def test_slash_command_usage_is_recorded_as_user(tmp_path: Path) -> None:
    from lamtools_core.composer_commands import prepare_composer_input

    skill_dir = tmp_path / ".lam" / "skills" / "alpha"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: demo\n---\nbody\n", encoding="utf-8"
    )
    state = SkillStateStore(tmp_path / "data" / "skill_state.json")

    prepare_composer_input(
        work_root=tmp_path,
        input_items=[{"type": "skill", "name": "alpha"}],
        skill_registry=SkillRegistry(explicit_roots=()),
        skill_state_store=state,
    )

    entry = SkillUsageStore(tmp_path / "data" / "skill_usage.json").snapshot()["alpha"]
    assert entry["count"] == 1
    assert entry["user_count"] == 1
    assert entry["model_count"] == 0


# ── CLI 能力（工具规则：GUI 能力要有对应的 CLI 能力）──────────────────────


def test_cli_registers_skill_usage_subcommand() -> None:
    from lamtools_core.cli_commands.parse_resources import register_skill

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    register_skill(sub)
    parsed = parser.parse_args(["skill", "usage"])
    assert parsed.skill_command == "usage"
    assert parsed.func.__name__ == "cmd_skill_usage"
