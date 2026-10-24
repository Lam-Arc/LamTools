"""v2 plugins can ship a backend; its handlers and context reach the agent."""

from __future__ import annotations

import json
from pathlib import Path

from lamtools_core.app.base_agent import assemble_core_agent_plugins
from lamtools_core.tool import ToolCall

BACKEND = '''
from pathlib import Path


class Runtime:
    def __init__(self, context):
        self.context = context

    @property
    def tool_handlers(self):
        async def handle(call):
            from lamtools_core.tool import ToolResult

            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="ok",
                content="from backend",
            )

        return {"demo_tool": handle}


def create_plugin(context):
    return Runtime(context)
'''

OPS = '''
from lamtools_core.app import OperationResult


async def run(request, *, context=None):
    return OperationResult(
        name=request.name,
        payload={"has_context": context is not None},
    )
'''


def make_plugin(root: Path) -> Path:
    directory = root / "demo"
    directory.mkdir(parents=True)
    (directory / "plugin.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "version": "1.0.0",
                "assembly": "v2",
                "backend": "./backend.py",
                "tools": ["./tools.jsonc"],
                "operations": ["./operations.jsonc"],
            }
        ),
        encoding="utf-8",
    )
    (directory / "tools.jsonc").write_text(
        json.dumps(
            {
                "tools": [
                    {
                        "name": "demo_tool",
                        "permission": "auto_allow",
                        "handler": "unused:unused",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (directory / "operations.jsonc").write_text(
        json.dumps({"operations": [{"name": "demo.op", "handler": "ops:run"}]}),
        encoding="utf-8",
    )
    (directory / "backend.py").write_text(BACKEND, encoding="utf-8")
    (directory / "ops.py").write_text(OPS, encoding="utf-8")
    return directory


def test_backend_handlers_reach_the_agent_assembly(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    make_plugin(plugin_root)

    assembly = assemble_core_agent_plugins(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[plugin_root],
    )

    handler = assembly["plugin_tool_handlers"].get("demo_tool")
    assert callable(handler)
    names = {spec.name for spec in assembly["plugin_runtime_specs"]}
    assert "demo_tool" in names


async def test_operation_handler_receives_the_plugin_context(tmp_path: Path) -> None:
    from lamtools_core.app import OperationCatalog
    from lamtools_core.plugin_system import PluginHost
    from lamtools_core.plugin_system.operations import register_plugin_system_operations

    plugin_root = tmp_path / "plugins"
    make_plugin(plugin_root)
    assemble_core_agent_plugins(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[plugin_root],
    )
    host = PluginHost(
        roots=[plugin_root],
        state_path=tmp_path / "data" / "plugin-system.jsonc",
    )
    catalog = OperationCatalog()
    register_plugin_system_operations(catalog, host)

    result = await catalog.execute("demo.op", {"work_root": str(tmp_path)})

    assert result.status == "ok"
    assert result.payload["has_context"] is True


async def test_backend_handler_runs_through_the_toolbox(tmp_path: Path) -> None:
    from lamtools_core.tool.default_toolbox import build_core_toolbox

    plugin_root = tmp_path / "plugins"
    make_plugin(plugin_root)
    assembly = assemble_core_agent_plugins(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[plugin_root],
    )
    toolbox = build_core_toolbox(
        work_root=tmp_path,
        plugin_tool_specs=assembly["plugin_runtime_specs"],
        plugin_tool_handlers=assembly["plugin_tool_handlers"],
    )

    result = await toolbox.execute(ToolCall(id="c1", name="demo_tool", arguments={}))

    assert result.status == "ok"
    assert result.content == "from backend"
