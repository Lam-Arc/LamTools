"""Static contract checks for the Sunday backend plugin packaging boundary."""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = (ROOT / "core" / "lamtools-core-backend.spec").read_text(encoding="utf-8")
PACKAGE_SCRIPT = (ROOT / "scripts" / "package.ps1").read_text(encoding="utf-8")
RELEASE_WORKFLOW = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
def _release_skill() -> str:
    """惰性读取：.agents/ 是本地目录，收集阶段读会让独立工作树直接崩。"""
    return (ROOT / ".agents" / "skills" / "release-lamtools" / "SKILL.md").read_text(
        encoding="utf-8"
    )

EXCLUDED_PLUGINS = {"workflow"}


def _declared_plugin_lists(script: str) -> list[set[str]]:
    """Every ``foreach (... in @("a", "b"))`` plugin list in a PowerShell step.

    Pinning the whole loop text made these checks fail whenever the list grew,
    even though a longer exclusion list is strictly safer.  Parsing the lists
    keeps the contract about which plugins are excluded/required, and lets the
    local script and the release workflow be compared with each other.
    """
    return [
        {item.strip().strip('"') for item in match.split(",") if item.strip().strip('"')}
        for match in re.findall(r'foreach \(\$\w+ in @\(([^)]*)\)\)', script)
    ]


def _excluded_plugins(script: str) -> set[str]:
    matches = [names for names in _declared_plugin_lists(script) if "workflow" in names]
    assert len(matches) == 1, "each build path must declare exactly one excluded plugin list"
    return matches[0]


def _required_plugins(script: str) -> set[str]:
    matches = [names for names in _declared_plugin_lists(script) if "imagegen" in names]
    assert len(matches) == 1, "each build path must declare exactly one required plugin list"
    return matches[0]


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
    excluded = _excluded_plugins(PACKAGE_SCRIPT)
    required = _required_plugins(PACKAGE_SCRIPT)

    assert EXCLUDED_PLUGINS <= excluded
    assert {"imagegen", "websearch"} <= required
    # A plugin cannot be both required and forbidden: that combination would
    # make the build fail no matter what the spec embedded.
    assert not (excluded & required)


def test_release_workflow_boundary_checks_excluded_and_required_plugins() -> None:
    excluded = _excluded_plugins(RELEASE_WORKFLOW)
    required = _required_plugins(RELEASE_WORKFLOW)

    assert EXCLUDED_PLUGINS <= excluded
    assert {"imagegen", "websearch"} <= required
    assert not (excluded & required)
    # The local script and CI must enforce the same boundary; a plugin checked
    # in one place and not the other ships silently.
    assert excluded == _excluded_plugins(PACKAGE_SCRIPT)
    assert required == _required_plugins(PACKAGE_SCRIPT)


def test_release_skill_documents_the_same_plugin_boundary() -> None:
    release_skill = _release_skill()
    assert "`resources/plugins/bundled/workflow`" in release_skill
    required_line = re.search(r"(?m)^- Still contains (.+)$", release_skill)
    assert required_line, "release skill must explicitly list the required bundled plugins"
    required_plugins = re.findall(r"`([^`]+)`", required_line.group(1))
    assert len(required_plugins) == 3
    assert set(required_plugins) == {"git", "websearch", "imagegen"}
    assert "四个必要内置插件" not in release_skill
