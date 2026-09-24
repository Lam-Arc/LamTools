from __future__ import annotations

import json

import pytest

from lamtools_core.config.model_group_store import (
    ModelGroupRevisionConflict,
    ModelGroupStore,
)
from lamtools_core.config.model_store import ModelConfig, ModelStore
from lamtools_core.config.operations import build_config_operation_catalog
from lamtools_core.config.provider_store import ProviderConfig, ProviderStore


def test_group_store_crud_members_order_and_revision(isolated_config_root):
    store = ModelGroupStore()
    created = store.create("Coding", model_ids=["model-a", "model-b"])
    group_id = created["group_id"]
    assert created["revision"] == 1
    assert created["groups"][0]["model_ids"] == ["model-a", "model-b"]

    changed = store.set_members(group_id, ["model-b", "model-a"], expected_revision=1)
    assert changed["revision"] == 2
    assert changed["groups"][0]["model_ids"] == ["model-b", "model-a"]
    with pytest.raises(ModelGroupRevisionConflict):
        store.update(group_id, name="Stale", expected_revision=1)

    renamed = store.update(group_id, name="Agents", expected_revision=2)
    assert renamed["groups"][0]["name"] == "Agents"
    deleted = store.delete(group_id, expected_revision=3)
    assert deleted["groups"] == []
    assert deleted["memberships"] == []


def test_group_snapshot_separates_dangling_members(isolated_config_root):
    store = ModelGroupStore()
    created = store.create("Mixed", model_ids=["present", "missing"])
    snapshot = store.snapshot(available_model_ids=["present"])
    group = snapshot["groups"][0]
    assert group["model_ids"] == ["present"]
    assert group["dangling_model_ids"] == ["missing"]
    assert created["group_id"] == group["id"]


@pytest.mark.asyncio
async def test_group_rpc_and_create_with_provider_keep_external_model_id(isolated_config_root):
    catalog = build_config_operation_catalog()
    created_group = await catalog.execute("config.model_group.create", {"name": "Frontier"})
    assert created_group.status == "ok"
    group_id = created_group.payload["group_id"]

    created = await catalog.execute(
        "config.model.create_with_provider",
        {
            "group_id": group_id,
            "expected_revision": created_group.payload["revision"],
            "model": {
                "model_id": "Qwen/Qwen3.8-Max",
                "display_name": "Qwen 3.8 Max",
                "context_window": 262144,
                "max_output_tokens": 32768,
                "thinking_supported": True,
                "adapter_profile_id": "openai-chat",
            },
            "provider": {
                "mode": "new",
                "name": "Command Code",
                "base_url": "https://api.commandcode.ai/provider/v1/",
                "api_type": "openai",
                "api_key": "secret",
                "request_body": {"custom": True},
            },
        },
    )
    assert created.status == "ok", created.payload
    model_payload = created.payload["model"]
    assert model_payload["id"] != model_payload["model_id"]
    assert model_payload["model_id"] == "Qwen/Qwen3.8-Max"
    assert "/" not in model_payload["id"]
    assert created.payload["provider"]["api_key"] == "********"

    loaded = ModelStore().get_sync(model_payload["id"])
    assert loaded is not None
    assert loaded.model_id == "Qwen/Qwen3.8-Max"
    assert loaded.id == model_payload["id"]
    group_list = await catalog.execute("config.model_groups.list", {})
    assert group_list.payload["groups"][0]["model_ids"] == [model_payload["id"]]


@pytest.mark.asyncio
async def test_create_with_provider_rejects_full_completion_url(isolated_config_root):
    catalog = build_config_operation_catalog()
    group = await catalog.execute("config.model_group.create", {"name": "Strict URL"})
    result = await catalog.execute(
        "config.model.create_with_provider",
        {
            "group_id": group.payload["group_id"],
            "model": {"model_id": "m"},
            "provider": {
                "mode": "new",
                "name": "Bad URL",
                "base_url": "https://example.test/v1/chat/completions",
            },
        },
    )
    assert result.status == "error"
    assert "API base URL" in result.payload["error"]


