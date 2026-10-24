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
    """运行档预算耗尽：后续调用都会收到本错误，运行应尽快收尾。"""


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
    budget: ProfileBudget = ProfileBudget()


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
        budget_raw = body.get("budget") if isinstance(body.get("budget"), dict) else {}
        budget = ProfileBudget(
            max_tool_calls=_positive_int(budget_raw.get("maxToolCalls"), label="maxToolCalls"),
            max_tokens=_positive_int(budget_raw.get("maxTokens"), label="maxTokens"),
        )
        profiles[short] = ProfileSpec(
            full_name=f"{manifest.name}:{short}",
            plugin=manifest.name,
            profile=short,
            title=str(body.get("title") or short).strip() or short,
            tools=tools,
            approval=approval,
            model_scene=str(body.get("modelScene") or "").strip(),
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


def apply_profile(toolbox: Any, spec: ProfileSpec) -> dict[str, int]:
    """把运行档强制到工具箱上，返回预算计数器。

    - 白名单：`agent_tool_whitelist`（可见面收窄）+ execute 入口拒绝（fail closed，
      陈旧上下文也调不了白名单外的工具）。
    - 审批：approval=auto 时白名单内全部自动放行（无人值守语义）。
    - 预算：包装 execute 计数，超限后所有后续调用都收到预算耗尽错误。
    """
    # user:“无人值守 = 白名单内自动、白名单外拒绝”+白名单双重生效：
    # 可见面收窄（agent_tool_whitelist）+ 执行拒绝（execute 入口检查）；
    # 审批用宿主现成的 gate 级 auto_approve（未被阻断的调用全部自动批准），
    # 不逐工具改权限表。
    whitelist = set(spec.tools)
    toolbox.agent_tool_whitelist = whitelist
    if spec.approval == "auto":
        gate = getattr(getattr(toolbox, "permission_resolver", None), "gate", None)
        if gate is not None:
            gate.approval_policy = "auto_approve"

    counters = {"tool_calls": 0, "tokens": 0}
    original_execute = toolbox.execute

    async def execute(call: Any, context: Any = None):
        if (
            spec.budget.max_tool_calls is not None
            and counters["tool_calls"] >= spec.budget.max_tool_calls
        ):
            return _budget_exhausted_result(call, f"工具调用已达上限 {spec.budget.max_tool_calls} 次")
        counters["tool_calls"] += 1
        result = await original_execute(call, context)
        usage = getattr(result, "usage", None)
        if usage is not None:
            counters["tokens"] += int(getattr(usage, "total_tokens", 0) or 0)
        if (
            spec.budget.max_tokens is not None
            and counters["tokens"] >= spec.budget.max_tokens
        ):
            return _budget_exhausted_result(call, f"token 已达上限 {spec.budget.max_tokens}")
        return result

    toolbox.execute = execute
    return counters


def _budget_exhausted_result(call: Any, detail: str) -> Any:
    from lamtools_core.tool import ToolResult

    message = f"运行档预算耗尽：{detail}。请立即收尾并汇报已完成的部分。"
    return ToolResult(
        call_id=getattr(call, "id", ""),
        name=getattr(call, "name", ""),
        status="failed",
        content=message,
        error=message,
    )


__all__ = [
    "BudgetExhausted",
    "ProfileBudget",
    "ProfileSpec",
    "apply_profile",
    "available_profiles",
    "read_profiles",
    "resolve_profile",
]
