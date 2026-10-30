"""user:“宿主能力补齐和接口完善与文档更新”+(配置复用原路径和管理入口，版本冲突、坏文件与保存/生效区别有明确契约)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.lifecycle import PluginRuntimeHandle, start_plugin_backend, stop_plugin_backend
from lamtools_core.plugin_system.manifest import PluginManifest
from lamtools_core.plugin_system.config_access import ConfigError


@pytest.fixture
async def env(tmp_path):
    root = PluginContext(tmp_path, data_dir=tmp_path / "data")
    handles = []
    async def start(callback, name="example", raw=None):
        folder = tmp_path / "plugins" / name
        folder.mkdir(parents=True, exist_ok=True)
        handle = PluginRuntimeHandle(PluginManifest(name, "1", root=folder, raw=raw or {}), {"start": callback}, context=root.for_work_root(tmp_path))
        handles.append(handle)
        await start_plugin_backend(handle, root)
        return handle
    try:
        yield root, start
    finally:
        for handle in reversed(handles):
            await stop_plugin_backend(handle)


async def access(start, name="example", raw=None):
    views = []
    handle = await start(lambda ctx: views.append(ctx.config), name, raw)
    return views[0], handle


@pytest.mark.asyncio
async def test_missing_read_and_atomic_replace_are_distinct_from_runtime_application(env):
    _, start = env
    config, handle = await access(start)
    initial = config.read()
    assert initial.values == {} and not initial.exists and initial.revision
    values = {"nested": {"items": [1, True]}}
    saved = config.replace(values, expected_revision=initial.revision)
    assert saved.saved and not saved.applied and saved.requires_reload
    assert handle.state == "ready" and handle.attempts == 1
    values["nested"]["items"].append("caller mutation")
    saved.snapshot.values["nested"]["items"].append("result mutation")
    assert config.read().values == {"nested": {"items": [1, True]}}
    assert config.read().exists and config.read().revision != initial.revision


@pytest.mark.asyncio
async def test_reader_accepts_jsonc_comments_trailing_commas_bom_and_string_urls(env):
    _, start = env
    config, handle = await access(start)
    path = handle.plugin.root / "data/config.jsonc"
    path.parent.mkdir()
    path.write_text('\ufeff{// comment\n"url":"https://example.invalid/a//b", "nested":{"x":1,},}', encoding="utf-8")
    assert config.read().values == {"url": "https://example.invalid/a//b", "nested": {"x": 1}}


@pytest.mark.asyncio
async def test_revision_covers_external_document_and_schema_edits(env):
    _, start = env
    config, handle = await access(start)
    original = config.read()
    path = handle.plugin.root / "data/config.jsonc"
    path.parent.mkdir()
    path.write_text('{"external":true}', encoding="utf-8")
    with pytest.raises(ConfigError) as error:
        config.replace({"overwrite": True}, expected_revision=original.revision)
    assert error.value.code == "config/conflict" and config.read().values == {"external": True}


@pytest.mark.asyncio
async def test_schema_basic_validation_rejects_bad_candidate_and_tracks_schema_revision(env, tmp_path):
    _, start = env
    folder = tmp_path / "plugins/example"
    folder.mkdir(parents=True)
    schema = folder / "schema.json"
    schema.write_text(json.dumps({"type": "object", "required": ["count"], "properties": {"count": {"type": "integer"}}}))
    config, _ = await access(start, raw={"config": {"schema": "./schema.json"}})
    snapshot = config.read()
    assert snapshot.validation.level == "basic" and not snapshot.validation.valid
    assert not config.validate({"count": True}).valid
    with pytest.raises(ConfigError) as error:
        config.replace({"count": "wrong"}, expected_revision=snapshot.revision)
    assert error.value.code == "config/invalid-values" and not config.read().exists
    schema.write_text(json.dumps({"type": "object", "properties": {"count": {"type": "string"}}}))
    with pytest.raises(ConfigError) as error:
        config.replace({"count": "new"}, expected_revision=snapshot.revision)
    assert error.value.code == "config/conflict"
    assert config.replace({"count": "new"}, expected_revision=config.read().revision).saved


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["broken", "[]", '{"bad": NaN}'])
async def test_malformed_config_is_never_silently_reset_by_replacement(env, raw):
    _, start = env
    config, handle = await access(start)
    initial = config.read()
    path = handle.plugin.root / "data/config.jsonc"
    path.parent.mkdir()
    path.write_text(raw)
    for callback in (config.read, lambda: config.replace({}, expected_revision=initial.revision)):
        with pytest.raises(ConfigError):
            callback()
        assert path.read_text() == raw


@pytest.mark.asyncio
async def test_scope_restart_and_plugin_owners_preserve_only_own_configuration(env):
    root, start = env
    first, handle = await access(start, "first")
    first.replace({"private": 1}, expected_revision=first.read().revision)
    second, _ = await access(start, "second")
    assert second.read().values == {}
    await stop_plugin_backend(handle)
    with pytest.raises(RuntimeError):
        first.read()
    await start_plugin_backend(handle, root)
    assert handle.context.config.read().values == {"private": 1}
    with pytest.raises(RuntimeError):
        first.replace({}, expected_revision="stale")


@pytest.mark.asyncio
async def test_invalid_json_values_and_failed_replace_preserve_previous_file(env, monkeypatch):
    _, start = env
    config, _ = await access(start)
    config.replace({"value": "original"}, expected_revision=config.read().revision)
    before = config.read()
    for value in ({1: "not JSON"}, {"nested": (1, 2)}, {"number": float("inf")}):
        with pytest.raises(ConfigError):
            config.replace(value, expected_revision=before.revision)
    with monkeypatch.context() as patched:
        patched.setattr("lamtools_core.plugin_system.config_store.os.replace", lambda *a: (_ for _ in ()).throw(OSError("save failed")))
        with pytest.raises(ConfigError):
            config.replace({"value": "new"}, expected_revision=before.revision)
    assert config.read().values == before.values and config.read().revision == before.revision


@pytest.mark.asyncio
async def test_declared_bad_schema_is_not_treated_as_no_schema(env, tmp_path):
    _, start = env
    folder = tmp_path / "plugins/example"
    folder.mkdir(parents=True)
    schema = folder / "schema.json"
    schema.write_text("not a JSON object")
    config, _ = await access(start, raw={"config": {"schema": "./schema.json"}})
    for callback in (config.read, lambda: config.validate({}), lambda: config.replace({}, expected_revision="0" * 64)):
        with pytest.raises(ConfigError) as error:
            callback()
        assert error.value.code == "config/schema"
    assert not (folder / "data/config.jsonc").exists()


@pytest.mark.asyncio
async def test_bundled_plugin_uses_legacy_shared_path_and_old_writer_invalidates_revision(tmp_path, monkeypatch):
    from lamtools_core.plugin_system.plugin_data import read_plugin_config, write_plugin_config
    bundled = tmp_path / "bundled"
    folder = bundled / "core-demo"
    folder.mkdir(parents=True)
    monkeypatch.setattr("lamtools_core.plugin_system.paths.bundled_plugins_dir", lambda: bundled)
    root = PluginContext(tmp_path, data_dir=tmp_path / "data")
    configs = []
    handle = PluginRuntimeHandle(PluginManifest("core-demo", "1", root=folder), {"start": lambda ctx: configs.append(ctx.config)}, context=root.for_work_root(tmp_path))
    await start_plugin_backend(handle, root)
    try:
        config = configs[0]
        initial = config.read()
        assert Path(initial.path) == tmp_path / "data/plugins/core-demo.jsonc"
        config.replace({"value": "sdk"}, expected_revision=initial.revision)
        assert read_plugin_config(tmp_path / "data", "core-demo") == {"value": "sdk"}
        previous = config.read()
        write_plugin_config(tmp_path / "data", "core-demo", {"value": "legacy"})
        assert config.read().values == {"value": "legacy"}
        with pytest.raises(ConfigError) as error:
            config.replace({}, expected_revision=previous.revision)
        assert error.value.code == "config/conflict" and not (folder / "data").exists()
    finally:
        await stop_plugin_backend(handle)


@pytest.mark.asyncio
async def test_process_writers_cannot_both_commit_the_same_expected_revision(env):
    import subprocess
    import sys
    _, start = env
    config, handle = await access(start)
    before = config.read()
    source = '''
import sys
from pathlib import Path
from lamtools_core.plugin_system.manifest import PluginManifest
from lamtools_core.plugin_system.config_store import save_config_values, ConfigError
manifest = PluginManifest("example", "1", root=Path(sys.argv[1]))
try:
    save_config_values(manifest, {"winner": sys.argv[3]}, expected_revision=sys.argv[2])
except ConfigError as error:
    if error.code == "config/conflict":
        sys.exit(2)
    raise
'''
    processes = [subprocess.Popen([sys.executable, "-c", source, str(handle.plugin.root), before.revision, name], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for name in ("one", "two")]
    statuses = []
    for process in processes:
        _, errors = process.communicate()
        assert process.returncode in {0, 2}, errors.decode("utf-8", errors="replace")
        statuses.append(process.returncode)
    assert sorted(statuses) == [0, 2] and config.read().values["winner"] in {"one", "two"}


@pytest.mark.asyncio
async def test_busy_config_writer_reports_error_then_releases_for_explicit_retry(env):
    import subprocess
    import sys
    _, start = env
    config, _ = await access(start)
    initial = config.read()
    source = '''
import sys
from pathlib import Path
from lamtools_core.plugin_system.file_lock import locked_file
with locked_file(Path(sys.argv[1]).with_suffix(".lock")):
    print("locked", flush=True)
    sys.stdin.readline()
'''
    process = subprocess.Popen([sys.executable, "-c", source, initial.path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert process.stdout.readline().strip() == b"locked"
        with pytest.raises(ConfigError) as error:
            config.replace({"value": "blocked"}, expected_revision=initial.revision)
        assert error.value.code == "config/busy" and not config.read().exists
    finally:
        _, errors = process.communicate(input=b"release\n")
        assert process.returncode == 0, errors.decode("utf-8", errors="replace")
    assert config.replace({"value": "retry"}, expected_revision=initial.revision).saved


@pytest.mark.asyncio
async def test_failed_start_revokes_config_access_without_undoing_committed_file(env):
    _, start = env
    views = []
    def initialize(ctx):
        config = ctx.config
        views.append(config)
        config.replace({"saved": True}, expected_revision=config.read().revision)
        raise RuntimeError("startup failed")
    with pytest.raises(RuntimeError):
        await start(initialize)
    with pytest.raises(RuntimeError):
        views[0].read()
    current, _ = await access(start)
    assert current.read().values == {"saved": True}


def test_desktop_sdk_and_management_routes_share_path_revision_and_validation(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from lamtools_core.app.http_agent_app import create_core_agent_http_app
    monkeypatch.setattr("lamtools_core.app.http_agent_app.warm_command_shell", lambda: None)
    monkeypatch.setattr("lamtools_core.runtime.power.apply_keep_awake", lambda: None)
    folder = tmp_path / "plugins/config-consumer"
    folder.mkdir(parents=True)
    (folder / "plugin.json").write_text(json.dumps({"name": "config-consumer", "version": "1", "backend": "./backend.py"}))
    (folder / "backend.py").write_text('''
class Runtime:
    def start(self, context):
        self.config = context.config
        self.initial = self.config.read()
def create_plugin(context):
    return Runtime()
''')
    app = create_core_agent_http_app(core_db=tmp_path / "boot.db", data_dir=tmp_path / "data", work_root=tmp_path / "project", plugin_roots=[tmp_path / "plugins"])
    with TestClient(app) as client:
        state = app.state.core_agent_app_state
        handle = next(h for h in state["plugin_runtimes"] if h.plugin.name == "config-consumer")
        assert handle.state == "ready", handle.error
        operations = state["operations"]
        read = client.portal.call(operations.execute, "plugin.system.config.get", {"name": "config-consumer"})
        assert read.payload["revision"] == handle.value.initial.revision
        saved = client.portal.call(operations.execute, "plugin.system.config.update", {"name": "config-consumer", "config": {"value": "route"}, "expected_revision": read.payload["revision"]})
        assert saved.status == "ok" and saved.payload["saved"] and saved.payload["applied"] is False
        assert handle.value.config.read().values == {"value": "route"}
        rejected = client.portal.call(operations.execute, "plugin.system.config.update", {"name": "config-consumer", "config": {}, "expected_revision": read.payload["revision"]})
        assert rejected.status == "error" and rejected.payload["code"] == "config/conflict"
        current = handle.value.config.read()
        handle.value.config.replace({"value": "sdk"}, expected_revision=current.revision)
        assert client.portal.call(operations.execute, "plugin.system.config.get", {"name": "config-consumer"}).payload["config"] == {"value": "sdk"}
    with pytest.raises(RuntimeError):
        handle.value.config.read()
