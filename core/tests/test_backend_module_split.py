"""Acceptance coverage for extracting backend responsibilities."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import importlib
import json

import httpx
import pytest

from lamtools_core import cli
from lamtools_core.llm import ChatMessage, LLMRequest
from lamtools_core.app import live_operations as live
from lamtools_core.plugins.bundled.workflow.backend import runtime as workflow

# user:“审查后端大文件并拆分”+(拆分前固定分页、输出和工作流行为，拆分后验证原入口兼容。)


def test_http_client_keeps_request_defaults_and_normalizes_tool_calls():
    config = cli.LLMConfig(provider_name="test", provider_api_type="openai", base_url="https://example.invalid/v1",
        api_key="test-key", model_record_id="model", model_id="test-model", display_name="Test", notes="model note")
    client = cli.CoreHttpLLMClient(config=config, adapter_profile=cli._resolve_adapter_profile(config, ()),
        thinking_enabled=False, thinking_budget=100, max_tokens=200, temperature=0.1)
    messages = [ChatMessage(role="user", content="hello")]
    request = client._request_with_defaults(LLMRequest(model="test-model", messages=messages))
    assembled = client._assemble_request(request, stream=False)
    assert assembled["endpoint"] == "/chat/completions"
    assert assembled["payload"]["model"] == "test-model"
    assert assembled["payload"]["messages"][0]["role"] == "system"
    assert "model note" in assembled["payload"]["messages"][0]["content"]
    assert messages == [ChatMessage(role="user", content="hello")]
    assert client._headers(request)["Authorization"] == "Bearer test-key"
    response = client._normalize_response({"choices": [{"message": {"content": "ok", "tool_calls": [
        {"id": "call", "function": {"name": "read", "arguments": '{"path":"a"}'}}
    ]}, "finish_reason": "tool_calls"}]}, model="test-model")
    calls = cli._llm_tool_calls_from_raw(response["tool_calls"])
    assert (calls[0].id, calls[0].name, calls[0].arguments) == ("call", "read", {"path": "a"})


def test_http_provider_errors_keep_retry_classification():
    from lamtools_core.kernel.errors import LLMProviderError, RateLimitError

    error = cli._http_provider_error(429, "slow down", {"retry-after": "2"})
    assert isinstance(error, RateLimitError)
    assert error.retry_after == 2
    denied = cli._http_provider_error(403, "denied", {}, provider_name="test")
    assert isinstance(denied, LLMProviderError)
    assert denied.status_code == 403
    assert "provider=test" in str(denied)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_http_client_transport_keeps_complete_and_stream_results(monkeypatch, stream):
    config = cli.LLMConfig(provider_name="test", provider_api_type="openai", base_url="https://example.invalid/v1",
        api_key="test-key", model_record_id="model", model_id="test-model", display_name="Test")
    client = cli.CoreHttpLLMClient(config=config, adapter_profile=cli._resolve_adapter_profile(config, ()),
        thinking_enabled=False, thinking_budget=100, max_tokens=200, temperature=0.1)
    sent = []

    def respond(request):
        sent.append(json.loads(request.content))
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        if stream:
            chunk = {"choices": [{"index": 0, "delta": {"content": "完成"}, "finish_reason": None}]}
            return httpx.Response(200, text="data:" + json.dumps(chunk) + "\n\ndata: [DONE]\n\n",
                headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "完成"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2}})

    original_client = httpx.AsyncClient

    def mock_client(**kwargs):
        return original_client(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(httpx, "AsyncClient", mock_client)
    request = LLMRequest(model="test-model", messages=[ChatMessage(role="user", content="hello")])
    if stream:
        events = [event async for event in client.stream(request)]
        assert "".join(event.content for event in events) == "完成"
        assert events[-1].kind == "done"
    else:
        response = await client.complete(request)
        assert response.content == "完成"
        assert response.usage.total_tokens == 5
    assert len(sent) == 1
    assert sent[0].get("stream", False) is stream


@pytest.mark.parametrize(("original", "extracted", "names"), [
    ("lamtools_core.cli", "lamtools_core.llm.http_client", ("LLMConfig", "CoreHttpLLMClient")),
    ("lamtools_core.cli", "lamtools_core.cli_reporting", ("_build_summary", "_redact_event")),
    ("lamtools_core.app.live_operations", "lamtools_core.app.thread_history", ("_character_page_snapshot", "_history_cursor")),
    ("lamtools_core.plugins.bundled.workflow.backend.runtime", "lamtools_core.plugins.bundled.workflow.backend.models",
        ("WorkflowDef", "WorkflowNode", "WorkflowRunResult")),
])
def test_original_imports_share_the_extracted_implementation(original, extracted, names):
    old_module = importlib.import_module(original)
    new_module = importlib.import_module(extracted)
    for name in names:
        assert getattr(old_module, name) is getattr(new_module, name)
        assert getattr(new_module, name).__module__ == extracted


def test_history_pages_reassemble_mixed_unicode_timeline_without_mutation():
    ids = [f"item-{index}" for index in range(12)]
    items = {
        key: {"id": key, "seq": index + 1, "turn_id": "turn", "text": "历史" * 120}
        for index, key in enumerate(ids)
    }
    snapshot = {
        "thread_id": "thread",
        "items": {key: items[key] for key in ids[::2]},
        "item_order": ids[::2],
        "core": {"items": {key: items[key] for key in ids[1::2]}, "item_order": ids[1::2]},
    }
    original = deepcopy(snapshot)
    cursor = (None, None)
    seen = []
    for _ in range(len(ids)):
        page = live._character_page_snapshot(
            snapshot, before_item_id=cursor[0], before_seq=cursor[1],
            char_limit=200_000, turn_limit=10, byte_limit=2_000,
        )
        info = page["history_page"]
        assert 0 < info["byte_count"] <= 2_000
        ordered = sorted([*page["items"], *page["core"]["items"]], key=lambda key: items[key]["seq"])
        seen = ordered + seen
        if not info["has_more"]:
            break
        next_cursor = (info["next_before_item_id"], info["next_before_seq"])
        assert next_cursor != cursor
        cursor = next_cursor
    else:
        pytest.fail("history cursor did not finish")
    assert seen == ids
    assert snapshot == original


def test_history_artifact_reference_keeps_stored_body():
    artifact = {"artifact_id": "image", "metadata": {"image_data_url": "data:image/png;base64," + "A" * 300_000}}
    item = {"artifacts": [artifact]}
    original = deepcopy(item)
    reference = live._reference_oversized_item_artifacts(item)["artifacts"][0]
    assert reference["artifact_id"] == "image"
    assert reference["availability"] == "reference"
    assert reference["mime_type"] == "image/png"
    assert reference["size_bytes"] == 225_000
    assert reference["metadata"] == {}
    assert item == original


def test_history_limits_and_legacy_cursor_inputs():
    assert live._history_byte_budget({"pageBytes": "999999999"}) == live.MAX_THREAD_HISTORY_PAGE_BYTES
    assert live._history_byte_budget({"page_bytes": "bad"}) == live.DEFAULT_THREAD_HISTORY_PAGE_BYTES
    assert live._history_turn_limit({"turnLimit": -1}) == 1
    assert live._history_cursor({"beforeItemId": " old ", "beforeSeq": "12"}) == ("old", 12)


def test_cli_summary_preserves_repeat_and_failure_metrics(tmp_path):
    def event(name, **payload):
        return SimpleNamespace(name=name, payload=payload)

    events = [
        event("runtime.tool.started", tool_name="read", arguments={"path": "a"}),
        event("runtime.tool.started", tool_name="read", arguments={"path": "a"}),
        event("runtime.tool.finished", status="ok"),
        event("runtime.tool.finished", status="error"),
        event("runtime.part", part_type="text", content="完成", response_index=0),
    ]
    result = SimpleNamespace(state=None, decision="done", steps=[1], run_id="run", session_id="session", message="完成")
    summary = cli._build_summary(result=result, events=events, model_context={"model": "test"}, run_dir=tmp_path)
    assert summary["ok"] is True
    assert summary["execution"]["tool_calls"] == 2
    assert summary["execution"]["repeated_exact_tool_calls"] == 1
    assert summary["execution"]["tool_failure_rate"] == 0.5
    assert summary["proof"]["max_text_chars"] == 2


def test_cli_redaction_keeps_input_and_removes_inline_data():
    raw = {"payload": {"part_type": "reasoning", "content": "private", "raw": "provider"},
           "metadata": {"image": "data:image/png;base64,AAAA"}}
    event = SimpleNamespace(name="runtime.part", to_dict=lambda: deepcopy(raw))
    redacted = cli._redact_event(event)
    assert "content" not in redacted["payload"]
    assert "raw" not in redacted["payload"]
    assert redacted["payload"]["content_len"] == 7
    assert redacted["metadata"]["image"]["redacted"] == "embedded_data_url"
    assert raw["payload"]["content"] == "private"


def test_workflow_legacy_model_roundtrip_and_stable_port_ids():
    raw = {"name": "legacy", "nodes": [{"id": "node", "kind": "action", "config": {"action_type": "script"},
           "inputs": [{"name": "value"}], "outputs": [{"name": "out", "value": 42}]}]}
    definition = workflow.WorkflowDef.from_dict(raw)
    assert definition.nodes[0].kind == "script"
    assert definition.nodes[0].ports[0].id
    assert workflow.WorkflowDef.from_dict(raw).nodes[0].ports[0].id == definition.nodes[0].ports[0].id
    assert workflow.WorkflowDef.from_dict(definition.to_dict()).to_dict() == definition.to_dict()
    assert workflow.ensure_workflow_id(definition, seed="legacy-path") == workflow.ensure_workflow_id(
        workflow.WorkflowDef(name="legacy"), seed="legacy-path")


def test_workflow_public_result_redaction_preserves_durable_state():
    state = workflow.WorkflowNodeState.from_dict({"nodeId": "node", "status": "completed", "attemptId": "attempt",
        "output": {"value": 42, "apiKey": "secret", "reasoning": "hidden"}})
    result = workflow.WorkflowRunResult(node_states={"node": state}, values={"node.out": 42},
        wait_descriptor={"kind": "signal", "resume_token": "bearer"})
    stored = result.to_dict()
    assert workflow.WorkflowRunResult.from_dict(stored).to_dict() == stored
    public = result.to_public_dict()
    assert public["node_states"]["node"]["output"] == {"value": 42}
    assert public["wait_descriptor"] == {"kind": "signal"}
    assert result.to_dict() == stored
    assert state.status == "done"


@pytest.mark.asyncio
async def test_workflow_runner_accepts_extracted_models():
    definition = workflow.WorkflowDef(name="content", nodes=[workflow.WorkflowNode(
        id="node", kind="content", ports=[workflow.WorkflowPort(name="out", direction="out", value=42)],
    )], output_port="node.out")
    result = await workflow.WorkflowRunner().run(definition)
    assert isinstance(result, workflow.WorkflowRunResult)
    assert result.status == "completed"
    assert result.output == 42
