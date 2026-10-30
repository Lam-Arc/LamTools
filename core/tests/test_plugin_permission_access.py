"""user:“宿主能力补齐和接口完善与文档更新”+(权限读取复用会话规则并保持可见性，不因查询升级权限或写回旧数据)。"""
from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from copy import deepcopy

import pytest

from lamtools_core.app.core_db import CoreThreadSnapshot, open_core_app_db
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.app.live_operations import CoreLiveContext
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.app.plugin_sessions import install_plugin_session_services
from lamtools_core.app import runtime_permissions
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.session import SessionRecord


@pytest.fixture
async def env(tmp_path, monkeypatch):
    controls = {"permission_preset": "ask", "base_tier": "full_edit", "base_allow_access_outside_workdir": False}
    monkeypatch.setattr(runtime_permissions, "load_global_runtime_controls", lambda: dict(controls))
    db = await open_core_app_db(tmp_path / "permissions.db")
    hidden = set()
    store = CoreDbSessionStore(lambda: db, session_visible=lambda sid, metadata: sid not in hidden)
    live = CoreLiveContext(session_factory=db.session_factory, persistence=db.persistence,
                           operations=OperationCatalog(), hub=CoreAppEventHub())
    live.host.session_store = store
    root = PluginContext(tmp_path)
    sessions = install_plugin_session_services(root, lambda: live)
    root._begin_registration_scope("example", 1)
    await store.create(SessionRecord("s", "core", "Title", "idle", metadata={"private": "not in result"}))
    try:
        yield root, live, store, db, hidden, controls, sessions
    finally:
        sessions.shutdown()
        await root._registration_scope.dispose()
        await db.close()


@pytest.mark.asyncio
async def test_catalog_and_session_selection_use_existing_authority(env):
    root, _, _, _, _, controls, _ = env
    api = root.permissions
    catalog = api.catalog()
    assert tuple(p.name for p in catalog.options) == runtime_permissions.PERMISSION_PRESETS
    assert tuple(p.auto_approve_level for p in catalog.options) == (1, 2, 3)
    assert catalog.default_preset == "ask"
    view = await api.read("s")
    assert view.session_id == "s" and view.preset == "ask" and view.preferences_stored
    assert view.base_tier == "full_edit" and view.base_available_level == 3
    assert view.preset_auto_approve_level == 1 and not view.allow_access_outside_workdir
    assert view.basis == "session-preferences" and "private" not in repr(view)
    with pytest.raises(FrozenInstanceError):
        view.preset = "full_access"
    controls["permission_preset"] = "full_access"
    assert api.catalog().default_preset == "full_access"
    assert (await api.read("s")).preset == "ask"


@pytest.mark.asyncio
@pytest.mark.parametrize("preset,threshold,outside", [("ask", 1, False), ("auto", 2, False), ("full_access", 3, True)])
async def test_preset_never_invents_capability_above_base(env, preset, threshold, outside):
    root, _, store, _, _, _, _ = env
    await store.create(SessionRecord("restricted", "core", "Restricted", "idle", metadata={"runtime_preferences": {
        "permission_preset": preset, "base_tier": "read_only", "base_allow_access_outside_workdir": False}}))
    view = await root.permissions.read("restricted")
    assert view.preset == preset and view.preset_auto_approve_level == threshold
    assert view.base_tier == "read_only" and view.base_available_level == 1
    assert view.allow_access_outside_workdir == outside


@pytest.mark.asyncio
async def test_read_is_fresh_after_canonical_session_patch(env):
    root, _, store, _, _, _, _ = env
    api = root.permissions
    assert (await api.read("s")).preset == "ask"
    record = await store.get("s")
    metadata = runtime_permissions.with_session_runtime_preferences(record.metadata, permission_preset="auto")
    await store.patch("s", metadata=metadata)
    assert (await api.read("s")).preset == "auto"


