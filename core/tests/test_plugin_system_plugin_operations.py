"""v2 plugins can declare RPC operations, and disabling one hides them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.app import OperationCatalog
from lamtools_core.plugin_system import PluginHost
from lamtools_core.plugin_system.operations import register_plugin_system_operations

OPERATIONS = json.dumps(
    {
        "operations": [
            {
                "name": "demo.hello",
                "description": "say hello",
                "handler": "ops:hello",
            }
        ]
    }
)

HANDLER = '''
from pathlib import Path

from lamtools_core.app import OperationResult


async def hello(request, *, work_root, data_dir):
    (Path(data_dir) / "called.txt").write_text(str(work_root), encoding="utf-8")
    return OperationResult(
        name=request.name,
        payload={"greeting": "hi", "query": request.payload.get("query")},
    )
'''


def make_plugin(root: Path, name: str, *, handler: str = HANDLER) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "plugin.json").write_text(
        json.dumps({"name": name, "version": "1.0.0", "assembly": "v2", "operations": ["./operations.jsonc"]}),
        encoding="utf-8",
    )
    (directory / "operations.jsonc").write_text(OPERATIONS, encoding="utf-8")
    (directory / "ops.py").write_text(handler, encoding="utf-8")
    return directory


def make_catalog(tmp_path: Path, root: Path) -> tuple[OperationCatalog, PluginHost]:
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    host = PluginHost(roots=[root], state_path=tmp_path / "data" / "plugin-system.jsonc")
    catalog = OperationCatalog()
    register_plugin_system_operations(catalog, host)
    return catalog, host


async def test_declared_operation_is_registered_and_runs(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(root, "demo")
    catalog, _host = make_catalog(tmp_path, root)

    result = await catalog.execute("demo.hello", {"query": "abc"}, metadata={"work_root": str(tmp_path)})

    assert result.status == "ok"
    assert result.payload["greeting"] == "hi"
    assert result.payload["query"] == "abc"
    called = (tmp_path / "data" / "called.txt").read_text(encoding="utf-8")
    assert called == str(tmp_path)


async def test_dict_return_becomes_a_payload(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(
        root,
        "demo",
        handler="async def hello(request):\n    return {'value': 1}\n",
    )
    catalog, _host = make_catalog(tmp_path, root)

    result = await catalog.execute("demo.hello", {})

    assert result.status == "ok"
    assert result.payload == {"value": 1}


async def test_disabling_the_plugin_hides_its_operation(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(root, "demo")
    catalog, host = make_catalog(tmp_path, root)

    assert catalog.has("demo.hello") is True
    host.disable("demo")
    assert catalog.has("demo.hello") is False
    with pytest.raises(KeyError):
        await catalog.execute("demo.hello", {})


async def test_duplicate_operation_names_are_refused_not_overwritten(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(root, "alpha")
    make_plugin(root, "beta")
    catalog, _host = make_catalog(tmp_path, root)

    assert [item["plugin"] for item in catalog.plugin_operation_errors] == ["beta"]
    assert "already declared" in catalog.plugin_operation_errors[0]["error"]
    result = await catalog.execute("demo.hello", {})
    assert result.status == "ok"


async def test_a_broken_handler_reports_instead_of_raising(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(root, "demo", handler="VALUE = 1\n")
    catalog, _host = make_catalog(tmp_path, root)

    result = await catalog.execute("demo.hello", {})

    assert result.status == "error"
    assert "unavailable" in result.payload["error"]
