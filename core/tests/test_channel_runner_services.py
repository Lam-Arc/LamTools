"""Host services for plugin channel runtimes: models, presets, child sessions."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent
from lamtools_core.plugin_system.agent_presets import AgentPresetRegistry
from lamtools_core.plugin_system.model_catalog import ModelCatalogService
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState
from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner


def _write_model(tmp_path: Path, model_id: str = "test-model", capability: str = "text") -> None:
    models = tmp_path / ".lam" / "config" / "models"
    models.mkdir(parents=True, exist_ok=True)
    (models / f"{model_id}.jsonc").write_text(
        json.dumps(
            {
                "model_id": model_id,
                "display_name": "Test Model",
                "provider": "test-provider",
                "capability": capability,
                "context_window": 100000,
                "max_output_tokens": 4096,
                "is_default": True,
            }
        ),
        encoding="utf-8",
    )


def test_model_catalog_reads_project_models(tmp_path: Path) -> None:
    _write_model(tmp_path, "test-model", "multimodal")
    catalog = ModelCatalogService(work_root=tmp_path)
    models = catalog.list()
    assert any(model.id == "test-model" for model in models)
    info = catalog.resolve("Test Model")
    assert info is not None
    assert info.id == "test-model"
    assert info.provider == "test-provider"
    assert info.capability == "multimodal"
    assert catalog.capability("test-model") == "multimodal"
    assert catalog.default() is not None


def test_preset_service_scope() -> None:
    registry = AgentPresetRegistry([])
    service = object()
    unregister = registry.register_service("readonly", "compaction", service)
    assert registry.service_for("readonly", "compaction") is service
    unregister()
    assert registry.service_for("readonly", "compaction") is None


class _FakeLLM:
    async def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(content="summary of the compacted history")

    async def stream(self, request: LLMRequest):
        yield LLMStreamEvent(kind="content_delta", content="summary of the compacted history")
        yield LLMStreamEvent(kind="done")


async def _runner(tmp_path: Path) -> tuple[KernelSubAgentRunner, InMemoryRuntimeStateStore]:
    store = InMemoryRuntimeStateStore()
    runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=_FakeLLM(),
        model_id="test-model",
        state_store=store,
    )
    return runner, store


async def test_child_fork_and_session_info(tmp_path: Path) -> None:
    runner, store = await _runner(tmp_path)
    old_id = f"{runner.session_prefix}:sub:old"
    state = RuntimeState(
        session_id=old_id,
        run_id="run-1",
        status="idle",
        metadata={
            "model_id": "test-model",
            "agent_preset": "readonly",
            "runtime_usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "delegated_session": {"session_id": old_id, "agent": "old"},
        },
    )
    await store.save_checkpoint(
        state,
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
    )
    info = await runner.session_info(old_id)
    assert info["message_count"] == 2
    assert info["usage"]["input"] == 10
    assert info["agent_preset"] == "readonly"

    forked = await runner.fork(old_id, "branch")
    assert forked["agent"] == "branch"
    new_id = forked["session_id"]
    assert new_id != old_id
    new_state = await store.get(new_id)
    assert new_state is not None
    assert new_state.metadata["delegated_session"]["agent"] == "branch"
    assert len(await store.get_history(new_id)) == 2


async def test_child_manual_compaction(tmp_path: Path) -> None:
    runner, store = await _runner(tmp_path)
    session_id = f"{runner.session_prefix}:sub:compact"
    state = RuntimeState(
        session_id=session_id,
        run_id="run-1",
        metadata={
            "model_id": "test-model",
            "runtime_snapshot": {"model_id": "test-model", "context_window_tokens": 100000},
            "runtime_context_metrics": {
                "context_window_tokens": 100000,
                "context_compaction_trigger_tokens": 1000,
                "model_id": "test-model",
            },
            "compact_limit_tokens": 2000,
        },
    )
    history = []
    for index in range(12):
        history.append({"role": "user", "content": f"question {index} " + ("x" * 200)})
        history.append({"role": "assistant", "content": f"answer {index} " + ("y" * 200)})
    await store.save_checkpoint(state, history)

    result = await runner.compact(session_id)
    assert result["status"] in {"compacted", "not_needed"}
    service = runner.preset_service("compaction", "readonly")
    assert service is not None
    assert hasattr(service, "compact_now")


async def test_clone_with_work_root_shares_state_store(tmp_path: Path) -> None:
    runner, store = await _runner(tmp_path)
    other = tmp_path / "bot-home"
    clone = runner.clone_with_work_root(other)
    assert clone.work_root == other
    assert clone.state_store is store
    assert clone.agent_presets is runner.agent_presets


async def test_runner_wraps_a_callable_parent_event_sink(tmp_path: Path) -> None:
    from lamtools_core.event import CoreEvent

    runner, _ = await _runner(tmp_path)
    seen: list[CoreEvent] = []

    async def sink(event: CoreEvent) -> None:
        seen.append(event)

    runner.parent_event_sink = sink

    assert hasattr(runner.parent_event_sink, "emit")
    await runner.parent_event_sink.emit(CoreEvent(name="runtime.done", category="progress"))
    assert [event.name for event in seen] == ["runtime.done"]
