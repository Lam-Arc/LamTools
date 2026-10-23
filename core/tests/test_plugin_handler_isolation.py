"""Plugin handlers must not share a global module name; failures keep the tool."""

from __future__ import annotations

import asyncio
from pathlib import Path

from lamtools_core.tool import ToolCall, ToolSpec
from lamtools_core.tool.default_toolbox import CoreToolbox, _unavailable_plugin_handler


def _write_tools_module(root: Path, function_name: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "tools.py").write_text(
        f"def {function_name}(call):\n    return None\n",
        encoding="utf-8",
    )


def _spec(name: str, root: Path) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="",
        metadata={"plugin_root": str(root), "handler": "tools:" + name},
    )


def test_two_plugins_with_tools_module_do_not_collide(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_tools_module(first, "first_tool")
    _write_tools_module(second, "second_tool")

    toolbox = object.__new__(CoreToolbox)
    first_module = toolbox._load_plugin_module(_spec("first_tool", first), "tools")
    second_module = toolbox._load_plugin_module(_spec("second_tool", second), "tools")

    assert hasattr(first_module, "first_tool")
    assert not hasattr(first_module, "second_tool")
    assert hasattr(second_module, "second_tool")
    assert not hasattr(second_module, "first_tool")
    assert first_module is not second_module


def test_unavailable_handler_returns_explicit_failure() -> None:
    handler = _unavailable_plugin_handler("gpt_web_image", "module 'tools' has no attribute")
    result = asyncio.run(handler(ToolCall(id="call-1", name="gpt_web_image")))
    assert result.status == "failed"
    assert "module 'tools' has no attribute" in result.error
    assert result.metadata["error_type"] == "plugin_handler_unavailable"
