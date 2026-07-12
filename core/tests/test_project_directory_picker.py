from __future__ import annotations

import pytest

from lamtools_core.app import live_operations


@pytest.mark.asyncio
async def test_core_project_directory_operation_returns_selected_path(monkeypatch):
    monkeypatch.setattr(live_operations, "pick_project_directory", lambda: "E:\\Workspace")

    outcome = await live_operations.handle_project_directory_pick_operation(
        request_id="pick-1",
        params={},
        context=None,  # type: ignore[arg-type]
    )

    assert outcome.response == {"id": "pick-1", "result": {"path": "E:\\Workspace"}}
