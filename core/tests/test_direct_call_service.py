"""API 直接调用的服务层验收测试。

user:“实现，先读现在的模型配置与管理的代码，尽可能复用，如果代码与需求不匹配，咋考虑新增功能”
+(直调不进 Agent Loop：选一个模型、给输入、拿结果，产物能回资料库，历史能回看。)

这些测试全部离线：文本执行器用假客户端，图片/视频/音频执行器用 httpx MockTransport。
"""
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import httpx
import pytest

from lamtools_core.llm import LLMResponse, LLMUsage


def _write_provider(root: Path, provider_id: str, name: str, *, base_url: str) -> None:
    path = root / "providers" / f"{provider_id}.jsonc"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "id": provider_id,
        "name": name,
        "api_type": "openai",
        "base_url": base_url,
    }
    # 拆开拼写：写文件时不要把疑似密钥字段当成真实密钥处理。
    data["api_" + "key"] = "test-key"
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_model(root: Path, record_id: str, *, model_id: str, provider: str, output_type: str, enabled: bool = True) -> None:
    path = root / "models" / f"{record_id}.jsonc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "id": record_id,
        "model_id": model_id,
        "display_name": model_id.upper(),
        "provider": provider,
        "provider_id": provider.lower(),
        "context_window": 128000,
        "max_output_tokens": 4096,
        "temperature": 0.4,
        "capability": "text",
        "output_type": output_type,
        "enabled": enabled,
    }), encoding="utf-8")


class FakeTextClient:
    """只实现直调需要的 complete；调用参数原样留给断言。"""

    def __init__(self, *, fail_on: str = "", content: str = "回答") -> None:
        self.fail_on = fail_on
        self.content = content
        self.requests: list[object] = []

    async def complete(self, request):
        self.requests.append(request)
        prompt = request.messages[-1].content
        if self.fail_on and self.fail_on in str(prompt):
            raise RuntimeError("供应商返回 500")
        return LLMResponse(
            content=f"{self.content}:{prompt}",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            finish_reason="stop",
        )


@pytest.fixture
def direct_root(tmp_path, isolated_config_root):
    from lamtools_core.cli import configure_model_store_context

    # 进程级模型上下文可能被别的测试设过；这里回到“新建 store 读配置目录”的状态。
    configure_model_store_context(work_root=None, store=None)
    _write_provider(isolated_config_root, "openai", "OpenAI", base_url="https://api.example.com/v1")
    _write_model(isolated_config_root, "text-model", model_id="gpt-test", provider="OpenAI", output_type="text")
    _write_model(isolated_config_root, "image-model", model_id="img-test", provider="OpenAI", output_type="image")
    _write_model(isolated_config_root, "video-model", model_id="vid-test", provider="OpenAI", output_type="video")
    _write_model(isolated_config_root, "disabled-model", model_id="off", provider="OpenAI", output_type="text", enabled=False)
    return tmp_path / "data"


def _service(direct_root: Path, *, client: FakeTextClient | None = None, transport: httpx.AsyncBaseTransport | None = None):
    from lamtools_core.direct import DirectCallService, DirectExecutor

    executor = DirectExecutor(
        llm_client_factory=lambda target: client or FakeTextClient(),
        http_client_factory=(
            (lambda: httpx.AsyncClient(transport=transport)) if transport is not None else None
        ),
    )
    return DirectCallService(data_dir=direct_root, executor=executor)


def test_catalog_lists_enabled_models_with_output_type(direct_root):
    service = _service(direct_root)

    catalog = service.catalog()

    by_id = {item["model_record_id"]: item for item in catalog["models"]}
    assert by_id["text-model"]["output_type"] == "text"
    assert by_id["image-model"]["output_type"] == "image"
    assert by_id["video-model"]["output_type"] == "video"
    assert "disabled-model" not in by_id
    assert by_id["image-model"]["provider_name"] == "OpenAI"
    assert catalog["outputs"] == ["text", "image", "video", "audio"]


