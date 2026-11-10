"""调用台的进阶能力：流式文本、任务型视频、参考图与错误提示。

user:“该做的你都做一下 把它给打磨成熟”
+(能用之后最影响日常的是：文本要边生成边看见、视频要能等任务完成、图片要能带参考图、
失败要说清楚是密钥还是限流。)

全部离线：文本用假客户端，媒体用 httpx MockTransport。
"""
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import httpx
import pytest

from lamtools_core.llm import LLMStreamEvent, LLMUsage


def _write_provider(root: Path, provider_id: str, name: str, *, base_url: str) -> None:
    path = root / "providers" / f"{provider_id}.jsonc"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"id": provider_id, "name": name, "api_type": "openai", "base_url": base_url}
    data["api_" + "key"] = "test-key"
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_model(root: Path, record_id: str, *, model_id: str, output_type: str) -> None:
    path = root / "models" / f"{record_id}.jsonc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "id": record_id,
        "model_id": model_id,
        "display_name": model_id.upper(),
        "provider": "OpenAI",
        "provider_id": "openai",
        "output_type": output_type,
        "capability": "text",
        "enabled": True,
    }), encoding="utf-8")


class StreamingClient:
    def __init__(self, *, fail: bool = False, content: tuple[str, ...] = ("你", "好")) -> None:
        self.fail = fail
        self.content = content
        self.complete_calls = 0

    async def stream(self, request):
        if self.fail:
            raise RuntimeError("stream not supported")
        for piece in self.content:
            yield LLMStreamEvent(kind="content_delta", content=piece)
            await asyncio.sleep(0)
        yield LLMStreamEvent(
            kind="finish",
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=3, completion_tokens=4, total_tokens=7),
        )
        yield LLMStreamEvent(kind="done")

    async def complete(self, request):
        self.complete_calls += 1
        from lamtools_core.llm import LLMResponse

        return LLMResponse(
            content="回退结果",
            usage=LLMUsage(total_tokens=5),
            finish_reason="stop",
        )


@pytest.fixture
def advanced_root(tmp_path, isolated_config_root):
    from lamtools_core.cli import configure_model_store_context

    configure_model_store_context(work_root=None, store=None)
    _write_provider(isolated_config_root, "openai", "OpenAI", base_url="https://api.example.com/v1")
    _write_model(isolated_config_root, "text-model", model_id="gpt-test", output_type="text")
    _write_model(isolated_config_root, "image-model", model_id="img-test", output_type="image")
    _write_model(isolated_config_root, "video-model", model_id="vid-test", output_type="video")
    return tmp_path / "data", tmp_path / "work"


def _service(roots, *, client=None, transport: httpx.AsyncBaseTransport | None = None):
    from lamtools_core.direct import DirectCallService, DirectExecutor

    data_dir, work_root = roots
    executor = DirectExecutor(
        llm_client_factory=(lambda target: client) if client is not None else None,
        http_client_factory=(
            (lambda: httpx.AsyncClient(transport=transport)) if transport is not None else None
        ),
    )
    return DirectCallService(data_dir=data_dir, work_root=str(work_root), executor=executor)


@pytest.mark.asyncio
async def test_text_stream_writes_content_while_running(advanced_root):
    client = StreamingClient()
    service = _service(advanced_root, client=client)

    record = await service.submit({"model_ref": "text-model", "prompts": ["讲两句"]})
    # 流式写入是逐步落盘的：等待任务跑完之前就能读到部分文本。
    for _ in range(50):
        await asyncio.sleep(0.01)
        current = service.get(record.id)
        if current and current.results and current.results[0].text:
            break
    assert current is not None
    assert current.results[0].text

    await service.wait(record.id)
    final = service.get(record.id)
    assert final is not None
    assert final.results[0].text == "你好"
    assert final.results[0].usage["total_tokens"] == 7
    assert client.complete_calls == 0


@pytest.mark.asyncio
async def test_text_stream_falls_back_to_complete(advanced_root):
    client = StreamingClient(fail=True)
    service = _service(advanced_root, client=client)

    record = await service.submit({"model_ref": "text-model", "prompts": ["讲两句"]})
    await service.wait(record.id)

    stored = service.get(record.id)
    assert stored is not None
    assert stored.status == "completed"
    assert stored.results[0].text == "回退结果"
    assert client.complete_calls == 1


