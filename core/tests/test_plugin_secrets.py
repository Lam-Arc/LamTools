"""Per-plugin secret storage and scoped service views."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.plugin_system import PluginContext, load_manifest
from lamtools_core.plugin_system.lifecycle import (
    load_plugin_backend,
    start_plugin_backend,
    stop_plugin_backend,
)
from lamtools_core.plugin_system.secrets import PluginSecretStore, SecretStoreError


def _plugin(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plugin.json").write_text(
        json.dumps({"name": name, "version": "1", "backend": "./backend.py"}),
        encoding="utf-8",
    )
    (folder / "backend.py").write_text(
        "class Runtime:\n"
        "    def __init__(self, context):\n"
        "        self.secrets = context.service('secrets')\n"
        "        self.shared = context.service('plugin_secrets')\n"
        "        self.started_with = None\n"
        "    async def start(self, context):\n"
        "        self.started_with = context.service('secrets')\n"
        "def create_plugin(context):\n"
        "    return Runtime(context)\n",
        encoding="utf-8",
    )
    return folder


def test_secret_store_roundtrip_and_persistence(tmp_path: Path) -> None:
    store = PluginSecretStore(tmp_path / "secrets")
    store.set("demo", "appSecret", "super-secret-value")
    store.set("demo", "empty", "")

    assert store.get("demo", "appSecret") == "super-secret-value"
    assert store.get("demo", "empty") == ""
    assert store.keys("demo") == ["appSecret"]
    assert "super-secret-value" not in store.path.read_text(encoding="utf-8")

    reopened = PluginSecretStore(tmp_path / "secrets")
    assert reopened.get("demo", "appSecret") == "super-secret-value"

    reopened.delete("demo", "appSecret")
    assert reopened.get("demo", "appSecret") == ""
    assert reopened.keys("demo") == []


def test_secret_views_are_isolated_per_plugin(tmp_path: Path) -> None:
    store = PluginSecretStore(tmp_path / "secrets")
    first = store.view("first")
    second = store.view("second")

    first.set("token", "first-value")
    second.set("token", "second-value")

    assert first.get("token") == "first-value"
    assert second.get("token") == "second-value"
    assert store.get("first", "token") == "first-value"
    assert store.get("second", "token") == "second-value"

    first.clear()
    assert first.keys() == []
    assert second.get("token") == "second-value"


def test_backend_receives_only_its_own_scoped_secret_view(tmp_path: Path) -> None:
    store = PluginSecretStore(tmp_path / "secrets")
    context = PluginContext(work_root=tmp_path, data_dir=tmp_path)
    context._secret_store = store

    first_manifest = load_manifest(_plugin(tmp_path / "plugins" / "first", "first") / "plugin.json")
    second_manifest = load_manifest(_plugin(tmp_path / "plugins" / "second", "second") / "plugin.json")
    first = load_plugin_backend(first_manifest, context)
    second = load_plugin_backend(second_manifest, context)

    assert first is not None and second is not None
    first.value.secrets.set("appSecret", "one")
    second.value.secrets.set("appSecret", "two")

    assert first.value.secrets.get("appSecret") == "one"
    assert second.value.secrets.get("appSecret") == "two"
    assert first.value.secrets is not second.value.secrets
    # The shared store is deliberately not a service; a plugin asking for it
    # gets nothing and cannot reach another plugin's namespace.
    assert first.value.shared is None


def test_corrupt_secret_raises_instead_of_returning_wrong_text(tmp_path: Path) -> None:
    store = PluginSecretStore(tmp_path / "secrets")
    store.set("demo", "token", "value")
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    raw["plugins"]["demo"]["token"]["value"] = "unknown:abc"
    store.path.write_text(json.dumps(raw), encoding="utf-8")

    reopened = PluginSecretStore(tmp_path / "secrets")
    with pytest.raises(SecretStoreError):
        reopened.get("demo", "token")


async def test_scoped_secret_view_survives_disable_enable(tmp_path: Path) -> None:
    store = PluginSecretStore(tmp_path / "secrets")
    context = PluginContext(work_root=tmp_path, data_dir=tmp_path)
    context._secret_store = store
    manifest = load_manifest(_plugin(tmp_path / "plugins" / "demo", "demo") / "plugin.json")
    handle = load_plugin_backend(manifest, context)
    assert handle is not None

    await start_plugin_backend(handle, context)
    try:
        assert handle.value.started_with is not None
        handle.value.started_with.set("token", "kept")
    finally:
        await stop_plugin_backend(handle)

    await start_plugin_backend(handle, context)
    try:
        assert handle.value.started_with is not None
        assert handle.value.started_with.get("token") == "kept"
    finally:
        await stop_plugin_backend(handle)
