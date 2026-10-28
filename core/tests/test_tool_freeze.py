"""Tool-array freeze per compaction cycle."""

from __future__ import annotations

from lamtools_core.app.tool_freeze import (
    TOOL_FREEZE_MESSAGE,
    freeze_tool_specs,
    frozen_tool_block_message,
    frozen_tool_names,
    prune_frozen_tools,
    reset_session_tool_freeze,
    reset_tool_freeze_cache,
    tool_freeze_epoch,
    tool_name,
)


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name}}


def setup_function() -> None:
    reset_tool_freeze_cache()


def test_epoch_comes_from_movable_context() -> None:
    state = type("State", (), {"metadata": {"movable_system_context": {"epoch_id": "e1"}}})()
    assert tool_freeze_epoch(state) == "e1"
    assert tool_freeze_epoch(type("State", (), {"metadata": {}})()) == "static"


def test_first_request_freezes_and_later_changes_are_ignored() -> None:
    first = freeze_tool_specs("s1", "epoch-1", [_tool("read_file"), _tool("write_file")])
    second = freeze_tool_specs("s1", "epoch-1", [_tool("read_file")])
    assert [tool_name(item) for item in first] == ["read_file", "write_file"]
    assert [tool_name(item) for item in second] == ["read_file", "write_file"]


def test_removed_tool_is_pruned_but_additions_still_wait() -> None:
    freeze_tool_specs("s1", "epoch-1", [_tool("read_file"), _tool("write_file")])
    prune_frozen_tools("s1", "epoch-1", {"read_file", "generate_image"})
    assert frozen_tool_names("s1", "epoch-1") == {"read_file"}


def test_new_epoch_rebuilds() -> None:
    freeze_tool_specs("s1", "epoch-1", [_tool("read_file")])
    next_cycle = freeze_tool_specs("s1", "epoch-2", [_tool("read_file"), _tool("generate_image")])
    assert [tool_name(item) for item in next_cycle] == ["read_file", "generate_image"]


def test_restart_rebuilds_from_current_tools() -> None:
    freeze_tool_specs("s1", "epoch-1", [_tool("read_file")])
    reset_tool_freeze_cache()
    after_restart = freeze_tool_specs("s1", "epoch-1", [_tool("read_file"), _tool("generate_image")])
    assert [tool_name(item) for item in after_restart] == ["read_file", "generate_image"]


def test_reset_session_clears_only_that_session() -> None:
    freeze_tool_specs("s1", "epoch-1", [_tool("read_file")])
    freeze_tool_specs("s2", "epoch-1", [_tool("write_file")])
    reset_session_tool_freeze("s1")
    assert frozen_tool_names("s1", "epoch-1") is None
    assert frozen_tool_names("s2", "epoch-1") == {"write_file"}


def test_new_tool_not_in_frozen_array_returns_explanation() -> None:
    freeze_tool_specs("s1", "epoch-1", [_tool("read_file")])
    names = frozen_tool_names("s1", "epoch-1")
    message = frozen_tool_block_message(
        "generate_image",
        frozen_names=names,
        current_names={"read_file", "generate_image"},
    )
    assert message is not None
    assert TOOL_FREEZE_MESSAGE in message
    assert "generate_image" in message


def test_frozen_tool_is_not_blocked() -> None:
    freeze_tool_specs("s1", "epoch-1", [_tool("read_file")])
    names = frozen_tool_names("s1", "epoch-1")
    assert frozen_tool_block_message(
        "read_file", frozen_names=names, current_names={"read_file"}
    ) is None


def test_unknown_tool_is_left_to_existing_handling() -> None:
    freeze_tool_specs("s1", "epoch-1", [_tool("read_file")])
    names = frozen_tool_names("s1", "epoch-1")
    assert frozen_tool_block_message(
        "not_a_real_tool", frozen_names=names, current_names={"read_file"}
    ) is None
