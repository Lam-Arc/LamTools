"""user:“继续，把 2 阶段都做完”+(会话查询要有扫描限额、隐藏资源隔离和只读语义，不能直接公开全量元数据)。"""
import pytest

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.app.live_operations import CoreLiveContext
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.app.plugin_sessions import install_plugin_session_services
from lamtools_core.plugin_system import PluginContext
from lamtools_core.session import SessionRecord


@pytest.fixture
async def env(tmp_path):
    db = await open_core_app_db(tmp_path / "query.db")
    store = CoreDbSessionStore(lambda: db)
    for sid in ("a", "b", "c", "hidden-secret-session"):
        await store.create(SessionRecord(sid, "core", "Title " + sid, "idle"))
    store._session_visible = lambda sid, meta: not sid.startswith("hidden")
    live = CoreLiveContext(session_factory=db.session_factory, persistence=db.persistence, operations=OperationCatalog(), hub=CoreAppEventHub())
    live.host.session_store = store
    context = PluginContext(tmp_path)
    sessions = install_plugin_session_services(context, lambda: live)
    context._begin_registration_scope("example", 1)
    try:
        yield context, store, sessions
    finally:
        sessions.shutdown()
        await context._registration_scope.dispose()
        await db.close()


@pytest.mark.asyncio
async def test_real_query_has_bounded_pages_and_opaque_owner_bound_cursor(env, tmp_path):
    root, _, _ = env
    first = await root.session_query.query(limit=1)
    assert [r.session_id for r in first.items] == ["a"] and first.has_more
    assert first.next_cursor and "a" != first.next_cursor
    second = await root.session_query.query(limit=1, cursor=first.next_cursor)
    assert [r.session_id for r in second.items] == ["b"]
    last = await root.session_query.query(limit=10, cursor=second.next_cursor)
    assert [r.session_id for r in last.items] == ["c"] and not last.has_more
    assert "hidden-secret-session" not in repr(first) + repr(last)
    other = root.for_work_root(tmp_path)
    other._registration_scope = None
    other._begin_registration_scope("other", 1)
    from lamtools_core.plugin_system import SessionQueryError
    try:
        with pytest.raises(SessionQueryError) as error:
            await other.session_query.query(cursor=first.next_cursor)
        assert error.value.code == "session-query/invalid-cursor"
    finally:
        await other._registration_scope.dispose()


@pytest.mark.asyncio
async def test_filter_is_literal_and_cursor_cannot_change_filter(env):
    from lamtools_core.plugin_system import SessionQueryError
    root, _, _ = env
    found = await root.session_query.query(title_contains="TITLE B")
    assert [r.session_id for r in found.items] == ["b"]
    first = await root.session_query.query(limit=1)
    with pytest.raises(SessionQueryError):
        await root.session_query.query(cursor=first.next_cursor, title_contains="other")


@pytest.mark.asyncio
async def test_query_does_not_use_legacy_mutating_list_or_get(env, monkeypatch):
    root, store, _ = env
    async def forbidden(*args, **kwargs):
        pytest.fail("query must not materialize legacy preferences")
    monkeypatch.setattr(store, "get", forbidden)
    monkeypatch.setattr(store, "list", forbidden)
    assert len((await root.session_query.query()).items) == 3


@pytest.mark.asyncio
async def test_closed_host_and_revoked_view_are_not_empty_results(env):
    from lamtools_core.plugin_system import SessionQueryError
    from lamtools_core.plugin_system.services import ServiceError
    root, _, sessions = env
    api = root.session_query
    sessions.shutdown()
    with pytest.raises(SessionQueryError) as error:
        await api.query()
    assert error.value.code == "session-query/closed"
    await root._registration_scope.dispose()
    with pytest.raises(ServiceError):
        await api.query()


@pytest.mark.asyncio
async def test_hidden_scan_budget_returns_continuation_not_false_complete_empty(env):
    from lamtools_core.app.core_db import CoreThreadSnapshot
    from lamtools_core.app.core_session_store import session_snapshot
    root, store, _ = env
    db = store._db_provider()
    async def insert(connection):
        for i in range(1002):
            sid = f"00hidden{i:04d}"
            record = SessionRecord(sid, "core", "Private", "idle")
            connection.add(CoreThreadSnapshot(thread_id=sid, snapshot_seq=0, snapshot_json=session_snapshot(record)))
    await db.persistence.write(insert)
    store._session_visible = lambda sid, meta: not (sid.startswith("00hidden") or sid.startswith("hidden"))
    first = await root.session_query.query()
    assert first.items == () and first.has_more and first.next_cursor
    assert "hidden" not in first.next_cursor
    rest = await root.session_query.query(cursor=first.next_cursor)
    assert [row.session_id for row in rest.items] == ["a", "b", "c"] and not rest.has_more
