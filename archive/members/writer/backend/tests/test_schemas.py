"""Tests for WriterTurn, WriterAction, WriterPart, WriterSessionState schemas."""

from typing import get_args

import pytest
from pydantic import ValidationError

from app.core.writer.schemas import (
    WriterAction,
    WriterActionType,
    WriterPart,
    WriterSessionState,
    WriterTurn,
    WriterArtifact,
    WriterToolResult,
    WriterOutputType,
)
from app.core.writer.permission import TOOL_PERMISSIONS


class TestWriterTurn:
    def test_creation_with_defaults(self):
        turn = WriterTurn()
        assert turn.text == ""
        assert turn.actions == []
        assert turn.parts == []
        assert turn.phase == "idle"
        assert turn.mode == "EXECUTE"
        assert turn.is_complete is False
        assert turn.self_critique is None
        assert turn.next_phase is None

    def test_with_actions(self):
        action = WriterAction(action_type="read_file")
        turn = WriterTurn(text="reading file", actions=[action])
        assert len(turn.actions) == 1
        assert turn.actions[0].action_type == "read_file"
        assert turn.text == "reading file"

    def test_with_multiple_actions(self):
        actions = [
            WriterAction(action_type="read_file"),
            WriterAction(action_type="write_file"),
        ]
        turn = WriterTurn(actions=actions)
        assert len(turn.actions) == 2
        assert turn.actions[0].action_type == "read_file"
        assert turn.actions[1].action_type == "write_file"

    def test_with_parts(self):
        part = WriterPart(part_type="text", content="hello")
        turn = WriterTurn(parts=[part])
        assert len(turn.parts) == 1
        assert turn.parts[0].part_type == "text"

    def test_phase_and_mode(self):
        turn = WriterTurn(phase="executing", mode="EXECUTE")
        assert turn.phase == "executing"
        assert turn.mode == "EXECUTE"

    def test_is_complete_and_next_phase(self):
        turn = WriterTurn(is_complete=True, next_phase="verifying")
        assert turn.is_complete is True
        assert turn.next_phase == "verifying"

    def test_self_critique_field(self):
        turn = WriterTurn(self_critique="could improve naming")
        assert turn.self_critique == "could improve naming"

    def test_output_type_default(self):
        turn = WriterTurn()
        assert turn.output_type == "text"

    def test_output_type_explicit(self):
        turn = WriterTurn(output_type="email")
        assert turn.output_type == "email"

    def test_output_meta_default(self):
        turn = WriterTurn()
        assert turn.output_meta == {}

    def test_output_meta_explicit(self):
        turn = WriterTurn(output_meta={"subject": "Test", "format": "html"})
        assert turn.output_meta == {"subject": "Test", "format": "html"}

    def test_output_type_all_valid_values(self):
        valid_types = ["text", "email", "document", "code", "report", "outline"]
        for ot in valid_types:
            turn = WriterTurn(output_type=ot)
            assert turn.output_type == ot


class TestWriterAction:
    def test_creation_with_required_fields(self):
        action = WriterAction(action_type="read_file")
        assert action.action_type == "read_file"
        assert action.description == ""
        assert action.params == {}
        assert action.permission_tier == "ask_user"
        assert action.approved is None

    def test_with_params(self):
        action = WriterAction(
            action_type="write_file",
            params={"path": "/tmp/test.txt", "content": "hello"},
        )
        assert action.params["path"] == "/tmp/test.txt"
        assert action.params["content"] == "hello"

    def test_permission_tier_override(self):
        action = WriterAction(action_type="write_file", permission_tier="hard_block")
        assert action.permission_tier == "hard_block"

    def test_approved_flag(self):
        action = WriterAction(action_type="read_file", approved=True)
        assert action.approved is True

        action = WriterAction(action_type="write_file", approved=False)
        assert action.approved is False

    def test_missing_action_type_raises(self):
        with pytest.raises(ValidationError):
            WriterAction()  # action_type is required

    def test_agent_tool_action_types_exist(self):
        assert "architecture_agent" not in get_args(WriterActionType)
        assert "sub_agent" in get_args(WriterActionType)
        action = WriterAction(action_type="sub_agent", params={"task": "审查实现"})
        assert action.action_type == "sub_agent"

    def test_recall_session_action_type_exists(self):
        assert "recall_session" in get_args(WriterActionType)
        action = WriterAction(action_type="recall_session", params={"path": "backend/app/core/writer/runtime.py"})
        assert action.action_type == "recall_session"

    def test_agent_tools_are_auto_allowed(self):
        assert "architecture_agent" not in TOOL_PERMISSIONS
        assert TOOL_PERMISSIONS["sub_agent"] == "auto_allow"

    def test_recall_session_is_auto_allowed(self):
        assert TOOL_PERMISSIONS["recall_session"] == "auto_allow"


