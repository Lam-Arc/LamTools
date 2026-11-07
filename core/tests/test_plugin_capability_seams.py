"""user:“每一个地方 sunday 都有等价或者近似接口”+(外部能力按上游真实注册契约验收，不伪造操作结果)。"""
import asyncio

import pytest

from lamtools_core.plugin_system import PluginContext


def contexts(tmp_path):
    first = PluginContext(tmp_path)
    first._begin_registration_scope("first", 1)
    second = first.for_work_root(tmp_path)
    second._registration_scope = None
    second._begin_registration_scope("second", 1)
    return first, second


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", [[], {}, None, 1])
async def test_lsp_invalid_operation_shapes_are_classified_before_provider_dispatch(tmp_path, operation):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(操作名类型错误统一归invalid-query，不能泄露集合查找TypeError或派发提供方)。
    from lamtools_core.plugin_system.capability_seams import CapabilityError
    first, second = contexts(tmp_path)
    (tmp_path / "sample.py").write_text("x = 1", encoding="utf8")
    calls = []
    async def query(request):
        calls.append(request)
        return {"kind": "hover", "hover": None}
    first.lsp.register_provider("python", {".py": "python"}, query)
    first._registration_scope.publish(set())
    try:
        with pytest.raises(CapabilityError) as error:
            await second.lsp.query(operation, "sample.py", line=0, character=0)
        assert error.value.code == "capability/invalid-query"
        assert not calls and not second._registration_scope._calls
        assert (await second.lsp.query("hover", "sample.py", line=0, character=0))["hover"] is None
        assert len(calls) == 1
    finally:
        await second._registration_scope.dispose()
        await first._registration_scope.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["hover", "goToDefinition", "findReferences", "goToImplementation"])
@pytest.mark.parametrize("change", ["none", "requester", "provider"])
async def test_lsp_read_publication_rechecks_original_provider_and_requester(tmp_path, operation, change):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(四种语言查询等待后复核原提供方与请求启动代，正常提供方结果仍按原协议返回)。
    from lamtools_core.plugin_system.services import ServiceError
    first, second = contexts(tmp_path)
    (tmp_path / "sample.py").write_text("x = 1", encoding="utf8")
    entered, release = asyncio.Event(), asyncio.Event()
    async def query(request):
        entered.set()
        await release.wait()
        return ({"kind": "hover", "hover": {"contents": "actual callback"}} if operation == "hover" else
            {"kind": "locations", "locations": [], "resolvedWorkspaceUri": tmp_path.as_uri()})
    withdraw = first.lsp.register_provider("python", {".py": "python"}, query)
    first._registration_scope.publish(set())
    task = asyncio.create_task(second.lsp.query(operation, "sample.py", line=0, character=0))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        if change == "requester":
            second._registration_scope.revoke()
        elif change == "provider":
            withdraw()
        release.set()
        if change == "none":
            result = await task
            assert result["kind"] == ("hover" if operation == "hover" else "locations")
        else:
            with pytest.raises(ServiceError) as error:
                await task
            assert error.value.code == ("service/scope-closed" if change == "requester" else "service/unavailable")
        assert not first._registration_scope._calls and not second._registration_scope._calls
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await second._registration_scope.dispose()
        await first._registration_scope.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["browser_use", "computer_use"])
async def test_exclusive_named_slot_retained_until_cleanup_and_old_disposer_safe(tmp_path, key):
    from lamtools_core.plugin_system.capability_seams import CapabilityError
    first, second = contexts(tmp_path)
    api = getattr(first, key)
    entered, release = asyncio.Event(), asyncio.Event()
    async def cleanup():
        entered.set()
        await release.wait()
    dispose = api.register("provider-one", cleanup=cleanup)
    assert getattr(second, key).provider_name == "provider-one"
    with pytest.raises(CapabilityError):
        getattr(second, key).register("provider-one")
    closing = asyncio.create_task(first._registration_scope.dispose())
    await asyncio.wait_for(entered.wait(), 3)
    assert getattr(second, key).provider_name == "provider-one"
    with pytest.raises(CapabilityError):
        getattr(second, key).register("new")
    release.set()
    await closing
    assert getattr(second, key).provider_name is None
    getattr(second, key).register("new")
    await dispose()
    assert getattr(second, key).provider_name == "new"
    await second._registration_scope.dispose()


@pytest.mark.asyncio
async def test_lsp_atomic_reservations_selection_utf16_and_bounded_results(tmp_path):
    from lamtools_core.plugin_system.capability_seams import CapabilityError
    first, second = contexts(tmp_path)
    path = tmp_path / "sample.py"
    path.write_text("# 😀\nx = 1", encoding="utf8")
    received = []
    async def query(request):
        received.append(request)
        return {"kind": "hover", "hover": {"contents": "value"}}
    dispose = first.lsp.register_provider("python", {".py": "python"}, query)
    first._registration_scope.publish(set())
    with pytest.raises(CapabilityError):
        second.lsp.register_provider("conflict", {".js": "javascript", ".py": "python"}, query)
    second.lsp.register_provider("js", {".js": "javascript"}, query)
    result = await second.lsp.query("hover", "sample.py", line=0, character=4)
    assert result["hover"]["contents"] == "value"
    assert received[0]["position"] == {"line": 0, "character": 4}
    assert received[0]["languageId"] == "python"
    assert received[0]["workspaceRoot"] == str(tmp_path)
    dispose()
    with pytest.raises(CapabilityError) as error:
        await second.lsp.query("hover", "sample.py", line=0, character=0)
    assert error.value.code == "capability/unavailable"
    await first._registration_scope.dispose()
    await second._registration_scope.dispose()


@pytest.mark.asyncio
async def test_lsp_provider_leases_cancel_join_and_reject_stale_and_invalid(tmp_path):
    from lamtools_core.plugin_system.capability_seams import CapabilityError
    from lamtools_core.plugin_system.services import ServiceError
    first, second = contexts(tmp_path)
    (tmp_path / "sample.py").write_text("x", encoding="utf8")
    entered, finished = asyncio.Event(), asyncio.Event()
    async def query(request):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()
    first.lsp.register_provider("python", {".py": "python"}, query)
    first._registration_scope.publish(set())
    api = second.lsp
    task = asyncio.create_task(api.query("hover", "sample.py", line=0, character=0))
    await asyncio.wait_for(entered.wait(), 3)
    closing = asyncio.create_task(first._registration_scope.dispose())
    await asyncio.sleep(0)
    assert not closing.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await closing
    assert finished.is_set()
    with pytest.raises(CapabilityError):
        await api.query("execute", "sample.py", line=0, character=0)
    with pytest.raises(CapabilityError):
        await api.query("hover", "../outside.py", line=0, character=-1)
    await second._registration_scope.dispose()
    with pytest.raises(ServiceError):
        await api.query("hover", "sample.py", line=0, character=0)
