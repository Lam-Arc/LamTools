"""user:“继续，把 2 阶段都做完”+(模型不止列目录，真实调用和流要保持项目、模型记录、取消和清理边界)。"""
import asyncio

import pytest

from lamtools_core.llm import ChatMessage, LLMRequest, LLMResponse, LLMUsage, LLMStreamEvent
from lamtools_core.plugin_system import PluginContext
from lamtools_core.plugin_system.model_catalog import ModelCatalogService
from .test_plugin_model_access import store


@pytest.mark.asyncio
async def test_cancelled_stream_close_waits_for_provider_cleanup_then_preserves_cancellation(env,monkeypatch):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(关闭调用者重复取消也要等真实清理，结束后保留取消结果)。
    ctx, client, _ = env
    entered, release = asyncio.Event(), asyncio.Event()
    class Source:
        closed = False
        async def aclose(self):
            entered.set()
            await release.wait()
            self.closed = True
    source = Source()
    monkeypatch.setattr(client,"stream",lambda request: source)
    stream = await ctx.llm.stream(LLMRequest(),ref="route-one").__aenter__()
    task = asyncio.create_task(stream.aclose())
    try:
        await asyncio.wait_for(entered.wait(),3)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not source.closed
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task,3)
    assert source.closed and stream not in stream._api._streams


@pytest.mark.asyncio
@pytest.mark.parametrize("stage",["initialization","read"])
@pytest.mark.parametrize("suppress_cancel",[False,True])
async def test_close_joins_pending_provider_operation_without_leaking_stream(env,monkeypatch,stage,suppress_cancel):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(并发关闭必须排空初始化或读取，提供方处理取消后也不能发布迟到事件)。
    ctx, client, _ = env
    entered, released = asyncio.Event(), asyncio.Event()
    sources = []
    class Source:
        def __init__(self):
            self.closed = False
        def __aiter__(self):
            return self
        async def __anext__(self):
            if stage == "read":
                entered.set()
                try:
                    await released.wait()
                except asyncio.CancelledError:
                    if not suppress_cancel:
                        raise
            return LLMStreamEvent(kind="content_delta",content="late")
        async def aclose(self):
            self.closed = True
    async def initialize(request):
        if stage == "initialization":
            entered.set()
            try:
                await released.wait()
            except asyncio.CancelledError:
                if not suppress_cancel:
                    raise
        source = Source()
        sources.append(source)
        return source
    monkeypatch.setattr(client,"stream",initialize)
    stream = ctx.llm.stream(LLMRequest(),ref="route-one")
    if stage == "read":
        await stream.__aenter__()
    operation = asyncio.create_task(stream.__aenter__() if stage == "initialization" else anext(stream))
    try:
        await asyncio.wait_for(entered.wait(),3)
        await asyncio.wait_for(stream.aclose(),3)
        outcome = (await asyncio.wait_for(asyncio.gather(operation,return_exceptions=True),3))[0]
        assert isinstance(outcome,BaseException)
        assert all(source.closed for source in sources)
        assert stream not in stream._api._streams
    finally:
        released.set()
        if not operation.done():
            operation.cancel()
        await asyncio.gather(operation,return_exceptions=True)
        await stream.aclose()


@pytest.fixture
async def env(tmp_path, store):
    class Client:
        uses_config_routing = True
        def __init__(self):
            self.calls, self.routes = [], []
            self.entered = asyncio.Event()
            self.block = False
            self.closed = False
        def with_runtime_options(self, **kwargs):
            self.routes.append(kwargs)
            return self
        async def complete(self, request):
            self.calls.append(request)
            self.entered.set()
            if self.block:
                await asyncio.Event().wait()
            return LLMResponse(content="answer", usage=LLMUsage(10, 2), raw={"internal": "not exported"})
        async def stream(self, request):
            self.calls.append(request)
            try:
                yield LLMStreamEvent(kind="content_delta", content="first")
                yield LLMStreamEvent(kind="usage", usage=LLMUsage(10, 2))
                yield LLMStreamEvent(kind="done")
            finally:
                self.closed = True
    client = Client()
    context = PluginContext(tmp_path, llm_client=client)
    context.set_service("model_catalog", ModelCatalogService(work_root=tmp_path))
    context._begin_registration_scope("example", 1)
    try:
        yield context, client, store
    finally:
        await context._registration_scope.dispose()


@pytest.mark.asyncio
async def test_actual_call_uses_exact_record_and_pinned_project_and_copies_input(env, tmp_path):
    context, client, _ = env
    api = context.llm
    context.work_root = tmp_path / "changed"
    request = LLMRequest(messages=[ChatMessage(role="user", content="hello")])
    result = await api.complete(request, scene="chat", ref="route-one")
    assert result.content == "answer" and result.usage.total_tokens == 12 and result.raw is None
    request.messages[0].content = "mutated"
    assert client.calls[0].messages[0].content == "hello"
    assert client.calls[0].model == "route-one"
    assert client.routes[0]["work_root"] == str(tmp_path.resolve())


