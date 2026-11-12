"""Acceptance: tell "building/sending the model request" apart from "waiting for the first token".

The desktop waiting indicator shows two different animations:
  * phase 1 — message accepted → the HTTP request has actually been sent;
  * phase 2 — request sent → the provider's first visible token arrived.

These tests pin the two facts the UI consumes:
  1. the HTTP client invokes ``LLMRequest.on_request_sent`` only after the
     provider answered the request (2xx response headers), before any stream
     event is yielded;
  2. the kernel publishes transient ``runtime.model_phase`` facts in order
     (building → sent → first_token), and the projection turns them into
     turn-level run items instead of transcript rows.
"""

import asyncio
import time

import httpx
import pytest

from lamtools_core.app.base_agent import core_events_to_run_items
from lamtools_core.app.default_agent import _persist_core_event_live
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.cli import CoreHttpLLMClient, LLMConfig
from lamtools_core.event import CollectingEventSink, CoreEvent
from lamtools_core.event.runtime_projection import runtime_fact_to_run_item_events
from lamtools_core.kernel import CoreLoopKernel, LoopPolicy
from lamtools_core.llm import ChatMessage, LLMRequest, LLMResponse, LLMStreamEvent
from lamtools_core.llm.policy import RetryPolicy
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState


class _Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        return None


def _model_client() -> CoreHttpLLMClient:
    return CoreHttpLLMClient(
        config=LLMConfig(
            provider_name="test-provider",
            provider_id="test-provider",
            provider_api_type="openai",
            base_url="https://test.invalid/v1",
            api_key="test-key",
            model_record_id="record",
            model_id="test-model",
            display_name="test",
            thinking_supported=False,
            thinking_budget=0,
        ),
        adapter_profile={"protocol": "openai-chat-completions"},
        thinking_enabled=False,
        thinking_budget=0,
        max_tokens=100,
        temperature=0.2,
    )


def _sse_body(*lines: str) -> bytes:
    return "".join(line + "\n\n" for line in [*lines, "data: [DONE]"]).encode()


@pytest.fixture
def mock_httpx(monkeypatch):
    """Route every httpx client through an in-process transport."""

    def install(handler):
        real = httpx.AsyncClient

        def build(**kwargs):
            return real(**kwargs, transport=httpx.MockTransport(handler))

        monkeypatch.setattr(httpx, "AsyncClient", build)

    return install


async def test_http_stream_reports_request_sent_before_the_first_stream_event(mock_httpx):
    """The hook marks "request crossed the wire"; it must fire before any token."""
    seen: list[LLMStreamEvent] = []
    sent_after_events: list[int] = []
    body = _sse_body(
        'data: {"id":"1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"hi"},"finish_reason":null}]}',
    )
    mock_httpx(lambda request: httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        stream=_Chunks([body]),
    ))

    request = LLMRequest(
        messages=[ChatMessage(role="user", content="hi")],
        # The kernel attaches this hook; storing an async callback must survive
        # `_request_with_defaults` and the shallow-thinking wrapper.
        on_request_sent=lambda: sent_after_events.append(len(seen)),
    )

    async for event in _model_client().stream(request):
        seen.append(event)

    assert seen and seen[-1].kind == "done"
    assert sent_after_events == [0], "hook must run once, before the first token"


class _PhaseRecordingStreamLLM:
    """Streaming client that simulates the HTTP client's sent-callback."""

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        assert request.on_request_sent is not None
        await request.on_request_sent()
        # A real gateway sits quiet between the 2xx headers and the first token.
        await asyncio.sleep(0)
        yield LLMStreamEvent(kind="thinking_delta", content="想")
        yield LLMStreamEvent(kind="content_delta", content="答")
        yield LLMStreamEvent(kind="done", metadata={"finish_reason": "stop"})

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("streaming fixture must not fall back to complete()")


def _kernel_with(llm_client, sink: CollectingEventSink) -> CoreLoopKernel:
    return CoreLoopKernel(
        kit=object(),  # type: ignore[arg-type] — the streaming path never touches the kit
        llm_client=llm_client,
        state_store=InMemoryRuntimeStateStore(),
        event_sink=sink,
        policy=LoopPolicy(),
        retry_policy=RetryPolicy(),
    )


