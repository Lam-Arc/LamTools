"""user:“继续，无人值守模式，不要停下来”+(领域表和全局状态在同一原存储事务中提交，冲突/校验失败不能留下半份数据)。"""
import pytest

from lamtools_core.plugin_system import PluginContext
from lamtools_core.plugin_system.storage_access import StorageError, ensure_plugin_storage


@pytest.fixture
def ctx(tmp_path):
    context = PluginContext(tmp_path, data_dir=tmp_path / "data")
    ensure_plugin_storage(context, root=tmp_path / "data" / "plugin-data")
    context._begin_registration_scope("domain", 1)
    context._registration_scope.publish(set())
    return context


@pytest.mark.asyncio
@pytest.mark.parametrize("withdraw", ["none", "dispose", "close"])
async def test_observer_withdrawn_by_earlier_callback_is_not_notified_after_close(ctx, withdraw):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(已提交通知遍历中撤回的观察者不能继续调用，关闭句柄立即撤回其通知，提交事实不回滚)。
    writer = ctx.storage_domain.open("notify", tables=["notes"])
    reader = ctx.storage_domain.open("notify", tables=["notes"])
    seen = []
    def first(event):
        seen.append(("first", event["revision"]))
        if withdraw == "dispose":
            dispose_second()
        elif withdraw == "close":
            reader.close()
    writer.on_change(first)
    dispose_second = reader.on_change(lambda event: seen.append(("second", event["revision"])))
    try:
        saved = writer.commit([], expected_revision=0, global_value="committed")
        assert saved.revision == 1 and writer.read().global_value == "committed"
        assert seen == ([("first", 1), ("second", 1)] if withdraw == "none" else [("first", 1)])
        dispose_second()
        writer.commit([], expected_revision=1, global_value="next")
        assert seen[-1] == ("first", 2)
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_domain_tables_global_atomic_revision_and_reopen(ctx):
    domain = ctx.storage_domain.open("notes", tables=["notes", "labels"])
    initial = domain.read()
    assert initial.revision == 0 and initial.global_value is None
    saved = domain.commit([{"table": "notes", "key": "one", "value": {"text": "saved"}},
                           {"table": "labels", "key": "tag", "value": "important"}],
                          global_value={"selected": "one"}, expected_revision=0)
    assert saved.revision == 1
    saved.tables["notes"]["one"]["text"] = "caller mutation"
    domain.close()
    reopened = ctx.storage_domain.open("notes", tables=["notes", "labels"])
    current = reopened.read()
    assert current.tables["notes"]["one"]["text"] == "saved"
    assert current.global_value == {"selected": "one"}
    with pytest.raises(StorageError) as error:
        reopened.commit([], global_value="stale", expected_revision=0)
    assert error.value.code == "storage/conflict"
    assert reopened.read() == current
    await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_invalid_transaction_changes_nothing_and_exact_schema_is_required(ctx):
    domain = ctx.storage_domain.open("notes", tables=["notes"])
    with pytest.raises(ValueError):
        domain.commit([{"table": "notes", "key": "one", "value": "valid"},
                       {"table": "unknown", "key": "two", "value": "invalid"}], expected_revision=0)
    assert domain.read().revision == 0
    domain.commit([], expected_revision=0, global_value="saved")
    with pytest.raises(StorageError):
        ctx.storage_domain.open("notes", tables=["different"])
    with pytest.raises(StorageError):
        ctx.storage_domain.open("notes", tables=["notes"], version=2)
    await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_local_change_observers_see_commits_and_are_removed_on_close_and_reload(ctx):
    domain = ctx.storage_domain.open("notes", tables=["notes"])
    other = ctx.storage_domain.open("notes", tables=["notes"])
    seen = []
    other.on_change(lambda event: seen.append(event))
    domain.commit([], global_value=1, expected_revision=0)
    assert seen == [{"name": "notes", "revision": 1}]
    other.close()
    domain.commit([], global_value=2, expected_revision=1)
    assert len(seen) == 1
    await ctx._registration_scope.dispose()
    with pytest.raises(Exception):
        domain.read()
    ctx._begin_registration_scope("domain", 2)
    assert ctx.storage_domain.open("notes", tables=["notes"]).read().global_value == 2
    await ctx._registration_scope.dispose()
