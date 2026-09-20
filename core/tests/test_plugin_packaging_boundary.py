"""Static contract checks for the Sunday backend plugin packaging boundary."""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = (ROOT / "core" / "lamtools-core-backend.spec").read_text(encoding="utf-8")
PACKAGE_SCRIPT = (ROOT / "scripts" / "package.ps1").read_text(encoding="utf-8")
RELEASE_WORKFLOW = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
RELEASE_SKILL = (ROOT / ".agents" / "skills" / "release-lamtools" / "SKILL.md").read_text(encoding="utf-8")

EXCLUDED_PLUGINS = {"emotion-ball-pet", "workflow"}


def _spec_excluded_plugins(spec: str) -> set[str]:
    match = re.search(r"_EXCLUDED_BUNDLED_PLUGINS\s*=\s*(\{[^\n]+\})", spec)
    assert match, "spec must declare the excluded bundled plugin set"
    value = ast.literal_eval(match.group(1))
    assert isinstance(value, set)
    return {str(item) for item in value}


def test_spec_excludes_optional_plugins_and_drops_workflow_hidden_imports() -> None:
    assert _spec_excluded_plugins(SPEC) == EXCLUDED_PLUGINS
    assert not re.search(r'"lamtools_core\.plugins\.bundled\.workflow(?:\.|")', SPEC)


def test_spec_embeds_manifest_declared_websearch_python_handler() -> None:
    assert '"lamtools_core.plugins.bundled.websearch.backend.operations"' in SPEC


def test_local_packaging_boundary_checks_excluded_and_required_plugins() -> None:
    assert 'foreach ($ExcludedPlugin in @("emotion-ball-pet", "workflow"))' in PACKAGE_SCRIPT
    assert 'foreach ($RequiredPlugin in @("git", "imagegen", "websearch"))' in PACKAGE_SCRIPT


def test_release_workflow_boundary_checks_excluded_and_required_plugins() -> None:
    assert 'foreach ($name in @("emotion-ball-pet", "workflow"))' in RELEASE_WORKFLOW
    assert 'foreach ($name in @("git", "imagegen", "websearch"))' in RELEASE_WORKFLOW


def test_release_skill_documents_the_same_plugin_boundary() -> None:
    assert "`resources/plugins/bundled/emotion-ball-pet`" in RELEASE_SKILL
    assert "`resources/plugins/bundled/workflow`" in RELEASE_SKILL
    assert "`git`、`websearch`、`imagegen`" in RELEASE_SKILL
    assert "四个必要内置插件" not in RELEASE_SKILL
