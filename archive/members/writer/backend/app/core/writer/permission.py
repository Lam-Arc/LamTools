from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from lamtools_core.tool.approval import (
    ApprovalGate,
    CommandApprovalPolicy,
    CommandPermissionDecision,
    CommandPermissionGroup,
    DEFAULT_BLOCKED_FILE_PATTERNS,
    DEFAULT_COMMAND_POLICIES,
    classify_command,
    command_permission_decision,
    normalize_command_policies as _normalize_command_policies,
)
from lamtools_core.tool.permission import AUTO_ALLOW, ASK_USER, HARD_BLOCK, PermissionTier

from .schemas import WriterAction
from .tool_specs import WRITER_TOOL_PERMISSIONS

# --- Permission Tiers ---
# auto_allow: No user confirmation needed (read-only, low-risk)
# ask_user: Requires user confirmation (writes, high-risk commands)
# hard_block: Tool is unavailable, not a command blacklist

# --- Tool Permission Mapping ---

# Keep permissions sourced from tool_specs.py.  This prevents the previous
# duplicate table from drifting away from the declarative tool contract.
TOOL_PERMISSIONS: dict[str, PermissionTier] = dict(WRITER_TOOL_PERMISSIONS)


def split_command_for_path_validation(command: str) -> list[str]:
    """Split a command for validation while preserving Windows shell behavior."""
    try:
        return shlex.split(command, posix=False)
    except ValueError:
        return command.split()

# --- Blocked File Patterns ---

BLOCKED_FILE_PATTERNS: list[str] = list(DEFAULT_BLOCKED_FILE_PATTERNS)


class PermissionChecker:
    """Permission checker for Writer actions."""

    def __init__(self, work_root: str, auto_approve_read: bool = True):
        self.work_root = Path(work_root).resolve()
        self.auto_approve_read = auto_approve_read
        self._gate = ApprovalGate(
            work_root=self.work_root,
            tool_permissions=TOOL_PERMISSIONS,
            auto_approve_read=auto_approve_read,
            blocked_file_patterns=tuple(BLOCKED_FILE_PATTERNS),
        )

    def check(self, action: WriterAction) -> tuple[bool, str]:
        """Check if an action is allowed.

        Returns (allowed, reason) where allowed is True if the action
        can proceed, False if it needs confirmation or cannot pass bounds checks.
        """
        decision = self._gate.check(action.action_type, action.params)
        return (decision.allowed, decision.reason)

    def _check_hard_blocks(self, action: WriterAction) -> str:
        """Check sensitive file targets that must not be touched through Writer."""
        return self._gate._check_hard_blocks(action.action_type, action.params)

    def _check_path_bounds(self, params: dict[str, Any]) -> str:
        """Check that file operations stay within work_root."""
        return self._gate._check_path_bounds(params)
