"""browser 工具与浏览器 Agent 通道的单元测试。

user:“只跑相关测试”+(这一份只覆盖 M4 新增的 Python 侧：队列、超时、信封、ref 校验透传、
高风险声明、截图落盘、以及工具在默认工具箱里的注册位置)。
"""

from __future__ import annotations

import base64
import threading
import time

import pytest

from lamtools_core import browser as browser_pkg
from lamtools_core.browser import agent as browser_agent
from lamtools_core.browser import tools as browser_tools
from lamtools_core.tool import ToolCall


@pytest.fixture(autouse=True)
def clean_queue():
    browser_agent.queue().clear()
    yield
    browser_agent.queue().clear()


def _call(**arguments) -> ToolCall:
    return ToolCall(id="call-1", name=browser_tools.BROWSER_TOOL_NAME, arguments=arguments)


def _run_with_host(call: ToolCall, respond, *, work_root: str = "") -> dict:
    """在后台线程跑一次工具调用，拿到排队请求后由测试扮演桌面宿主回结果。"""

    outcome: dict = {}

    def target() -> None:
        try:
            outcome["value"] = browser_tools.handle(call, work_root=work_root)
        except Exception as error:  # noqa: BLE001 - 测试里要拿到原异常类型
            outcome["error"] = error

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    deadline = time.time() + 3.0
    requests: list[dict] = []
    while time.time() < deadline and not requests:
        requests = browser_agent.take_pending()
        time.sleep(0.01)
    assert requests, "工具必须把请求放进队列，否则桌面端没有东西可执行"
    respond(requests[0])
    worker.join(timeout=5.0)
    assert not worker.is_alive(), "工具必须等到结果或超时"
    return outcome


def test_request_queue_pairs_request_with_result():
    request_id = browser_agent.queue().submit("browser_snapshot", {"tab": "t1"})
    taken = browser_agent.take_pending()
    assert taken == [{"id": request_id, "command": "browser_snapshot", "args": {"tab": "t1"}}]
    # 认领过的请求不会重复下发。
    assert browser_agent.take_pending() == []

    accepted = browser_agent.submit_result({"id": request_id, "ok": True, "payload": {"tab": "t1"}})
    assert accepted == {"accepted": True}
    ok, payload, error = browser_agent.queue().wait(request_id, 1.0)
    assert ok and payload == {"tab": "t1"} and error is None


def test_unclaimed_request_reports_missing_desktop(monkeypatch):
    # 桌面端没取走请求：必须报「桌面端不可用」，而不是无限等待。
    monkeypatch.setattr(browser_agent, "CLAIM_TIMEOUT", 0.05)
    request_id = browser_agent.queue().submit("browser_tabs", {})
    ok, payload, error = browser_agent.queue().wait(request_id, 2.0)
    assert not ok and payload is None
    assert error and error["code"] == "unsupported"
    assert "桌面" in error["message"]


def test_result_timeout_is_retriable_and_readable():
    request_id = browser_agent.queue().submit("browser_snapshot", {"tab": "t1"})
    browser_agent.take_pending()  # 模拟已认领但一直不回
    ok, _, error = browser_agent.queue().wait(request_id, 0.1)
    assert not ok and error and error["code"] == "timeout"
    assert "重试" in error["message"]


def test_call_surfaces_host_errors_verbatim():
    def respond(request: dict) -> None:
        browser_agent.submit_result(
            {"id": request["id"], "ok": False, "error": {"code": "human_owned", "message": "用户正在操作"}}
        )

    outcome = _run_with_host(_call(action="click", tab="t1", ref="e12"), respond)
    error = outcome.get("error")
    assert error is not None, "宿主拒绝时必须抛错，不能静默"
    assert error.code == "human_owned"
    assert "用户正在操作" in error.message


def test_snapshot_result_carries_untrusted_envelope():
    def respond(request: dict) -> None:
        browser_agent.submit_result(
            {
                "id": request["id"],
                "ok": True,
                "payload": {
                    "tab": "t1",
                    "url": "https://example.com/",
                    "fetchedAt": "2026-11-16T00:00:00Z",
                    "trust": "untrusted",
                    "refs": [{"ref": "e1", "role": "link", "name": "首页"}],
                    "text": {"blocks": [], "truncated": False},
                },
            }
        )

    outcome = _run_with_host(_call(action="snapshot", tab="t1"), respond)
    payload = outcome["value"]
    assert payload["trust"] == "untrusted"
    assert payload["source"] == "web"
    assert "不可信" in payload["note"]
    assert payload["content"]["refs"][0]["ref"] == "e1"


def test_write_actions_forward_only_structured_instructions():
    seen: dict = {}

    def respond(request: dict) -> None:
        seen.update(request["args"])
        browser_agent.submit_result(
            {"id": request["id"], "ok": True, "payload": {"tab": "t1", "op": "type", "navigated": False}}
        )

    call = _call(action="type", tab="t1", ref="e7", text="hello", clear=True, submit=True)
    outcome = _run_with_host(call, respond)
    instruction = seen["instruction"]
    assert instruction == {"op": "type", "ref": "e7", "text": "hello", "clear": True, "submit": True}
    assert outcome["value"]["trust"] == "untrusted"


def test_high_risk_intent_needs_explicit_approval():
    seen: dict = {}

    def respond(request: dict) -> None:
        seen.update(request["args"]["instruction"])
        browser_agent.submit_result(
            {"id": request["id"], "ok": True, "payload": {"tab": "t1", "op": "click"}}
        )

    _run_with_host(_call(action="click", tab="t1", ref="e9", intent="delete"), respond)
    # 没有审批信息时绝不自己盖章：宿主会拒绝这条指令。
    assert seen["intent"] == "delete"
    assert "approved" not in seen


