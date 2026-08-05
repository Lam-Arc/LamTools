from pathlib import Path

import lamtools_core.composer_commands as composer_commands
from lamtools_core.composer_commands import (
    build_composer_command_catalog,
    default_core_resource_roots,
    default_core_skill_roots,
    load_command_catalog,
    prepare_composer_input,
)
from lamtools_core.skills import SkillRegistry


def write_json(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_default_core_resource_roots_prefers_packaged_resources(monkeypatch, tmp_path: Path):
    package_root = tmp_path / "site-packages" / "lamtools_core"
    module_path = package_root / "composer_commands.py"
    resource_root = package_root / "resources"
    resource_root.mkdir(parents=True)
    monkeypatch.setattr(composer_commands, "__file__", str(module_path))

    assert default_core_resource_roots() == [resource_root]


def test_default_core_skill_roots_do_not_expose_the_whole_core_package(monkeypatch, tmp_path: Path):
    package_root = tmp_path / "site-packages" / "lamtools_core"
    module_path = package_root / "composer_commands.py"
    skill_root = package_root / "resources" / "skills"
    skill_root.mkdir(parents=True)
    monkeypatch.setattr(composer_commands, "__file__", str(module_path))

    assert default_core_skill_roots() == [skill_root]


def test_catalog_loads_core_before_member_and_blocks_overrides(tmp_path: Path):
    core = tmp_path / "core"
    member = tmp_path / "members" / "writer"
    write_json(
        core / "config" / "command" / "compact.json",
        '{"name":"compact","title":"Compact","description":"Core compact","icon":"archive","action":"run_action"}',
    )
    write_json(
        member / "config" / "command" / "git-status.json",
        '{"name":"git status","title":"Git status","description":"Show git status","icon":"git-branch","action":"run_action"}',
    )
    write_json(
        member / "config" / "command" / "compact.json",
        '{"name":"compact","title":"Bad","description":"Override","icon":"x","action":"run_action"}',
    )

    catalog = load_command_catalog(core_roots=[core], member_roots=[member])

    assert [item.name for item in catalog] == ["compact", "git status"]
    assert catalog[0].source == "core"
    assert catalog[1].source == "member"


def test_member_config_disables_core_command_for_that_member(tmp_path: Path):
    core = tmp_path / "core"
    writer = tmp_path / "members" / "writer"
    artist = tmp_path / "members" / "artist"
    write_json(
        core / "config" / "command" / "fork.json",
        '{"name":"fork","title":"Fork","description":"Fork session","icon":"git-branch","action":"run_action"}',
    )
    write_json(
        writer / "config" / "command" / "config.json",
        '{"disabled_core_commands":["fork","unknown"]}',
    )

    writer_catalog = load_command_catalog(core_roots=[core], member_roots=[writer])
    artist_catalog = load_command_catalog(core_roots=[core], member_roots=[artist])

    assert [item.name for item in writer_catalog] == []
    assert [item.name for item in artist_catalog] == ["fork"]


def test_member_cannot_replace_disabled_core_command_name(tmp_path: Path):
    core = tmp_path / "core"
    member = tmp_path / "members" / "member"
    write_json(
        core / "config" / "command" / "fork.json",
        '{"name":"fork","title":"Fork","description":"Core fork","icon":"git-branch","action":"run_action"}',
    )
    write_json(
        member / "config" / "command" / "config.json",
        '{"disabled_core_commands":["fork"]}',
    )
    write_json(
        member / "config" / "command" / "fork.json",
        '{"name":"fork","title":"Member fork","description":"Override disabled core","icon":"x","action":"run_action"}',
    )

    catalog = load_command_catalog(core_roots=[core], member_roots=[member])

    assert [item.name for item in catalog] == []


def test_core_catalog_includes_skills_and_core_prepares_skill_with_attachments(tmp_path: Path):
    core = tmp_path / "core"
    work_root = tmp_path / "workspace"
    write_json(
        core / "config" / "command" / "compact.json",
        '{"name":"compact","title":"Compact","description":"Compact context","icon":"archive","action":"run_action"}',
    )
    skill_dir = work_root / ".lam" / "skills" / "reviewer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: reviewer\ndescription: Review changes\n---\nREVIEW WORKFLOW\n",
        encoding="utf-8",
    )
    registry = SkillRegistry()

    catalog = build_composer_command_catalog(
        core_roots=[core],
        member_roots=[],
        work_root=work_root,
        skill_registry=registry,
    )
    prepared = prepare_composer_input(
        work_root=work_root,
        input_items=[
            {"type": "skill", "name": "reviewer", "source_text": "/reviewer"},
            {"type": "text", "text": " check this"},
            {"type": "attachment", "attachment_id": "att-1", "filename": "note.md"},
        ],
        skill_registry=registry,
    )

    actions = {item.name: item.action for item in catalog}
    assert actions["compact"] == "run_action"
    assert actions["reviewer"] == "insert_token"
    assert prepared.visible_items == [
        {"type": "text", "text": "/reviewer"},
        {"type": "text", "text": " check this"},
        {"type": "attachment", "attachment_id": "att-1", "filename": "note.md"},
    ]
    assert prepared.visible_text == "/reviewer check this"
    assert "REVIEW WORKFLOW" in prepared.runtime_text
    assert prepared.runtime_items[-1] == {
        "type": "attachment",
        "attachment_id": "att-1",
        "filename": "note.md",
    }