@pytest.mark.asyncio
async def test_stream_closes_on_context_exit_and_stop_closes_parked_stream(env):
    context, client, _ = env
    async with context.llm.stream(LLMRequest(messages=[ChatMessage(role="user", content="hello")]), ref="route-one") as stream:
        assert (await anext(stream)).content == "first"
    assert client.closed
    client.closed = False
    stream = context.llm.stream(LLMRequest(), ref="route-one")
    await stream.__aenter__()
    await anext(stream)
    await context._registration_scope.dispose()
    assert client.closed
    from lamtools_core.plugin_system.services import ServiceError
    with pytest.raises(ServiceError):
        await anext(stream)


@pytest.mark.asyncio
async def test_stream_all_events_and_token_estimate_are_explicit(env):
    context, _, _ = env
    request = LLMRequest(messages=[ChatMessage(role="user", content="你好")])
    events = []
    async with context.llm.stream(request, ref="route-one") as stream:
        async for event in stream:
            events.append(event)
    assert [e.kind for e in events] == ["content_delta", "usage", "done"]
    estimate = context.llm.estimate(request)
    assert estimate.tokens > 0 and not estimate.exact


@pytest.mark.asyncio
async def test_timeout_and_caller_cancellation_do_not_fake_success(env):
    from lamtools_core.plugin_system import LLMAccessError
    context, client, _ = env
    client.block = True
    with pytest.raises(LLMAccessError) as error:
        await context.llm.complete(LLMRequest(timeout=0.01), ref="route-one")
    assert error.value.code == "llm/timeout"
    client.entered.clear()
    task = asyncio.create_task(context.llm.complete(LLMRequest(timeout=10), ref="route-one"))
    await client.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_ambiguous_and_unavailable_models_never_call_provider(env):
    from lamtools_core.plugin_system import LLMAccessError
    context, client, state = env
    for ref in ("Shared", "unknown"):
        with pytest.raises(LLMAccessError):
            await context.llm.complete(LLMRequest(), ref=ref)
    state["unavailable"].update({"one", "One"})
    with pytest.raises(LLMAccessError):
        await context.llm.complete(LLMRequest(), ref="route-one")
    assert not client.calls


def test_project_config_lookup_is_explicit_instead_of_global(tmp_path, store, monkeypatch):
    from lamtools_core.cli_commands import config
    from lamtools_core.config import model_selection
    monkeypatch.setattr(config, "_get_model_store", lambda: ModelCatalogService()._store())
    monkeypatch.setattr(config, "ProviderStore", model_selection.ProviderStore)
    result = config.load_llm_config(model_ref="route-one", work_root=str(tmp_path))
    assert result.model_record_id == "route-one" and result.model_id == "shared-wire"
    assert store["roots"][-1] == str(tmp_path)


@pytest.mark.asyncio
async def test_real_config_routing_client_keeps_workspace_and_wire_identity(env, tmp_path, monkeypatch):
    from lamtools_core.app import http_agent_app as app
    from lamtools_core.cli_commands import config
    from lamtools_core.config import model_selection
    context, _, _ = env
    monkeypatch.setattr(config, "_get_model_store", lambda: ModelCatalogService()._store())
    monkeypatch.setattr(config, "ProviderStore", model_selection.ProviderStore)
    seen = []
    def load(**kwargs):
        seen.append(kwargs)
        return config.load_llm_config(**kwargs)
    class Wire:
        async def complete(self, request):
            assert request.model == "shared-wire"
            return LLMResponse(content="wire answer")
    monkeypatch.setattr(app, "load_llm_config", load)
    monkeypatch.setattr(app, "_resolve_adapter_profile", lambda *args: {})
    monkeypatch.setattr(app, "CoreHttpLLMClient", lambda **kwargs: Wire())
    context.llm_client = app.CoreConfigRoutingLLMClient(default_model_ref="wrong-global-route")
    response = await context.llm.complete(LLMRequest(), ref="route-one")
    assert response.content == "wire answer"
    assert seen == [{"model_ref": "route-one", "work_root": str(tmp_path)}]


@pytest.mark.asyncio
async def test_provider_error_and_invalid_request_are_typed_not_payload_leaks(env):
    from lamtools_core.plugin_system import LLMAccessError
    context, client, _ = env
    async def fail(request):
        raise RuntimeError("SENSITIVE-provider-payload")
    client.complete = fail
    with pytest.raises(LLMAccessError) as error:
        await context.llm.complete(LLMRequest(), ref="route-one")
    assert error.value.code == "llm/provider-error" and "SENSITIVE" not in str(error.value)
    with pytest.raises(LLMAccessError) as error:
        await context.llm.complete(LLMRequest(timeout=float("nan")), ref="route-one")
    assert error.value.code == "llm/invalid-request"


@pytest.mark.asyncio
async def test_incomplete_stream_raises_and_closes(env):
    from lamtools_core.plugin_system import LLMAccessError
    context, client, _ = env
    async def incomplete(request):
        try:
            yield LLMStreamEvent(kind="content_delta", content="partial")
        finally:
            client.closed = True
    client.stream = incomplete
    with pytest.raises(LLMAccessError) as error:
        async with context.llm.stream(LLMRequest(), ref="route-one") as stream:
            async for event in stream:
                pass
    assert error.value.code == "llm/incomplete-stream" and client.closed
