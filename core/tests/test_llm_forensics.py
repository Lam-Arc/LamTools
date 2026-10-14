"""quality-task-1: local-only HTTP forensic acceptance."""
import asyncio
import gzip
import hashlib
import json

import httpx
import pytest

from lamtools_core.cli import CoreHttpLLMClient, LLMConfig
from lamtools_core.llm import ChatMessage, LLMRequest
from lamtools_core.llm.forensics import Capture, recorded_request
from lamtools_core.llm.retry import complete_with_retry, stream_with_retry


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks, error=None):
        self.chunks, self.error, self.closed = chunks, error, False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.error:
            raise self.error

    async def aclose(self):
        self.closed = True


@pytest.fixture
def forensic_root(tmp_path, monkeypatch):
    monkeypatch.setenv("LAMTOOLS_LLM_RAW_RECORDING", "1")
    monkeypatch.setenv("LAMTOOLS_LLM_FORENSIC_DIR", str(tmp_path))
    return tmp_path


def records(root):
    return [(p, json.loads(p.read_text(encoding="utf-8"))) for p in root.glob("*/metadata.json")]


def model_client(protocol="openai-chat-completions"):
    return CoreHttpLLMClient(
        config=LLMConfig(provider_name="test-provider", provider_api_type="openai",
                         base_url="https://user:password@test.invalid/v1?secret=key",
                         api_key="AUTHENTICATION_SECRET", model_record_id="record", model_id="test-model",
                         display_name="test", thinking_supported=False, thinking_budget=0),
        adapter_profile={"protocol": protocol}, thinking_enabled=False, thinking_budget=0,
        max_tokens=100, temperature=0.2,
    )


def mock_client(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real(
        **kwargs, transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("protocol", ["openai-chat-completions", "openai-responses", "anthropic-messages", "gemini"])
async def test_serialized_requests_sse_tail_and_identity(forensic_root, monkeypatch, protocol):
    raw = b'data: [DONE]\r\n\r\n' + b': trailing evidence\r\n\r\n' + b'\xff\x00'
    sent = []
    chunks = Chunks([raw[:5], raw[5:19], raw[19:]])
    def handler(request):
        sent.append(request.content)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=chunks)
    mock_client(monkeypatch, handler)
    request = LLMRequest(messages=[ChatMessage(role="user", content="private \u4e2d\u6587")],
                         metadata={"_runtime_session_id": "session", "_runtime_run_id": "run", "_runtime_step": 283})
    events = [event async for event in model_client(protocol).stream(request)]
    assert events[-1].kind == "done"
    path, meta = records(forensic_root)[0]
    assert (path.parent / "request.bin").read_bytes() == sent[0]
    assert (path.parent / "response.bin").read_bytes() == raw
    assert meta["capture_state"] == "complete" and meta["response_complete"]
    assert meta["request_bytes"] == len(sent[0]) and meta["response_bytes"] == len(raw)
    assert meta["response_sha256"] == hashlib.sha256(raw).hexdigest()
    assert (meta["session_id"], meta["run_id"], meta["step"], meta["retry_index"]) == ("session", "run", 283, 0)
    assert events[-1].metadata["cache_diagnostic_route"]["forensic_record_id"] == meta["record_id"]
    assert chunks.closed
    for secret in ("AUTHENTICATION_SECRET", "password", "secret=key", "private"):
        assert secret not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("status", [200, 429, 500])
async def test_nonstream_compression_and_error_bodies(forensic_root, status):
    body = gzip.compress(b'{"private":"' + b'x' * 1000000 + b'"}')
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
        status, headers={"content-encoding": "gzip"}, stream=Chunks([body[:7], body[7:]])))) as client:
        async with recorded_request(client, "POST", "https://test.invalid", context={}, json={"x": 1}) as response:
            assert len(response.json()["private"]) == 1000000
    path, meta = records(forensic_root)[0]
    assert (path.parent / "response.bin").read_bytes() == body
    assert meta["status"] == status and meta["capture_state"] == "complete"


@pytest.mark.parametrize("error", [httpx.ReadError("secret failure"), asyncio.CancelledError()])
async def test_partial_failure_and_cancel_preserve_bytes(forensic_root, error):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
        200, stream=Chunks([b"available evidence"], error)))) as client:
        with pytest.raises(type(error)):
            async with recorded_request(client, "POST", "https://test.invalid", context={}, json={}):
                pass
    path, meta = records(forensic_root)[0]
    assert (path.parent / "response.bin").read_bytes() == b"available evidence"
    assert meta["capture_state"] == ("interrupted" if isinstance(error, asyncio.CancelledError) else "failed")
    assert not meta["response_complete"] and meta["response_bytes"] == 18
    assert "secret failure" not in path.read_text()


