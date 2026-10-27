"""运行档（Run Profile）：命名的运行约束，宿主强制执行。

user:“给拉起的会话完整定义任意工具面与运行档是第一类缺口”+清单声明
`profiles` 段（工具白名单、审批策略、模型场景、预算），宿主按声明强制：
白名单内的调用在无人值守轮自动放行，白名单外一律拒绝并记录；预算超限终止。
对齐 DSH 的 profile 能力（命名上下文选工具面与审批），但不复制它的
按 profile 隔离插件安装目录——我们的插件全局安装，跨版本兼容走 engine 声明。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .capabilities import CapabilityError
from .manifest import PluginManifest

VALID_APPROVALS = ("auto", "ask")


class BudgetExhausted(RuntimeError):
    """运行档预算耗尽：终止当前执行循环。"""
    budget_exhausted = True


@dataclass(frozen=True)
class ProfileBudget:
    max_tool_calls: int | None = None
    max_tokens: int | None = None


@dataclass(frozen=True)
class ProfileSpec:
    full_name: str  # "plugin:profile"
    plugin: str
    profile: str
    title: str = ""
    tools: tuple[str, ...] = ()
    approval: str = "auto"  # auto | ask
    model_scene: str = ""  # 空值 = 不覆盖模型
    # 拉起的会话需激活的 MCP 服务器名（如 {"bilibili"}）；白名单里的 MCP
    # 工具只有在其服务器激活后才真的可用。
    mcp_servers: tuple[str, ...] = ()
    budget: ProfileBudget = ProfileBudget()
    mcp_tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    # user:“值守的时候…有什么办法能开放吗”+(只对这里列出的 MCP 工具跳过确认；
    # 目标工具的等级与能力上限照常判断，不能拿它去放行普通工具)。
    approved_tools: tuple[str, ...] = ()


def _positive_int(value: Any, *, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CapabilityError("", f"profile budget {label} must be a positive integer")
    return value


def read_profiles(manifest: PluginManifest) -> dict[str, ProfileSpec]:
    """读清单的 profiles 段：短名 → 规格声明；坏声明按能力错误报出。"""
    raw = manifest.raw.get("profiles")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CapabilityError(manifest.name, "profiles must be an object")
    profiles: dict[str, ProfileSpec] = {}
    for profile_name, body in raw.items():
        short = str(profile_name or "").strip()
        if not short or any(ch.isspace() for ch in short) or ":" in short:
            raise CapabilityError(
                manifest.name, f"profile name must be one token without ':': {short!r}"
            )
        if not isinstance(body, dict):
            raise CapabilityError(manifest.name, f"profile '{short}' must be an object")
        tools_raw = body.get("tools")
        if (
            not isinstance(tools_raw, list)
            or not tools_raw
            or any(not isinstance(item, str) or not item.strip() for item in tools_raw)
        ):
            raise CapabilityError(
                manifest.name,
                f"profile '{short}' requires a non-empty tools array (a profile without a whitelist is meaningless)",
            )
        tools = tuple(str(item).strip() for item in tools_raw)
        approval = str(body.get("approval") or "auto").strip().lower()
        if approval not in VALID_APPROVALS:
            raise CapabilityError(
                manifest.name,
                f"profile '{short}' approval must be one of {', '.join(VALID_APPROVALS)}: {approval}",
            )
        servers_raw = body.get("mcpServers") or body.get("mcp_servers")
        servers = (
            tuple(str(item).strip() for item in servers_raw if str(item).strip())
            if isinstance(servers_raw, list)
            else ()
        )
        budget_raw = body.get("budget") if isinstance(body.get("budget"), dict) else {}
        budget = ProfileBudget(
            max_tool_calls=_positive_int(budget_raw.get("maxToolCalls"), label="maxToolCalls"),
            max_tokens=_positive_int(budget_raw.get("maxTokens"), label="maxTokens"),
        )
        approved_tools = _string_list(body.get("approvedTools"), "approvedTools")
        invalid_approved = [name for name in approved_tools if not name.startswith("mcp__")]
        if invalid_approved:
            raise CapabilityError(
                manifest.name,
                f"profile '{short}' approvedTools entries must be mcp__<server>__<tool>: {', '.join(invalid_approved)}",
            )
        profiles[short] = ProfileSpec(
            full_name=f"{manifest.name}:{short}",
            plugin=manifest.name,
            profile=short,
            title=str(body.get("title") or short).strip() or short,
            tools=tools,
            approval=approval,
            model_scene=str(body.get("modelScene") or "").strip(),
            mcp_servers=servers,
            mcp_tools=_string_list(body.get("mcpTools"), "mcpTools"),
            skills=_string_list(body.get("skills"), "skills"),
            approved_tools=approved_tools,
            budget=budget,
        )
    return profiles


def available_profiles(manifests: list[PluginManifest]) -> list[ProfileSpec]:
    """收集全部启用的运行档；坏声明进错误列表而不是阻断其它插件。"""
    from .capabilities import assemble_capabilities  # noqa: F401  (保持导入面一致)

    specs: list[ProfileSpec] = []
    for manifest in manifests:
        if not manifest.enabled:
            continue
        try:
            specs.extend(read_profiles(manifest).values())
        except CapabilityError:
            continue
    return specs


def resolve_profile(manifests: list[PluginManifest], name: str) -> ProfileSpec:
    """按名字解析运行档：`插件:档名` 精确匹配，短名唯一时可用；否则报出可用清单。"""
    wanted = str(name or "").strip()
    if not wanted:
        raise ValueError("profile name is required")
    specs = available_profiles(manifests)
    exact = [spec for spec in specs if spec.full_name == wanted]
    if exact:
        return exact[0]
    short = [spec for spec in specs if spec.profile == wanted]
    if len(short) == 1:
        return short[0]
    if len(short) > 1:
        names = ", ".join(sorted(spec.full_name for spec in short))
        raise ValueError(f"profile '{wanted}' is ambiguous: {names}")
    available = ", ".join(sorted(spec.full_name for spec in specs)) or "(none declared)"
    raise ValueError(f"profile '{wanted}' not found. available profiles: {available}")


def _string_list(raw: Any, label: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(not isinstance(value, str) or not value.strip() for value in raw):
        raise CapabilityError("", f"profile {label} must be an array of non-empty strings")
    return tuple(value.strip() for value in raw)


class RunBudget:
    """user:“该修修”+(运行预算归单次任务，模型与工具共用同一停止条件)。"""
    def __init__(self, spec: ProfileBudget) -> None:
        self.spec = spec
        self.counters = {"tool_calls": 0, "tokens": 0}

    def check(self) -> None:
        if self.spec.max_tokens is not None and self.counters["tokens"] >= self.spec.max_tokens:
            raise BudgetExhausted(f"运行档 token 预算已耗尽：{self.spec.max_tokens}")

    def record_model_usage(self, usage: Any, *, estimated_tokens: int = 0) -> None:
        self.counters["tokens"] += max(0, int(getattr(usage, "total_tokens", 0) or estimated_tokens))
        self.check()

    def take_tool_call(self) -> None:
        self.check()
        if self.spec.max_tool_calls is not None and self.counters["tool_calls"] >= self.spec.max_tool_calls:
            raise BudgetExhausted(f"运行档工具调用预算已耗尽：{self.spec.max_tool_calls}")
        self.counters["tool_calls"] += 1


def apply_profile(toolbox: Any, spec: ProfileSpec) -> dict[str, int]:
    toolbox.agent_tool_whitelist = set(spec.tools)
    # user:“值守的时候…有什么办法能开放吗”+(只对 approvedTools 里的目标
    # MCP 工具跳过确认；等级与能力上限由 ApprovalGate 照常判断)。
    toolbox.approved_mcp_tools = set(spec.approved_tools)
    gate = getattr(getattr(toolbox, "permission_resolver", None), "gate", None)
    if gate is not None:
        gate.mcp_approved_tools = set(spec.approved_tools)
    if spec.approval == "auto":
        gate = getattr(getattr(toolbox, "permission_resolver", None), "gate", None)
        if gate is not None:
            gate.approval_policy = "auto_approve"
            # user:“auto模式自动通过小于等于2级”+(运行档的 auto 也不能隐式提升成完全访问)。
            from lamtools_core.tool.operation_levels import AUTO_APPROVE_LEVELS
            gate.auto_approve_level = max(2, AUTO_APPROVE_LEVELS.get(getattr(gate, "permission_preset", "ask"), 1))
    budget = RunBudget(spec.budget)
    toolbox.run_budget = budget
    original_execute = toolbox.execute
    service = getattr(toolbox, "mcp_service", None)
    if spec.mcp_tools and service is not None:
        service.allowed_tools = frozenset(spec.mcp_tools)

    async def execute(call: Any, context: Any = None):
        # user:“通过 command 运行”+(无人值守仅放行声明的 MCP 命令，不借 command 扩大到任意 shell)。
        if spec.mcp_tools and call.name == "run_command":
            from lamtools_core.tool import ToolResult

            try:
                if service is None:
                    raise ValueError("MCP command service unavailable")
                service.check_command(str((call.arguments or {}).get("command") or ""))
            except ValueError as exc:
                return ToolResult(call_id=call.id, name=call.name, status="blocked", error=str(exc))
        # user:“mcp run 名 参”+(同一份运行档白名单也要挡住直接走 mcp 入口的调用)。
        if spec.mcp_tools and call.name == "mcp" and str((call.arguments or {}).get("action") or "") == "run":
            from lamtools_core.tool import ToolResult

            try:
                if service is None:
                    raise ValueError("MCP command service unavailable")
                service.check_tool_allowed(str((call.arguments or {}).get("tool_name") or ""))
            except ValueError as exc:
                return ToolResult(call_id=call.id, name=call.name, status="blocked", error=str(exc))
        budget.take_tool_call()
        return await original_execute(call, context)

    toolbox.execute = execute
    return budget.counters


__all__ = [
    "BudgetExhausted",
    "ProfileBudget",
    "RunBudget",
    "ProfileSpec",
    "apply_profile",
    "available_profiles",
    "read_profiles",
    "resolve_profile",
]
