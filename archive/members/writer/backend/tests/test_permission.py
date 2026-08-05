"""Tests for PermissionChecker."""

from app.core.writer.permission import PermissionChecker
from app.core.writer.schemas import WriterAction


class TestPermissionChecker:
    @property
    def checker(self):
        return PermissionChecker(work_root="C:/safe_workspace")

    def test_auto_allow_read_file(self):
        action = WriterAction(action_type="read_file")
        allowed, reason = self.checker.check(action)
        assert allowed is True
        assert "Auto-approved" in reason

    def test_auto_allow_search_content(self):
        action = WriterAction(action_type="search_content")
        allowed, _ = self.checker.check(action)
        assert allowed is True

    def test_auto_allow_search_files(self):
        action = WriterAction(action_type="search_files")
        allowed, _ = self.checker.check(action)
        assert allowed is True

    def test_auto_allow_git_status(self):
        action = WriterAction(action_type="git_status")
        allowed, _ = self.checker.check(action)
        assert allowed is True

    def test_auto_allow_git_diff(self):
        action = WriterAction(action_type="git_diff")
        allowed, _ = self.checker.check(action)
        assert allowed is True

    def test_auto_allow_chat_only(self):
        action = WriterAction(action_type="chat_only")
        allowed, _ = self.checker.check(action)
        assert allowed is True

    def test_write_file_requires_user_confirmation(self):
        action = WriterAction(action_type="write_file")
        allowed, reason = self.checker.check(action)
        assert allowed is False
        assert "requires user confirmation" in reason

    def test_edit_file_requires_user_confirmation(self):
        action = WriterAction(action_type="edit_file")
        allowed, reason = self.checker.check(action)
        assert allowed is False
        assert "requires user confirmation" in reason

    def test_regular_run_command_allowed_by_default(self):
        action = WriterAction(
            action_type="run_command",
            params={"command": "echo hello"},
        )
        allowed, reason = self.checker.check(action)
        assert allowed is True
        assert "Auto-approved regular command" in reason

    def test_write_file_outside_work_root(self):
        action = WriterAction(
            action_type="write_file",
            params={"path": "C:/outside/file.txt"},
        )
        allowed, reason = self.checker.check(action)
        assert allowed is False
        assert "outside work_root" in reason

    def test_write_file_path_traversal(self):
        action = WriterAction(
            action_type="write_file",
            params={"path": "../../etc/passwd"},
        )
        allowed, reason = self.checker.check(action)
        assert allowed is False
        assert "outside work_root" in reason

    def test_write_file_inside_work_root(self):
        action = WriterAction(
            action_type="write_file",
            params={"path": "subdir/file.txt"},
        )
        allowed, reason = self.checker.check(action)
        assert allowed is False
        assert "requires user confirmation" in reason

    def test_read_file_inside_work_root(self):
        action = WriterAction(
            action_type="read_file",
            params={"path": "subdir/file.txt"},
        )
        allowed, _ = self.checker.check(action)
        assert allowed is True

    def test_read_file_outside_work_root(self):
        action = WriterAction(
            action_type="read_file",
            params={"path": "C:/outside/secret.txt"},
        )
        allowed, reason = self.checker.check(action)
        assert allowed is False
        assert "outside work_root" in reason

    def test_unknown_action_hard_blocked(self):
        # Use model_construct to bypass Literal validation
        action = WriterAction.model_construct(action_type="dangerous_operation")
        allowed, reason = self.checker.check(action)
        assert allowed is False
        assert "hard-blocked" in reason

    def test_sensitive_file_pattern_env(self):
        action = WriterAction(
            action_type="write_file",
            params={"path": ".env"},
        )
        allowed, reason = self.checker.check(action)
        assert allowed is False
        assert "sensitive pattern" in reason

    def test_sensitive_file_pattern_git_config(self):
        action = WriterAction(
            action_type="edit_file",
            params={"path": ".git/config"},
        )
        allowed, reason = self.checker.check(action)
        assert allowed is False
        assert "sensitive pattern" in reason

    def test_sensitive_file_pattern_ssh_key(self):
        action = WriterAction(
            action_type="write_file",
            params={"path": "id_rsa"},
        )
        allowed, reason = self.checker.check(action)
        assert allowed is False
        assert "sensitive pattern" in reason

    def test_dangerous_command_shutdown_requires_confirmation(self):
        action = WriterAction(
            action_type="run_command",
            params={"command": "shutdown /s"},
        )
        allowed, reason = self.checker.check(action)
        assert allowed is False
        assert "高危命令需要运行前确认" in reason

    def test_dangerous_command_rm_rf_requires_confirmation(self):
        action = WriterAction(
            action_type="run_command",
            params={"command": "rm -rf /"},
        )
        allowed, reason = self.checker.check(action)
        assert allowed is False
        assert "高危命令需要运行前确认" in reason

    def test_safe_command_allowed(self):
        action = WriterAction(
            action_type="run_command",
            params={"command": "echo hello"},
        )
        allowed, _ = self.checker.check(action)
        assert allowed is True

    def test_write_file_empty_path_still_requires_user_confirmation(self):
        action = WriterAction(
            action_type="write_file",
            params={"path": ""},
        )
        allowed, reason = self.checker.check(action)
        # Empty path passes path bounds check but still needs the write approval gate.
        assert allowed is False
        assert "requires user confirmation" in reason
