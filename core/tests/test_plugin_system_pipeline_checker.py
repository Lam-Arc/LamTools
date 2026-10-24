"""The bundled pipeline checker finds the exports a replacement forgot.

user:“管道完整性的校验，对于那些插件开发者来说，甚至都可以开发一个插件来做”
+这颗插件要能真的跑起来，而不只是声明。
"""

from __future__ import annotations

import json
from pathlib import Path

from lamtools_core.plugin_system import PluginHost, PluginSystemRuntime
from lamtools_core.plugin_system.paths import bundled_plugins_dir
from lamtools_core.tool import ToolCall
from lamtools_core.tool.default_toolbox import build_core_toolbox


def assemble_spec(tmp_path: Path):
    host = PluginHost(
        roots=[bundled_plugins_dir()],
        state_path=tmp_path / "plugin-system.jsonc",
    )
    manifests = host.discover()
    artifacts = PluginSystemRuntime(host).assemble(manifests=manifests)
    return next(spec for spec in artifacts.tools if spec.name == "check_exports")


async def test_reports_the_exports_the_replacement_dropped(tmp_path: Path) -> None:
    spec = assemble_spec(tmp_path)
    assert spec.metadata["plugin"] == "pipeline-checker"
    replacement = tmp_path / "replacement.py"
    replacement.write_text("def load_manifest(path):\n    return path\n", encoding="utf-8")
    toolbox = build_core_toolbox(work_root=tmp_path, plugin_tool_specs=[spec])

    result = await toolbox.execute(
        ToolCall(
            id="check-1",
            name="check_exports",
            arguments={
                "target": "lamtools_core.plugin_system.manifest",
                "replacement": str(replacement),
            },
        )
    )

    assert result.status == "failed"
    payload = json.loads(result.content)
    assert payload["ok"] is False
    assert "MANIFEST_FILENAME" in payload["missing"]
    assert "load_manifest" not in payload["missing"]


async def test_a_complete_replacement_passes(tmp_path: Path) -> None:
    spec = assemble_spec(tmp_path)
    replacement = tmp_path / "replacement.py"
    replacement.write_text(
        "MANIFEST_FILENAME = 'plugin.json'\n"
        "SUPPORTED_SCOPES = ('global',)\n"
        "class PluginManifestError(ValueError):\n    pass\n"
        "class PluginManifest:\n    pass\n"
        "def load_manifest(path, *, enabled=True):\n    return path\n",
        encoding="utf-8",
    )
    toolbox = build_core_toolbox(work_root=tmp_path, plugin_tool_specs=[spec])

    result = await toolbox.execute(
        ToolCall(
            id="check-2",
            name="check_exports",
            arguments={
                "target": "lamtools_core.plugin_system.manifest",
                "replacement": str(replacement),
            },
        )
    )

    assert result.status == "ok"
    payload = json.loads(result.content)
    assert payload["missing"] == []
    assert payload["ok"] is True


async def test_a_broken_replacement_is_reported_not_raised(tmp_path: Path) -> None:
    spec = assemble_spec(tmp_path)
    replacement = tmp_path / "broken.py"
    replacement.write_text("def broken(:\n", encoding="utf-8")
    toolbox = build_core_toolbox(work_root=tmp_path, plugin_tool_specs=[spec])

    result = await toolbox.execute(
        ToolCall(
            id="check-3",
            name="check_exports",
            arguments={
                "target": "lamtools_core.plugin_system.manifest",
                "replacement": str(replacement),
            },
        )
    )

    assert result.status == "failed"
    assert "syntax error" in (result.error or "")
