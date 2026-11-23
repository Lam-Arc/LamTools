"""user:“工具权限是改成 123 级，不一棒子按工具类型打死了”+(按本次操作判级)。"""
from __future__ import annotations

import re
import shlex
from typing import Any

AUTO_APPROVE_LEVELS = {"ask": 1, "auto": 2, "full_access": 3}
CAPABILITY_LEVELS = {"read_only": 1, "limited_edit": 2, "full_edit": 3}

# Exact operation rows; an unregistered operation always defaults to 3.
OPERATION_LEVELS = {
    "read_file": 1, "read": 1, "list_dir": 1, "search_files": 1, "search_content": 1,
    "write_file": 2, "write": 2, "edit_file": 2, "edit": 2,
    "list_processes": 1, "kill_process": 1, "process.list": 1, "process.kill": 1,
    "memory": 1, "library": 1, "load_skill": 1,
    # user:“ok，那就这么做”+(当前会话历史的搜索和原文读取属于只读能力)。
    "search_context": 1, "recall_context": 1,
    "write_checklist": 1, "update_checklist": 1, "checklist": 1,
    "goal": 2, "goal.list": 1, "goal.get": 1,
    "arrange": 3, "arrange.list": 1, "arrange.get": 1,
    "plugin": 3, "plugin.list": 2, "plugin.deps": 2,
    "plugin_list": 2, "plugin_deps": 2, "plugin_install": 3,
    # user:“互不依赖的任务应委派 sub-agent 并行执行”+(委派本身不是写操作：
    # 子代理继承同一 approval_policy/preset/active_tier，它真正要做的每一步
    # 都在自己的闸门里重新判级；在启动处再拦一次只会多一次无保护的点击，
    # 还会让 access_tools.jsonc 给 read_only 档的 sub_agent 授权变成硬拦截)。
    "sub_agent": 1, "sub_agent_message": 1, "subagent": 1,
    # 子代理向父级回报用的 message 工具：纯交互，不触碰工作区。
    "message": 1,
    "web_search": 1, "web_fetch": 2, "web.search": 1, "web.fetch": 2,
    "generate_image": 2, "check_exports": 1,
    # user:“无需做安全边界”+(桌面动作全部按 1 级放行，不再每步弹审批；
    # 任务本身仍可 pause/stop)。
    "computer_use": 1,
    "computer_use.start": 1, "computer_use.screenshot": 1, "computer_use.snapshot": 1,
    # user:“把「截图/选中区域 → 提取文字」做通”+(只读屏幕，不改任何状态，和截图同级)。
    "computer_use.ocr": 1,
    "computer_use.status": 1, "computer_use.pause": 1, "computer_use.stop": 1,
    "computer_use.resume": 1, "computer_use.click": 1, "computer_use.type": 1,
    "computer_use.key": 1, "computer_use.scroll": 1, "computer_use.drag": 1,
    "computer_use.focus": 1,
    # user:“让 Agent Loop 能直接调用”+(browser 按动作分级：读与普通交互都是 1 级，
    # 关闭标签会丢状态所以给 2 级；payment/delete/publish/auth 由宿主拒绝未经审批的声明)。
    "browser": 1, "browser.open": 1, "browser.tabs": 1, "browser.activate": 1,
    "browser.close": 2, "browser.snapshot": 1, "browser.screenshot": 1,
    "browser.click": 1, "browser.type": 1, "browser.clear": 1, "browser.hover": 1,
    "browser.scroll": 1, "browser.select": 1, "browser.pressKey": 1,
    "browser.waitFor": 1, "browser.control": 1,
    # user:“让 Sunday 的内置浏览器同时承担普通网页浏览、Agent 网页搜索和网页信息获取”+
    # (搜索与阅读都是只读网页；它们会开后台标签，但不覆盖用户当前页面)。
    "browser.search": 1, "browser.open_result": 1, "browser.read_page": 1, "browser.inspect_page": 1,
    # Preserve the existing Study/Workflow domain behavior outside this migration's scope.
    "get_knowledge_net": 1, "build_knowledge_net": 1, "sign": 1, "notes": 1, "exam": 1,
    "workflow_graph": 1, "workflow_add_node": 2, "workflow_connect": 2,
    "workflow_delete_node": 2, "workflow_update_node": 2,
    "mcp": 1, "mcp.servers": 1, "mcp.tools": 1, "mcp.schema": 1,
}