class TestWriterPart:
    def test_creation_with_defaults(self):
        part = WriterPart(part_type="text")
        assert part.part_type == "text"
        assert part.status == "pending"
        assert part.content == ""
        assert part.metadata == {}
        assert part.tool_name is None
        assert part.tool_args is None
        assert part.tool_result is None
        assert part.tool_error is None
        assert part.started_at is None
        assert part.completed_at is None

    def test_state_machine_transitions(self):
        part = WriterPart(part_type="text")
        assert part.status == "pending"

        part.status = "running"
        assert part.status == "running"

        part.status = "completed"
        assert part.status == "completed"

    def test_error_state(self):
        part = WriterPart(part_type="tool_call", status="error", tool_error="file not found")
        assert part.status == "error"
        assert part.tool_error == "file not found"

    def test_tool_call_part(self):
        part = WriterPart(
            part_type="tool_call",
            tool_name="read_file",
            tool_args={"path": "/tmp/test.txt"},
        )
        assert part.tool_name == "read_file"
        assert part.tool_args == {"path": "/tmp/test.txt"}

    def test_tool_result_part(self):
        part = WriterPart(
            part_type="tool_result",
            tool_result="file contents here",
            status="completed",
        )
        assert part.tool_result == "file contents here"
        assert part.status == "completed"

    def test_missing_part_type_raises(self):
        with pytest.raises(ValidationError):
            WriterPart()  # part_type is required

    def test_timing_fields(self):
        from datetime import datetime

        now = datetime.now()
        part = WriterPart(part_type="text", started_at=now, completed_at=now)
        assert part.started_at == now
        assert part.completed_at == now


class TestWriterSessionState:
    def test_creation_with_required_fields(self):
        state = WriterSessionState(session_id="test-session-1")
        assert state.session_id == "test-session-1"
        assert state.work_root == ""
        assert state.branch is None
        assert state.phase == "idle"
        assert state.mode == "EXECUTE"
        assert state.todos == []
        assert state.open_loops == []
        assert state.context_summary == ""
        assert state.turn_count == 0
        assert state.error_count == 0
        assert state.last_action_type is None
        assert state.git_state == {}
        assert state.git_history == []
        assert state.session_memory == {}

    def test_todos_as_list_of_dicts(self):
        state = WriterSessionState(
            session_id="test-session-2",
            todos=[
                {"id": "1", "content": "write tests", "status": "in_progress"},
                {"id": "2", "content": "run tests", "status": "pending"},
            ],
        )
        assert len(state.todos) == 2
        assert state.todos[0]["status"] == "in_progress"
        assert state.todos[1]["content"] == "run tests"

    def test_with_work_root_and_branch(self):
        state = WriterSessionState(
            session_id="test-session-3",
            work_root="/home/user/project",
            branch="writer/feature/test",
        )
        assert state.work_root == "/home/user/project"
        assert state.branch == "writer/feature/test"

    def test_turn_count_increment(self):
        state = WriterSessionState(session_id="test-session-4")
        assert state.turn_count == 0
        state.turn_count = 5
        assert state.turn_count == 5

    def test_error_count_tracking(self):
        state = WriterSessionState(session_id="test-session-5")
        assert state.error_count == 0
        state.error_count = 3
        assert state.error_count == 3

    def test_missing_session_id_raises(self):
        with pytest.raises(ValidationError):
            WriterSessionState()  # session_id is required

    def test_created_at_and_updated_at(self):
        state = WriterSessionState(session_id="test-session-6")
        assert state.created_at is not None
        assert state.updated_at is not None


class TestWriterOutputType:
    """Tests for WriterOutputType Literal type and WriterTurn output fields."""

    def test_output_type_literal_exists(self):
        """WriterOutputType should be importable and contain expected values."""
        assert WriterOutputType is not None

    def test_output_type_default_on_empty_turn(self):
        turn = WriterTurn()
        assert turn.output_type == "text"
        assert turn.output_meta == {}

    def test_output_type_persisted_in_model_dump(self):
        turn = WriterTurn(output_type="report", output_meta={"sections": 3})
        dumped = turn.model_dump()
        assert dumped["output_type"] == "report"
        assert dumped["output_meta"] == {"sections": 3}
