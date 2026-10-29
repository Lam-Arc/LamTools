from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
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
    from lamtools_core.plugin_system.jsonc import load_jsonc_text

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
    #: The decision asks about reaching outside the workspace.  Such a request
    #: is never settled by a preset alone (see ``CoreToolbox.prepare_call``);
    #: once the user approves it, the call receives a one-shot grant.
    outside_workdir: bool = False
    #: True when the session's automatic preset settled this call.  The gate
    #: records it so callers can keep the audit marker without re-deciding
    #: whether the preset applies.
    auto_approved: bool = False
    #: Command confirmation remains in automatic mode; explicit full access
    #: settles it together with other approval requests.
    command_confirmation: bool = False
    level: int = 0
    auto_approve_level: int = 1
    available_level: int = 3


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
        permission_preset: str = "ask",
        manifest_tool_permissions: dict[str, PermissionTier] | None = None,
        manifest_hard_block_tools: set[str] | None = None,
        resource_roots: Callable[[], Iterable[Path]] | Iterable[Path] | None = None,
        plugin_approval: str | None = None,
        operation_levels: dict[str, int] | None = None,
        auto_approve_level: int | None = None,
        available_level: int | None = None,
        mcp_operation_level: Callable[[str], int] | None = None,
        mcp_call_level: Callable[[str, dict[str, Any]], int] | None = None,
        mcp_approved_tools: Iterable[str] | None = None,
        trust_store: Any | None = None,
    ) -> None:
        from .operation_trust import OperationTrustStore
        self.trust_store = trust_store or OperationTrustStore()
        self.operation_levels = dict(operation_levels or {})
        # user:“宿主能力补齐和接口完善与文档更新”+(动态工具提供等级默认值，显式用户等级覆盖仍是同一审批权威)。
        self.declared_operation_levels: dict[str, int] = {}
        self.auto_approve_level = auto_approve_level
        self.available_level = available_level
        self.mcp_operation_level = mcp_operation_level
        self.mcp_call_level = mcp_call_level
        # user:“值守的时候…有什么办法能开放吗”+(运行档只精确放行指定的
        # MCP 写工具；不降低目标工具的等级，也不越过能力上限)。
        self.mcp_approved_tools = set(mcp_approved_tools or ())
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
        self.permission_preset = permission_preset
        self.manifest_tool_permissions = dict(manifest_tool_permissions or {})
        self.manifest_hard_block_tools = set(manifest_hard_block_tools or set())
        self.resource_roots = resource_roots
        # user:“插件可以自定义整个 Agent”+审批策略也由当前生效的插件 Agent
        # 声明接管：ask 保持现状，auto 免去确认，block 拒绝需要确认的调用。
        # 它只作用于“要问用户”的那一类调用，硬边界和敏感路径拦截不因此放开。
        self.plugin_approval = (
            plugin_approval if plugin_approval in {"ask", "auto", "block"} else None
        )

    def allowed_roots(self) -> tuple[Path, ...]:
        """Workspace plus caller-provided resource roots (loaded skill folders).

        A skill's own directory is inside the agent's granted scope by virtue of
        loading it, so its assets are not a consent question.
        """
        roots = self.resource_roots
        if roots is None:
            return (self.work_root,)
        if callable(roots):
            try:
                values = roots()
            except Exception:  # noqa: BLE001 - a broken provider must not widen access
                return (self.work_root,)
        else:
            values = roots
        extra: list[Path] = []
        for item in values or ():
            try:
                extra.append(Path(item).resolve())
            except (TypeError, ValueError, OSError):
                continue
        return (self.work_root, *extra)

    def check(self, tool_name: str, params: dict[str, Any] | None = None) -> ToolApprovalDecision:
        # user:“工具权限是改成 123 级，不一棒子按工具类型打死了”+(硬拦截后按操作等级、能力上限、免问线依次判断)。
        from .operation_levels import AUTO_APPROVE_LEVELS, CAPABILITY_LEVELS, operation_level, valid_level
        params = params or {}
        threshold = self.auto_approve_level
        if threshold is None:
            preset = self.permission_preset
            threshold = AUTO_APPROVE_LEVELS.get(preset, 1)
        if self.plugin_approval == "auto":
            threshold = max(threshold, 2)
        cap = self.available_level if self.available_level is not None else CAPABILITY_LEVELS.get(self.active_tier, 3)
        if self.plugin_approval == "block":
            cap = min(cap, threshold)
        hard = (tool_name in self.manifest_hard_block_tools
                or self.manifest_tool_permissions.get(tool_name) == HARD_BLOCK
                or self.tool_permissions.get(tool_name) == HARD_BLOCK)
        reason = self._check_hard_blocks(tool_name, params)
        if hard or reason:
            return ToolApprovalDecision(False, reason or f"Tool '{tool_name}' is hard-blocked", HARD_BLOCK,
                                        blocked=True, level=0, auto_approve_level=threshold, available_level=cap)
        try:
            level = operation_level(tool_name, params, levels={**self.declared_operation_levels, **self.operation_levels},
                                    mcp_level=self.mcp_operation_level,
                                    mcp_call_level=self.mcp_call_level)
            if not valid_level(level):
                raise ValueError("Operation level must be a non-negative integer")
        except ValueError as exc:
            return ToolApprovalDecision(False, str(exc), HARD_BLOCK, blocked=True,
                                        level=0, auto_approve_level=threshold, available_level=cap)
        mcp_target = ""
        if tool_name == "mcp" and str(params.get("action") or "") == "run":
            mcp_target = str(params.get("tool_name") or "")
        # Trust and approval are keyed by the target MCP tool, never by the
        # generic ``mcp`` entry tool: trusting ``mcp`` would trust every server.
        key = self._trust_key(tool_name, params)
        level = self.trust_store.level(key, level)
        approved_mcp = bool(mcp_target and mcp_target in self.mcp_approved_tools)
        blocked = level == 0 or level > cap
        ask = not blocked and not approved_mcp and level > threshold
        allowed = not blocked and not ask
        reason = (f"操作等级 {level} 超过当前能力上限 {cap}" if blocked else
                  f"操作等级 {level}，运行档已授权" if approved_mcp else
                  f"操作等级 {level} 超过免问线 {threshold}，需要确认" if ask else f"操作等级 {level}，自动放行")
        return ToolApprovalDecision(allowed, reason, HARD_BLOCK if blocked else ASK_USER if ask else AUTO_ALLOW,
                                    requires_approval=ask, blocked=blocked, auto_approved=allowed,
                                    command_confirmation=ask and tool_name in {"run_command", "command"},
                                    level=level, auto_approve_level=threshold, available_level=cap)

    def trust_operation(self, tool_name: str, params: dict[str, Any]) -> int:
        decision = self.check(tool_name, params)
        if decision.blocked or decision.level == 0:
            raise ValueError("Hard-blocked or unavailable operations cannot be trusted")
        key = self._trust_key(tool_name, params)
        return self.trust_store.lower(key, decision.level)

    def _trust_key(self, tool_name: str, params: dict[str, Any]) -> str:
        # user:“该修修 如果是架构问题就重构”+(信任写入与检查共用目标标识，只授权所选 MCP 工具)。
        target = str(params.get("tool_name") or "").strip() if tool_name == "mcp" and params.get("action") == "run" else tool_name
        return self.trust_store.selector(self.work_root, target or tool_name, params)

    def _check_hard_blocks(self, tool_name: str, params: dict[str, Any]) -> str:
        if tool_name in {"write_file", "edit_file"}:
            path = str(params.get("path", "")).casefold()
            for pattern in self.blocked_file_patterns:
                if pattern.casefold() in path:
                    return f"Blocked: path contains sensitive pattern '{pattern}'"
        return ""


