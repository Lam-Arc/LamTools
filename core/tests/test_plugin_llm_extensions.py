"""user:“宿主能力补齐和接口完善与文档更新”+(扩展真实序列化请求和HTTP2xx接收，不把模型最终完成冒充接收)。"""
import asyncio
import json

import httpx
import pytest

from lamtools_core.llm import LLMRequest, ChatMessage
from .test_plugin_llm_access import env
from .test_plugin_model_access import store


@pytest.mark.asyncio
@pytest.mark.parametrize("change",["add","remove"])
async def test_extension_conflicts_use_frozen_base_during_provider_wait(env,change):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(扩展字段冲突必须依据准备时冻结的最终请求，不能受调用者等待期间增删原对象影响)。
    ctx, _, _ = env
    body = {"model":"model"}
    if change == "remove":
        body["z_field"] = "native-base"
    entered, release = asyncio.Event(), asyncio.Event()
    requests, second = [], []
    async def blocking(request):
        requests.append(request)
        entered.set()
        await release.wait()
    def later(request):
        second.append(request)
        return {"value":"extension-value"}
    ctx.llm_extensions.register("a_blocking",blocking)
    ctx.llm_extensions.register("z_field",later)
    task = asyncio.create_task(ctx.llm_extensions.prepare(body))
    try:
        await asyncio.wait_for(entered.wait(),3)
        if change == "add":
            body["z_field"] = "caller-added"
        else:
            del body["z_field"]
        release.set()
        prepared = await asyncio.wait_for(task,3)
        assert ("z_field" in requests[0].body) == (change == "remove")
        if change == "add":
            assert prepared.fields_for_wire() == {"z_field":"extension-value"} and len(second) == 1
        else:
            assert prepared.fields_for_wire() == {} and not second
            assert prepared.omitted["z_field"] == "base-field-conflict"
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_prepared_body_and_values_are_detached_and_accept_is_once(env):
    ctx, _, _ = env
    api = ctx.llm_extensions
    value = {"items": [1]}
    accepted = []
    def prepare(request):
        with pytest.raises(TypeError):
            request.body["model"] = "corrupt"
        assert request.session_id == "s" and request.purpose == "compaction"
        return {"value": value, "accept": lambda: accepted.append(True)}
    api.register("extra_field", prepare)
    txn = await api.prepare({"model": "model", "messages": []}, session_id="s", purpose="compaction")
    value["items"].append(2)
    assert txn.fields["extra_field"]["items"] == (1,)
    await asyncio.gather(txn.accept(), txn.accept())
    assert accepted == [True]
    api.register("body_copy", lambda request: {"value": [request.body]})
    assert "body_copy" in (await api.prepare({"model": "m"})).fields


@pytest.mark.asyncio
async def test_failures_omit_fields_cancel_rejects_and_old_provider_cannot_accept(env):
    from lamtools_core.plugin_system.llm_extensions import LLMExtensionError
    ctx, _, _ = env
    api = ctx.llm_extensions
    def bad(request):
        raise RuntimeError("private error")
    api.register("bad_field", bad)
    api.register("bad_value", lambda request: {"value": float('nan')})
    txn = await api.prepare({"model": "m"})
    assert not txn.fields and set(txn.omitted) == {"bad_field", "bad_value"}
    api.register("accept_failure", lambda request: {"value": True, "accept": lambda: (_ for _ in ()).throw(ValueError("private"))})
    called = []
    api.register("accepted", lambda request: {"value": 1, "accept": lambda: called.append(True)})
    txn = await api.prepare({"model": "m"})
    for _ in range(2):
        with pytest.raises(LLMExtensionError) as error:
            await txn.accept()
        assert "private" not in str(error.value)
    assert called == [True]
    entered = asyncio.Event()
    async def hanging(request):
        entered.set()
        await asyncio.Event().wait()
    api.register("hanging", hanging)
    task = asyncio.create_task(api.prepare({"model": "m"}))
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not ctx._registration_scope._calls


def native_client():
    from lamtools_core.llm.http_client import CoreHttpLLMClient, LLMConfig
    return CoreHttpLLMClient(config=LLMConfig(provider_name="test", provider_id="test", provider_api_type="openai",
        base_url="https://example.invalid/v1", api_key="test-only", model_record_id="route-one",
        model_id="shared-wire", display_name="test"), adapter_profile={}, thinking_enabled=False,
        thinking_budget=0, max_tokens=128, temperature=0)


