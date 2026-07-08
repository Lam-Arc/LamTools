"""Tests for Writer prompt assembly on the production Kernel path."""

import re

import pytest

import app.core.prompt_assembler as prompt_assembler
from app.core.persona import get_writer_system_prompt
from app.core.prompt_assembler import current_date_prompt, get_writer_execution_discipline
from app.core.prompt_files import load_writer_prompt
from app.core.writer.core_kernel_adapter import WriterKit
from lamtools_core.runtime import RuntimeState, RuntimeTurnInput


async def _system_messages(work_root: str = "") -> list[str]:
    kit = WriterKit(work_root=work_root)
    state = RuntimeState(session_id="prompt-test")
    context = await kit.build_context(
        state,
        RuntimeTurnInput(user_message="请处理当前任务"),
        history=[],
        step_index=0,
    )
    request = await kit.build_model_request(state, context)
    return [message.content for message in request.messages if message.role == "system"]


def test_legacy_writer_prompt_assembler_class_is_not_exposed():
    assert not hasattr(prompt_assembler, "WriterPromptAssembler")


def test_persona_is_loaded_from_markdown():
    assert get_writer_system_prompt() == load_writer_prompt("persona")


def test_current_date_prompt_uses_day_precision():
    assert re.fullmatch(r"now: \d{4}-\d{2}-\d{2}", current_date_prompt())


def test_execution_discipline_can_be_overridden(monkeypatch, tmp_path):
    prompt_root = tmp_path / "prompts" / "writer"
    prompt_root.mkdir(parents=True)
    (prompt_root / "execution_discipline.md").write_text("Custom execution rules", encoding="utf-8")
    monkeypatch.setenv("LAMWRITER_PROMPT_DIR", str(tmp_path / "prompts"))

    assert get_writer_execution_discipline() == "Custom execution rules"


def test_prompt_can_load_from_member_resource_dir(monkeypatch, tmp_path):
    resource_root = tmp_path / "runtime" / "members" / "writer"
    prompt_root = resource_root / "prompts" / "writer"
    prompt_root.mkdir(parents=True)
    (prompt_root / "resource_only.md").write_text("Editable packaged prompt", encoding="utf-8")
    monkeypatch.delenv("LAMWRITER_PROMPT_DIR", raising=False)
    monkeypatch.setenv("LAMWRITER_MEMBER_RESOURCE_DIR", str(resource_root))

    assert load_writer_prompt("resource_only") == "Editable packaged prompt"


@pytest.mark.asyncio
async def test_kernel_prompt_includes_core_system_blocks():
    messages = await _system_messages()
    joined = "\n\n".join(messages)

    assert get_writer_system_prompt() in joined
    assert "Writer 执行协议" in joined
    assert "先理解再修改" in joined
    assert "优先复用项目已有接口" in joined
    assert "不回滚无关文件" in joined
    assert "每个交付都要有可验证结果" in joined
    assert any(re.fullmatch(r"now: \d{4}-\d{2}-\d{2}", message) for message in messages)


@pytest.mark.asyncio
async def test_kernel_prompt_loads_agents_md(tmp_dir):
    work_root = tmp_dir / "repo"
    work_root.mkdir()
    (work_root / "AGENTS.md").write_text(
        "# Project Rules\n\n- 不得使用 mock 测试\n- 使用中文汇报\n",
        encoding="utf-8",
    )

    joined = "\n\n".join(await _system_messages(str(work_root)))

    assert "Project instructions:" in joined
    assert "Instructions from:" in joined
    assert "AGENTS.md" in joined
    assert "不得使用 mock 测试" in joined


@pytest.mark.asyncio
async def test_kernel_prompt_agents_md_wins_over_claude_md(tmp_dir):
    work_root = tmp_dir / "repo"
    work_root.mkdir()
    (work_root / "AGENTS.md").write_text("AGENTS rule", encoding="utf-8")
    (work_root / "CLAUDE.md").write_text("CLAUDE rule", encoding="utf-8")

    joined = "\n\n".join(await _system_messages(str(work_root)))

    assert "AGENTS rule" in joined
    assert "CLAUDE rule" not in joined


@pytest.mark.asyncio
async def test_kernel_prompt_loads_skill_index_without_full_skill_body(tmp_dir):
    work_root = tmp_dir / "repo"
    skill_dir = work_root / ".agents" / "skills" / "reviewer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: reviewer\ndescription: Use for code review tasks\n---\n"
        "FULL SECRET WORKFLOW\n",
        encoding="utf-8",
    )

    joined = "\n\n".join(await _system_messages(str(work_root)))

    assert "Available Writer skills:" in joined
    assert "<name>reviewer</name>" in joined
    assert "Use for code review tasks" in joined
    assert "FULL SECRET WORKFLOW" not in joined
