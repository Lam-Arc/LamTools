from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from lamtools_core.tool.permission import AUTO_ALLOW, ASK_USER, HARD_BLOCK, PermissionTier

CommandPermissionGroup = Literal["regular", "dangerous"]
CommandApprovalPolicy = Literal["auto_allow", "ask_user"]
PermissionMode = Literal["read_only", "limited_edit", "full_edit"]
RuntimeApprovalPolicy = Literal["require", "auto_approve"]

DANGEROUS_COMMAND_RE = re.compile(
    r"(?ix)"
    r"(^|[;&|]\s*|\s)"
    r"("
    r"rm|rmdir|del|erase|move|mv|rename|ren|"
    r"remove-item|clear-item|move-item|rename-item|"
    r"git\s+(reset|clean|checkout|restore|rebase)|"
    r"mkfs|dd|shutdown|reboot|format|"
    r"chmod|chown|takeown|icacls|reg\s+(delete|add)|"
    r"powershell\s+.*\bremove-item\b|"
    r"pwsh\s+.*\bremove-item\b"
    r")\b"
)

# Shell structure features that defeat static path validation.  ``~`` and
# ``$VAR`` expand outside the work root, command substitution / backticks run
# nested commands, escaped/quoted command names hide the real binary, and
# interpreter ``-c`` arguments are opaque code.  Commands containing any of
# these are classified dangerous and are never auto-allowed, regardless of
# configured command policies (audit 06 S1: ``\rm``, ``$(rm -rf /)``,
# ``cat ~/.ssh/id_rsa``, ``python -c ...`` all bypassed the old heuristic).
SHELL_STRUCTURE_RE = re.compile(
    r"(?ix)"
    r"((^|[;&|]\s*|\s)~[\w./\\-]*)"            # tilde expansion
    r"|(\$\()"                                 # command substitution $(
    r"|(\$\{)"                                 # parameter expansion ${
    r"|(\$[A-Za-z_][A-Za-z0-9_]*)"             # parameter expansion $VAR
    r"|(`)"                                    # backtick substitution
    r"|((^|[;&|]\s*)\\(rm|rmdir|del|erase|format|mkfs|dd|shutdown|reboot|remove-item|move-item|rename-item|clear-item)\b)"  # escaped dangerous name
    r"|((^|[;&|]\s*)[\"'](rm|rmdir|del|erase|format|mkfs|dd|shutdown|reboot|remove-item|move-item|rename-item|clear-item)[\"'])"  # quoted dangerous name
    r"|(\b(python|python3|py|bash|sh|pwsh|powershell|cmd)(\s+(-c|/c))\b)"  # interpreter -c code argument
)

DEFAULT_COMMAND_POLICIES: dict[CommandPermissionGroup, CommandApprovalPolicy] = {
    "regular": "auto_allow",
    "dangerous": "ask_user",
}

TierTools = dict[PermissionMode, set[str]]


def load_access_tools(path: Path | str) -> TierTools:
    """Load access_tools.jsonc and return {tier: set of auto-allowed tool names}."""
    tier_tools: TierTools = {"read_only": set(), "limited_edit": set(), "full_edit": set()}
    # 文件名叫 .jsonc、随包副本也带注释：严格 json.loads 会把整份 tier 静默
    # 清空（所有工具降级为需审批），2026-09-25 审计 P3。
    from lamtools_core.plugins._jsonc import load_jsonc_text

    try:
        data = load_jsonc_text(path)
    except (OSError, ValueError):
        return tier_tools
    tiers = data.get("tiers") if isinstance(data, dict) else None
    if not isinstance(tiers, dict):
        return tier_tools
    for tier_name in ("read_only", "limited_edit", "full_edit"):
        tier_data = tiers.get(tier_name)
        if not isinstance(tier_data, dict):
            continue
        access = tier_data.get("access")
        if isinstance(access, list):
            tier_tools[tier_name] = {str(item) for item in access if isinstance(item, str) and str(item).strip()}
    return tier_tools

