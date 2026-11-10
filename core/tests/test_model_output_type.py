"""模型定义的输出类型：jsonc 读写、RPC 暴露与保存。

user:“实现，先读现在的模型配置与管理的代码，尽可能复用，如果代码与需求不匹配，咋考虑新增功能”
+(直调台要按模型能产出什么切换界面，所以模型定义里必须有一个可读可写的输出类型，
不能只靠模型 ID 猜。)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.config.model_store import ModelConfig, ModelStore


def _write_model(dir_path: Path, record_id: str, **overrides) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / f"{record_id}.jsonc"
    data = {
        "model_id": record_id,
        "display_name": record_id.upper(),
        "provider": "Test Provider",
        "context_window": 128000,
        "max_output_tokens": 32768,
        "temperature": 0.7,
        "capability": "text",
    }
    data.update(overrides)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_model_without_output_type_reads_as_text(isolated_config_root):
    """旧文件没有 output_type 时按文本处理，不能因为缺字段而拒绝加载。"""
    _write_model(isolated_config_root / "models", "legacy-model")

    model = ModelStore().get_sync("legacy-model", work_root=None)

    assert model is not None
    assert model.output_type == "text"


def test_model_output_type_parses_supported_values(isolated_config_root):
    models_dir = isolated_config_root / "models"
    _write_model(models_dir, "img-model", output_type="image")
    _write_model(models_dir, "video-model", output_type="video")
    _write_model(models_dir, "audio-model", output_type="audio")
    _write_model(models_dir, "bogus-model", output_type="spreadsheet")

    store = ModelStore()

    assert store.get_sync("img-model", work_root=None).output_type == "image"
    assert store.get_sync("video-model", work_root=None).output_type == "video"
    assert store.get_sync("audio-model", work_root=None).output_type == "audio"
    # 不认识的类型按文本处理，避免把不可执行的类型带进调用台。
    assert store.get_sync("bogus-model", work_root=None).output_type == "text"


def test_model_store_write_roundtrips_output_type(isolated_config_root):
    store = ModelStore()
    model = ModelConfig(
        id="dall-e-record",
        model_id="gpt-image-1",
        display_name="Image Model",
        provider="OpenAI",
        provider_id="openai",
        output_type="image",
    )

    path = store.write(model, scope="global", work_root=None)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["output_type"] == "image"
    loaded = ModelStore().get_sync("dall-e-record", work_root=None)
    assert loaded is not None
    assert loaded.output_type == "image"


@pytest.mark.asyncio
async def test_config_model_rpc_roundtrips_output_type(tmp_path, isolated_config_root):
    """UI 用的 config.model.create/update 必须能保存并读回输出类型。"""
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.cli import configure_model_store_context
    from lamtools_core.config.operations import build_config_operation_catalog

    work = tmp_path / "work"
    providers_dir = isolated_config_root / "providers"
    providers_dir.mkdir(parents=True, exist_ok=True)
    (providers_dir / "openai.jsonc").write_text(
        json.dumps({
            "id": "openai",
            "name": "OpenAI",
            "api_type": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
        }),
        encoding="utf-8",
    )
    configure_model_store_context(work_root=str(work), store=None)
    catalog: OperationCatalog = build_config_operation_catalog(work_root=work)

    created = await catalog.execute("config.model.create", {
        "scope": "global",
        "model_id": "tts-1",
        "display_name": "TTS One",
        "provider": "OpenAI",
        "provider_id": "openai",
        "output_type": "audio",
    })
    assert created.status == "ok"

    listed = await catalog.execute("config.models.list", {})
    entry = next(
        item for item in listed.payload["models"]
        if item["model_id"] == "tts-1"
    )
    assert entry["output_type"] == "audio"


@pytest.mark.asyncio
async def test_legacy_models_upsert_keeps_output_type(tmp_path, isolated_config_root):
    """旧写入路径（config.models.upsert）同样不能丢掉输出类型。"""
    from lamtools_core.app.http_agent_app import _register_model_operations
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.cli import configure_model_store_context

    work = tmp_path / "work"
    configure_model_store_context(work_root=str(work), store=None)
    catalog = OperationCatalog()
    _register_model_operations(catalog, work_root=work)

    created = await catalog.execute("config.models.upsert", {
        "scope": "global",
        "model_id": "sora-2",
        "display_name": "Sora Two",
        "provider": "OpenAI",
        "provider_id": "openai",
        "output_type": "video",
    })
    assert created.status == "ok"

    model = ModelStore().get_sync(created.payload["model_record_id"], work_root=None)
    assert model is not None
    assert model.output_type == "video"
