from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.app.operation_catalog import OperationCatalog, OperationRequest
from lamtools_core.config.subagent_prompt import (
    DEFAULT_SUBAGENT_GUIDE,
    guide_path_for_scope,
    load_subagent_guide,
    resolve_subagent_guide_path,
    write_subagent_guide,
)


@pytest.mark.asyncio
async def test_load_subagent_guide_returns_builtin_when_no_file(tmp_path, isolated_config_root):
    # Isolate from any real ~/.lam config on the test machine.

    guide = load_subagent_guide(tmp_path / "work")

    assert guide == DEFAULT_SUBAGENT_GUIDE
    assert "委派" in guide
    assert resolve_subagent_guide_path(tmp_path / "work") is None


@pytest.mark.asyncio
async def test_load_subagent_guide_prefers_project_over_global(tmp_path, isolated_config_root):
    work = tmp_path / "work"
    global_dir = isolated_config_root / "subagent"
    global_dir.mkdir(parents=True)
    (global_dir / "guide.md").write_text("# Global guide\nuse sub_agent wisely", encoding="utf-8")
    project_dir = work / ".lam" / "config" / "subagent"
    project_dir.mkdir(parents=True)
    (project_dir / "guide.md").write_text("# Project guide\nproject-specific rules", encoding="utf-8")

    guide = load_subagent_guide(work)

    assert "Project guide" in guide
    assert "project-specific rules" in guide
    resolved = resolve_subagent_guide_path(work)
    assert resolved is not None and resolved.name == "guide.md"
    assert resolved.parent == project_dir


@pytest.mark.asyncio
async def test_load_subagent_guide_falls_back_to_global(tmp_path, isolated_config_root):
    work = tmp_path / "work"
    global_dir = isolated_config_root / "subagent"
    global_dir.mkdir(parents=True)
    (global_dir / "guide.md").write_text("# Global only\nstandalone guide", encoding="utf-8")

    guide = load_subagent_guide(work)

    assert "Global only" in guide


@pytest.mark.asyncio
async def test_write_subagent_guide_writes_to_requested_scope(tmp_path, isolated_config_root):
    work = tmp_path / "work"

    project_path = write_subagent_guide("# New project guide", scope="project", work_root=work)
    global_path = write_subagent_guide("# New global guide", scope="global", work_root=work)

    assert project_path == work / ".lam" / "config" / "subagent" / "guide.md"
    assert project_path.read_text(encoding="utf-8") == "# New project guide"
    assert global_path == isolated_config_root / "subagent" / "guide.md"
    assert global_path.read_text(encoding="utf-8") == "# New global guide"
    # After writing, the loader returns the project (higher priority) content.
    assert "# New project guide" in load_subagent_guide(work)


def test_guide_path_for_scope_project_without_work_root_falls_to_global(tmp_path, isolated_config_root):
    # Without a work_root, even a "project" scope cannot point at a project dir,
    # so the writer falls back to the global path (home) rather than erroring.
    path = guide_path_for_scope("project", None)
    assert path == isolated_config_root / "subagent" / "guide.md"

    path_with_root = guide_path_for_scope("project", tmp_path / "work")
    assert path_with_root == tmp_path / "work" / ".lam" / "config" / "subagent" / "guide.md"


# --- RPC operations -------------------------------------------------------


def _guide_catalog(work_root: Path | None) -> OperationCatalog:
    from lamtools_core.app.http_agent_app import _register_subagent_guide_operations

    catalog = OperationCatalog()
    _register_subagent_guide_operations(catalog, work_root=work_root)
    return catalog


@pytest.mark.asyncio
async def test_rpc_guide_get_returns_builtin_when_unset(tmp_path, isolated_config_root):
    catalog = _guide_catalog(tmp_path / "work")

    result = await catalog.execute(
        "config.subagent.guide.get", {"work_root": str(tmp_path / "work")}
    )

    assert result.status == "ok"
    assert result.payload["is_builtin"] is True
    assert result.payload["scope"] == "builtin"
    assert result.payload["content"] == DEFAULT_SUBAGENT_GUIDE