@pytest.mark.asyncio
async def test_native_http_stream_survives_owned_read_tasks_and_releases_transport(env,monkeypatch):
    # user:“复用原宿主权威”+(独立读取任务仍使用原HTTP流和扩展上下文，读至结束并关闭实际响应)。
    from lamtools_core.llm import http_client
    ctx, _, _ = env
    ctx.llm_client, ctx.model_id = native_client(), "route-one"
    accepted, sent, closed = [], [], []
    ctx.llm_extensions.register("owned_read",lambda request: {"value":True,"accept":lambda: accepted.append(True)})
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            for text in ("one","two"):
                await asyncio.sleep(0)
                yield ('data: '+json.dumps({"choices":[{"delta":{"content":text}}]})+'\n\n').encode()
            yield b'data: [DONE]\n\n'
        async def aclose(self):
            closed.append(True)
    def transport(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200,stream=Body())
    original = httpx.AsyncClient
    monkeypatch.setattr(http_client.httpx,"AsyncClient",lambda **kw: original(transport=httpx.MockTransport(transport)))
    monkeypatch.setattr(http_client,"httpx_client_kwargs",lambda endpoint: {})
    monkeypatch.setattr(http_client.CoreHttpLLMClient,"_record_usage",lambda *args: None)
    async with ctx.llm.stream(LLMRequest(),ref="route-one") as stream:
        events = [event async for event in stream]
    assert ''.join(event.content or '' for event in events) == "onetwo"
    assert events[-1].kind in {"done","finish"}
    assert sent[0]["owned_read"] and accepted == [True] and closed
    assert stream not in stream._api._streams
    assert not ctx._registration_scope._calls


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 400])
async def test_sdk_extensions_reach_actual_native_http_payload_and_accept_only_2xx(env, monkeypatch, status):
    from lamtools_core.llm import http_client
    from lamtools_core.plugin_system.llm_access import LLMAccessError
    ctx, _, _ = env
    ctx.llm_client, ctx.model_id = native_client(), "route-one"
    facts, accepted, sent = [], [], []
    ctx.llm_extensions.register("extra_field", lambda request: (facts.append(request.body) or
        {"value": {"hello": [1]}, "accept": lambda: accepted.append(True)}))
    def transport(request):
        sent.append(json.loads(request.content))
        return httpx.Response(status, content=b'not-valid-json')
    original = httpx.AsyncClient
    monkeypatch.setattr(http_client.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(transport)))
    monkeypatch.setattr(http_client, "httpx_client_kwargs", lambda endpoint: {})
    with pytest.raises(LLMAccessError):
        await ctx.llm.complete(LLMRequest(messages=[ChatMessage(role="user", content="hello")]), ref="route-one")
    assert sent[0]["extra_field"] == {"hello": [1]}
    assert sent[0]["model"] == facts[0]["model"] == "shared-wire"
    assert "extra_field" not in facts[0]
    assert accepted == ([True] if status == 200 else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("forensics", [False, True])
async def test_accept_happens_before_response_body_and_stream_consumer(env, monkeypatch, streaming, forensics, tmp_path):
    from lamtools_core.llm import http_client
    ctx, _, _ = env
    ctx.llm_client, ctx.model_id = native_client(), "route-one"
    monkeypatch.setenv("LAMTOOLS_LLM_RAW_RECORDING", "1" if forensics else "0")
    monkeypatch.setenv("LAMTOOLS_LLM_FORENSIC_DIR", str(tmp_path / "forensics"))
    monkeypatch.setattr(ctx.llm_client, "_record_usage", lambda *args: None)
    accepted, body_reads = [], []
    ctx.llm_extensions.register("extra_field", lambda request: {"value": 1, "accept": lambda: accepted.append(True)})
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            assert accepted == [True]
            body_reads.append(True)
            if streaming:
                yield b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
                yield b'data: [DONE]\n\n'
            else:
                yield b'{"choices":[{"message":{"role":"assistant","content":"hello"},"finish_reason":"stop"}]}'
    original = httpx.AsyncClient
    monkeypatch.setattr(http_client.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Body()))))
    monkeypatch.setattr(http_client, "httpx_client_kwargs", lambda endpoint: {})
    if streaming:
        async with ctx.llm.stream(LLMRequest(), ref="route-one") as stream:
            assert (await anext(stream)).content == "hello"
    else:
        assert (await ctx.llm.complete(LLMRequest(), ref="route-one")).content == "hello"
    assert accepted == [True] and body_reads == [True]
    from lamtools_core.llm.request_extensions import current_extensions
    assert current_extensions.get() is None


@pytest.mark.asyncio
async def test_fields_are_exclusive_and_registration_revocation_removes_provider(env):
    from lamtools_core.plugin_system.services import ServiceError
    ctx, _, _ = env
    api = ctx.llm_extensions
    registration = api.register("extra_field", lambda request: {"value": 1})
    with pytest.raises(ServiceError):
        api.register("extra_field", lambda request: {"value": 2})
    registration()
    assert not (await api.prepare({"model": "m"})).fields


@pytest.mark.asyncio
async def test_stopped_provider_never_runs_accept_and_no_lease_blocks_idle_stream(env):
    from lamtools_core.plugin_system.services import ServiceError
    ctx, _, _ = env
    called = []
    api = ctx.llm_extensions
    api.register("field", lambda request: {"value": 1, "accept": lambda: called.append(True)})
    txn = await api.prepare({"model": "m"})
    assert not ctx._registration_scope._calls
    await ctx._registration_scope.dispose()
    with pytest.raises(ServiceError):
        await txn.accept()
    assert not called


