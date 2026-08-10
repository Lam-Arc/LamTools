"""Tests for the dreaming settings entry point (app_settings core.dreaming).

Covers:
- turn.start reads core.dreaming from app_settings and applies it to the
  kernel's LoopPolicy (dynamic, no restart).
- Settings absent → falls back to spec defaults (False / 3).
- Catalog without settings.get → no error, spec defaults.
- Corrupt settings values → silent fallback to spec defaults.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lamtools_core.app import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.app.http_agent_app import _register_missing_operations
from lamtools_core.config.operations import build_shared_config_operation_catalog
from lamtools_core.config.shared_database import AppSetting, init_shared_config_schema
from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent


class FinalReplyLLM:
    """Streaming LLMClient that immediately replies — drives the real kernel."""

    def __init__(self, reply: str = "done") -> None:
        self.reply = reply

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Core operation should use streaming")

    async def stream(self, request: LLMRequest):
        yield LLMStreamEvent(kind="content_delta", content=self.reply, raw={})
        yield LLMStreamEvent(kind="done", raw={})


@dataclass
class KernelCapture:
    """Captures the LoopPolicy passed to CoreLoopKernel at construction."""

    policies: list[object] = None

    def __post_init__(self) -> None:
        if self.policies is None:
            self.policies = []


@pytest.fixture
async def config_catalog(tmp_path):
    """A shared-config operation catalog (settings.get/update) on a temp db."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'shared.db'}", future=True)
    try:
        await init_shared_config_schema(engine)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        catalog = build_shared_config_operation_catalog(session_factory)
        yield catalog, session_factory
    finally:
        await engine.dispose()


@pytest.fixture
def capture_kernel(monkeypatch):
    """Monkeypatch CoreLoopKernel construction to capture LoopPolicy args."""
    import lamtools_core.app.default_agent as default_agent

    capture = KernelCapture()

    real_init = default_agent.CoreLoopKernel.__init__

    def patched_init(self, *args, **kwargs):
        capture.policies.append(kwargs.get("policy"))
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(default_agent.CoreLoopKernel, "__init__", patched_init)
    return capture


async def _run_turn(tmp_path, *, spec: CoreAgentSpec | None = None, config_catalog=None):
    """Build a full catalog (core db + optional config catalog) and run a turn."""
    spec = spec or CoreAgentSpec()
    db = await open_core_app_db(tmp_path / "core.db")
    catalog = create_core_agent_operations(
        spec=spec,
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path),
        model_provider=FinalReplyLLM(),
        db_session_factory=db.session_factory,
        app_event_store=db.event_store,
        thread_snapshot_store=db.snapshot_store,
        runtime_state_store=db.runtime_state_store,
    )
    if config_catalog is not None:
        _register_missing_operations(catalog, config_catalog)

    try:
        result = await catalog.execute(
            "turn.start",
            {"thread_id": "thread-1", "message": "do work"},
        )
        return result
    finally:
        await db.close()


async def _seed_dreaming(session_factory, *, enabled: bool, min_turns: int) -> None:
    async with session_factory() as db:
        db.add(
            AppSetting(
                namespace="core.dreaming",
                value={"enabled": enabled, "min_turns": min_turns},
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_turn_start_applies_dreaming_settings_from_app_settings(tmp_path, config_catalog, capture_kernel):
    config_catalog, session_factory = config_catalog
    await _seed_dreaming(session_factory, enabled=True, min_turns=7)

    result = await _run_turn(
        tmp_path,
        spec=CoreAgentSpec(dreaming_enabled=False, dream_min_turns=3),
        config_catalog=config_catalog,
    )
    assert result.status == "ok"

    # The kernel was constructed with a policy reflecting the settings.
    assert capture_kernel.policies, "kernel should have been constructed"
    policy = capture_kernel.policies[-1]
    assert getattr(policy, "dreaming_enabled") is True
    assert getattr(policy, "dream_min_turns") == 7


@pytest.mark.asyncio
async def test_turn_start_falls_back_to_spec_defaults_without_settings(tmp_path, config_catalog, capture_kernel):
    config_catalog, _ = config_catalog
    result = await _run_turn(
        tmp_path,
        spec=CoreAgentSpec(dreaming_enabled=False, dream_min_turns=3),
        config_catalog=config_catalog,
    )
    assert result.status == "ok"
    policy = capture_kernel.policies[-1]
    assert getattr(policy, "dreaming_enabled") is False
    assert getattr(policy, "dream_min_turns") == 3


@pytest.mark.asyncio
async def test_turn_start_without_settings_operation_uses_spec_defaults(tmp_path, capture_kernel):
    """Catalog without settings.get (no config db) must not raise."""
    result = await _run_turn(
        tmp_path,
        spec=CoreAgentSpec(dreaming_enabled=True, dream_min_turns=5),
    )
    assert result.status == "ok"
    policy = capture_kernel.policies[-1]
    # Spec value is used directly (settings.get absent → no override).
    assert getattr(policy, "dreaming_enabled") is True
    assert getattr(policy, "dream_min_turns") == 5


@pytest.mark.asyncio
async def test_turn_start_ignores_corrupt_settings(tmp_path, config_catalog, capture_kernel):
    config_catalog, session_factory = config_catalog
    # Store a non-dict / non-numeric value — must not raise.
    async with session_factory() as db:
        db.add(AppSetting(namespace="core.dreaming", value="not-a-dict"))
        await db.commit()

    result = await _run_turn(
        tmp_path,
        spec=CoreAgentSpec(dreaming_enabled=False, dream_min_turns=3),
        config_catalog=config_catalog,
    )
    assert result.status == "ok"
    policy = capture_kernel.policies[-1]
    assert getattr(policy, "dreaming_enabled") is False
