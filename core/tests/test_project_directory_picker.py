from __future__ import annotations

from types import SimpleNamespace

import pytest

from lamtools_core.app import live_operations
from lamtools_core.project import directory_picker


@pytest.mark.asyncio
async def test_core_project_directory_operation_returns_selected_path(monkeypatch):
    monkeypatch.setattr(live_operations, "pick_project_directory", lambda: "E:\\Workspace")

    outcome = await live_operations.handle_project_directory_pick_operation(
        request_id="pick-1",
        params={},
        context=None,  # type: ignore[arg-type]
    )

    assert outcome.response == {"id": "pick-1", "result": {"path": "E:\\Workspace"}}


def test_windows_directory_picker_uses_a_topmost_owner(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="E:\\Workspace\n", stderr="")

    monkeypatch.setattr(directory_picker.subprocess, "run", fake_run)

    assert directory_picker._pick_directory_windows() == "E:\\Workspace"
    script = calls[0][0][-1]
    assert "$owner.TopMost = $true" in script
    assert "$dialog.ShowDialog($owner)" in script
