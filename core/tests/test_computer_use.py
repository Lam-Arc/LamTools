"""computer_use 单元测试：坐标换算、任务状态机、安全守卫、动作分级。

真实鼠标键盘注入不进单测，避免测试机被乱点；注入的端到端验证放在
``scripts/verify_computer_use.py``，由人工跑一次看截图。

user:“查一下 computer use 功能怎么做”+(先写能证明需求达成的验收测试)。
"""

from __future__ import annotations

import time

import pytest
from PIL import Image

from lamtools_core.computer_use import capture, session, tools, win32
from lamtools_core.computer_use.session import GuardError
from lamtools_core.tool import ToolCall
from lamtools_core.tool.operation_levels import operation_level


def _call(action: str, **kwargs):
    return ToolCall(id="call-1", name="computer_use", arguments={"action": action, **kwargs})


@pytest.fixture(autouse=True)
def _clean_session():
    session.clear()
    yield
    session.clear()


# ---------------------------------------------------------------------------
# 坐标换算
# ---------------------------------------------------------------------------


class TestFrameMapping:
    def test_scaled_frame_maps_back_to_physical_pixels(self):
        frame = capture.Frame(
            png=b"", image_width=1280, image_height=720,
            screen_width=2560, screen_height=1440, origin_x=-1920, origin_y=0,
        )
        assert frame.scale_x == 2.0
        assert frame.scale_y == 2.0
        # 负原点是副屏在主屏左边时的正常情况
        assert frame.to_screen(10, 20) == (-1920 + 20, 40)

    def test_unscaled_frame_is_identity_with_offset(self):
        frame = capture.Frame(
            png=b"", image_width=1000, image_height=500,
            screen_width=1000, screen_height=500, origin_x=100, origin_y=50,
        )
        assert frame.to_screen(300, 200) == (400, 250)

    def test_metadata_is_serialisable(self):
        frame = capture.Frame(
            png=b"", image_width=800, image_height=600,
            screen_width=1600, screen_height=1200, origin_x=0, origin_y=0,
        )
        meta = frame.to_dict()
        assert meta["scale_x"] == 2.0
        assert meta["origin"] == [0, 0]


# ---------------------------------------------------------------------------
# 截图编码
# ---------------------------------------------------------------------------


class TestCaptureEncoding:
    def test_downscale_keeps_ratio(self):
        image = Image.new("RGBA", (4000, 2000), (10, 20, 30, 255))
        png, width, height = capture.encode_png(image, max_width=1000)
        assert (width, height) == (1000, 500)
        assert png.startswith(b"\x89PNG\r\n\x1a\n")

    def test_small_image_is_not_upscaled(self):
        image = Image.new("RGBA", (400, 300), (0, 0, 0, 255))
        _, width, height = capture.encode_png(image, max_width=2000)
        assert (width, height) == (400, 300)

    def test_grid_annotation_keeps_size(self):
        image = Image.new("RGBA", (400, 300), (0, 0, 0, 255))
        out = capture.annotate_grid(image, step=100)
        assert out.size == (400, 300)

    def test_target_annotation_keeps_size(self):
        image = Image.new("RGBA", (400, 300), (0, 0, 0, 255))
        out = capture.annotate_target(image, 120, 90, label="click")
        assert out.size == (400, 300)

    def test_data_url_prefix(self):
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 16
        assert capture.to_data_url(png).startswith("data:image/png;base64,")


# ---------------------------------------------------------------------------
# 任务状态机
# ---------------------------------------------------------------------------


class TestSessionState:
    def test_start_then_guard_passes(self):
        active = session.start("测试目标")
        active.guard("click")
        assert active.status()["state"] == "running"
        assert active.status()["goal"] == "测试目标"

    def test_second_start_is_rejected(self):
        session.start("第一个")
        with pytest.raises(GuardError):
            session.start("第二个")

    def test_pause_blocks_until_resume(self):
        active = session.start("测试")
        active.pause("用户接管")
        with pytest.raises(GuardError) as exc:
            active.guard("click")
        assert "暂停" in str(exc.value)
        active.resume()
        active.guard("click")

    def test_step_limit_fails_task(self):
        active = session.start("测试", max_steps=1)
        active.record("click", "点了一下", ok=True)
        with pytest.raises(GuardError):
            active.guard("click")
        assert active.status()["state"] == "failed"

    def test_timeout_fails_task(self):
        active = session.start("测试", timeout_seconds=30)
        active.deadline = time.monotonic() - 1
        with pytest.raises(GuardError):
            active.guard("click")
        assert active.status()["state"] == "failed"

    def test_stop_is_terminal(self):
        active = session.start("测试")
        active.stop()
        with pytest.raises(GuardError):
            active.guard("click")

    def test_steps_are_recorded_in_order(self):
        active = session.start("测试")
        active.record("click", "第一步", ok=True)
        active.record("type", "第二步", ok=True)
        status = active.status()
        assert status["steps"] == 2
        assert status["last_action"]["action"] == "type"

    def test_max_steps_is_clamped(self):
        active = session.start("测试", max_steps=9999)
        assert active.max_steps == 200

    def test_status_exposes_cursor_relative_to_virtual_screen(self):
        active = session.start("测试")
        active.target_window = 424242
        active.last_action_point = (300, 400)
        status = active.status()
        assert status["target_window"] == 424242
        cursor = status["cursor"]
        assert cursor is not None and len(cursor) == 2
        vx, vy, _, _ = win32.virtual_screen()
        assert cursor == [300 - vx, 400 - vy]

    def test_status_without_action_has_no_cursor(self):
        active = session.start("测试")
        assert active.status()["cursor"] is None


