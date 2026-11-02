"""user:“让模型写完整路径”+(回复中提到的文件必须写全相对目录，裸文件名会被界面拼到项目根目录而显示“原文件不存在”)。"""
from __future__ import annotations

from pathlib import Path

import pytest

import lamtools_core.app.base_agent as base_agent
from lamtools_core.app.base_agent import (
    FILE_REFERENCE_PROTOCOL,
    CoreBaseAgentConfig,
    CoreBaseAgentKit,
)
from lamtools_core.runtime import RuntimeState


class _Toolbox:
    load_tools = None

    def tool_specs(self):
        return []

    def model_tools(self, active_mode=None):
        return []

    def skill_index(self):
        return ""


def _kit(tmp_path: Path) -> CoreBaseAgentKit:
    kit = CoreBaseAgentKit(
        work_root=tmp_path,
        config=CoreBaseAgentConfig(instructions="BASE INSTRUCTIONS"),
        toolbox=_Toolbox(),  # type: ignore[arg-type]
    )
    kit._cached_subagent_guide = lambda: ""  # type: ignore[method-assign]
    kit._cached_subagent_roles = lambda: ""  # type: ignore[method-assign]
    kit._cached_subagent_strategy = lambda: ""  # type: ignore[method-assign]
    kit._build_project_context_parts = lambda: []  # type: ignore[method-assign]
    return kit


def test_file_reference_rule_requires_full_directory_paths() -> None:
    # 文件引用规则独立于内联可视化协议，审计按块归类时不会被误记。
    assert "full workspace-relative path" in FILE_REFERENCE_PROTOCOL
    assert "never just the file name" in FILE_REFERENCE_PROTOCOL


@pytest.mark.asyncio
async def test_agent_mode_prompt_carries_the_rule(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(base_agent, "command_shell_prompt", lambda: "[Shell]")
    kit = _kit(tmp_path)
    state = RuntimeState(session_id="s", metadata={"work_root": str(tmp_path), "turn_id": "t"})
    system_prompt, _ = kit._compose_system_prompt(
        state,
        study_mode=False,
        effective_instructions="BASE INSTRUCTIONS",
    )
    assert "full workspace-relative path" in system_prompt
    assert "never just the file name" in system_prompt
    assert "directories included" in system_prompt


@pytest.mark.asyncio
async def test_study_mode_prompt_carries_the_rule(tmp_path: Path) -> None:
    kit = _kit(tmp_path)
    state = RuntimeState(session_id="s", metadata={"work_root": str(tmp_path), "turn_id": "t"})
    system_prompt, _ = kit._compose_system_prompt(
        state,
        study_mode=True,
        effective_instructions="BASE INSTRUCTIONS",
    )
    assert "full workspace-relative path" in system_prompt
    assert "never just the file name" in system_prompt
