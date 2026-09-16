import sys
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


def test_standard_openai_yaml_can_make_support_skill_explicit_only(tmp_path: Path):
    root = tmp_path / "skills"
    skill_path = _write_skill(root, "support-runtime", "support runtime")
    agents = skill_path.parent / "agents"
    agents.mkdir()
    (agents / "openai.yaml").write_text(
        "policy:\n  allow_implicit_invocation: false\n",
        encoding="utf-8",
    )
    registry = skill_runtime.SkillRegistry(explicit_roots=[root])

    skill = registry.get(tmp_path / "workspace", "support-runtime")

    assert skill is not None
    assert skill.allow_implicit_invocation is False
    assert "support-runtime" not in registry.prompt_index(tmp_path / "workspace")
    assert "support runtime" in registry.load_prompt_content(
        tmp_path / "workspace", "support-runtime"
    )


def test_openai_yaml_policy_change_invalidates_registry_cache(tmp_path: Path):
    root = tmp_path / "skills"
    skill_path = _write_skill(root, "toggle", "toggle support")
    agents = skill_path.parent / "agents"
    agents.mkdir()
    policy = agents / "openai.yaml"
    policy.write_text("policy:\n  allow_implicit_invocation: false\n", encoding="utf-8")
    registry = skill_runtime.SkillRegistry(explicit_roots=[root])
    assert "toggle" not in registry.prompt_index(tmp_path / "workspace")

    policy.write_text("policy:\n  allow_implicit_invocation: true\n# changed\n", encoding="utf-8")

    assert "toggle" in registry.prompt_index(tmp_path / "workspace")


def test_builtin_core_skill_roots_uses_frozen_bundle_resources(monkeypatch, tmp_path: Path):
    bundled = tmp_path / "resources" / "skills"
    bundled.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert skill_runtime.builtin_core_skill_roots() == (bundled,)


def test_builtin_core_skill_roots_falls_back_when_frozen_bundle_root_is_absent(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    roots = skill_runtime.builtin_core_skill_roots()

    assert roots
    assert roots[0].name == "skills"
