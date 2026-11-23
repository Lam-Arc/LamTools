"""浏览器高风险动作的审批链路测试。

user:“高风险操作审批回流…接到现有统一审批机制上：模型请求 → 走审批 → 用户批准后由宿主置位 approved
（模型参数不能自批），批准前操作保持拒绝并说明”+
(这份用例只钉链路本身：动作判级 → 闸门要求审批 → 宿主写回 approved → 工具把它交给 Rust；
 以及反向两条：模型参数不能自批、未批准时批准位不出现)。
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from lamtools_core import browser as browser_pkg
from lamtools_core.browser import agent as browser_agent
from lamtools_core.browser import tools as browser_tools
from lamtools_core.tool import ToolCall
from lamtools_core.tool.default_toolbox import build_core_toolbox
from lamtools_core.tool.operation_levels import BROWSER_APPROVAL_INTENTS, operation_level


@pytest.fixture(autouse=True)
def clean_queue():
    browser_agent.queue().clear()
    yield
    browser_agent.queue().clear()


def _high_risk_call(call_id: str = "call-1") -> ToolCall:
    return ToolCall(
        id=call_id,
        name=browser_tools.BROWSER_TOOL_NAME,
        arguments={"action": "click", "tab": "t1", "ref": "e9", "intent": "payment"},
    )


def _dispatch_instruction(call: ToolCall) -> dict:
    """跑一次 handler，把真正排队给宿主的 instruction 取回来。"""
    handler = browser_tools.make_browser_handler()
    seen: dict = {}

    def run() -> None:
        asyncio.run(handler(call))

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    deadline = time.time() + 3.0
    requests: list[dict] = []
    while time.time() < deadline and not requests:
        requests = browser_agent.take_pending()
        time.sleep(0.01)
    assert requests, "工具必须把请求放进队列，否则桌面端没有东西可执行"
    seen.update(requests[0]["args"]["instruction"])
    browser_agent.submit_result(
        {"id": requests[0]["id"], "ok": True, "payload": {"tab": "t1", "op": "click"}}
    )
    worker.join(timeout=5.0)
    assert not worker.is_alive()
    return seen


def test_high_risk_browser_intent_is_graded_three():
    # 同一动作：普通点击仍是 1 级，声明高风险才升到 3 级（闸门据此要求审批）。
    assert operation_level("browser", {"action": "click"}) == 1
    assert operation_level("browser", {"action": "snapshot"}) == 1
    for intent in BROWSER_APPROVAL_INTENTS:
        assert operation_level("browser", {"action": "click", "intent": intent}) == 3
    # 其它工具不受这条规则影响。
    assert operation_level("write_file", {"path": "a.txt"}) == 2


def test_operation_and_tool_agree_on_the_intent_set():
    # 两份集合分开写是为了避免 import 环路；这里钉住它们不会各自漂移。
    assert set(BROWSER_APPROVAL_INTENTS) == set(browser_tools.HIGH_RISK_INTENTS)


def test_gate_requires_approval_before_the_action_runs(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path)
    prepared = toolbox.prepare_call(_high_risk_call())

    assert prepared.requires_approval is True, "高风险 intent 必须先问用户"
    approval = prepared.metadata["approval"]
    assert approval["level"] == 3
    # 批准前没有任何批准位：工具不会把 approved 交给宿主。
    assert not approval.get("approved")
    assert not approval.get("auto_approved")


def test_user_approval_is_written_by_the_host_and_reaches_the_browser(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path)
    approved = toolbox.prepare_approved_call(toolbox.prepare_call(_high_risk_call()))

    # 批准之后：闸门不再要求审批，批准位由宿主写在 metadata 里。
    assert approved.requires_approval is False
    assert approved.metadata["approval"]["approved"] is True
    assert browser_tools.host_approval(approved.metadata) is True

    instruction = _dispatch_instruction(approved)
    assert instruction["intent"] == "payment"
    assert instruction["approved"] is True, "宿主批准必须一路传到 Rust 侧的 action 指令"


def test_unapproved_high_risk_action_stays_rejected(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path)
    prepared = toolbox.prepare_call(_high_risk_call())

    # 未批准：工具层看到的批准位是假，宿主会拒绝这条指令并说明原因。
    assert browser_tools.host_approval(prepared.metadata) is False
    instruction = _dispatch_instruction(prepared)
    assert instruction["intent"] == "payment"
    assert "approved" not in instruction


def test_model_arguments_cannot_self_approve():
    # 模型把 approved 写进 arguments 也不起作用：工具只读 metadata。
    forged = ToolCall(
        id="call-forged",
        name=browser_tools.BROWSER_TOOL_NAME,
        arguments={"action": "click", "tab": "t1", "ref": "e9", "intent": "delete", "approved": True},
        metadata={},
    )
    assert browser_tools.host_approval(forged.metadata) is False
    instruction = _dispatch_instruction(forged)
    assert instruction["intent"] == "delete"
    assert "approved" not in instruction


def test_blocked_approval_never_counts_as_approved():
    # 闸门判定为硬拦截时，哪怕带着历史批准位也不能当批准。
    metadata = {"approval": {"blocked": True, "approved": True, "auto_approved": True}}
    assert browser_tools.host_approval(metadata) is False


def test_auto_approved_runtime_tier_counts_as_host_authorization():
    # 运行档已授权（full_access / 运行档白名单）时闸门自己写 auto_approved：
    # 这仍然是宿主结论，所以算已批准；模型参数永远进不到这个字段。
    assert browser_tools.host_approval({"approval": {"auto_approved": True}}) is True
    assert browser_tools.host_approval({"approval": {"auto_approved": False}}) is False


def test_package_still_exports_the_tool_surface():
    assert hasattr(browser_pkg, "BROWSER_TOOL_NAME")
    assert browser_pkg.BROWSER_TOOL_NAME == browser_tools.BROWSER_TOOL_NAME
