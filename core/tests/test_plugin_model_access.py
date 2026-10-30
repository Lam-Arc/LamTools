"""user:“宿主能力补齐和接口完善与文档更新”+(模型查询保留项目和场景边界，区分目录记录与上游模型 ID，不把错误伪装为空目录)。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from lamtools_core.config.model_store import ModelConfig
from lamtools_core.config.provider_store import ProviderConfig
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.lifecycle import PluginRuntimeHandle, start_plugin_backend, stop_plugin_backend
from lamtools_core.plugin_system.manifest import PluginManifest
from lamtools_core.plugin_system.model_catalog import ModelCatalogService
from lamtools_core.plugin_system.model_access import ModelAccessError


@pytest.fixture
def store(monkeypatch):
    from lamtools_core.config import model_selection, model_store
    records = [ModelConfig(id="route-one", model_id="shared-wire", display_name="Shared", provider_id="one", provider="One", capability="multimodal", context_window=10000),
               ModelConfig(id="route-two", model_id="shared-wire", display_name="Shared", provider_id="two", provider="Two")]
    state = {"records": records, "memory": {"chat": ["route-one"], "background": ["route-two"]}, "unavailable": set(), "failure": False, "roots": []}
    class Store:
        def list_sync(self, *, work_root=None):
            state["roots"].append(work_root)
            if state["failure"]:
                raise OSError("SENSITIVE-store-error")
            return state["records"]
        def get_sync(self, ref, *, work_root=None):
            return next((m for m in self.list_sync(work_root=work_root) if ref in {m.id, m.model_id, m.display_name}), None)
    class Providers:
        def get_sync(self, ref, *, work_root=None):
            if ref in state["unavailable"]:
                return None
            return ProviderConfig(id=ref, name=ref, base_url="https://provider.invalid/v1", api_key="SENSITIVE-credential")
    monkeypatch.setattr(ModelCatalogService, "_store", lambda self: Store())
    monkeypatch.setattr(model_store, "ModelStore", Store)
    monkeypatch.setattr(model_selection, "ModelStore", Store)
    monkeypatch.setattr(model_selection, "ProviderStore", Providers)
    monkeypatch.setattr(model_selection, "_read_memory", lambda: state["memory"])
    monkeypatch.setattr(model_selection, "remember_scene_model", lambda *a, **k: pytest.fail("read-only selection wrote scene memory"))
    return state


@pytest.fixture
async def env(tmp_path, store):
    root = PluginContext(tmp_path)
    catalog = ModelCatalogService(work_root=tmp_path)
    root.set_service("model_catalog", catalog)
    handles = []
    async def start(callback, name="example"):
        handle = PluginRuntimeHandle(PluginManifest(name, "1", root=tmp_path), {"start": callback}, context=root.for_work_root(tmp_path))
        handles.append(handle)
        await start_plugin_backend(handle, root)
        return handle
    try:
        yield root, catalog, start
    finally:
        for handle in reversed(handles):
            await stop_plugin_backend(handle)


async def access(start):
    views = []
    await start(lambda ctx: views.append(ctx.models))
    return views[0]


@pytest.mark.asyncio
async def test_list_keeps_record_and_wire_ids_distinct_and_excludes_credentials(env):
    _, _, start = env
    models = await access(start)
    rows = models.list()
    assert {m.id for m in rows} == {"route-one", "route-two"}
    assert {m.model_id for m in rows} == {"shared-wire"}
    assert rows[0].capability == "multimodal"
    assert "SENSITIVE" not in str([m.to_dict() for m in rows])
    assert "base_url" not in rows[0].to_dict() and "source_path" not in rows[0].to_dict()
    with pytest.raises(FrozenInstanceError):
        rows[0].id = "changed"


@pytest.mark.asyncio
async def test_lookup_prefers_exact_record_and_rejects_ambiguous_or_partial_alias(env):
    _, _, start = env
    models = await access(start)
    assert models.resolve(" route-one ").provider_id == "one"
    for ref in ("shared-wire", "Shared"):
        with pytest.raises(ModelAccessError) as error:
            models.resolve(ref)
        assert error.value.code == "model/ambiguous"
    with pytest.raises(ModelAccessError) as error:
        models.resolve("Sha")
    assert error.value.code == "model/not-found"


@pytest.mark.asyncio
async def test_facade_pins_workspace_even_if_legacy_catalog_is_retargeted(env, tmp_path, store):
    _, catalog, start = env
    models = await access(start)
    catalog.set_work_root(tmp_path / "other")
    models.list()
    assert store["roots"][-1] == str(tmp_path.resolve())


@pytest.mark.asyncio
async def test_catalog_is_live_and_old_facades_stop_at_requester_revocation(env, store):
    root, _, start = env
    views = []
    handle = await start(lambda ctx: views.append(ctx.models))
    store["records"] = store["records"][:1]
    assert len(views[0].list()) == 1
    await stop_plugin_backend(handle)
    with pytest.raises(RuntimeError):
        views[0].list()
    await start_plugin_backend(handle, root)
    assert len(views[1].list()) == 1
    with pytest.raises(RuntimeError):
        views[0].resolve("route-one")


@pytest.mark.asyncio
async def test_scene_selection_preserves_scene_and_reports_same_scene_replacement(env, store):
    _, _, start = env
    models = await access(start)
    assert models.select("chat").model.id == "route-one"
    assert models.select("background").model.id == "route-two"
    store["memory"]["background"] = ["deleted-record", "route-two"]
    chosen = models.select("background")
    assert chosen.model.id == "route-two" and chosen.replaced_from == "deleted-record" and chosen.notice
    assert store["memory"]["background"] == ["deleted-record", "route-two"]


@pytest.mark.asyncio
async def test_no_cross_scene_or_legacy_default_fallback_and_explicit_choice_is_read_only(env, store):
    _, _, start = env
    models = await access(start)
    store["memory"]["background"] = []
    with pytest.raises(ModelAccessError) as error:
        models.select("background")
    assert error.value.code == "model/no-selection"
    assert models.select("background", ref="route-two").model.id == "route-two"
    assert store["memory"]["background"] == []
    with pytest.raises(ModelAccessError) as error:
        models.select("invented-scene", ref="route-one")
    assert error.value.code == "model/invalid-scene"


@pytest.mark.asyncio
async def test_catalog_membership_is_not_provider_availability_and_explicit_choice_never_switches(env, store):
    _, _, start = env
    models = await access(start)
    store["unavailable"] = {"two", "Two"}
    assert models.resolve("route-two").id == "route-two"
    with pytest.raises(ModelAccessError) as error:
        models.select("chat", ref="route-two")
    assert error.value.code == "model/unavailable"


@pytest.mark.asyncio
async def test_store_errors_are_explicit_not_empty_catalog_and_do_not_expose_error_payload(env, store):
    _, _, start = env
    models = await access(start)
    store["failure"] = True
    for callback in (models.list, lambda: models.resolve("route-one"), lambda: models.select("chat")):
        with pytest.raises(ModelAccessError) as error:
            callback()
        assert error.value.code == "model/store-error"
        assert "SENSITIVE" not in str(error.value)


@pytest.mark.asyncio
async def test_real_model_store_keeps_project_overrides_separate(tmp_path, monkeypatch):
    import json
    from lamtools_core.config import model_store
    global_dir = tmp_path / "global-models"
    global_dir.mkdir()
    (global_dir / "same.jsonc").write_text(json.dumps({"id": "same", "model_id": "global-wire", "display_name": "Global"}))
    a, b = tmp_path / "a", tmp_path / "b"
    project_dir = a / ".lam/config/models"
    project_dir.mkdir(parents=True)
    (project_dir / "same.jsonc").write_text(json.dumps({"id": "same", "model_id": "project-wire", "display_name": "Project"}))
    monkeypatch.setattr(model_store.ModelStore, "_candidate_dirs", lambda self, work_root: [global_dir, Path(work_root) / ".lam/config/models"])
    root = PluginContext(a)
    root.set_service("model_catalog", ModelCatalogService(work_root=a))
    views = []
    handle = PluginRuntimeHandle(PluginManifest("real", "1", root=a), {"start": lambda ctx: views.append(ctx.models)}, context=root.for_work_root(a))
    await start_plugin_backend(handle, root)
    try:
        assert views[0].resolve("same").model_id == "project-wire"
        other = handle.context.for_work_root(b).models
        assert other.resolve("same").model_id == "global-wire"
        assert views[0].resolve("same").model_id == "project-wire"
    finally:
        await stop_plugin_backend(handle)


def test_desktop_startup_exposes_models_and_selected_record_reaches_child_request(tmp_path, monkeypatch, store):
    import json
    from functools import partial
    from fastapi.testclient import TestClient
    from lamtools_core.app.http_agent_app import create_core_agent_http_app
    from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner
    from lamtools_core.runtime import InMemoryRuntimeStateStore
    from .test_agent_presets_prompt_waterfall import _ScriptedLLM
    monkeypatch.setattr("lamtools_core.app.http_agent_app.warm_command_shell", lambda: None)
    monkeypatch.setattr("lamtools_core.runtime.power.apply_keep_awake", lambda: None)
    plugin_root = tmp_path / "plugins/model-consumer"
    plugin_root.mkdir(parents=True)
    (plugin_root / "plugin.json").write_text(json.dumps({"name": "model-consumer", "version": "1", "backend": "./backend.py"}))
    (plugin_root / "backend.py").write_text('''
class Runtime:
    def start(self, context):
        self.models = context.models
        self.choice = self.models.select("background")
def create_plugin(context):
    return Runtime()
''')
    app = create_core_agent_http_app(core_db=tmp_path / "boot.db", data_dir=tmp_path / "data", work_root=tmp_path / "project", plugin_roots=[tmp_path / "plugins"])
    with TestClient(app) as client:
        handle = next(h for h in app.state.core_agent_app_state["plugin_runtimes"] if h.plugin.name == "model-consumer")
        assert handle.state == "ready", handle.error
        assert handle.value.choice.model.id == "route-two"
        llm = _ScriptedLLM()
        runner = KernelSubAgentRunner(work_root=tmp_path / "project", llm_client=llm, model_id="route-one", loaded_skill_roots=(), state_store=InMemoryRuntimeStateStore())
        result = client.portal.call(partial(runner.run, task="Reply done", agent="test", model=handle.value.choice.model.id))
        assert result.decision == "done" and llm.requests[0].model == "route-two"
    with pytest.raises(RuntimeError):
        handle.value.models.list()
