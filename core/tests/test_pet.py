from __future__ import annotations

import json
import asyncio
import base64
from pathlib import Path

from lamtools_core.app.pet import (
    DEFAULT_PET_ID,
    PetPackLoader,
    PetOverviewReducer,
    PetOverview,
    PetOverviewService,
    PetSettings,
)
from lamtools_core.config.settings_store import get_setting


def _write_pack(root: Path, pack_id: str = "test-cat") -> Path:
    pack = root / pack_id
    pack.mkdir(parents=True)
    (pack / "pet.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "id": pack_id,
                "name": "Test Cat",
                "states": {state: {"fps": 8} for state in ("idle", "running", "waiting", "error")},
            }
        ),
        encoding="utf-8",
    )
    for state in ("idle", "running", "waiting", "error"):
        state_dir = pack / state
        state_dir.mkdir()
        (state_dir / "0002.png").write_bytes(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg=="
        ))
        (state_dir / "0001.webp").write_bytes(base64.b64decode(
            "UklGRjwAAABXRUJQVlA4IDAAAADQAQCdASoBAAEAAUAmJaACdLoB+AADsAD+8ut//NgVzXPv9//S4P0uD9Lg/9KQAAA="
        ))
    return pack


def test_pet_settings_default_and_safe_migration() -> None:
    assert PetSettings.from_value(None).enabled is True
    settings = PetSettings.from_value(
        {
            "enabled": False,
            "selected_pet": "../../escape",
            "opacity": 99,
            "scale": 0,
            "placement": {"x": "12", "y": None},
        }
    )
    assert settings.enabled is False
    assert settings.selected_pet == DEFAULT_PET_ID
    assert settings.opacity == 1.0
    assert settings.scale == 0.5
    assert settings.placement.x == 12.0


def test_pet_pack_loader_validates_all_states_and_natural_order(tmp_path: Path) -> None:
    root = tmp_path / "pets"
    _write_pack(root)

    pack = PetPackLoader(root).load("test-cat")

    assert pack.valid is True
    assert [path.name for path in pack.animations["idle"].frames] == ["0001.webp", "0002.png"]


def test_pet_pack_loader_rejects_path_escape_and_bad_manifest(tmp_path: Path) -> None:
    root = tmp_path / "pets"
    root.mkdir()
    bad = root / "bad"
    bad.mkdir()
    (bad / "pet.json").write_text("{}", encoding="utf-8")

    result = PetPackLoader(root).load("bad")

    assert result.valid is False
    assert "schemaVersion" in result.error
    assert PetPackLoader(root).load("../bad").valid is False


def test_pet_pack_loader_rejects_undecodable_frame(tmp_path: Path) -> None:
    root = tmp_path / "pets"
    pack = _write_pack(root, "broken")
    (pack / "idle" / "0001.webp").write_bytes(b"not-an-image")

    result = PetPackLoader(root).load("broken")

    assert result.valid is False
    assert "cannot decode" in result.error


def test_pet_overview_service_clears_live_error_on_runtime_terminal_event() -> None:
    service = PetOverviewService(session_factory=lambda: None, hub=None)  # type: ignore[arg-type]

    service._record_live_error({
        "method": "runtime.failed",
        "thread_id": "thread-1",
        "payload": {"error": "boom"},
    })
    assert "thread-1" in service._live_errors

    service._record_live_error({
        "method": "runtime.done",
        "thread_id": "thread-1",
        "payload": {"message": "done"},
    })
    assert "thread-1" not in service._live_errors


def test_pet_overview_priority_and_current_interactions() -> None:
    reducer = PetOverviewReducer()
    reducer.set_session("running", {"status": "running", "metadata": {}})
    reducer.set_session(
        "waiting",
        {
            "status": "waiting",
            "title": "Needs input",
            "metadata": {
                "pending_waiting_request": {
                    "request_id": "request-1",
                    "prompt": "Choose a path",
                    "options": ["A", "B"],
                    "created_at": "2026-01-01T00:00:00Z",
                }
            },
        },
    )
    reducer.set_error("failed-now", {"message": "current failure"})

    overview = reducer.build()

    assert overview.global_state == "waiting"
    assert overview.running_count == 1
    assert overview.waiting_count == 1
    assert overview.error_count == 1
    assert overview.pending_interactions[0].options == ("A", "B")

    reducer.remove_session("waiting")
    assert reducer.build().global_state == "error"


def test_pet_settings_namespace_is_merged_without_reset(isolated_config_root) -> None:
    from lamtools_core.app.pet import update_pet_settings

    update_pet_settings({"enabled": False, "opacity": 0.7})
    update_pet_settings({"scale": 1.5})

    saved = get_setting("core.pet")
    assert saved["enabled"] is False
    assert saved["opacity"] == 0.7
    assert saved["scale"] == 1.5


def test_pet_overview_service_publishes_changed_global_projection(monkeypatch) -> None:
    async def run() -> None:
        from lamtools_core.app import pet as pet_module
        from lamtools_core.app.live_hub import CoreAppEventHub

        state = {"overview": PetOverview()}

        async def fake_loader(_session_factory):
            return state["overview"]

        monkeypatch.setattr(pet_module, "load_pet_overview_from_session_factory", fake_loader)
        hub = CoreAppEventHub()
        watcher = hub.subscribe_all()
        service = PetOverviewService(session_factory=lambda: None, hub=hub, refresh_delay=0)
        await service.start()

        initial = await asyncio.wait_for(watcher.get(), timeout=0.1)
        assert initial["method"] == "pet/overviewChanged"
        state["overview"] = PetOverview(global_state="running", running_count=1)
        await hub.publish({"thread_id": "thread-1", "method": "turn/accepted"})

        changed = await asyncio.wait_for(watcher.get(), timeout=0.2)
        while changed.get("method") != "pet/overviewChanged":
            changed = await asyncio.wait_for(watcher.get(), timeout=0.2)
        assert changed["payload"]["overview"]["global_state"] == "running"
        await service.stop()
        hub.unsubscribe_all(watcher)

    asyncio.run(run())
