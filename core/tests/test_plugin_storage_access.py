"""user:“宿主能力补齐和接口完善与文档更新”+(插件状态在稳定数据目录持久化，代际隔离、原子写入和版本冲突可验收)。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.lifecycle import PluginRuntimeHandle, start_plugin_backend, stop_plugin_backend
from lamtools_core.plugin_system.manifest import PluginManifest
from lamtools_core.plugin_system.storage_access import StorageError, ensure_plugin_storage


@pytest.fixture
async def env(tmp_path):
    root = PluginContext(tmp_path, data_dir=tmp_path / "data")
    ensure_plugin_storage(root, root=tmp_path / "data/plugin-data")
    handles = []
    async def start(callback, name="example"):
        handle = PluginRuntimeHandle(PluginManifest(name, "1", root=tmp_path), {"start": callback}, context=root.for_work_root(tmp_path))
        handles.append(handle)
        await start_plugin_backend(handle, root)
        return handle
    try:
        yield root, start
    finally:
        for handle in reversed(handles):
            await stop_plugin_backend(handle)


async def opened(start, *, name="example", unit="state"):
    views = []
    await start(lambda ctx: views.append(ctx.storage.open(unit)), name)
    return views[0]


@pytest.mark.asyncio
async def test_json_roundtrip_detaches_mutable_values_and_distinguishes_missing_from_null(env):
    _, start = env
    unit = await opened(start)
    absent = unit.get("missing")
    assert not absent.found and absent.value is None and absent.revision == 0
    value = {"nested": [1, True, "文字", None]}
    stored = unit.put("key", value)
    value["nested"].append("caller change")
    stored.value["nested"].append("returned change")
    assert unit.get("key").value == {"nested": [1, True, "文字", None]}
    null = unit.put("null", None)
    assert null.found and unit.get("null").found and unit.get("null").value is None


@pytest.mark.asyncio
async def test_restart_preserves_state_but_revokes_old_facade_and_unit(env):
    root, start = env
    views = []
    def initialize(ctx):
        views.append((ctx.storage, ctx.storage.open("state")))
    handle = await start(initialize)
    old_api, old_unit = views[0]
    old_unit.put("key", {"value": "retained"})
    await stop_plugin_backend(handle)
    for callback in (lambda: old_api.open("state"), lambda: old_unit.get("key"), lambda: old_unit.put("key", 2)):
        with pytest.raises(RuntimeError):
            callback()
    await start_plugin_backend(handle, root)
    assert views[1][1].get("key").value == {"value": "retained"}


@pytest.mark.asyncio
async def test_namespaces_and_plugin_owners_are_isolated(env):
    _, start = env
    apis = []
    await start(lambda ctx: apis.append(ctx.storage), name="first")
    first = apis[0].open("state")
    second = await opened(start, name="second")
    first.put("same", "private")
    assert not second.get("same").found
    assert not apis[0].open("other").get("same").found


@pytest.mark.asyncio
async def test_same_owner_units_share_data_across_host_instances(env, tmp_path):
    _, start = env
    first = await opened(start)
    first.put("key", "shared data")
    root = PluginContext(tmp_path, data_dir=tmp_path / "data")
    ensure_plugin_storage(root, root=tmp_path / "data/plugin-data")
    units = []
    handle = PluginRuntimeHandle(PluginManifest("example", "1", root=tmp_path), {"start": lambda ctx: units.append(ctx.storage.open("state"))}, context=root.for_work_root(tmp_path))
    await start_plugin_backend(handle, root)
    try:
        assert units[0].get("key").value == "shared data"
        units[0].put("key", "new value")
        assert first.get("key").value == "new value"
    finally:
        await stop_plugin_backend(handle)


@pytest.mark.asyncio
async def test_compare_revision_prevents_stale_overwrite_and_delete_recreate_aba(env):
    _, start = env
    unit = await opened(start)
    first = unit.put("key", "v1", expected_revision=0)
    second = unit.put("key", "v2", expected_revision=first.revision)
    with pytest.raises(StorageError) as error:
        unit.put("key", "stale", expected_revision=first.revision)
    assert error.value.code == "storage/conflict" and unit.get("key").value == "v2"
    deleted = unit.delete("key", expected_revision=second.revision)
    assert not deleted.found and deleted.revision > second.revision
    recreated = unit.put("key", "v3", expected_revision=deleted.revision)
    assert recreated.revision > deleted.revision
    with pytest.raises(StorageError):
        unit.delete("key", expected_revision=first.revision)
    assert unit.get("key").value == "v3"
    assert unit.delete("absent").revision == 0


@pytest.mark.asyncio
async def test_key_pagination_is_literal_case_sensitive_and_never_uses_keys_as_paths(env, tmp_path):
    _, start = env
    unit = await opened(start)
    for key in ("../outside", "A", "a%1", "a%2", "a_1", "中文"):
        unit.put(key, key)
    first = unit.keys(prefix="a%", limit=1)
    assert [entry.key for entry in first.entries] == ["a%1"] and first.next_after == "a%1"
    last = unit.keys(prefix="a%", after=first.next_after, limit=1)
    assert [entry.key for entry in last.entries] == ["a%2"] and last.next_after is None
    assert len(unit.keys(prefix="a").entries) == 3
    assert unit.get("../outside").value == "../outside" and not (tmp_path / "outside").exists()


@pytest.mark.asyncio
async def test_exact_unit_version_and_close_are_enforced(env):
    _, start = env
    views = []
    await start(lambda ctx: views.append(ctx.storage))
    unit = views[0].open("state", version=2)
    unit.put("key", 1)
    with pytest.raises(StorageError) as error:
        views[0].open("state", version=1)
    assert error.value.code == "storage/version-mismatch"
    unit.close()
    unit.close()
    with pytest.raises(StorageError) as error:
        unit.get("key")
    assert error.value.code == "storage/closed"
    assert views[0].open("state", version=2).get("key").value == 1


@pytest.mark.asyncio
async def test_invalid_json_and_size_limits_fail_before_overwriting_existing_value(env):
    _, start = env
    unit = await opened(start)
    first = unit.put("key", "original")
    for invalid in (float("nan"), {"nested": {1: "bad JSON key"}}, {"tuple": (1, 2)}, "x" * (1024 * 1024 + 1)):
        with pytest.raises((StorageError, ValueError, TypeError)):
            unit.put("key", invalid)
        assert unit.get("key").value == "original" and unit.get("key").revision == first.revision


@pytest.mark.asyncio
async def test_corrupt_medium_is_not_reset_or_treated_as_empty(env, tmp_path):
    _, start = env
    unit = await opened(start)
    unit.put("key", "retained")
    db = tmp_path / "data/plugin-data/example/host-kv.sqlite3"
    db.write_bytes(b"damaged medium")
    with pytest.raises(StorageError):
        unit.get("key")
    assert db.read_bytes() == b"damaged medium"


@pytest.mark.asyncio
async def test_busy_writer_fails_without_overwriting_and_can_retry_after_lock_release(env, tmp_path):
    _, start = env
    unit = await opened(start)
    original = unit.put("key", "retained")
    with sqlite3.connect(tmp_path / "data/plugin-data/example/host-kv.sqlite3") as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        with pytest.raises(StorageError) as error:
            unit.put("key", "must not commit", expected_revision=original.revision)
        assert error.value.code == "storage/busy"
        blocker.rollback()
    assert unit.get("key").value == "retained"
    assert unit.put("key", "retry", expected_revision=original.revision).found


@pytest.mark.asyncio
async def test_invalid_unit_key_and_revision_cannot_select_other_data(env):
    _, start = env
    views = []
    await start(lambda ctx: views.append(ctx.storage))
    for name in ("../other", "Upper", "", "name/child"):
        with pytest.raises(StorageError):
            views[0].open(name)
    unit = views[0].open("state")
    for key in ("", "nul\x00key", "x" * 513):
        with pytest.raises(StorageError):
            unit.put(key, 1)
    for revision in (-1, True, "1"):
        with pytest.raises(StorageError):
            unit.put("key", 1, expected_revision=revision)
    assert not unit.get("key").found


@pytest.mark.asyncio
async def test_commit_uncertainty_quarantines_handle_until_reopen(env, monkeypatch):
    _, start = env
    views = []
    await start(lambda ctx: views.append(ctx.storage))
    unit = views[0].open("state")
    real_connect = sqlite3.connect
    class CommitUncertain(sqlite3.Connection):
        def commit(self):
            super().commit()
            raise OSError("lost commit acknowledgement")
    with monkeypatch.context() as patched:
        patched.setattr("lamtools_core.plugin_system.storage_access.sqlite3.connect", lambda *a, **kw: real_connect(*a, **{**kw, "factory": CommitUncertain}))
        with pytest.raises(StorageError) as error:
            unit.put("key", "may be committed")
        assert error.value.code == "storage/unknown-state"
    with pytest.raises(StorageError) as error:
        unit.get("key")
    assert error.value.code == "storage/unknown-state"
    unit.close()
    assert views[0].open("state").get("key").value == "may be committed"


@pytest.mark.asyncio
async def test_failed_start_revokes_handle_but_does_not_undo_durable_application_state(env):
    _, start = env
    units = []
    def initialize(ctx):
        units.append(ctx.storage.open("state"))
        units[0].put("key", "committed before startup failed")
        raise RuntimeError("startup failed")
    with pytest.raises(RuntimeError):
        await start(initialize)
    with pytest.raises(RuntimeError):
        units[0].get("key")
    await start(lambda ctx: units.append(ctx.storage.open("state")))
    assert units[-1].get("key").value == "committed before startup failed"


def test_desktop_storage_matches_stable_plugin_data_path_and_survives_app_restart(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from lamtools_core.app.http_agent_app import create_core_agent_http_app
    monkeypatch.setattr("lamtools_core.app.http_agent_app.warm_command_shell", lambda: None)
    monkeypatch.setattr("lamtools_core.runtime.power.apply_keep_awake", lambda: None)
    plugin_root = tmp_path / "plugins/storage-consumer"
    plugin_root.mkdir(parents=True)
    (plugin_root / "plugin.json").write_text(json.dumps({"name": "storage-consumer", "version": "1", "backend": "./backend.py"}))
    (plugin_root / "backend.py").write_text('''
class Runtime:
    def start(self, context):
        self.unit = context.storage.open("settings")
        previous = self.unit.get("count")
        self.unit.put("count", (previous.value or 0) + 1, expected_revision=previous.revision)
def create_plugin(context):
    return Runtime()
''')
    def app():
        return create_core_agent_http_app(core_db=tmp_path / "boot.db", data_dir=tmp_path / "data",
                                         work_root=tmp_path / "project", plugin_roots=[tmp_path / "plugins"])
    instance = app()
    with TestClient(instance):
        state = instance.state.core_agent_app_state
        handle = next(h for h in state["plugin_runtimes"] if h.plugin.name == "storage-consumer")
        assert handle.state == "ready", handle.error
        assert handle.value.unit.get("count").value == 1
        host = state["operations"].plugin_system_host
        assert (host.data_path("storage-consumer") / "host-kv.sqlite3").is_file()
    with pytest.raises(RuntimeError):
        handle.value.unit.get("count")
    (plugin_root / "plugin.json").write_text(json.dumps({"name": "storage-consumer", "version": "2", "backend": "./backend.py"}))
    backend = plugin_root / "backend.py"
    backend.write_text(backend.read_text().replace("+ 1,", "+ 10,"))
    # A real restart has a fresh interpreter, not a new asyncio loop sharing
    # the preceding process's cached PluginHost and completed task objects.
    import subprocess
    import sys
    restarted = subprocess.run([sys.executable, "-c", '''
import sys
from pathlib import Path
from fastapi.testclient import TestClient
import lamtools_core.app.http_agent_app as http
import lamtools_core.runtime.power as power
http.warm_command_shell = lambda: None
power.apply_keep_awake = lambda: None
root = Path(sys.argv[1])
app = http.create_core_agent_http_app(core_db=root / "boot.db", data_dir=root / "data",
    work_root=root / "project", plugin_roots=[root / "plugins"])
with TestClient(app):
    handle = next(h for h in app.state.core_agent_app_state["plugin_runtimes"] if h.plugin.name == "storage-consumer")
    assert handle.state == "ready", handle.error
    assert handle.plugin.version == "2"
    assert handle.value.unit.get("count").value == 11
''', str(tmp_path)], capture_output=True, encoding="utf-8")
    assert restarted.returncode == 0, restarted.stderr
