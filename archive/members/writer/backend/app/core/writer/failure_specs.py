"""Writer failure recovery specifications.

Writer's failure recovery system handles tool failures, loop breaking,
and forced action enforcement. This module documents the recovery
strategies, loop breaker thresholds, and failure classification.

The actual recovery logic lives in WriterKit (core_kernel_adapter.py).
This module is for documentation, testing, and future spec-driven recovery.
"""

from __future__ import annotations


LOOP_BREAKER_CONSTANTS = {
    "LOOP_BREAKER_PAUSE": 10,
    "LOOP_BREAKER_FORCE_STRIP": 20,
    "LOOP_BREAKER_REPEAT": 10,
    "LOOP_BREAKER_READS": 10,
    "FORCED_ACTION_VIOLATION_LIMIT": 3,
    "FAILURE_NO_MUTATION_LIMIT": 3,
    "MAX_PLAN_REJECTION_ATTEMPTS": 3,
}


FAILURE_PREFIXES = (
    "WRITE REJECTED:",
    "EDIT REJECTED:",
    "PLAN REJECTED:",
    "AGENT TOOL REJECTED:",
    "old_string is empty",
    "old_string not found",
    "No files specified.",
    "Design doc not found:",
    "Verification error:",
    "Unknown agent:",
    "DECISION REJECTED:",
    "MCP TOOL ERROR:",
)


RECOVERABLE_FAILURE_PATTERNS = {
    "write_file": ("WRITE REJECTED:",),
    "edit_file": (
        "old_string is empty",
        "old_string not found",
        "WRITE REJECTED:",
        "EDIT REJECTED:",
    ),
}


RECOVERY_STRATEGIES = {
    "file_protocol_blocked": (
        '浏览器验证被 file:// 协议拦截时，不要修改业务代码。'
        '先用 run_command 启动或建议启动本地静态服务器，再用 http://127.0.0.1:<port>/ 验证；'
        '如果当前运行环境不能启动浏览器验证，应明确回复\u201c交付物已生成，浏览器验证受环境限制\u201d，'
        '并列出已完成文件和可手动验证步骤。'
    ),
    "no_test_command": (
        '没有检测到测试命令时，不要反复 run_tests。'
        '先判断项目类型：静态 HTML/CSS/JS 项目可用静态检查、目录检查、关键文件读取和本地服务器验证；'
        '若需要自动测试，应先创建明确的验证脚本或传入具体命令。'
    ),
    "test_failure": (
        '测试失败时先定位失败断言，然后必须执行 write_file/edit_file 做最小修复；'
        "必要时用 sub_agent 辅助诊断，但不要反复 recall_session/read_file/run_command。"
        '若失败来自你刚写的测试且测试超出用户需求，'
        '应把测试改回用户需求，而不是追逐过度约束。'
    ),
    "dependency_failure": (
        "依赖/安装失败时用 sub_agent 做依赖分析，先确认项目 manifest 和可用降级路径。"
    ),
    "ui_check_failure": (
        "界面或浏览器检查失败时用 sub_agent 做界面复核，修正真实工作流、状态和可访问性问题。"
    ),
    "permission_denied": (
        "权限、商业分发或产品路线无法自行决定时调用 decision_point，不要继续猜。"
    ),
}


def is_recoverable_tool_failure(action_type: str, output: str) -> bool:
    """Check if a tool failure is recoverable within the same plan step."""
    text = (output or "").strip()
    patterns = RECOVERABLE_FAILURE_PATTERNS.get(action_type, ())
    return any(text.startswith(p) for p in patterns)


def failure_recovery_instruction(action_failures: list[str]) -> str:
    """Build recovery strategy hints from action failure messages."""
    text = "\n".join(action_failures).lower()
    hints: list[str] = []
    if "access to \"file:\" protocol is blocked" in text or "access to 'file:' protocol is blocked" in text:
        hints.append(RECOVERY_STRATEGIES["file_protocol_blocked"])
    if "no test command detected" in text or "pass command explicitly" in text:
        hints.append(RECOVERY_STRATEGIES["no_test_command"])
    if "run_tests" in text or "pytest" in text or "npm test" in text or "failed" in text:
        hints.append(RECOVERY_STRATEGIES["test_failure"])
    if any(m in text for m in ("npm install", "pip install", "dependency", "module not found", "no module named", "cannot find module")):
        hints.append(RECOVERY_STRATEGIES["dependency_failure"])
    if any(m in text for m in ("browser_check", "页面", "html", "viewport", "accessibility")):
        hints.append(RECOVERY_STRATEGIES["ui_check_failure"])
    if "permission denied" in text or "decision" in text:
        hints.append(RECOVERY_STRATEGIES["permission_denied"])
    return "\n".join(f"恢复策略：{hint}" for hint in hints)


def is_test_or_command_failure(action_failures: list[str]) -> bool:
    """Check if failures include test or command failures (excluding environment issues)."""
    text = "\n".join(action_failures).lower()
    if "access to \"file:\" protocol is blocked" in text or "access to 'file:' protocol is blocked" in text:
        return False
    if "no test command detected" in text or "pass command explicitly" in text:
        return False
    return any(marker in text for marker in (
        "run_tests:",
        "run_command:",
        "pytest",
        "unittest",
        "command failed",
        "failed",
        "traceback",
        "assertionerror",
    ))


__all__ = [
    "LOOP_BREAKER_CONSTANTS",
    "FAILURE_PREFIXES",
    "RECOVERABLE_FAILURE_PATTERNS",
    "RECOVERY_STRATEGIES",
    "is_recoverable_tool_failure",
    "failure_recovery_instruction",
    "is_test_or_command_failure",
]
