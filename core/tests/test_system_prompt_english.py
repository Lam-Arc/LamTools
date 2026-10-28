from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
from lamtools_core.prompt import PromptContext
from lamtools_core.runtime import RuntimeState
from lamtools_core.skill_runtime import create_skill_runtime
from lamtools_core.tool.default_toolbox import CoreToolbox


# Keep the check narrow enough to allow normal Latin, punctuation, and model
# identifiers while covering the CJK blocks used by the built-in prompts.
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_STUDY_ROOT = Path(__file__).parents[1] / "src" / "lamtools_core" / "plugins" / "bundled" / "study"


@pytest.fixture(autouse=True)
def isolated_prompt_config_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep preset-prompt checks away from the developer's global config."""
    lam_home = tmp_path / "lam-home"
    monkeypatch.setenv("LAMTOOLS_CORE_CONFIG_ROOT", str(lam_home / "core"))
    monkeypatch.setenv("LAMTOOLS_HOME", str(lam_home))


def _prompt_text(
    tmp_path: Path,
    *,
    active_mode: str | None = None,
    config: CoreBaseAgentConfig | None = None,
    study_skills: bool = False,
) -> str:
    plugin_roots: list[Path] = []
    skill_modes: dict[Path, tuple[str, ...]] = {}
    if study_skills:
        plugin_roots = [_STUDY_ROOT, _STUDY_ROOT / "future"]
        skill_modes = {
            _STUDY_ROOT / "skills": ("study:study",),
            _STUDY_ROOT / "future": ("study:study",),
        }
    runtime = create_skill_runtime(
        plugin_skill_roots=plugin_roots,
        plugin_skill_modes=skill_modes,
    )
    toolbox = CoreToolbox(
        work_root=tmp_path,
        loaded_skill_roots=set(runtime.roots),
        skill_registry=runtime.registry,
        active_mode=active_mode,
    )
    kit = CoreBaseAgentKit(
        work_root=tmp_path,
        config=config or CoreBaseAgentConfig(active_mode=active_mode),
        toolbox=toolbox,
    )
    state = RuntimeState(
        session_id="prompt-language-check",
        metadata={"work_root": str(tmp_path)},
    )
    # This helper deliberately supplies no user message, history, project
    # files, memory, or other user-authored context.
    request = asyncio.run(
        kit.build_model_request(
            state,
            PromptContext(session_id=state.session_id),
        )
    )
    return str(request.messages[0].content)


def _assert_no_han(text: str) -> None:
    match = _HAN.search(text)
    assert match is None, f"unexpected Han character {match.group(0)!r} in system prompt"


# user:“收到用户消息之后第一时间先回复，再继续工具调用，同时 每过一段时间再说句话”+(普通和学习模式都要先回复，工作期间自然沟通，不规定固定间隔)。
@pytest.mark.parametrize("active_mode", [None, "study:study"])
def test_system_prompt_requires_initial_reply_and_natural_progress(tmp_path, active_mode):
    prompt = _prompt_text(tmp_path, active_mode=active_mode)

    assert "Immediately after receiving a user message, send a brief user-facing reply before making any tool call." in prompt
    assert "Keep the user informed naturally during ongoing work" in prompt
    assert "meaningful progress, encounter a problem, or the work is taking a while" in prompt
    assert "Do not follow a fixed time interval or tool-call count" in prompt
    assert "every 30 seconds" not in prompt
    assert "After 12 consecutive tool-only rounds" not in prompt


def test_normal_system_prompt_and_real_bundled_skill_descriptions_are_english(tmp_path):
    prompt = _prompt_text(tmp_path)

    assert prompt.startswith("You are Sunday Agent.\nCurrent project:")
    assert "Available skills:" in prompt
    assert "- office-documents:" in prompt
    _assert_no_han(prompt)


def test_study_system_prompt_and_study_skill_descriptions_are_english(tmp_path):
    prompt = _prompt_text(
        tmp_path,
        active_mode="study:study",
        study_skills=True,
    )

    assert prompt.startswith("# Study System Prompt\n")
    assert "Available skills:" in prompt
    assert "- answer:" in prompt
    assert "- teach:" in prompt
    _assert_no_han(prompt)


def test_user_authored_chinese_system_instructions_are_preserved(tmp_path):
    config = CoreBaseAgentConfig(instructions="用户自定义系统说明")

    prompt = _prompt_text(tmp_path, config=config)

    assert prompt.startswith("用户自定义系统说明\n")


def test_user_authored_chinese_project_context_is_preserved_in_normal_prompt(tmp_path):
    context_file = tmp_path / "CONTEXT.md"
    context_file.write_text("用户项目说明：保留这段中文上下文。", encoding="utf-8")
    config = CoreBaseAgentConfig(
        project_context_files=[("CONTEXT.md", 10, "system")],
    )

    prompt = _prompt_text(tmp_path, config=config)

    assert "用户项目说明：保留这段中文上下文。" in prompt


def test_study_omits_project_context_even_when_workspace_context_is_chinese(tmp_path):
    context_file = tmp_path / "CONTEXT.md"
    context_file.write_text("用户项目说明：保留这段中文上下文。", encoding="utf-8")
    config = CoreBaseAgentConfig(
        active_mode="study:study",
        project_context_files=[("CONTEXT.md", 10, "system")],
    )

    prompt = _prompt_text(
        tmp_path,
        active_mode="study:study",
        config=config,
        study_skills=True,
    )

    # Study intentionally omits project context from the leading prompt.
    assert "用户项目说明：保留这段中文上下文。" not in prompt