class PermissionResolver:
    """Single owner of a gate's mutable live-permission inputs.

    ``ApprovalGate.check`` owns the precedence table (manifest hard block,
    capability tier, destructive path/command rules, manifest tier, preset).
    This class owns the only place a runtime snapshot may change those inputs:
    the toolbox refresh, kernel re-preparation and approval continuation all
    call :meth:`apply_snapshot` instead of assigning gate fields themselves.
    """

    def __init__(self, gate: ApprovalGate) -> None:
        self.gate = gate

    def apply_snapshot(self, value: object) -> bool:
        """Apply one live runtime snapshot; invalid fields are ignored.

        Returns ``True`` when any input changed, so callers can mirror the
        effective values without re-implementing the validation rules.
        """
        if not isinstance(value, Mapping):
            return False
        from lamtools_core.app.runtime_permissions import normalize_tier_tools

        changed = False
        preset = value.get("permission_preset")
        if preset in {"ask", "auto", "full_access"} and self.gate.permission_preset != preset:
            self.gate.permission_preset = preset
            changed = True
        policy = value.get("approval_policy")
        if policy in {"require", "auto_approve"} and self.gate.approval_policy != policy:
            self.gate.approval_policy = policy  # type: ignore[assignment]
            changed = True
        tier = value.get("active_tier")
        if tier in {"read_only", "limited_edit", "full_edit"} and self.gate.active_tier != tier:
            self.gate.active_tier = tier  # type: ignore[assignment]
            changed = True
        raw_tier_tools = value.get("tier_tools")
        if isinstance(raw_tier_tools, Mapping):
            tier_tools = normalize_tier_tools(raw_tier_tools)
            if tier_tools != self.gate.tier_tools:
                self.gate.tier_tools = tier_tools
                changed = True
        outside = value.get("allow_access_outside_workdir")
        if isinstance(outside, bool) and self.gate.allow_access_outside_workdir != outside:
            self.gate.allow_access_outside_workdir = outside
            changed = True
        return changed

    def resolve(
        self, tool_name: str, params: dict[str, Any] | None = None
    ) -> ToolApprovalDecision:
        return self.gate.check(tool_name, params)