# ---------------------------------------------------------------------------
# 动作分级
# ---------------------------------------------------------------------------


class TestOperationLevels:
    def test_all_actions_are_level_one(self):
        # user:“无需做安全边界”+(桌面动作不再分 2 级，全部按只读放行)。
        for action in (
            "screenshot", "snapshot", "status", "pause", "stop",
            "start", "resume", "click", "type", "key", "scroll", "drag", "focus",
        ):
            assert operation_level("computer_use", {"action": action}) == 1

    def test_unregistered_action_falls_back_to_tool_level(self):
        assert operation_level("computer_use", {"action": "teleport"}) == 1


# ---------------------------------------------------------------------------
# 工具入口
# ---------------------------------------------------------------------------


class TestToolEntry:
    @pytest.mark.asyncio
    async def test_missing_action_reports_workflow(self, tmp_path):
        result = await tools.handle(_call(""), work_root=tmp_path)
        assert result.status == "failed"
        assert "start" in result.error

    @pytest.mark.asyncio
    async def test_unknown_action_is_rejected(self, tmp_path):
        result = await tools.handle(_call("teleport"), work_root=tmp_path)
        assert result.status == "failed"
        assert "未知 action" in result.error

    @pytest.mark.asyncio
    async def test_start_requires_goal(self, tmp_path):
        result = await tools.handle(_call("start"), work_root=tmp_path)
        assert result.status == "failed"
        assert "goal" in result.error

    @pytest.mark.asyncio
    async def test_action_without_task_is_blocked(self, tmp_path):
        result = await tools.handle(_call("click", x=1, y=1), work_root=tmp_path)
        assert result.status == "blocked"
        assert "start" in result.error

    @pytest.mark.asyncio
    async def test_click_without_screenshot_explains_the_fix(self, tmp_path):
        await tools.handle(_call("start", goal="测试"), work_root=tmp_path)
        result = await tools.handle(_call("click", x=10, y=10), work_root=tmp_path)
        assert result.status == "failed"
        assert "screenshot" in result.error

    @pytest.mark.asyncio
    async def test_click_without_coordinates_is_rejected(self, tmp_path):
        await tools.handle(_call("start", goal="测试"), work_root=tmp_path)
        frame = capture.Frame(
            png=b"", image_width=100, image_height=100,
            screen_width=100, screen_height=100, origin_x=0, origin_y=0,
        )
        session.current().last_frame = frame
        result = await tools.handle(_call("click"), work_root=tmp_path)
        assert result.status == "failed"
        assert "x 和 y" in result.error

    @pytest.mark.asyncio
    async def test_coordinate_outside_screenshot_is_rejected(self, tmp_path):
        await tools.handle(_call("start", goal="测试"), work_root=tmp_path)
        frame = capture.Frame(
            png=b"", image_width=100, image_height=100,
            screen_width=100, screen_height=100, origin_x=0, origin_y=0,
        )
        session.current().last_frame = frame
        result = await tools.handle(_call("click", x=500, y=10), work_root=tmp_path)
        assert result.status == "failed"
        assert "超出" in result.error

    @pytest.mark.asyncio
    async def test_stop_and_status_round_trip(self, tmp_path):
        await tools.handle(_call("start", goal="测试"), work_root=tmp_path)
        status = await tools.handle(_call("status"), work_root=tmp_path)
        assert status.status == "ok"
        stopped = await tools.handle(_call("stop", reason="测试结束"), work_root=tmp_path)
        assert stopped.status == "ok"
        assert session.current().state == "stopped"


# ---------------------------------------------------------------------------
# 安全边界
# ---------------------------------------------------------------------------


class TestSafety:
    # user:“无需做安全边界”+(窗口归属和提权都不再拦，函数只保留诊断语义)。
    def test_own_window_is_not_blocked(self):
        info = win32.WindowInfo(
            hwnd=1, title="Sunday", class_name="Tauri Window", pid=999999,
            x=0, y=0, width=100, height=100, z=0, minimized=False, elevated=False,
        )
        assert not tools._is_self_window(info)

    def test_elevated_window_is_not_blocked(self):
        info = win32.WindowInfo(
            hwnd=3, title="管理员窗口", class_name="Notepad", pid=999999,
            x=0, y=0, width=100, height=100, z=0, minimized=False, elevated=True,
        )
        assert not tools._is_self_window(info)


