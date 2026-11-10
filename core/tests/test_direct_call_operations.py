"""直调 RPC 契约：前端只认这些方法名与返回形状。

user:“实现，先读现在的模型配置与管理的代码，尽可能复用，如果代码与需求不匹配，咋考虑新增功能”
+(界面换一层皮不应该影响后端能力，所以 RPC 边界要单独锁住。)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.llm import LLMResponse, LLMUsage


def _write_config(root: Path) -> None:
    providers = root / "providers"
    providers.mkdir(parents=True, exist_ok=True)
    provider = {"id": "openai", "name": "OpenAI", "api_type": "openai", "base_url": "https://api.example.com/v1"}
    provider["api_" + "key"] = "test-key"
    (providers / "openai.jsonc").write_text(json.dumps(provider), encoding="utf-8")
    models = root / "models"
    models.mkdir(parents=True, exist_ok=True)
    (models / "text-model.jsonc").write_text(json.dumps({
        "id": "text-model",
        "model_id": "gpt-test",
        "display_name": "GPT Test",
        "provider": "OpenAI",
        "provider_id": "openai",
        "output_type": "text",
        "capability": "text",
        "enabled": True,
    }), encoding="utf-8")


class FakeClient:
    async def complete(self, request):
        return LLMResponse(content="ok", usage=LLMUsage(total_tokens=3), finish_reason="stop")


class FakeProject:
    id = "p1"
    work_root = "/tmp/direct-project"


class FakeProjectStore:
    async def get(self, project_id: str):
        return FakeProject() if project_id == "p1" else None


class FakeArtifacts:
    async def register(self, **kwargs):
        return type("Record", (), {"to_dict": lambda self: {"artifact_id": "a1", "path": kwargs.get("path")}})()


@pytest.fixture
def catalog(tmp_path, isolated_config_root):
    from lamtools_core.cli import configure_model_store_context
    from lamtools_core.direct import DirectCallService, DirectExecutor, build_direct_operation_catalog

    configure_model_store_context(work_root=None, store=None)
    _write_config(isolated_config_root)
    service = DirectCallService(
        data_dir=tmp_path / "data",
        executor=DirectExecutor(llm_client_factory=lambda target: FakeClient()),
    )
    return build_direct_operation_catalog(
        service,
        project_store=FakeProjectStore(),
        artifact_store=FakeArtifacts(),
    )


@pytest.mark.asyncio
async def test_direct_catalog_and_run_roundtrip(catalog: OperationCatalog):
    listed = await catalog.execute("direct.catalog", {})
    assert listed.status == "ok"
    assert [item["model_record_id"] for item in listed.payload["models"]] == ["text-model"]

    started = await catalog.execute("direct.run", {
        "model_ref": "text-model",
        "prompts": ["你好"],
        "project_id": "p1",
    })
    assert started.status == "ok"
    call_id = started.payload["call"]["id"]

    fetched = await catalog.execute("direct.get", {"call_id": call_id})
    assert fetched.status == "ok"
    assert fetched.payload["call"]["model_id"] == "gpt-test"

    history = await catalog.execute("direct.list", {})
    assert history.payload["total"] == 1


@pytest.mark.asyncio
async def test_direct_run_rejects_unknown_project(catalog: OperationCatalog):
    result = await catalog.execute("direct.run", {
        "model_ref": "text-model",
        "prompts": ["x"],
        "project_id": "missing",
    })
    assert result.status == "error"
    assert "项目不存在" in result.payload["error"]


@pytest.mark.asyncio
async def test_direct_run_rejects_empty_prompts(catalog: OperationCatalog):
    result = await catalog.execute("direct.run", {"model_ref": "text-model", "prompts": []})
    assert result.status == "error"
    assert "至少" in result.payload["error"]


@pytest.mark.asyncio
async def test_direct_save_requires_project(catalog: OperationCatalog):
    result = await catalog.execute("direct.save", {"call_id": "whatever"})
    assert result.status == "error"
    assert "项目" in result.payload["error"]


@pytest.mark.asyncio
async def test_direct_cancel_unknown_call_is_error(catalog: OperationCatalog):
    result = await catalog.execute("direct.cancel", {"call_id": "nope"})
    assert result.status == "error"


@pytest.mark.asyncio
async def test_direct_delete_removes_history(catalog: OperationCatalog):
    started = await catalog.execute("direct.run", {"model_ref": "text-model", "prompts": ["删除我"]})
    call_id = started.payload["call"]["id"]

    deleted = await catalog.execute("direct.delete", {"call_id": call_id})
    assert deleted.status == "ok"
    fetched = await catalog.execute("direct.get", {"call_id": call_id})
    assert fetched.status == "error"