async def test_kernel_publishes_model_phases_in_order_as_transient_facts():
    sink = CollectingEventSink()
    llm_client = _PhaseRecordingStreamLLM()
    kernel = _kernel_with(llm_client, sink)

    response = await kernel._stream_model(
        LLMRequest(messages=[ChatMessage(role="user", content="hi")]),
        RuntimeState(session_id="phase-session", run_id="phase-run"),
        response_index=0,
    )

    assert response is not None
    phases = [
        event
        for event in sink.events
        if event.name == "runtime.model_phase"
    ]
    assert [event.payload["phase"] for event in phases] == [
        "request_building",
        "request_sent",
        "first_token",
    ]
    for event in phases:
        assert event.metadata.get("delivery") == "transient"
        assert event.payload["response_index"] == 0
    assert isinstance(phases[1].payload.get("elapsed_ms"), int)
    assert phases[1].payload["elapsed_ms"] >= 0
    assert isinstance(phases[2].payload.get("ttft_ms"), int)
    assert phases[2].payload["ttft_ms"] >= 0

    # Phase facts are live-only: the persistence collector must not see them.
    persisted_phase_items = [
        item
        for item in core_events_to_run_items(sink.events, thread_id="phase-thread")
        if item.kind == "model_phase"
    ]
    assert persisted_phase_items == []
    live_items = core_events_to_run_items(
        sink.events,
        thread_id="phase-thread",
        include_transient=True,
    )
    phase_items = [item for item in live_items if item.kind == "model_phase"]
    assert [item.payload["phase"] for item in phase_items] == [
        "request_building",
        "request_sent",
        "first_token",
    ]
    assert all(item.turn_id for item in phase_items)


async def test_first_request_elapsed_is_counted_from_turn_start():
    """user:“阶段一应该是从 turn start 开始”.

    Time spent in the run's setup (before the model call) belongs to phase 1:
    the waiting animation must blame local preparation, not the provider.
    """
    from tests.test_kernel import MockKitStep, MockRuntimeKit, _make_kernel, _make_turn_input

    class SlowStartKit(MockRuntimeKit):
        async def on_run_start(self, state, turn_input):
            await super().on_run_start(state, turn_input)
            await asyncio.sleep(0.08)

    sink = CollectingEventSink()
    kit = SlowStartKit(steps=[MockKitStep(reply="ok", decision="done")])
    kernel = _make_kernel(
        kit,
        llm_client=_PhaseRecordingStreamLLM(),
        event_sink=sink,
    )

    await kernel.run(_make_turn_input())

    phases = [event for event in sink.events if event.name == "runtime.model_phase"]
    assert [event.payload["phase"] for event in phases] == [
        "request_building",
        "request_sent",
        "first_token",
    ]
    # SlowStartKit sleeps 80ms after turn start and before the request goes out.
    assert phases[1].payload["elapsed_ms"] >= 80


def test_model_phase_projection_is_a_turn_level_fact():
    events = runtime_fact_to_run_item_events(
        thread_id="thread-1",
        event_id="phase-sent",
        group="progress",
        source="core",
        phase="runtime.model_phase",
        status="running",
        sequence=1,
        metadata={"payload": {
            "phase": "request_sent",
            "response_index": 0,
            "elapsed_ms": 120,
            "ttft_ms": None,
            "turn_id": "turn-1",
        }},
    )

    assert events and len(events) == 1
    item = events[0]
    assert item.kind == "model_phase"
    assert item.item_id == ""
    assert item.turn_id == "turn-1"
    assert item.payload["phase"] == "request_sent"
    assert item.payload["elapsed_ms"] == 120


async def test_model_phase_reaches_the_live_hub_without_becoming_history():
    """The desktop listens on the live hub: the phase must arrive there too."""
    hub = CoreAppEventHub()
    queue = hub.subscribe("phase-thread")
    event = CoreEvent(
        name="runtime.model_phase",
        category="progress",
        session_id="phase-thread",
        run_id="phase-run",
        payload={"phase": "request_sent", "response_index": 0, "elapsed_ms": 12},
        metadata={"delivery": "transient"},
    )

    await _persist_core_event_live(
        event,
        thread_id="phase-thread",
        db_session_factory=None,
        app_event_store=None,
        thread_snapshot_store=None,
        app_event_hub=hub,
    )

    published = queue.get_nowait()
    assert published.method == "core/runItem"
    assert published.seq == 0
    assert published.payload["kind"] == "model_phase"
    assert published.payload["payload"]["phase"] == "request_sent"
    assert published.turn_id
    assert not published.payload.get("item_id")