def valid_level(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


# user:“高风险操作审批回流…接到现有统一审批机制上”+
# (带 payment/delete/publish/auth 声明的浏览器写操作按 3 级判级：审批闸门会先问用户，
#  用户批准后由宿主把 approved 写进 call.metadata["approval"]；模型给的参数永远不算授权)。
# 这份集合与 lamtools_core.browser.tools.HIGH_RISK_INTENTS 必须一致（tests 里钉住）。
BROWSER_APPROVAL_INTENTS = ("payment", "delete", "publish", "auth")


def command_level(command: str) -> int:
    from .approval import DANGEROUS_COMMAND_RE, SHELL_STRUCTURE_RE
    # This is an ordered classification table, not a shell security boundary.
    if SHELL_STRUCTURE_RE.search(command) or re.search(r"[;&|<>\r\n]", command):
        return 3
    if DANGEROUS_COMMAND_RE.search(command) or re.search(r"(?i)(--output\b|\s-o\b|--pre(?:=|\s)|--hostname-bin\b|\s-(?:delete|exec|execdir|ok)\b)", command):
        return 3
    try:
        argv = shlex.split(command)
    except ValueError:
        return 3
    words = [word.lower() for word in argv]
    if not words:
        return 3
    if words[0] in {"dir", "type", "cat", "rg", "find", "ls", "pwd", "get-content", "get-childitem", "get-location", "git-status"}:
        return 1
    if words[:2] in [["git", "status"], ["git", "diff"], ["git", "log"], ["git", "show"]]:
        return 1
    return 2


def operation_level(tool_name: str, params: dict[str, Any], *, levels: dict[str, int] | None = None,
                    mcp_level=None, mcp_call_level=None) -> int:
    table = {**OPERATION_LEVELS, **(levels or {})}
    action = str(params.get("action") or "")
    # user:“高风险操作审批回流”+(动作本身仍是 1 级交互，只有用户/模型声明了高风险 intent
    # 才升到 3 级：这样闸门一定会先问，批准前那条操作保持拒绝)。
    if tool_name == "browser" and str(params.get("intent") or "") in BROWSER_APPROVAL_INTENTS:
        return 3
    # user:“按 MCP 调的东西来分 1、2、3 级”+(mcp 入口只做查询时是 1 级；
    # action=run 的等级取自目标 MCP 工具的声明，而不是入口工具的静态表)。
    if tool_name == "mcp" and action == "run":
        target = str(params.get("tool_name") or "").strip()
        arguments = params.get("arguments")
        if not target or mcp_call_level is None:
            return 3
        return mcp_call_level(target, arguments if isinstance(arguments, dict) else {})
    if tool_name in {"run_command", "command"}:
        command = str(params.get("command") or "")
        from lamtools_core.mcp.command_service import parse_mcp_command
        if parse_mcp_command(command) is not None:
            return mcp_level(command) if mcp_level is not None else 3
        return command_level(command)
    return table.get(f"{tool_name}.{action}", table.get(tool_name, 3))


def pending_auto_approvable(call: dict[str, Any], preset: str) -> bool:
    """A mode change must not silently grant a level above its threshold."""
    approval = (call.get("metadata") or {}).get("approval") or {}
    if approval.get("blocked"):
        return False
    level = approval.get("level")
    if not valid_level(level):
        level = operation_level(str(call.get("name") or ""), call.get("arguments") or {})
    cap = approval.get("available_level", 3)
    if not valid_level(cap):
        return False
    return 0 < level <= min(AUTO_APPROVE_LEVELS[preset], cap)