@pytest.mark.asyncio
async def test_rpc_guide_set_then_get_roundtrips_project_scope(tmp_path, isolated_config_root):
    work = tmp_path / "work"
    catalog = _guide_catalog(work)

    written = await catalog.execute(
        "config.subagent.guide.set",
        {"scope": "project", "work_root": str(work), "content": "# Project RPC guide"},
    )
    assert written.status == "ok"
    assert written.payload["scope"] == "project"

    fetched = await catalog.execute(
        "config.subagent.guide.get", {"work_root": str(work)}
    )
    assert fetched.status == "ok"
    assert fetched.payload["is_builtin"] is False
    assert fetched.payload["scope"] == "project"
    assert fetched.payload["content"] == "# Project RPC guide"


@pytest.mark.asyncio
async def test_rpc_guide_set_rejects_invalid_scope(tmp_path, isolated_config_root):
    catalog = _guide_catalog(tmp_path / "work")

    result = await catalog.execute(
        "config.subagent.guide.set",
        {"scope": "weird", "content": "nope"},
    )

    assert result.status == "error"
    assert "scope" in result.payload["error"]


@pytest.mark.asyncio
async def test_rpc_guide_set_project_requires_work_root(tmp_path, isolated_config_root):
    # Catalog constructed without a work_root; payload also omits it.
    catalog = _guide_catalog(None)

    result = await catalog.execute(
        "config.subagent.guide.set",
        {"scope": "project", "content": "no root"},
    )

    assert result.status == "error"
    assert "work_root" in result.payload["error"]


# --- Prompt injection -----------------------------------------------------


@pytest.mark.asyncio
async def test_base_agent_injects_custom_subagent_guide_into_system_prompt(tmp_path, isolated_config_root):
    from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
    from lamtools_core.kernel.state import RuntimeState
    from lamtools_core.prompt import PromptContext

    project_dir = tmp_path / "work" / ".lam" / "config" / "subagent"
    project_dir.mkdir(parents=True)
    (project_dir / "guide.md").write_text(
        "CUSTOM SUBAGENT GUIDE: always specify model + mode when delegating.",
        encoding="utf-8",
    )

    kit = CoreBaseAgentKit(work_root=tmp_path / "work", config=CoreBaseAgentConfig())
    request = await kit.build_model_request(
        RuntimeState(session_id="guide-inject"),
        PromptContext(session_id="guide-inject"),
    )

    system_prompt = str(request.messages[0].content)
    assert "CUSTOM SUBAGENT GUIDE" in system_prompt
    # The old hard-coded delegation line is replaced by the guide.
    assert "互不依赖的任务应委派 sub-agent 并行执行。其 prompt 至少明确" not in system_prompt


@pytest.mark.asyncio
async def test_base_agent_injects_builtin_guide_when_no_file(tmp_path, isolated_config_root):
    from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
    from lamtools_core.kernel.state import RuntimeState
    from lamtools_core.prompt import PromptContext


    kit = CoreBaseAgentKit(work_root=tmp_path / "work", config=CoreBaseAgentConfig())
    request = await kit.build_model_request(
        RuntimeState(session_id="builtin-guide"),
        PromptContext(session_id="builtin-guide"),
    )

    system_prompt = str(request.messages[0].content)
    assert DEFAULT_SUBAGENT_GUIDE in system_prompt


@pytest.mark.asyncio
async def test_base_agent_injects_capability_prompt_for_text_model(tmp_path, isolated_config_root):
    from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
    from lamtools_core.kernel.state import RuntimeState
    from lamtools_core.prompt import PromptContext

    kit = CoreBaseAgentKit(
        work_root=tmp_path / "work",
        config=CoreBaseAgentConfig(capability="text"),
    )

    request = await kit.build_model_request(
        RuntimeState(session_id="cap-text"),
        PromptContext(session_id="cap-text"),
    )

    system_prompt = str(request.messages[0].content)
    assert "当前模型能力" in system_prompt
    assert "文本模型" in system_prompt
    assert "不支持图片" in system_prompt
    assert "sub_agent" in system_prompt
    assert "多模态模型" in system_prompt


@pytest.mark.asyncio
async def test_base_agent_injects_capability_prompt_for_multimodal_model(tmp_path, isolated_config_root):
    from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
    from lamtools_core.kernel.state import RuntimeState
    from lamtools_core.prompt import PromptContext

    kit = CoreBaseAgentKit(
        work_root=tmp_path / "work",
        config=CoreBaseAgentConfig(capability="multimodal"),
    )

    request = await kit.build_model_request(
        RuntimeState(session_id="cap-mm"),
        PromptContext(session_id="cap-mm"),
    )

    system_prompt = str(request.messages[0].content)
    assert "当前模型能力" in system_prompt
    assert "多模态" in system_prompt


