from pathlib import Path

from lamtools_core.app.desktop_plugin_session_store import DesktopPluginSessionStore


def test_desktop_plugin_session_store_round_trips_and_deletes(tmp_path: Path) -> None:
    path = tmp_path / "desktop-plugin-sessions.json"
    store = DesktopPluginSessionStore(path)

    assert store.get("emotion-ball-pet") is None
    store.set("emotion-ball-pet", "session-a")
    assert store.get("emotion-ball-pet") == "session-a"
    assert DesktopPluginSessionStore(path).get("emotion-ball-pet") == "session-a"

    store.delete("emotion-ball-pet")
    assert store.get("emotion-ball-pet") is None
