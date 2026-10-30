"""user:“宿主能力补齐和接口完善与文档更新”+(凭据读取保持 owner/代际边界，状态查询不泄露值，持久故障不能变成丢失或假成功)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.lifecycle import PluginRuntimeHandle, start_plugin_backend, stop_plugin_backend
from lamtools_core.plugin_system.manifest import PluginManifest
from lamtools_core.plugin_system.secrets import PluginSecretStore, SecretStoreError
from lamtools_core.plugin_system.credentials import CredentialError


@pytest.fixture
async def env(tmp_path):
    store = PluginSecretStore(tmp_path / "secrets")
    root = PluginContext(tmp_path, _secret_store=store)
    handles = []
    async def start(callback, name="example"):
        handle = PluginRuntimeHandle(PluginManifest(name, "1", root=tmp_path), {"start": callback}, context=root.for_work_root(tmp_path))
        handles.append(handle)
        await start_plugin_backend(handle, root)
        return handle
    try:
        yield root, store, start
    finally:
        for handle in reversed(handles):
            await stop_plugin_backend(handle)


async def access(start, name="example"):
    views = []
    await start(lambda ctx: views.append(ctx.credentials), name)
    return views[0]


@pytest.mark.asyncio
async def test_resolve_and_value_free_description_roundtrip_use_existing_protection(env, tmp_path, caplog):
    _, _, start = env
    credentials = await access(start)
    assert credentials.resolve("API_KEY") is None
    assert credentials.describe("API_KEY").to_dict() == {"configured": False, "source": None, "writable": True}
    value = "private-值-for-acceptance"
    credentials.set("API_KEY", value)
    hit = credentials.resolve("API_KEY")
    assert hit.value == value and hit.source == "plugin-store"
    assert value not in repr(hit) and value not in repr(credentials.describe("API_KEY"))
    assert "value" not in credentials.describe("API_KEY").to_dict()
    disk = (tmp_path / "secrets/secrets.json").read_text(encoding="utf-8")
    assert value not in disk and "dpapi:" in disk and value not in caplog.text
    credentials.unset("API_KEY")
    credentials.unset("API_KEY")
    assert credentials.resolve("API_KEY") is None


@pytest.mark.asyncio
async def test_plugin_owners_are_isolated_and_no_environment_fallback_is_assumed(env, monkeypatch):
    _, _, start = env
    first = await access(start, "first")
    second = await access(start, "second")
    monkeypatch.setenv("API_KEY", "host-environment-value")
    first.set("API_KEY", "first-value")
    assert second.resolve("API_KEY") is None
    second.set("API_KEY", "second-value")
    assert first.resolve("API_KEY").value == "first-value"
    assert second.resolve("API_KEY").value == "second-value"
    first.unset("API_KEY")
    assert first.resolve("API_KEY") is None


@pytest.mark.asyncio
async def test_scope_revocation_and_restart_require_new_facade(env):
    root, _, start = env
    views = []
    handle = await start(lambda ctx: views.append(ctx.credentials))
    views[0].set("API_KEY", "retained")
    await stop_plugin_backend(handle)
    for callback in (lambda: views[0].resolve("API_KEY"), lambda: views[0].describe("API_KEY"), lambda: views[0].set("API_KEY", "bad"), lambda: views[0].unset("API_KEY")):
        with pytest.raises(RuntimeError):
            callback()
    await start_plugin_backend(handle, root)
    assert views[1].resolve("API_KEY").value == "retained"


@pytest.mark.asyncio
async def test_failed_start_revokes_access_but_preserves_committed_secret(env):
    _, _, start = env
    views = []
    def initialize(ctx):
        views.append(ctx.credentials)
        views[0].set("API_KEY", "saved-before-failure")
        raise RuntimeError("startup failed")
    with pytest.raises(RuntimeError):
        await start(initialize)
    with pytest.raises(RuntimeError):
        views[0].resolve("API_KEY")
    current = await access(start)
    assert current.resolve("API_KEY").value == "saved-before-failure"


@pytest.mark.asyncio
async def test_invalid_references_and_empty_values_never_erase_existing_value(env):
    _, _, start = env
    credentials = await access(start)
    credentials.set("API_KEY", "retained")
    for key in ("", "other/KEY", "../KEY", " KEY", "KEY-NAME"):
        with pytest.raises(CredentialError):
            credentials.resolve(key)
    for value in ("", "   ", None, 7, "\ud800"):
        with pytest.raises(CredentialError):
            credentials.set("API_KEY", value)
    assert credentials.resolve("API_KEY").value == "retained"


def test_independent_store_instances_re_read_rotation_and_preserve_other_writes(tmp_path):
    root = tmp_path / "secrets"
    first, second = PluginSecretStore(root), PluginSecretStore(root)
    first.set("one", "API_KEY", "v1")
    assert second.get("one", "API_KEY") == "v1"
    second.set("two", "TOKEN", "v2")
    first.set("one", "API_KEY", "rotated")
    third = PluginSecretStore(root)
    assert third.get("two", "TOKEN") == "v2" and second.get("one", "API_KEY") == "rotated"
    second.delete("one", "API_KEY")
    assert first.get("one", "API_KEY") == "" and first.get("two", "TOKEN") == "v2"


@pytest.mark.parametrize("contents", [b"broken json", b'{"version":2,"plugins":{}}', b'{"version":1,"plugins":{"one":[]}}'])
def test_corrupt_or_unsupported_store_is_explicit_and_never_overwritten(tmp_path, contents):
    root = tmp_path / "secrets"
    root.mkdir()
    path = root / "secrets.json"
    path.write_bytes(contents)
    store = PluginSecretStore(root)
    for callback in (lambda: store.keys("one"), lambda: store.get("one", "API_KEY"), lambda: store.set("one", "API_KEY", "must-not-overwrite"), lambda: store.clear("one")):
        with pytest.raises(SecretStoreError):
            callback()
        assert path.read_bytes() == contents


def test_failed_atomic_save_leaves_disk_and_subsequent_reads_unchanged(tmp_path, monkeypatch):
    root = tmp_path / "secrets"
    store = PluginSecretStore(root)
    store.set("one", "API_KEY", "original")
    before = (root / "secrets.json").read_bytes()
    with monkeypatch.context() as patched:
        def fail_replace(*args):
            raise OSError("SIMULATED-sensitive-message")
        patched.setattr("lamtools_core.plugin_system.secrets.os.replace", fail_replace)
        with pytest.raises(SecretStoreError) as error:
            store.set("one", "API_KEY", "replacement")
        assert "SIMULATED" not in str(error.value)
        import traceback
        assert "SIMULATED" not in "".join(traceback.format_exception(error.value))
    assert (root / "secrets.json").read_bytes() == before
    assert store.get("one", "API_KEY") == "original"
    assert not list(root.glob(".secrets-*.tmp"))


@pytest.mark.asyncio
async def test_description_does_not_decrypt_and_bad_ciphertext_fails_without_revealing_it(env, tmp_path, monkeypatch):
    _, _, start = env
    credentials = await access(start)
    credentials.set("API_KEY", "original")
    path = tmp_path / "secrets/secrets.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["plugins"]["example"]["API_KEY"]["value"] = "dpapi:not-valid-ciphertext"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr("lamtools_core.plugin_system.secrets._decode", lambda value: (_ for _ in ()).throw(ValueError("SENSITIVE-decrypt-input")))
    assert credentials.describe("API_KEY").configured
    with pytest.raises(CredentialError) as error:
        credentials.resolve("API_KEY")
    assert error.value.code == "credentials/decrypt" and "SENSITIVE" not in str(error.value)
    import traceback
    assert "SENSITIVE" not in "".join(traceback.format_exception(error.value))


def test_legacy_scoped_view_uses_same_file_and_empty_set_remains_delete(tmp_path):
    store = PluginSecretStore(tmp_path / "secrets")
    view = store.view("one")
    view.set("API_KEY", "legacy")
    assert view.has("API_KEY") and view.get("API_KEY") == "legacy"
    view.set("API_KEY", "")
    assert not view.has("API_KEY") and view.get("API_KEY", "missing") == "missing"


def test_process_writers_preserve_each_others_keys_in_the_existing_file(tmp_path):
    import subprocess
    import sys
    root = tmp_path / "secrets"
    source = '''
import sys
from lamtools_core.plugin_system.secrets import PluginSecretStore
store = PluginSecretStore(sys.argv[1])
for index in range(20):
    store.set("shared", sys.argv[2] + "_" + str(index), "acceptance-value")
'''
    writers = [subprocess.Popen([sys.executable, "-c", source, str(root), prefix], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for prefix in ("FIRST", "SECOND")]
    for writer in writers:
        _, errors = writer.communicate()
        assert writer.returncode == 0, errors.decode("utf-8", errors="replace")
    store = PluginSecretStore(root)
    assert len(store.keys("shared")) == 40
    assert store.get("shared", "FIRST_19") == "acceptance-value"
    assert store.get("shared", "SECOND_19") == "acceptance-value"


def test_external_file_lock_is_bounded_and_failure_does_not_modify_credentials(tmp_path):
    import subprocess
    import sys
    root = tmp_path / "secrets"
    store = PluginSecretStore(root)
    store.set("one", "API_KEY", "retained")
    source = '''
import sys
from lamtools_core.plugin_system.secrets import PluginSecretStore
with PluginSecretStore(sys.argv[1])._locked():
    print("locked", flush=True)
    sys.stdin.readline()
'''
    blocker = subprocess.Popen([sys.executable, "-c", source, str(root)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert blocker.stdout.readline().strip() == b"locked"
        with pytest.raises(SecretStoreError) as error:
            store.set("one", "API_KEY", "not committed")
        assert error.value.code == "credentials/busy"
    finally:
        _, errors = blocker.communicate(input=b"release\n")
        assert blocker.returncode == 0, errors.decode("utf-8", errors="replace")
    assert store.get("one", "API_KEY") == "retained"


def test_desktop_startup_new_facade_and_legacy_secret_view_share_owner_namespace(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from lamtools_core.app.http_agent_app import create_core_agent_http_app
    monkeypatch.setattr("lamtools_core.app.http_agent_app.warm_command_shell", lambda: None)
    monkeypatch.setattr("lamtools_core.runtime.power.apply_keep_awake", lambda: None)
    plugin_root = tmp_path / "plugins/credential-consumer"
    plugin_root.mkdir(parents=True)
    (plugin_root / "plugin.json").write_text(json.dumps({"name": "credential-consumer", "version": "1", "backend": "./backend.py"}))
    (plugin_root / "backend.py").write_text('''
class Runtime:
    def start(self, context):
        self.credentials = context.credentials
        self.credentials.set("API_KEY", "acceptance-only")
        self.legacy = context.require_service("secrets")
        assert self.legacy.get("API_KEY") == "acceptance-only"
def create_plugin(context):
    return Runtime()
''')
    app = create_core_agent_http_app(core_db=tmp_path / "boot.db", data_dir=tmp_path / "data", work_root=tmp_path / "project", plugin_roots=[tmp_path / "plugins"])
    with TestClient(app):
        handle = next(h for h in app.state.core_agent_app_state["plugin_runtimes"] if h.plugin.name == "credential-consumer")
        assert handle.state == "ready", handle.error
        assert handle.value.credentials.describe("API_KEY").configured
        handle.value.legacy.set("API_KEY", "rotated")
        assert handle.value.credentials.resolve("API_KEY").value == "rotated"
    with pytest.raises(RuntimeError):
        handle.value.credentials.resolve("API_KEY")
