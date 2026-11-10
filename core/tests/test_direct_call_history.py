"""历史分页、单条重跑、生图配置导入与费用估算。

user:“该做的你都做一下 把它给打磨成熟”
+(历史要能翻页、失败的一条要能单独重跑、生图工具已经配好的模型要能一键带进调用台、
配了价格就要能看见这一次花了多少。)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.llm import LLMResponse, LLMUsage


def _write_provider(root: Path, provider_id: str, name: str, *, base_url: str) -> None:
    path = root / "providers" / f"{provider_id}.jsonc"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"id": provider_id, "name": name, "api_type": "openai", "base_url": base_url}
    data["api_" + "key"] = "test-key"
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_model(root: Path, record_id: str, *, model_id: str, output_type: str, pricing: dict | None = None) -> None:
    path = root / "models" / f"{record_id}.jsonc"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "id": record_id,
        "model_id": model_id,
        "display_name": model_id.upper(),
        "provider": "OpenAI",
        "provider_id": "openai",
        "output_type": output_type,
        "capability": "text",
        "enabled": True,
    }
    if pricing:
        data["pricing"] = pricing
    path.write_text(json.dumps(data), encoding="utf-8")


class FakeClient:
    async def complete(self, request):
        return LLMResponse(
            content="回答",
            usage=LLMUsage(prompt_tokens=1_000_000, completion_tokens=500_000, total_tokens=1_500_000),
            finish_reason="stop",
        )


@pytest.fixture
def extras_root(tmp_path, isolated_config_root):
    from lamtools_core.cli import configure_model_store_context

    configure_model_store_context(work_root=None, store=None)
    _write_provider(isolated_config_root, "openai", "OpenAI", base_url="https://api.example.com/v1")
    _write_model(
        isolated_config_root, "priced-model", model_id="priced-test", output_type="text",
        pricing={"input_per_1m": 2.0, "output_per_1m": 4.0, "currency": "USD"},
    )
    return tmp_path / "data", tmp_path / "work"


def _service(roots):
    from lamtools_core.direct import DirectCallService, DirectExecutor

    data_dir, work_root = roots
    return DirectCallService(
        data_dir=data_dir,
        work_root=str(work_root),
        executor=DirectExecutor(llm_client_factory=lambda target: FakeClient()),
    )


@pytest.mark.asyncio
async def test_history_paginates(extras_root):
    service = _service(extras_root)
    ids = []
    for index in range(3):
        record = await service.submit({"model_ref": "priced-model", "prompts": [f"第{index}条"]})
        await service.wait(record.id)
        ids.append(record.id)

    first = service.list_calls(limit=2, offset=0)
    second = service.list_calls(limit=2, offset=2)

    assert len(first) == 2
    assert len(second) == 1
    assert {item["id"] for item in first} | {item["id"] for item in second} == set(ids)


@pytest.mark.asyncio
async def test_retry_reruns_only_one_prompt(extras_root):
    service = _service(extras_root)
    record = await service.submit({"model_ref": "priced-model", "prompts": ["一", "二"]})
    await service.wait(record.id)

    retried = await service.retry(record.id, 1)
    await service.wait(retried.id)

    stored = service.get(retried.id)
    assert stored is not None
    assert stored.prompts == ["二"]
    assert stored.status == "completed"
    assert stored.id != record.id


@pytest.mark.asyncio
async def test_cost_is_estimated_from_model_pricing(extras_root):
    service = _service(extras_root)
    record = await service.submit({"model_ref": "priced-model", "prompts": ["算钱"]})
    await service.wait(record.id)

    stored = service.get(record.id)
    assert stored is not None
    # 输入 1M × 2 + 输出 0.5M × 4 = 2 + 2 = 4
    assert stored.results[0].cost == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_import_imagegen_creates_image_model(extras_root, isolated_config_root):
    data_dir, _work_root = extras_root
    plugin_dir = data_dir / "plugins"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "imagegen.jsonc").write_text(json.dumps({
        "enabled": True,
        "api_url": "https://img.example.com/v1",
        "model": "gpt-image-1",
    }), encoding="utf-8")

    service = _service(extras_root)
    result = service.import_imagegen()

    assert result["created"] is True
    catalog = service.catalog()
    entry = next(item for item in catalog["models"] if item["model_id"] == "gpt-image-1")
    assert entry["output_type"] == "image"

    # 再导入一次是幂等的，不重复建模型。
    again = service.import_imagegen()
    assert again["created"] is False
    assert again["model_record_id"] == result["model_record_id"]


@pytest.mark.asyncio
async def test_import_imagegen_without_config_is_explained(extras_root):
    service = _service(extras_root)

    with pytest.raises(ValueError) as excinfo:
        service.import_imagegen()

    assert "生图" in str(excinfo.value)