@pytest.mark.asyncio
async def test_create_with_provider_revision_conflict_leaves_no_files(isolated_config_root):
    catalog = build_config_operation_catalog()
    group = await catalog.execute("config.model_group.create", {"name": "Concurrent"})
    await catalog.execute("config.model_group.update", {
        "group_id": group.payload["group_id"],
        "name": "Concurrent updated",
        "expected_revision": group.payload["revision"],
    })

    result = await catalog.execute("config.model.create_with_provider", {
        "group_id": group.payload["group_id"],
        "expected_revision": group.payload["revision"],
        "model": {"model_id": "Org/Conflict"},
        "provider": {
            "mode": "new",
            "id": "conflict-provider",
            "name": "Conflict Provider",
            "base_url": "https://conflict.example/v1",
        },
    })

    assert result.status == "error"
    assert "revision conflict" in result.payload["error"]
    assert ProviderStore().get_sync("conflict-provider") is None
    assert ModelStore().get_sync("conflict-provider-org-conflict") is None


@pytest.mark.asyncio
async def test_provider_create_returns_nested_model_record_ids(isolated_config_root):
    result = await build_config_operation_catalog().execute(
        "config.provider.create",
        {
            "preset_id": "gateway",
            "name": "Gateway",
            "base_url": "https://gateway.example/v1",
            "api_key": "secret",
            "models": [{"model_id": "Org/Model", "display_name": "Model"}],
        },
    )

    assert result.status == "ok"
    assert result.payload["provider"]["id"] == "gateway"
    assert len(result.payload["models"]) == 1
    assert result.payload["models"][0]["model_id"] == "Org/Model"
    assert result.payload["models"][0]["id"] == "gateway-org-model"


@pytest.mark.asyncio
async def test_model_and_provider_delete_clean_group_memberships(isolated_config_root):
    providers = ProviderStore()
    provider = ProviderConfig(id="p", name="P", base_url="https://example.test/v1", api_key="k")
    providers.write(provider, scope="global", work_root=None)
    models = ModelStore()
    first = ModelConfig(id="p-a", model_id="a", provider="P", provider_id="p")
    second = ModelConfig(id="p-b", model_id="b", provider="P", provider_id="p")
    models.write(first, scope="global", work_root=None)
    models.write(second, scope="global", work_root=None)
    groups = ModelGroupStore()
    created = groups.create("Delete", model_ids=[first.id, second.id])
    catalog = build_config_operation_catalog()

    deleted_model = await catalog.execute("config.model.delete", {"model_record_id": first.id})
    assert deleted_model.status == "ok"
    assert groups.snapshot()["groups"][0]["model_ids"] == [second.id]

    deleted_provider = await catalog.execute("config.provider.delete", {"provider_id": provider.id})
    assert deleted_provider.status == "ok"
    assert groups.snapshot()["groups"][0]["model_ids"] == []
    assert created["group_id"] == groups.snapshot()["groups"][0]["id"]


@pytest.mark.asyncio
async def test_model_update_preserves_canonical_customization_from_ui_extra(isolated_config_root):
    provider = ProviderConfig(id="p", name="P", base_url="https://example.test/v1", api_key="k")
    ProviderStore().write(provider, scope="global", work_root=None)
    model = ModelConfig(id="p-m", model_id="m", provider="P", provider_id="p")
    ModelStore().write(model, scope="global", work_root=None)

    result = await build_config_operation_catalog().execute("config.model.update", {
        "model_record_id": model.id,
        "provider_id": provider.id,
        "model_id": model.model_id,
        "extra": {
            "adapter_profile_id": "qwen",
            "request_body": {"enable_thinking": True},
            "adapter_profile_override": {"request": {"unsupported_fields": ["temperature"]}},
            "reasoning": {"off_supported": False},
        },
    })

    assert result.status == "ok", result.payload
    loaded = ModelStore().get_sync(model.id)
    assert loaded is not None
    assert loaded.adapter_profile_id == "qwen"
    assert loaded.request_body == {"enable_thinking": True}
    assert loaded.adapter_profile_override == {"request": {"unsupported_fields": ["temperature"]}}
    assert loaded.reasoning == {"off_supported": False}