async def test_close_before_eof_and_connection_failure(forensic_root):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
        200, stream=Chunks([b"first", b"second"])))) as client:
        async with recorded_request(client, "POST", "https://test.invalid", context={}, stream=True, json={}) as response:
            iterator = response.aiter_raw()
            assert await anext(iterator) == b"first"
    assert records(forensic_root)[0][1]["capture_state"] == "interrupted"
    def fail(request):
        raise httpx.ConnectError("secret")
    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(httpx.ConnectError):
            async with recorded_request(client, "POST", "https://test.invalid", context={}, json={}):
                pass
    meta = next(m for _, m in records(forensic_root) if m["status"] is None)
    assert meta["request_complete"] and not meta["response_complete"] and meta["capture_state"] == "failed"


@pytest.mark.parametrize("stream", [False, True])
async def test_retry_attempts_have_distinct_records(forensic_root, monkeypatch, stream):
    attempt = 0
    def handler(request):
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            return httpx.Response(500, stream=Chunks([b"failure body"]))
        body = b'data: [DONE]\n\n' if stream else b'{"choices":[{"message":{"content":"ok"}}]}'
        return httpx.Response(200, stream=Chunks([body]))
    mock_client(monkeypatch, handler)
    async def no_sleep(delay): pass
    kwargs = dict(max_attempts=2, timeout_seconds=None, sleep=no_sleep)
    if stream:
        events = [e async for e in stream_with_retry(model_client(), LLMRequest(), **kwargs)]
        assert events[-1].kind == "done"
    else:
        await complete_with_retry(model_client(), LLMRequest(), **kwargs)
    metadata = [m for _, m in records(forensic_root)]
    assert sorted(m["retry_index"] for m in metadata) == [0, 1]
    assert sorted(m["status"] for m in metadata) == [200, 500]
    assert all(m["capture_state"] == "complete" for m in metadata)


async def test_disabled_no_artifacts(tmp_path, monkeypatch):
    monkeypatch.delenv("LAMTOOLS_LLM_RAW_RECORDING", raising=False)
    monkeypatch.setenv("LAMTOOLS_LLM_FORENSIC_DIR", str(tmp_path))
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"ok"))) as client:
        async with recorded_request(client, "POST", "https://test.invalid", context={}, json={}) as response:
            assert response.content == b"ok"
    assert not list(tmp_path.iterdir())


async def test_storage_failure_is_visible_and_not_complete(forensic_root, monkeypatch):
    original = Capture.append
    def fail(self, side, chunk):
        if side == "response": raise OSError("disk full")
        return original(self, side, chunk)
    monkeypatch.setattr(Capture, "append", fail)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Chunks([b"body"])))) as client:
        with pytest.raises(OSError):
            async with recorded_request(client, "POST", "https://test.invalid", context={}, json={}): pass
    assert records(forensic_root)[0][1]["capture_state"] == "failed"


def test_cache_diagnostic_links_both_requests():
    from lamtools_core.llm import LLMUsage
    from lamtools_core.llm.cache_diagnostics import record_cache_observation
    request = LLMRequest()
    record_cache_observation("forensic-test", request, LLMUsage(prompt_tokens=100, cached_tokens=97, cache_usage_reported=True),
                             {"forensic_record_id": "before"})
    diagnostic = record_cache_observation("forensic-test", request, LLMUsage(prompt_tokens=100, cached_tokens=1, cache_usage_reported=True),
                                          {"forensic_record_id": "after"})
    assert diagnostic["forensic_record_id"] == "after"
    assert diagnostic["previous_forensic_record_id"] == "before"


async def test_multipart_bytes_and_integrity_audit(forensic_root):
    from lamtools_core.llm.forensics import inspect_record, runtime_context
    sent = []
    def handler(request):
        sent.append(request.content)
        return httpx.Response(200, stream=Chunks([b"response bytes"]))
    token = runtime_context.set({"session_id": "image-session", "run_id": "image-run", "step": 9})
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async with recorded_request(client, "POST", "https://test.invalid/images/edits", context={"model": "image"},
                                        files={"image": ("image.png", b"\x00\xff\r\n", "image/png")},
                                        data={"prompt": "exact prompt"}):
                pass
    finally:
        runtime_context.reset(token)
    path, meta = records(forensic_root)[0]
    assert (path.parent / "request.bin").read_bytes() == sent[0]
    assert meta["session_id"] == "image-session" and meta["step"] == 9
    assert inspect_record(path.parent)["verified_complete"]
    with (path.parent / "response.bin").open("ab") as file:
        file.write(b"corruption")
    assert not inspect_record(path.parent)["verified_complete"]
    path.write_text('{"capture_state":', encoding="utf-8")
    audit = inspect_record(path.parent)
    assert not audit["verified_complete"] and "missing_or_invalid_metadata" in audit["problems"]


async def test_native_finish_event_also_drains(forensic_root, monkeypatch):
    body = b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
    tail = b'\xff\x00tail without newline'
    mock_client(monkeypatch, lambda r: httpx.Response(200, stream=Chunks([body, tail])))
    events = [e async for e in model_client("openai-responses").stream(LLMRequest())]
    assert events[-1].kind == "finish"
    path, meta = records(forensic_root)[0]
    assert (path.parent / "response.bin").read_bytes() == body + tail
    assert meta["capture_state"] == "complete"