@pytest.mark.asyncio
async def test_base_agent_omits_capability_line_when_capability_unknown(tmp_path, isolated_config_root):
    from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
    from lamtools_core.kernel.state import RuntimeState
    from lamtools_core.prompt import PromptContext

    kit = CoreBaseAgentKit(
        work_root=tmp_path / "work",
        config=CoreBaseAgentConfig(capability=""),  # unknown
    )

    request = await kit.build_model_request(
        RuntimeState(session_id="cap-none"),
        PromptContext(session_id="cap-none"),
    )

    system_prompt = str(request.messages[0].content)
    assert "当前模型能力" not in system_prompt


# --- Default multimodal model resolution -----------------------------------


def _write_model(config_dir: Path, model_id: str, *, capability: str) -> None:
    """Write a minimal model jsonc into a config-root models dir."""
    models_dir = config_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / f"{model_id}.jsonc").write_text(
        json.dumps({"model_id": model_id, "capability": capability}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_resolve_default_multimodal_model_prefers_settings(tmp_path, isolated_config_root):
    from lamtools_core.config.subagent_prompt import resolve_default_multimodal_model

    _write_model(isolated_config_root, "alpha-mm", capability="multimodal")
    settings_dir = isolated_config_root / "subagent"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "settings.json").write_text(
        json.dumps({"default_multimodal_model": "alpha-mm"}), encoding="utf-8"
    )

    assert resolve_default_multimodal_model(tmp_path / "work") == "alpha-mm"


def test_resolve_default_multimodal_model_picks_first_multimodal_from_store(tmp_path, isolated_config_root):
    from lamtools_core.config.subagent_prompt import resolve_default_multimodal_model

    # Two multimodal models: "model-a" sorts before "model-b" by model_id.
    _write_model(isolated_config_root, "model-b", capability="multimodal")
    _write_model(isolated_config_root, "model-a", capability="multimodal")
    # A text model must never be picked.
    _write_model(isolated_config_root, "text-only", capability="text")

    assert resolve_default_multimodal_model(tmp_path / "work") == "model-a"


def test_resolve_default_multimodal_model_returns_none_without_multimodal(tmp_path, isolated_config_root):
    from lamtools_core.config.subagent_prompt import resolve_default_multimodal_model

    _write_model(isolated_config_root, "text-only", capability="text")

    assert resolve_default_multimodal_model(tmp_path / "work") is None


@pytest.mark.asyncio
async def test_text_model_capability_prompt_uses_first_multimodal_model(tmp_path, isolated_config_root):
    from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
    from lamtools_core.kernel.state import RuntimeState
    from lamtools_core.prompt import PromptContext

    _write_model(isolated_config_root, "alpha-mm", capability="multimodal")

    kit = CoreBaseAgentKit(
        work_root=tmp_path / "work",
        config=CoreBaseAgentConfig(capability="text"),
    )
    request = await kit.build_model_request(
        RuntimeState(session_id="cap-dynamic"),
        PromptContext(session_id="cap-dynamic"),
    )

    system_prompt = str(request.messages[0].content)
    assert '指定 model 为 "alpha-mm"' in system_prompt
    assert "Kimi-K2.6" not in system_prompt


@pytest.mark.asyncio
async def test_text_model_capability_prompt_omits_concrete_model_when_none(tmp_path, isolated_config_root):
    from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
    from lamtools_core.kernel.state import RuntimeState
    from lamtools_core.prompt import PromptContext

    kit = CoreBaseAgentKit(
        work_root=tmp_path / "work",
        config=CoreBaseAgentConfig(capability="text"),
    )
    request = await kit.build_model_request(
        RuntimeState(session_id="cap-no-mm"),
        PromptContext(session_id="cap-no-mm"),
    )

    system_prompt = str(request.messages[0].content)
    assert "指定 model 为支持图片的模型" in system_prompt
    assert 'model="' not in system_prompt
    assert "Kimi-K2.6" not in system_prompt
