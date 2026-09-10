from pathlib import Path

import lamtools_core.skill_runtime as skill_runtime
from lamtools_core.tool.default_toolbox import build_core_toolbox


def _write_skill(root: Path, name: str, marker: str) -> Path:
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {marker}\n---\n{marker}\n",
        encoding="utf-8",
    )
    return path


def test_skill_runtime_orders_user_plugin_and_builtin_roots(monkeypatch, tmp_path: Path):
    user_root = tmp_path / "user-skills"
    legacy_root = tmp_path / "legacy" / "skills"
    plugin_root = tmp_path / "plugin-skills"
    builtin_root = tmp_path / "builtin-skills"
    monkeypatch.setattr(skill_runtime, "core_skills_root", lambda: user_root)
    monkeypatch.setattr(skill_runtime, "lam_home", lambda: legacy_root.parent)
    monkeypatch.setattr(skill_runtime, "builtin_core_skill_roots", lambda: (builtin_root,))

    runtime = skill_runtime.create_skill_runtime(plugin_skill_roots=[plugin_root])

    assert runtime.roots == tuple(
        path.resolve() for path in (user_root, legacy_root, plugin_root, builtin_root)
    )


def test_skill_runtime_resolves_workspace_before_user_plugin_and_builtin(monkeypatch, tmp_path: Path):
    user_root = tmp_path / "user-skills"
    legacy_root = tmp_path / "legacy" / "skills"
    plugin_root = tmp_path / "plugin-skills"
    builtin_root = tmp_path / "builtin-skills"
    workspace = tmp_path / "workspace"
    external_workspace = tmp_path / "external-workspace"
    monkeypatch.setattr(skill_runtime, "core_skills_root", lambda: user_root)
    monkeypatch.setattr(skill_runtime, "lam_home", lambda: legacy_root.parent)
    monkeypatch.setattr(skill_runtime, "builtin_core_skill_roots", lambda: (builtin_root,))

    workspace_skill = _write_skill(workspace / ".lam", "shared", "workspace")
    user_skill = _write_skill(user_root, "shared", "user")
    _write_skill(legacy_root, "shared", "legacy")
    _write_skill(plugin_root, "shared", "plugin")
    _write_skill(builtin_root, "shared", "builtin")
    runtime = skill_runtime.create_skill_runtime(plugin_skill_roots=[plugin_root])

    assert runtime.registry.get(workspace, "shared").location == workspace_skill
    assert runtime.registry.get(external_workspace, "shared").location == user_skill


def test_skill_runtime_resolves_plugin_before_additional_and_packaged_builtins(monkeypatch, tmp_path: Path):
    user_root = tmp_path / "user-skills"
    legacy_root = tmp_path / "legacy" / "skills"
    plugin_root = tmp_path / "plugin-skills"
    additional_builtin_root = tmp_path / "custom-core"
    packaged_builtin_root = tmp_path / "packaged-core"
    monkeypatch.setattr(skill_runtime, "core_skills_root", lambda: user_root)
    monkeypatch.setattr(skill_runtime, "lam_home", lambda: legacy_root.parent)
    monkeypatch.setattr(
        skill_runtime,
        "builtin_core_skill_roots",
        lambda: (packaged_builtin_root,),
    )

    plugin_skill = _write_skill(plugin_root, "shared", "plugin")
    _write_skill(additional_builtin_root / "skills", "shared", "additional builtin")
    _write_skill(packaged_builtin_root, "shared", "packaged builtin")

    runtime = skill_runtime.create_skill_runtime(
        plugin_skill_roots=[plugin_root],
        builtin_skill_roots=[additional_builtin_root],
    )

    assert runtime.registry.get(tmp_path / "workspace", "shared").location == plugin_skill


def test_default_core_toolbox_uses_authoritative_skill_runtime(tmp_path: Path):
    toolbox = build_core_toolbox(work_root=tmp_path / "workspace")

    skill = toolbox.skill_registry.get(tmp_path / "workspace", "office-documents")

    assert skill is not None
    assert skill.location.parent.name == "office-documents"
