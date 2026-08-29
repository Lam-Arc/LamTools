"""Project-scope binding tests for manifest-declared plugin operations."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from lamtools_core.app.operation_catalog import OperationCatalog, OperationResult
from lamtools_core.plugins.context import PluginContext
from lamtools_core.plugins.models import PluginOperationSpec
from lamtools_core.plugins.operations_loader import register_plugin_operations


@pytest.mark.asyncio
async def test_operation_request_metadata_is_authoritative_for_work_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A switched project must override stale payload/startup roots."""
    startup_root = tmp_path / "startup"
    payload_root = tmp_path / "payload"
    metadata_root = tmp_path / "metadata"
    data_dir = tmp_path / "data"
    observed: dict[str, object] = {}
    module_name = f"_operation_scope_{id(tmp_path)}"

    async def handler(request, *, context=None, work_root=None, data_dir=None):
        observed.update(
            {
                "payload_root": request.payload.get("work_root"),
                "metadata_root": request.metadata.get("work_root"),
                "work_root": work_root,
                "context_root": context.work_root if context is not None else None,
                "data_dir": data_dir,
            }
        )
        return OperationResult(name=request.name, payload={"ok": True})

    module = types.ModuleType(module_name)
    module.handler = handler
    monkeypatch.setitem(sys.modules, module_name, module)

    context = PluginContext(work_root=startup_root, data_dir=data_dir)
    catalog = OperationCatalog()
    errors = register_plugin_operations(
        catalog,
        [PluginOperationSpec(name="scope.echo", handler=f"{module_name}:handler")],
        plugin_name="scope-test",
        work_root=startup_root,
        data_dir=data_dir,
        context=context,
    )
    assert errors == []

    result = await catalog.execute(
        "scope.echo",
        {"work_root": str(payload_root)},
        metadata={"work_root": str(metadata_root)},
    )

    assert result.status == "ok"
    assert observed == {
        "payload_root": str(metadata_root),
        "metadata_root": str(metadata_root),
        "work_root": metadata_root,
        "context_root": metadata_root.resolve(),
        "data_dir": data_dir,
    }


@pytest.mark.asyncio
async def test_operation_session_metadata_scopes_context_before_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_root = tmp_path / "session-project"
    payload_root = tmp_path / "stale-payload"
    observed: dict[str, object] = {}
    module_name = f"_operation_session_scope_{id(tmp_path)}"

    async def handler(request, *, context=None, work_root=None):
        observed.update(
            {
                "payload_root": request.payload.get("work_root"),
                "work_root": work_root,
                "context_root": context.work_root if context is not None else None,
            }
        )
        return OperationResult(name=request.name)

    module = types.ModuleType(module_name)
    module.handler = handler
    monkeypatch.setitem(sys.modules, module_name, module)

    context = PluginContext(work_root=tmp_path / "startup")
    catalog = OperationCatalog()
    errors = register_plugin_operations(
        catalog,
        [PluginOperationSpec(name="scope.session", handler=f"{module_name}:handler")],
        plugin_name="scope-test",
        work_root=context.work_root,
        context=context,
    )
    assert errors == []

    await catalog.execute(
        "scope.session",
        {"work_root": str(payload_root)},
        metadata={"_runtime_session_metadata": {"work_root": str(session_root)}},
    )

    assert observed == {
        "payload_root": str(session_root),
        "work_root": session_root,
        "context_root": session_root.resolve(),
    }