@pytest.mark.asyncio
async def test_legacy_query_does_not_materialize_preferences_or_emit_events(env):
    root, _, store, db, _, controls, _ = env
    async def remove(db_session):
        row = await db_session.get(CoreThreadSnapshot, "s")
        payload = deepcopy(row.snapshot_json)
        payload["session"]["metadata"].pop("runtime_preferences")
        row.snapshot_json = payload
    await db.persistence.write(remove)
    async def raw():
        async with db.session_factory() as connection:
            row = await connection.get(CoreThreadSnapshot, "s")
            return deepcopy(row.snapshot_json), row.revision, row.snapshot_seq, row.updated_at
    before = await raw()
    controls["permission_preset"] = "auto"
    view = await root.permissions.read("s")
    assert view.preset == "auto" and not view.preferences_stored
    assert await raw() == before
    # 原有 get 仍保留按需落盘行为，新增只读入口不改变旧调用者。
    await store.get("s")
    assert (await root.permissions.read("s")).preferences_stored


@pytest.mark.asyncio
async def test_hidden_and_missing_are_indistinguishable(env):
    root, _, _, _, hidden, _, _ = env
    from lamtools_core.plugin_system import PermissionAccessError
    hidden.add("s")
    for sid in ("s", "absent"):
        with pytest.raises(PermissionAccessError) as error:
            await root.permissions.read(sid)
        assert error.value.code == "permissions/not-found"


@pytest.mark.asyncio
@pytest.mark.parametrize("sid", ["", " ", None, "a" * 257])
async def test_invalid_session_id_rejected(env, sid):
    from lamtools_core.plugin_system import PermissionAccessError
    with pytest.raises(PermissionAccessError) as error:
        await env[0].permissions.read(sid)
    assert error.value.code == "permissions/invalid-session"


@pytest.mark.asyncio
async def test_closed_host_and_replaced_store_are_not_silent_defaults(env):
    from lamtools_core.plugin_system import PermissionAccessError
    root, live, store, _, _, _, sessions = env
    api = root.permissions
    live.host.session_store = object()
    with pytest.raises(PermissionAccessError) as error:
        await api.read("s")
    assert error.value.code == "permissions/host-changed"
    live.host.session_store = store
    sessions.shutdown()
    for call in [lambda: api.catalog(), lambda: api.read("s")]:
        with pytest.raises(PermissionAccessError) as error:
            value = call()
            if asyncio.iscoroutine(value):
                await value
        assert error.value.code == "permissions/closed"


@pytest.mark.asyncio
async def test_old_views_are_revoked_and_cancel_releases_read_lease(env, monkeypatch):
    from lamtools_core.plugin_system.services import ServiceError
    root, _, store, _, _, _, _ = env
    api = root.permissions
    entered = asyncio.Event()
    async def block(sid):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(store, "get_readonly", block)
    task = asyncio.create_task(api.read("s"))
    try:
        await asyncio.wait_for(entered.wait(), 5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    await root._registration_scope.dispose()
    with pytest.raises(ServiceError):
        api.catalog()
    with pytest.raises(ServiceError):
        await api.read("s")


@pytest.mark.asyncio
async def test_backend_read_failure_is_not_a_default_permission(env, monkeypatch):
    from lamtools_core.plugin_system import PermissionAccessError
    root, _, store, _, _, _, _ = env
    async def fail(sid):
        raise RuntimeError("private backing payload")
    monkeypatch.setattr(store, "get_readonly", fail)
    with pytest.raises(PermissionAccessError) as error:
        await root.permissions.read("s")
    assert error.value.code == "permissions/read-failed"
    assert "private backing payload" not in str(error.value)


@pytest.mark.asyncio
async def test_read_does_not_fallback_to_mutating_store_method(env, monkeypatch):
    from lamtools_core.plugin_system import PermissionAccessError
    root, _, store, _, _, _, _ = env
    monkeypatch.setattr(store, "get_readonly", None)
    async def unexpected(sid):
        pytest.fail("permission read must not invoke the potentially mutating get")
    monkeypatch.setattr(store, "get", unexpected)
    with pytest.raises(PermissionAccessError) as error:
        await root.permissions.read("s")
    assert error.value.code == "permissions/unavailable"


def test_permissions_require_managed_scope_and_host(tmp_path):
    from lamtools_core.plugin_system.services import ServiceError
    root = PluginContext(tmp_path)
    with pytest.raises(ServiceError):
        _ = root.permissions
    root._begin_registration_scope("example", 1)
    with pytest.raises(LookupError):
        _ = root.permissions
