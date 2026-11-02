"""user:“skill 界面也做成瀑布流，并分组管理”+技能分组的验收测试：
状态文件的分组存取、宿主 skill.group.* RPC、skill.list 载荷携带分组，
以及删除技能时分组痕迹一并清理。"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from lamtools_core.app import OperationCatalog
from lamtools_core.plugin_system.host import PluginHost
from lamtools_core.plugin_system.hooks import HookTrustStore
from lamtools_core.plugin_system.host_operations import register_host_operations
from lamtools_core.skills import Skill, SkillRegistry, SkillStateStore


@pytest.fixture()
def env(tmp_path: Path):
    host = PluginHost(roots=[tmp_path / "plugins"], state_path=tmp_path / "plugin-system.jsonc")
    store = SkillStateStore(tmp_path / "skill_state.json")
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
        skill_state_store=store,
        skill_registry_factory=lambda: registry,
        hook_trust_store=HookTrustStore(tmp_path / "hook_trust.json"),
    )
    return catalog, store


# ── SkillStateStore 分组存取 ──────────────────────────────────────────────


def test_store_group_list_round_trip(tmp_path: Path) -> None:
    store = SkillStateStore(tmp_path / "skill_state.json")
    assert store.groups() == []
    store.set_groups(["写作", "编程"])
    assert store.groups() == ["写作", "编程"]


def test_store_group_list_strips_and_dedupes(tmp_path: Path) -> None:
    store = SkillStateStore(tmp_path / "skill_state.json")
    store.set_groups(["写作", " 写作 ", "编程", ""])
    assert store.groups() == ["写作", "编程"]


def test_store_assign_rename_delete_group(tmp_path: Path) -> None:
    store = SkillStateStore(tmp_path / "skill_state.json")
    store.set_groups(["写作"])
    store.set_group("alpha", "写作")
    assert store.group_of("alpha") == "写作"
    # 未分组的技能返回空串，而不是抛错。
    assert store.group_of("beta") == ""

    store.rename_group("写作", "文案")
    assert store.groups() == ["文案"]
    assert store.group_of("alpha") == "文案"

    store.delete_group("文案")
    assert store.groups() == []
    assert store.group_of("alpha") == ""


def test_store_rejects_assignment_to_unknown_group(tmp_path: Path) -> None:
    store = SkillStateStore(tmp_path / "skill_state.json")
    with pytest.raises(ValueError):
        store.set_group("alpha", "不存在的分组")
    # 空串表示移出分组，永远合法。
    store.set_group("alpha", "")


def test_store_assignment_survives_enable_toggle(tmp_path: Path) -> None:
    store = SkillStateStore(tmp_path / "skill_state.json")
    store.set_groups(["写作"])
    store.set_group("alpha", "写作")
    store.set_enabled("alpha", False)
    assert store.group_of("alpha") == "写作"
    assert store.is_enabled("alpha") is False


# ── 宿主 RPC ──────────────────────────────────────────────────────────────


async def test_skill_list_carries_groups(env) -> None:
    catalog, store = env
    store.set_groups(["写作"])
    store.set_group("alpha", "写作")

    result = await catalog.execute("skill.list", {})
    assert result.status == "ok", result.payload
    assert result.payload["groups"] == ["写作"]
    by_name = {item["name"]: item for item in result.payload["skills"]}
    assert by_name["alpha"]["group"] == "写作"
    assert by_name["beta"]["group"] == ""


async def test_skill_group_create_rejects_empty_and_duplicates(env) -> None:
    catalog, _ = env
    ok = await catalog.execute("skill.group.create", {"name": " 编程 "})
    assert ok.status == "ok", ok.payload
    duplicate = await catalog.execute("skill.group.create", {"name": "编程"})
    assert duplicate.status == "error"
    empty = await catalog.execute("skill.group.create", {"name": "   "})
    assert empty.status == "error"


async def test_skill_group_assign_flow(env) -> None:
    catalog, store = env
    await catalog.execute("skill.group.create", {"name": "写作"})

    assigned = await catalog.execute("skill.group.assign", {"name": "beta", "group": "写作"})
    assert assigned.status == "ok", assigned.payload

    unknown = await catalog.execute("skill.group.assign", {"name": "beta", "group": "没有的"})
    assert unknown.status == "error"

    ungrouped = await catalog.execute("skill.group.assign", {"name": "beta", "group": ""})
    assert ungrouped.status == "ok", ungrouped.payload
    assert store.group_of("beta") == ""


async def test_skill_group_rename_and_delete_update_members(env) -> None:
    catalog, store = env
    await catalog.execute("skill.group.create", {"name": "写作"})
    await catalog.execute("skill.group.assign", {"name": "beta", "group": "写作"})

    renamed = await catalog.execute("skill.group.rename", {"from": "写作", "to": "文案"})
    assert renamed.status == "ok", renamed.payload
    assert store.group_of("beta") == "文案"
    missing = await catalog.execute("skill.group.rename", {"from": "没有的", "to": "x"})
    assert missing.status == "error"

    deleted = await catalog.execute("skill.group.delete", {"name": "文案"})
    assert deleted.status == "ok", deleted.payload
    assert store.groups() == []
    assert store.group_of("beta") == ""


async def test_skill_group_rejects_reserved_filter_names(env) -> None:
    # 界面用 all / ungrouped 做筛选哨兵；允许同名分组会让筛选无法区分。
    catalog, store = env
    for name in ("all", "ungrouped", "ALL"):
        created = await catalog.execute("skill.group.create", {"name": name})
        assert created.status == "error", name
    await catalog.execute("skill.group.create", {"name": "写作"})
    renamed = await catalog.execute("skill.group.rename", {"from": "写作", "to": "all"})
    assert renamed.status == "error"
    assert store.groups() == ["写作"]


async def test_skill_group_delete_unknown_name_is_an_error(env) -> None:
    catalog, _ = env
    deleted = await catalog.execute("skill.group.delete", {"name": "没有的"})
    assert deleted.status == "error"
    assert "不存在" in str(deleted.payload.get("error") or "")


async def test_skill_group_operations_preserve_enabled_state(env) -> None:
    catalog, _ = env
    await catalog.execute("skill.disable", {"name": "alpha"})
    await catalog.execute("skill.group.create", {"name": "写作"})
    await catalog.execute("skill.group.assign", {"name": "alpha", "group": "写作"})

    result = await catalog.execute("skill.list", {})
    by_name = {item["name"]: item for item in result.payload["skills"]}
    assert by_name["alpha"]["enabled"] is False
    assert by_name["alpha"]["group"] == "写作"


async def test_skill_delete_clears_group_assignment(tmp_path: Path) -> None:
    host = PluginHost(roots=[tmp_path / "plugins"], state_path=tmp_path / "plugin-system.jsonc")
    store = SkillStateStore(tmp_path / "skill_state.json")
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
        skill_state_store=store,
        skill_registry_factory=lambda: registry,
        hook_trust_store=HookTrustStore(tmp_path / "hook_trust.json"),
    )

    await catalog.execute("skill.group.create", {"name": "写作"})
    await catalog.execute("skill.group.assign", {"name": "alpha", "group": "写作"})
    deleted = await catalog.execute("skill.delete", {"name": "alpha"})
    assert deleted.status == "ok", deleted.payload
    # 技能删掉后，状态文件里不应残留它的分组记录。
    assert store.group_of("alpha") == ""
    assert store.groups() == ["写作"]


# ── CLI 能力（工具规则：GUI 能力要有对应的 CLI 能力）──────────────────────


def test_cli_registers_skill_group_subcommands() -> None:
    from lamtools_core.cli_commands.parse_resources import register_skill

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    register_skill(sub)
    assign = parser.parse_args(["skill", "group", "assign", "alpha", "--group", "写作"])
    assert assign.skill_command == "group"
    assert assign.group_command == "assign"
    assert assign.name == "alpha"
    assert assign.group == "写作"
    create = parser.parse_args(["skill", "group", "create", "写作"])
    assert create.group_command == "create"
    assert create.name == "写作"
    rename = parser.parse_args(["skill", "group", "rename", "--from", "写作", "--to", "文案"])
    assert rename.group_command == "rename"
    assert rename.from_group == "写作"
    assert rename.to_group == "文案"
