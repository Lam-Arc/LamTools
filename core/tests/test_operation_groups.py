from __future__ import annotations

import pytest

from lamtools_core.app import (
    CORE_WORKBENCH_OPERATION_NAMES,
    OperationCatalog,
    OperationResult,
    build_member_operation_catalog,
    register_operation_handlers,
)
from lamtools_core.app.queue_state import build_queue_update_plan


def test_core_workbench_operations_include_project_workspace_contracts() -> None:
    names = set(CORE_WORKBENCH_OPERATION_NAMES)

    assert {
        "project.list",
        "project.create",
        "project.get",
        "project.update",
        "project.delete",
        "project.sessions.list",
        "project.agents_md.get",
        "project.agents_md.update",
    } <= names
    assert {"attachment.list", "attachment.get", "attachment.preview", "attachment.open"} <= names
    assert "session.commit_review.get" not in names


@pytest.mark.asyncio
async def test_register_operation_handlers_registers_declared_names_only() -> None:
    async def handler(request):
        return OperationResult(name=request.name, payload={"ok": True})

    catalog = OperationCatalog()
    register_operation_handlers(catalog, ["turn.start", "turn.cancel"], {
        "turn.start": handler,
        "turn.cancel": handler,
    })

    assert catalog.list() == ["turn.cancel", "turn.start"]
    assert (await catalog.execute("turn.start")).payload == {"ok": True}


def test_register_operation_handlers_requires_complete_mapping() -> None:
    catalog = OperationCatalog()

    with pytest.raises(KeyError, match="turn.cancel"):
        register_operation_handlers(catalog, ["turn.start", "turn.cancel"], {})


def test_build_member_operation_catalog_registers_core_and_overlay_handlers() -> None:
    def handler(request):
        return OperationResult(name=request.name)

    catalog = build_member_operation_catalog(
        core_handlers={name: handler for name in CORE_WORKBENCH_OPERATION_NAMES},
        overlay_names=["session.commit_review.get"],
        overlay_handlers={"session.commit_review.get": handler},
    )

    assert catalog.has("turn.start")
    assert catalog.has("plugin.list")
    assert catalog.has("attachment.list")
    assert catalog.has("session.commit_review.get")


def test_build_member_operation_catalog_rejects_overlay_that_shadows_core() -> None:
    def handler(request):
        return OperationResult(name=request.name)

    with pytest.raises(ValueError, match="shadows core"):
        build_member_operation_catalog(
            core_handlers={name: handler for name in CORE_WORKBENCH_OPERATION_NAMES},
            overlay_names=["turn.start"],
            overlay_handlers={"turn.start": handler},
        )


@pytest.mark.parametrize("status", ["deleted", "dispatched", "sent"])
def test_queue_update_plan_rejects_terminal_or_missing_items(status: str) -> None:
    terminal_snapshot = {
        "queue": [
            {
                "queue_item_id": "queue-1",
                "status": status,
                "input": [{"type": "text", "text": "before"}],
            }
        ]
    }

    terminal = build_queue_update_plan(
        terminal_snapshot,
        queue_item_id="queue-1",
        input_items=[{"type": "text", "text": "after"}],
    )
    missing = build_queue_update_plan(
        {"queue": []},
        queue_item_id="missing",
        input_items=[{"type": "text", "text": "after"}],
    )

    assert terminal.applied is False
    assert terminal.reason == "queue_item_unavailable"
    assert missing.applied is False
    assert missing.reason == "queue_item_unavailable"