DEFAULT_BLOCKED_FILE_PATTERNS: tuple[str, ...] = (
    ".env",
    ".git/config",
    "id_rsa",
    "id_ed25519",
    ".ssh/",
    "credentials",
    ".aws/",
)


@dataclass(frozen=True)
class CommandPermissionDecision:
    group: CommandPermissionGroup
    policy: CommandApprovalPolicy
    requires_approval: bool
    reason: str = ""


@dataclass(frozen=True)
class ToolApprovalDecision:
    allowed: bool
    reason: str
    permission_tier: PermissionTier
    requires_approval: bool = False
    blocked: bool = False


def normalize_command_policies(raw: dict[str, object] | None) -> dict[CommandPermissionGroup, CommandApprovalPolicy]:
    policies = dict(DEFAULT_COMMAND_POLICIES)
    if not isinstance(raw, dict):
        return policies
    for group in ("regular", "dangerous"):
        value = raw.get(group)
        if value in {"auto_allow", "ask_user"}:
            policies[group] = value  # type: ignore[assignment]
    return policies


def classify_command(command: str) -> CommandPermissionGroup:
    command_lower = command.lower().strip()
    if not command_lower:
        return "regular"
    if DANGEROUS_COMMAND_RE.search(command_lower) or SHELL_STRUCTURE_RE.search(command_lower):
        return "dangerous"
    return "regular"


def command_permission_decision(
    command: str,
    raw_policies: dict[str, object] | None = None,
) -> CommandPermissionDecision:
    group = classify_command(command)
    policies = normalize_command_policies(raw_policies)
    policy = policies[group]
    if group == "dangerous" and SHELL_STRUCTURE_RE.search(command.lower()):
        # Shell structure features (expansion, substitution, ``-c`` code)
        # cannot be statically validated — never auto-allowed even when the
        # dangerous-group policy is configured to ``auto_allow``.
        policy = "ask_user"
    return CommandPermissionDecision(
        group=group,
        policy=policy,
        requires_approval=policy == "ask_user",
        reason="高危命令需要运行前确认" if group == "dangerous" and policy == "ask_user" else "",
    )


