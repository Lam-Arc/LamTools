from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.config.model_store import ModelConfig, ModelStore


def _write_model(dir_path: Path, model_id: str, **overrides) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / f"{model_id}.jsonc"
    data = {
        "model_id": model_id,
        "display_name": model_id.upper(),
        "provider": "Test Provider",
        "context_window": 128000,
        "max_output_tokens": 32768,
        "temperature": 0.7,
        "thinking": {"supported": True, "budget": 10000},
        "adapter_profile_id": "openai-chat",
        "capability": "text",
        "is_default": False,
    }
    data.update(overrides)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_model_store_returns_empty_when_no_files(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    store = ModelStore()
    assert store.list_sync(work_root=str(tmp_path / "work")) == []
    assert store.default_model_id_sync(work_root=str(tmp_path / "work")) == ""
    assert store.get_sync("anything", work_root=str(tmp_path / "work")) is None


def test_model_store_loads_global_models(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    global_dir = home / ".lam" / "config" / "models"
    _write_model(global_dir, "model-a", is_default=True)
    _write_model(global_dir, "model-b")

    store = ModelStore()
    models = store.list_sync(work_root=None)

    assert {m.model_id for m in models} == {"model-a", "model-b"}
    assert store.default_model_id_sync(work_root=None) == "model-a"
    assert store.get_sync("model-a", work_root=None).display_name == "MODEL-A"


def test_model_store_project_overrides_global(tmp_path, monkeypatch):
    home = tmp_path / "home"
    work = tmp_path / "work"
    monkeypatch.setattr(Path, "home", lambda: home)
    global_dir = home / ".lam" / "config" / "models"
    project_dir = work / ".lam" / "config" / "models"
    _write_model(global_dir, "shared", display_name="GLOBAL VERSION", capability="text")
    # Project overrides with a different display name + multimodal capability.
    _write_model(project_dir, "shared", display_name="PROJECT VERSION", capability="multimodal")

    store = ModelStore()
    model = store.get_sync("shared", work_root=str(work))

    assert model is not None
    assert model.display_name == "PROJECT VERSION"
    assert model.resolved_capability == "multimodal"


def test_model_store_caches_by_mtime(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    global_dir = home / ".lam" / "config" / "models"
    path = _write_model(global_dir, "cached")

    store = ModelStore()
    first = store.list_sync(work_root=None)
    assert len(first) == 1
    # Second call hits the mtime cache (same signature).
    second = store.list_sync(work_root=None)
    assert store._cached_models is not None
    assert len(second) == 1

    # Touching the file invalidates the cache.
    import time

    time.sleep(0.01)
    path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    third = store.list_sync(work_root=None)
    assert len(third) == 1


def test_model_store_parses_jsonc_with_comments(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    global_dir = home / ".lam" / "config" / "models"
    global_dir.mkdir(parents=True, exist_ok=True)
    (global_dir / "commented.jsonc").write_text(
        """{
          // a comment
          "model_id": "commented",
          "display_name": "Commented Model", /* block comment */
          "provider": "P",
          "context_window": 64000,
          "max_output_tokens": 8192,
          "temperature": 0.3,
          "thinking": {"supported": false, "budget": 0},
          "capability": "text",
        }
        """,
        encoding="utf-8",
    )

    store = ModelStore()
    model = store.get_sync("commented", work_root=None)

    assert model is not None
    assert model.context_window == 64000
    assert model.thinking_supported is False
    assert model.display_name == "Commented Model"


def test_model_store_get_matches_by_display_name_and_substring(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    global_dir = home / ".lam" / "config" / "models"
    _write_model(global_dir, "xopglm52", display_name="GLM-5.2")

    store = ModelStore()
    assert store.get_sync("GLM-5.2", work_root=None) is not None
    assert store.get_sync("glm", work_root=None).model_id == "xopglm52"


def test_model_store_to_extra_surfaces_adapter_profile_and_capability():
    model = ModelConfig(
        model_id="m", adapter_profile_id="xfyun-coding-plan",
        request_body={"enable_thinking": True}, capability="multimodal",
    )
    extra = model.to_extra()
    assert extra["adapter_profile_id"] == "xfyun-coding-plan"
    assert extra["adapter_profile_override"]["request"]["body"] == {"enable_thinking": True}
    assert extra["capability"] == "multimodal"


def test_model_store_write_roundtrips(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    store = ModelStore()
    model = ModelConfig(
        model_id="written", display_name="Written", provider="P",
        context_window=128000, max_output_tokens=32768, temperature=0.7,
        thinking_supported=True, thinking_budget=10000,
        adapter_profile_id="openai-chat", capability="text", is_default=True,
    )

    path = store.write(model, scope="global", work_root=None)

    assert path.exists()
    # Re-read via a fresh store.
    store2 = ModelStore()
    loaded = store2.get_sync("written", work_root=None)
    assert loaded is not None
    assert loaded.display_name == "Written"
    assert loaded.is_default is True
    assert loaded.thinking_supported is True


# --- RPC operations (config.models.upsert/delete) -------------------------


def _model_catalog(work_root: Path | None) -> "OperationCatalog":  # type: ignore[name-defined]
    from lamtools_core.app.http_agent_app import _register_model_operations
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.cli import configure_model_store_context

    configure_model_store_context(work_root=str(work_root) if work_root else None, store=None)
    catalog = OperationCatalog()
    _register_model_operations(catalog, work_root=work_root)
    return catalog


@pytest.mark.asyncio
async def test_rpc_models_upsert_then_list_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    work = tmp_path / "work"
    catalog = _model_catalog(work)

    upsert = await catalog.execute("config.models.upsert", {
        "scope": "project",
        "work_root": str(work),
        "model_id": "new-model",
        "display_name": "New Model",
        "provider": "讯飞 MaaS",
        "context_window": 64000,
        "max_output_tokens": 8192,
        "temperature": 0.3,
        "thinking": {"supported": True, "budget": 5000},
        "capability": "multimodal",
        "is_default": True,
    })
    assert upsert.status == "ok"
    assert upsert.payload["model_id"] == "new-model"

    # Verify via the store.
    store = ModelStore()
    model = store.get_sync("new-model", work_root=str(work))
    assert model is not None
    assert model.display_name == "New Model"
    assert model.resolved_capability == "multimodal"
    assert model.is_default is True


@pytest.mark.asyncio
async def test_rpc_models_upsert_rejects_invalid_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    catalog = _model_catalog(tmp_path / "work")
    result = await catalog.execute("config.models.upsert", {
        "model_id": "x", "scope": "bogus",
    })
    assert result.status == "error"
    assert "scope" in result.payload["error"]


@pytest.mark.asyncio
async def test_rpc_models_delete_removes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    work = tmp_path / "work"
    catalog = _model_catalog(work)
    # First create, then delete.
    await catalog.execute("config.models.upsert", {
        "scope": "global", "model_id": "doomed", "display_name": "Doomed",
        "provider": "P", "context_window": 128000, "max_output_tokens": 4096,
        "temperature": 0.2,
    })
    result = await catalog.execute("config.models.delete", {
        "scope": "global", "model_id": "doomed",
    })
    assert result.status == "ok"
    # Second delete should fail (file gone).
    again = await catalog.execute("config.models.delete", {
        "scope": "global", "model_id": "doomed",
    })
    assert again.status == "error"