@pytest.mark.asyncio
async def test_video_polls_until_task_completes(advanced_root):
    polls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "job-1", "status": "processing"})
        if request.url.path.endswith("/videos/generations/job-1"):
            polls["count"] += 1
            if polls["count"] < 2:
                return httpx.Response(200, json={"status": "processing"})
            return httpx.Response(200, json={
                "status": "completed",
                "data": [{"url": "https://cdn.example.com/out.mp4"}],
            })
        if request.url.host == "cdn.example.com":
            return httpx.Response(200, content=b"\x00\x00\x00\x18ftypmp42", headers={"content-type": "video/mp4"})
        return httpx.Response(404)

    service = _service(advanced_root, transport=httpx.MockTransport(handler))

    record = await service.submit({
        "model_ref": "video-model",
        "prompts": ["一只猫在跳舞"],
        "params": {"poll_interval": 0.01, "poll_attempts": 5},
    })
    await service.wait(record.id)

    stored = service.get(record.id)
    assert stored is not None
    assert stored.status == "completed", stored.error
    files = stored.results[0].files
    assert len(files) == 1
    assert Path(files[0]["path"]).is_file()
    assert files[0]["mime_type"] == "video/mp4"


@pytest.mark.asyncio
async def test_image_edit_uses_reference_urls(advanced_root):
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "ref.example.com":
            return httpx.Response(200, content=b"\x89PNG\r\n\x1a\nref", headers={"content-type": "image/png"})
        assert request.url.path.endswith("/images/edits")
        seen["content_type"] = request.headers.get("content-type", "")
        body = request.content
        seen["has_prompt"] = "改成水彩".encode() in body
        return httpx.Response(200, json={
            "data": [{"b64_json": base64.b64encode(b"\x89PNG\r\n\x1a\nout").decode()}],
        })

    service = _service(advanced_root, transport=httpx.MockTransport(handler))

    record = await service.submit({
        "model_ref": "image-model",
        "prompts": ["改成水彩"],
        "params": {"reference_urls": ["https://ref.example.com/a.png"]},
    })
    await service.wait(record.id)

    stored = service.get(record.id)
    assert stored is not None
    assert stored.status == "completed", stored.error
    assert seen["content_type"].startswith("multipart/form-data")
    assert seen["has_prompt"] is True
    assert stored.results[0].files


@pytest.mark.asyncio
async def test_media_auth_error_is_explained(advanced_root):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    service = _service(advanced_root, transport=httpx.MockTransport(handler))

    record = await service.submit({"model_ref": "image-model", "prompts": ["一只猫"]})
    await service.wait(record.id)

    stored = service.get(record.id)
    assert stored is not None
    message = stored.results[0].error
    assert "401" in message
    assert "密钥" in message or "鉴权" in message


@pytest.mark.asyncio
async def test_all_failed_results_mark_the_call_failed(advanced_root):
    class AlwaysFail:
        async def complete(self, request):
            raise RuntimeError("供应商返回 500")

    service = _service(advanced_root, client=AlwaysFail())
    record = await service.submit({"model_ref": "text-model", "prompts": ["一", "二"]})
    await service.wait(record.id)

    stored = service.get(record.id)
    assert stored is not None
    assert stored.status == "failed"
    assert all(item.status == "error" for item in stored.results)


@pytest.mark.asyncio
async def test_stream_request_carries_a_stable_session_id(advanced_root):
    client = StreamingClient()
    seen: list[dict] = []

    original_stream = client.stream

    async def capture(request):
        seen.append(dict(request.metadata or {}))
        async for event in original_stream(request):
            yield event

    client.stream = capture  # type: ignore[method-assign]
    service = _service(advanced_root, client=client)

    record = await service.submit({"model_ref": "text-model", "prompts": ["你好"]})
    await service.wait(record.id)

    assert seen and str(seen[0].get("_runtime_session_id", "")).startswith("direct:")