class ApprovalGate:
    def __init__(
        self,
        *,
        work_root: Path | str,
        tool_permissions: dict[str, PermissionTier],
        auto_approve_read: bool = True,
        blocked_file_patterns: tuple[str, ...] = DEFAULT_BLOCKED_FILE_PATTERNS,
        command_policies: dict[str, object] | None = None,
        active_tier: PermissionMode | None = None,
        tier_tools: TierTools | None = None,
        allow_access_outside_workdir: bool = False,
        approval_policy: RuntimeApprovalPolicy | None = None,
        manifest_tool_permissions: dict[str, PermissionTier] | None = None,
        manifest_hard_block_tools: set[str] | None = None,
    ) -> None:
        self.work_root = Path(work_root).resolve()
        self.tool_permissions = dict(tool_permissions)
        self.auto_approve_read = auto_approve_read
        self.blocked_file_patterns = blocked_file_patterns
        self.command_policies = normalize_command_policies(command_policies)
        self.active_tier = active_tier
        # ``None`` means the legacy caller did not provide a capability map.
        # An explicit empty map is meaningful: ``full_edit`` uses an empty
        # access list as its all-tools capability, while a restricted tier
        # with an empty list exposes no tools.
        self.tier_tools = tier_tools
        self.allow_access_outside_workdir = allow_access_outside_workdir
        self.approval_policy = approval_policy
        self.manifest_tool_permissions = dict(manifest_tool_permissions or {})
        self.manifest_hard_block_tools = set(manifest_hard_block_tools or set())

    def check(self, tool_name: str, params: dict[str, Any] | None = None) -> ToolApprovalDecision:
        params = params or {}
        if tool_name in self.manifest_hard_block_tools:
            return ToolApprovalDecision(
                False,
                f"Tool '{tool_name}' is hard-blocked by its manifest",
                HARD_BLOCK,
                blocked=True,
            )

        # A manifest declaration is a higher-precedence source than user
        # overrides/defaults.  This is intentionally resolved here as well as
        # in CoreToolbox so direct ApprovalGate users get the same boundary.
        base_tier = self.manifest_tool_permissions.get(
            tool_name,
            self.tool_permissions.get(tool_name, HARD_BLOCK),
        )
        if base_tier == HARD_BLOCK:
            return ToolApprovalDecision(False, f"Action '{tool_name}' is hard-blocked", base_tier, blocked=True)

        block_reason = self._check_hard_blocks(tool_name, params)
        if block_reason:
            return ToolApprovalDecision(False, block_reason, base_tier, blocked=True)

        # Workdir bounds check is bypassed when the user allows access outside
        # work_root (settings core.runtimeControls.allow_access_outside_workdir);
        # sensitive-pattern hard blocks above still apply.
        if tool_name in {"read_file", "write_file", "edit_file"} and not self.allow_access_outside_workdir:
            path_check = self._check_path_bounds(params)
            if path_check:
                return ToolApprovalDecision(False, path_check, base_tier, blocked=True)

        # Capability/tier access is a hard boundary.  It is evaluated before
        # manifest approval and before the Composer approval preset.  A
        # full_edit empty list is the documented all-tools sentinel; for
        # read_only/limited_edit an empty list grants nothing.
        if self.active_tier is not None and self.tier_tools is not None:
            access_set = self.tier_tools.get(self.active_tier, set())
            tier_allows = self.active_tier == "full_edit" and not access_set
            if not tier_allows and tool_name not in access_set:
                return ToolApprovalDecision(
                    False,
                    f"Action '{tool_name}' is outside the {self.active_tier} capability tier",
                    base_tier,
                    blocked=True,
                )

        if tool_name == "run_command":
            command = params.get("command", "")
            if isinstance(command, str) and command.strip():
                decision = command_permission_decision(command, self.command_policies)
                if decision.requires_approval:
                    return ToolApprovalDecision(
                        False,
                        decision.reason or "Command requires user confirmation",
                        base_tier,
                        requires_approval=True,
                    )
                if base_tier == AUTO_ALLOW:
                    return ToolApprovalDecision(True, f"Auto-approved {decision.group} command", base_tier)

        if self.auto_approve_read and base_tier == AUTO_ALLOW:
            return ToolApprovalDecision(True, "Auto-approved (read-only)", base_tier)

        if base_tier == ASK_USER:
            if self.approval_policy == "auto_approve":
                return ToolApprovalDecision(True, "Auto-approved by permission preset", base_tier)
            return ToolApprovalDecision(
                False,
                f"Action '{tool_name}' requires user confirmation",
                base_tier,
                requires_approval=True,
            )

        return ToolApprovalDecision(False, f"Action '{tool_name}' is hard-blocked", base_tier, blocked=True)

    def _check_hard_blocks(self, tool_name: str, params: dict[str, Any]) -> str:
        if tool_name in {"write_file", "edit_file"}:
            path = str(params.get("path", "")).casefold()
            for pattern in self.blocked_file_patterns:
                if pattern.casefold() in path:
                    return f"Blocked: path contains sensitive pattern '{pattern}'"
        return ""

    def _check_path_bounds(self, params: dict[str, Any]) -> str:
        path = params.get("path", "")
        if not path:
            return ""
        try:
            resolved = (self.work_root / str(path)).resolve()
            if resolved.is_relative_to(self.work_root):
                return ""
            return f"Blocked: path '{path}' is outside work_root '{self.work_root}'"
        except (ValueError, OSError):
            return f"Blocked: invalid path '{path}'"