# ---------------------------------------------------------------------------
# 工具注册
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_spec_is_registered_with_action_required(self):
        from lamtools_core.tool.default_toolbox import (
            DEFAULT_TOOL_DEFINITIONS,
            default_core_tool_specs,
        )

        specs = {spec.name: spec for spec in default_core_tool_specs()}
        assert "computer_use" in specs
        schema = specs["computer_use"].input_schema
        # strict 适配会把所有属性都标成 required，所以原始 required 从定义里读。
        raw = {item["name"]: item for item in DEFAULT_TOOL_DEFINITIONS}["computer_use"]
        assert raw["input_schema"]["required"] == ["action"]
        actions = schema["properties"]["action"]["enum"]
        assert "screenshot" in actions
        assert "click" in actions
        assert "start" in actions

    def test_default_permission_auto_allows(self):
        from lamtools_core.tool.default_toolbox import (
            DEFAULT_TOOL_CATEGORIES,
            DEFAULT_TOOL_PERMISSIONS,
        )
        from lamtools_core.tool.permission import AUTO_ALLOW

        # user:“无需做安全边界”+(桌面工具默认放行，不再弹审批)。
        assert DEFAULT_TOOL_PERMISSIONS["computer_use"] == AUTO_ALLOW
        assert DEFAULT_TOOL_CATEGORIES["computer_use"] == "computer"

    def test_toolbox_exposes_the_tool(self, tmp_path):
        from lamtools_core.tool.default_toolbox import build_core_toolbox

        toolbox = build_core_toolbox(work_root=tmp_path)
        specs = {spec.name: spec for spec in toolbox.tool_specs()}
        assert "computer_use" in specs
        assert "snapshot" in specs["computer_use"].description

    @pytest.mark.asyncio
    async def test_toolbox_allows_start_under_ask_preset(self, tmp_path):
        from lamtools_core.tool.default_toolbox import build_core_toolbox

        # user:“无需做安全边界”+(ask 档下桌面动作也直接放行，不再卡审批)。
        toolbox = build_core_toolbox(work_root=tmp_path)
        started = await toolbox.execute(
            ToolCall(id="call-2", name="computer_use", arguments={"action": "start", "goal": "装配验证"})
        )
        assert started.status == "ok"
        assert started.metadata["state"] == "running"

    @pytest.mark.asyncio
    async def test_toolbox_executes_status_without_touching_the_desktop(self, tmp_path):
        from lamtools_core.tool.default_toolbox import build_core_toolbox

        toolbox = build_core_toolbox(work_root=tmp_path)
        result = await toolbox.execute(
            ToolCall(id="call-1", name="computer_use", arguments={"action": "status"})
        )
        assert result.status == "ok"
        assert "没有桌面任务" in result.content

        auto = build_core_toolbox(work_root=tmp_path, permission_preset="auto")
        started = await auto.execute(
            ToolCall(id="call-2", name="computer_use", arguments={"action": "start", "goal": "装配验证"})
        )
        assert started.status == "ok"
        assert started.metadata["state"] == "running"

        stopped = await auto.execute(
            ToolCall(id="call-3", name="computer_use", arguments={"action": "stop"})
        )
        assert stopped.status == "ok"
        assert stopped.metadata["state"] == "stopped"


# ---------------------------------------------------------------------------
# 界面用的 HTTP 状态与控制端点
# ---------------------------------------------------------------------------


class TestStatusEndpoint:
    @pytest.fixture()
    def client(self):
        fastapi = pytest.importorskip("fastapi")
        pytest.importorskip("fastapi.testclient")
        from fastapi.testclient import TestClient

        from lamtools_core.http.routes import create_core_router

        app = fastapi.FastAPI()
        app.include_router(create_core_router(), prefix="/api/core")
        return TestClient(app)

    def test_reports_no_active_task(self, client):
        response = client.get("/api/core/computer-use/status")
        assert response.status_code == 200
        assert response.json() == {"active": False, "session": None}

    def test_reports_running_task(self, client):
        session.start("在设置里关掉通知")
        payload = client.get("/api/core/computer-use/status").json()
        assert payload["active"] is True
        assert payload["session"]["goal"] == "在设置里关掉通知"
        assert payload["session"]["state"] == "running"

    def test_control_pause_resume_stop(self, client):
        session.start("测试控制")
        paused = client.post("/api/core/computer-use/control", json={"action": "pause"})
        assert paused.status_code == 200
        assert paused.json()["session"]["state"] == "paused"

        resumed = client.post("/api/core/computer-use/control", json={"action": "resume"})
        assert resumed.status_code == 200
        assert resumed.json()["session"]["state"] == "running"

        stopped = client.post("/api/core/computer-use/control", json={"action": "stop"})
        assert stopped.status_code == 200
        assert stopped.json()["session"]["state"] == "stopped"

    def test_control_without_task_is_404(self, client):
        response = client.post("/api/core/computer-use/control", json={"action": "pause"})
        assert response.status_code == 404

    def test_unknown_control_action_is_400(self, client):
        session.start("测试控制")
        response = client.post("/api/core/computer-use/control", json={"action": "explode"})
        assert response.status_code == 400