@pytest.mark.asyncio
async def test_cancelled_accept_waits_for_once_only_callback_and_releases_lease(env):
    ctx, _, _ = env
    entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def accept():
        entered.set()
        await release.wait()
        finished.set()
    api = ctx.llm_extensions
    api.register("field", lambda request: {"value": 1, "accept": accept})
    txn = await api.prepare({"model": "m"})
    task = asyncio.create_task(txn.accept())
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set() and not ctx._registration_scope._calls
    await txn.accept()


@pytest.mark.asyncio
async def test_provider_scope_project_isolation_and_body_conflict(env, tmp_path):
    from lamtools_core.plugin_system.services import ServiceError
    from lamtools_core.plugin_system.llm_extensions import LLMExtensionError
    ctx, _, _ = env
    api = ctx.llm_extensions
    api.register("field", lambda request: {"value": 1})
    ctx._registration_scope.publish(set())
    other = ctx.for_work_root(tmp_path)
    other._registration_scope = None
    other._begin_registration_scope("other", 1)
    foreign = other.for_work_root(tmp_path / "foreign")
    try:
        assert (await other.llm_extensions.prepare({"model": "m"})).fields["field"] == 1
        assert not (await foreign.llm_extensions.prepare({"model": "m"})).fields
        with pytest.raises(ServiceError):
            other.llm_extensions.register("field", lambda request: {"value": 2})
        txn = await api.prepare({"field": "base"})
        assert not txn.fields and txn.omitted["field"] == "base-field-conflict"
        with pytest.raises(LLMExtensionError):
            api.register("model", lambda request: {"value": 2})
    finally:
        await other._registration_scope.dispose()


@pytest.mark.asyncio
async def test_invalid_extension_metadata_is_typed_error(env):
    from lamtools_core.plugin_system.llm_extensions import LLMExtensionError
    ctx, _, _ = env
    for kwargs in [{"purpose": []}, {"session_id": "\x00"}, {"session_id": 42}]:
        with pytest.raises(LLMExtensionError) as error:
            await ctx.llm_extensions.prepare({"model": "m"}, **kwargs)
        assert error.value.code == "llm-extension/invalid-request"


@pytest.mark.asyncio
async def test_custom_client_cannot_silently_drop_registered_extensions(env):
    from lamtools_core.plugin_system.llm_access import LLMAccessError
    ctx, client, _ = env
    ctx.llm_extensions.register("field", lambda request: {"value": 1})
    with pytest.raises(LLMAccessError) as error:
        await ctx.llm.complete(LLMRequest(), ref="route-one")
    assert error.value.code == "llm/extensions-unavailable" and not client.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("shallow", [False, True], ids=["plain", "shallow"])
async def test_real_config_routing_client_preserves_extensions(env, monkeypatch, streaming, shallow):
    """user:“如果不需要，就自己继续”+(清单勾选后继续修复真实宿主路由包装器遗漏的扩展接线)。"""
    from lamtools_core.app import http_agent_app
    from lamtools_core.llm import http_client
    ctx, _, _ = env
    config = native_client().config
    routes, sent, accepted = [], [], []
    def load(**kwargs):
        routes.append(kwargs)
        return config
    monkeypatch.setattr(http_agent_app, "load_llm_config", load)
    monkeypatch.setattr(http_agent_app, "_resolve_adapter_profile", lambda *args: {})
    monkeypatch.setattr(http_client.CoreHttpLLMClient, "_record_usage", lambda *args: None)
    ctx.llm_client = http_agent_app.CoreConfigRoutingLLMClient(default_model_ref="route-one")
    if shallow:
        from lamtools_core.llm.shallow_thinking import ShallowThinkingClient
        ctx.llm_client = ShallowThinkingClient(ctx.llm_client, enabled=True)
    def prepare(request):
        if shallow:
            from lamtools_core.llm.shallow_thinking import SHALLOW_THINKING_PROMPT
            assert any(message["role"] == "system" and SHALLOW_THINKING_PROMPT in message["content"]
                       for message in request.body["messages"])
        return {"value": True, "accept": lambda: accepted.append(True)}
    ctx.llm_extensions.register("native_route_field", prepare)
    def transport(request):
        sent.append(json.loads(request.content))
        data = (b'data: {"choices":[{"delta":{"content":"routed"}}]}\n\ndata: [DONE]\n\n' if streaming
                else b'{"choices":[{"message":{"role":"assistant","content":"routed"}}]}')
        return httpx.Response(200, content=data)
    original = httpx.AsyncClient
    monkeypatch.setattr(http_client.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(transport)))
    monkeypatch.setattr(http_client, "httpx_client_kwargs", lambda endpoint: {})
    if streaming:
        async with ctx.llm.stream(LLMRequest(), ref="route-one") as stream:
            assert (await anext(stream)).content == "routed"
    else:
        assert (await ctx.llm.complete(LLMRequest(), ref="route-one")).content == "routed"
    assert sent[0]["native_route_field"] is True and accepted == [True]
    assert routes == [{"model_ref": "route-one", "work_root": str(ctx.work_root)}]
