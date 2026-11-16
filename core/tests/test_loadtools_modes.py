"""运行模式注册表：chat / work / superagent，旧名字映射。

user:“将现有的consider，excute迭代为 super Agent、chat、work”
+(三种模式必须始终存在，否则新建会话选不出模式；旧配置里只有 consider/execute 时
也要能开起来，并且用户自己写的工具清单不能被改名弄丢)。
"""

from __future__ import annotations

from pathlib import Path
import json

from lamtools_core.tool.loadtools import (
    default_load_tools,
    load_loadtools,
    mode_tool_set,
)


def _write(path: Path, modes: dict[str, dict]) -> Path:
    path.write_text(
        json.dumps({"modes": modes}, ensure_ascii=False), encoding="utf-8"
    )
    return path


def test_default_modes_are_chat_work_auto() -> None:
    modes = default_load_tools()
    assert list(modes) == ["chat", "work", "auto"]
    assert modes["work"].is_full_access, "工作模式应当能用全部工具"
    assert not modes["chat"].is_full_access, "聊天模式必须有白名单"


def test_chat_mode_is_read_only() -> None:
    """user:“聊天不改文件”+(改文件的工具在聊天模式里根本不出现；run_command 保留，
    但执行时按单条命令定级，只放只读命令)。"""
    tools = mode_tool_set(default_load_tools(), "chat")
    assert tools is not None
    for forbidden in ("write_file", "edit_file", "kill_process"):
        assert forbidden not in tools, f"聊天模式不该出现 {forbidden}"
    assert "run_command" in tools, "只读命令仍要能跑（git status 这类）"


def test_superagent_cannot_touch_files_or_run_commands() -> None:
    """Router 不碰文件、不跑 shell，活交给子代理。"""
    tools = mode_tool_set(default_load_tools(), "auto")
    assert tools is not None
    for forbidden in ("write_file", "edit_file", "run_command", "kill_process"):
        assert forbidden not in tools, f"Super Agent 模式不该出现 {forbidden}"
    assert "sub_agent" in tools and "sub_agent_message" in tools


def test_legacy_names_are_renamed_and_custom_tools_kept(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "loadtools.jsonc",
        {
            "consider": {"description": "旧只读", "tools": ["read_file", "web_search"]},
            "execute": {"description": "旧全量", "tools": []},
        },
    )

    modes = load_loadtools(path)

    assert "consider" not in modes and "execute" not in modes
    assert modes["chat"].tools == ["read_file", "web_search"], "自定义工具清单被改了"
    assert modes["work"].is_full_access
    assert "auto" in modes, "旧配置里没有 superagent，必须补上"


def test_an_explicit_new_name_wins_over_a_legacy_alias(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "loadtools.jsonc",
        {
            "consider": {"description": "旧", "tools": ["read_file"]},
            "chat": {"description": "新", "tools": ["read_file", "list_dir"]},
        },
    )

    modes = load_loadtools(path)

    assert modes["chat"].tools == ["read_file", "list_dir"]


def test_missing_modes_are_filled_from_defaults(tmp_path: Path) -> None:
    path = _write(tmp_path / "loadtools.jsonc", {"chat": {"description": "", "tools": ["read_file"]}})

    modes = load_loadtools(path)

    assert set(modes) == {"chat", "work", "auto"}


def test_a_missing_file_still_yields_the_three_modes(tmp_path: Path) -> None:
    modes = load_loadtools(tmp_path / "nope.jsonc")
    assert list(modes) == ["chat", "work", "auto"]