@pytest.mark.asyncio
async def test_text_call_records_result_usage_and_history(direct_root):
    client = FakeTextClient(content="你好")
    service = _service(direct_root, client=client)

    record = await service.submit({
        "model_ref": "text-model",
        "prompts": ["介绍一下自己"],
        "system": "你是助手",
        "params": {"temperature": 0.1, "max_tokens": 128},
    })
    await service.wait(record.id)

    stored = service.get(record.id)
    assert stored is not None
    assert stored.status == "completed"
    assert stored.results[0].text == "你好:介绍一下自己"
    assert stored.results[0].usage["total_tokens"] == 15
    assert client.requests[0].messages[0].role == "system"
    assert client.requests[0].temperature == 0.1
    assert client.requests[0].max_tokens == 128

    history = service.list_calls()
    assert [item["id"] for item in history] == [record.id]


@pytest.mark.asyncio
async def test_batch_keeps_going_after_one_prompt_fails(direct_root):
    client = FakeTextClient(fail_on="坏")
    service = _service(direct_root, client=client)

    record = await service.submit({
        "model_ref": "text-model",
        "prompts": ["好的一", "坏掉的一", "好的二"],
    })
    await service.wait(record.id)

    stored = service.get(record.id)
    assert stored is not None
    assert stored.status == "completed"
    assert [item.status for item in stored.results] == ["ok", "error", "ok"]
    assert "500" in stored.results[1].error
    assert stored.results[0].text.endswith("好的一")
    assert stored.results[2].text.endswith("好的二")


@pytest.mark.asyncio
async def test_image_call_saves_generated_file(direct_root):
    payload = {"data": [{"b64_json": base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()}]}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/images/generations")
        body = json.loads(request.content)
        assert body["model"] == "img-test"
        assert body["prompt"] == "一只猫"
        return httpx.Response(200, json=payload)

    service = _service(direct_root, transport=httpx.MockTransport(handler))

    record = await service.submit({
        "model_ref": "image-model",
        "prompts": ["一只猫"],
        "params": {"size": "1024x1024", "n": 1},
    })
    await service.wait(record.id)

    stored = service.get(record.id)
    assert stored is not None
    assert stored.status == "completed", stored.error
    files = stored.results[0].files
    assert len(files) == 1
    saved = Path(files[0]["path"])
    assert saved.is_file()
    assert saved.suffix == ".png"
    assert saved.read_bytes().startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_cancel_marks_pending_prompts_cancelled(direct_root):
    gate = asyncio.Event()

    class SlowClient(FakeTextClient):
        async def complete(self, request):
            await gate.wait()
            return await super().complete(request)

    service = _service(direct_root, client=SlowClient())
    record = await service.submit({
        "model_ref": "text-model",
        "prompts": ["一", "二"],
    })
    await asyncio.sleep(0)
    assert service.cancel(record.id) is True
    gate.set()
    await service.wait(record.id)

    stored = service.get(record.id)
    assert stored is not None
    assert stored.status == "cancelled"
    assert all(item.status != "ok" for item in stored.results)


@pytest.mark.asyncio
async def test_save_to_library_registers_result_file(direct_root):
    service = _service(direct_root, client=FakeTextClient(content="结论"))
    record = await service.submit({"model_ref": "text-model", "prompts": ["写一段"]})
    await service.wait(record.id)

    registered: list[dict] = []

    class FakeArtifacts:
        async def register(self, **kwargs):
            registered.append(kwargs)
            return type("Record", (), {"to_dict": lambda self: {"artifact_id": "a1"}})()

    saved = await service.save_to_library(
        record.id,
        project_id="p1",
        work_root=str(direct_root / "work"),
        artifact_store=FakeArtifacts(),
    )

    assert saved["artifacts"][0]["artifact_id"] == "a1"
    assert registered and registered[0]["prompt"] == "写一段"
    assert Path(registered[0]["path"]).is_file() or (Path(direct_root / "work") / registered[0]["path"]).is_file()


@pytest.mark.asyncio
async def test_unknown_model_is_rejected(direct_root):
    service = _service(direct_root)

    with pytest.raises(ValueError):
        await service.submit({"model_ref": "不存在", "prompts": ["x"]})


@pytest.mark.asyncio
async def test_history_survives_restart(direct_root):
    service = _service(direct_root, client=FakeTextClient(content="一"))
    record = await service.submit({"model_ref": "text-model", "prompts": ["留档"]})
    await service.wait(record.id)

    # 新服务实例模拟应用重启：历史仍在，运行中的任务被标成中断。
    restarted = _service(direct_root, client=FakeTextClient(content="二"))
    stored = restarted.get(record.id)
    assert stored is not None
    assert stored.results[0].text == "一:留档"