def test_approval_flag_comes_from_call_metadata_not_model_arguments():
    import asyncio

    handler = browser_tools.make_browser_handler()
    seen: dict = {}

    def respond(request: dict) -> None:
        seen.update(request["args"]["instruction"])
        browser_agent.submit_result(
            {"id": request["id"], "ok": True, "payload": {"tab": "t1", "op": "click"}}
        )

    # 审批标记只能由框架写在 metadata 里；模型给参数加 approved 不起作用。
    call = ToolCall(
        id="call-2",
        name=browser_tools.BROWSER_TOOL_NAME,
        arguments={"action": "click", "tab": "t1", "ref": "e9", "intent": "delete", "approved": True},
        metadata={"approved": True},
    )
    worker = threading.Thread(target=lambda: asyncio.run(handler(call)), daemon=True)
    worker.start()
    deadline = time.time() + 3.0
    requests: list[dict] = []
    while time.time() < deadline and not requests:
        requests = browser_agent.take_pending()
        time.sleep(0.01)
    assert requests
    respond(requests[0])
    worker.join(timeout=5.0)
    assert seen["intent"] == "delete"
    assert seen["approved"] is True


def test_unknown_action_and_missing_tab_are_rejected_before_dispatch():
    with pytest.raises(browser_agent.BrowserChannelError) as unknown:
        browser_tools.handle(_call(action="evaluate", script="alert(1)"))
    assert unknown.value.code == "unsupported"

    with pytest.raises(browser_agent.BrowserChannelError) as missing:
        browser_tools.handle(_call(action="snapshot"))
    assert missing.value.code == "unsupported"
    assert "tab" in missing.value.message

    with pytest.raises(browser_agent.BrowserChannelError) as bad_intent:
        browser_tools.handle(_call(action="click", tab="t1", ref="e1", intent="whatever"))
    assert bad_intent.value.code == "unsupported"


def test_screenshot_is_saved_to_disk_and_base64_is_not_returned(tmp_path):
    # 1x1 PNG，只为断言落盘与裁剪逻辑。
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")

    def respond(request: dict) -> None:
        browser_agent.submit_result(
            {
                "id": request["id"],
                "ok": True,
                "payload": {
                    "tab": "t1",
                    "url": "https://example.com/",
                    "target": "viewport",
                    "png": data_url,
                    "width": 1,
                    "height": 1,
                    "fetchedAt": "2026-11-16T00:00:00Z",
                },
            }
        )

    outcome = _run_with_host(_call(action="screenshot", tab="t1"), respond, work_root=str(tmp_path))
    payload = outcome["value"]
    content = payload["content"]
    assert "png" not in content, "base64 不能进模型上下文"
    saved = tmp_path / ".lam" / "artifacts" / "browser"
    files = list(saved.glob("*.png"))
    assert len(files) == 1
    assert files[0].read_bytes() == png
    assert content["path"].endswith(".png")


def test_browser_tool_is_registered_in_the_default_toolbox():
    from lamtools_core.tool import default_toolbox

    name = browser_tools.BROWSER_TOOL_NAME
    assert name in default_toolbox.DEFAULT_TOOL_PERMISSIONS
    assert name in default_toolbox.DEFAULT_TOOL_ORDER
    assert name in default_toolbox.DEFAULT_TOOL_CATEGORIES
    names = {str(item["name"]) for item in default_toolbox.DEFAULT_TOOL_DEFINITIONS}
    assert name in names

    from lamtools_core.tool.operation_levels import OPERATION_LEVELS

    # 只读与普通交互按 1 级放行，关闭标签丢状态给 2 级。
    assert OPERATION_LEVELS["browser.snapshot"] == 1
    assert OPERATION_LEVELS["browser.screenshot"] == 1
    assert OPERATION_LEVELS["browser.click"] == 1
    assert OPERATION_LEVELS["browser.close"] == 2


def test_package_exports_the_tool_surface():
    for exported in ("BROWSER_TOOL_NAME", "make_browser_handler", "take_pending", "submit_result"):
        assert hasattr(browser_pkg, exported)

def test_every_command_the_agent_code_calls_is_in_the_bridge_whitelist():
    """跨语言契约：Python 侧真的会发的 browser_* 命令，前端白名单必须都放行。

    user:“宿主没有这个命令：browser_nav”+(这条契约之前靠人记，漏一个就整段功能静默降级；
    这里从 Python 源码里扫出实际会调的命令名，和 agentBridge.ts 的白名单对账)。
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sources = [
        root / "src/lamtools_core/browser/tools.py",
        root / "src/lamtools_core/browser/search/engine.py",
    ]
    called = set()
    for path in sources:
        text = path.read_text(encoding="utf-8")
        called.update(re.findall(r'"(browser_[a-z_]+)"', text))
    called.discard("browser")  # 工具名，不是命令
    assert called, "没扫到任何 browser_* 命令，断言等于没跑"

    bridge = (root / "ui/src/browser/agentBridge.ts").read_text(encoding="utf-8")
    block = bridge.split("const ALLOWED_COMMANDS", 1)[1].split("])", 1)[0]
    allowed = set(re.findall(r"'(browser_[a-z_]+)'", block))
    assert allowed, "白名单解析为空，断言等于没跑"

    missing = sorted(called - allowed)
    assert not missing, f"这些命令 Python 会发，但桥白名单没放行：{missing}"

