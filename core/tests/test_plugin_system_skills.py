"""Author-facing skills must ship with the rules they promise.

user:“这个后面在完整设计之后，我们再重新设计 create plugin 这个 skill 的
提示词”+作者工具是插件系统的一部分，内容退化要能被测试挡住。
"""

from __future__ import annotations

from lamtools_core.skill_runtime import builtin_core_skill_roots
from lamtools_core.skills import SkillRegistry


def load_skill(name: str):
    roots = builtin_core_skill_roots()
    assert roots, "built-in skill roots are missing"
    registry = SkillRegistry(explicit_roots=roots)
    skill = registry.get(None, name)
    assert skill is not None, f"skill '{name}' is not discoverable"
    return skill


def test_create_plugin_documents_the_v2_contract() -> None:
    skill = load_skill("create-plugin")
    content = skill.content

    assert "assembly" in content
    assert "overrides" in content
    assert "config.schema" in content or "config/schema.jsonc" in content
    assert "run_command" in content
    assert "LamToolsPluginPanels" in content


def test_port_plugin_starts_with_the_licence_check() -> None:
    skill = load_skill("port-plugin")
    content = skill.content.lower()

    assert "licence" in content or "license" in content
    assert "difference report" in content
    assert "run_command" in content
