"""desktop_overlay 验收测试：标注状态、坐标、过期、批注队列、工具参数与注册。

user:“AI 直接在屏幕上标记、绘制、互动、发弹幕：箭头、框选、高亮、涂鸦、文字、
悬浮控件、动态提示。标记可跟随窗口和对象，用户能直接点击、圈选、批注，与
Agent 实时互动。”+(先证明标注能存住、能过期、能按 id 清除，用户批注能回到会话；
窗口跟随的换算在前端测试里证明)。

这里不碰真实窗口枚举：窗口矩形由注入的解析函数提供，测试可预测。
"""

from __future__ import annotations

import time

import pytest

from lamtools_core.overlay import store as overlay_store
from lamtools_core.overlay import tools as overlay_tools
from lamtools_core.tool import ToolCall


@pytest.fixture(autouse=True)
def _clean_store():
    overlay_store.clear()
    yield
    overlay_store.clear()


def _mark(**overrides):
    base = {"kind": "arrow", "points": [[100, 100], [300, 200]]}
    base.update(overrides)
    return base


def _call(**arguments):
    return ToolCall(id="call-overlay", name="desktop_overlay", arguments=arguments)


# ---------------------------------------------------------------------------
# 标注状态
# ---------------------------------------------------------------------------


class TestMarkState:
    def test_apply_assigns_ids_and_keeps_order(self):
        store = overlay_store.current()
        ids = store.apply([_mark(kind="arrow"), _mark(kind="text", points=[[10, 10]], text="看这里")])
        assert len(ids) == 2
        assert ids[0] != ids[1]
        state = store.snapshot()
        assert [mark["kind"] for mark in state["marks"]] == ["arrow", "text"]
        assert state["marks"][1]["text"] == "看这里"

    def test_rejects_unknown_kind(self):
        store = overlay_store.current()
        with pytest.raises(ValueError):
            store.apply([_mark(kind="laser")])

    def test_rejects_wrong_point_count(self):
        store = overlay_store.current()
        with pytest.raises(ValueError):
            store.apply([_mark(kind="arrow", points=[[1, 2]])])
        with pytest.raises(ValueError):
            store.apply([_mark(kind="rect", points=[[1, 2]])])
        with pytest.raises(ValueError):
            store.apply([_mark(kind="text", points=[[1, 2]], text="")])

    def test_rejects_non_numeric_points(self):
        store = overlay_store.current()
        with pytest.raises(ValueError):
            store.apply([_mark(points=[["x", 2], [3, 4]])])

    def test_rejects_more_than_batch_limit(self):
        store = overlay_store.current()
        with pytest.raises(ValueError):
            store.apply([_mark() for _ in range(overlay_store.MAX_BATCH + 1)])

    def test_total_limit_is_enforced(self):
        store = overlay_store.current()
        for _ in range(overlay_store.MAX_MARKS // overlay_store.MAX_BATCH):
            store.apply([_mark() for _ in range(overlay_store.MAX_BATCH)])
        with pytest.raises(ValueError):
            store.apply([_mark()] * (overlay_store.MAX_BATCH if overlay_store.MAX_MARKS % overlay_store.MAX_BATCH == 0 else 1))

    def test_ttl_marks_expire(self):
        store = overlay_store.current()
        store.apply([_mark(ttl=0.2)])
        assert len(store.snapshot()["marks"]) == 1
        time.sleep(0.25)
        assert store.prune_expired() == 1
        assert store.snapshot()["marks"] == []

    def test_clear_by_id_keeps_others(self):
        store = overlay_store.current()
        first, second = store.apply([_mark(), _mark(kind="rect")])
        assert store.clear(ids=[first]) == 1
        remaining = store.snapshot()["marks"]
        assert [mark["id"] for mark in remaining] == [second]

    def test_clear_all(self):
        store = overlay_store.current()
        store.apply([_mark(), _mark()])
        assert store.clear(all_marks=True) == 2
        assert store.snapshot()["marks"] == []

    def test_state_version_advances_on_change(self):
        store = overlay_store.current()
        start = store.snapshot()["version"]
        store.apply([_mark()])
        assert store.snapshot()["version"] > start

    def test_window_target_is_recorded(self):
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: {"id": window_id, "title": "记事本", "bounds": [10, 20, 800, 600]})
        ids = store.apply([_mark(window_id=4242)])
        mark = next(item for item in store.snapshot()["marks"] if item["id"] == ids[0])
        assert mark["window"]["id"] == 4242
        assert mark["window"]["bounds"] == [10, 20, 800, 600]

    def test_unknown_window_degrades_to_screen_coordinates(self):
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        ids = store.apply([_mark(window_id=999)])
        mark = next(item for item in store.snapshot()["marks"] if item["id"] == ids[0])
        assert mark["window"] is None
        assert mark["window_missing"] is True


# ---------------------------------------------------------------------------
# 批注队列
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


class TestTool:
    def test_show_returns_ids_and_marks_are_visible(self):
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        result = overlay_tools.handle(_call(action="show", marks=[_mark()]))
        assert result.status == "ok"
        assert "1" in result.content
        assert len(store.snapshot()["marks"]) == 1
        assert result.metadata["ids"]

    def test_show_requires_marks(self):
        result = overlay_tools.handle(_call(action="show"))
        assert result.status == "failed"
        assert "marks" in result.error

    def test_show_rejects_empty_list(self):
        result = overlay_tools.handle(_call(action="show", marks=[]))
        assert result.status == "failed"

    def test_clear_by_ids(self):
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        ids = store.apply([_mark(), _mark(kind="ellipse")])
        result = overlay_tools.handle(_call(action="clear", ids=[ids[0]]))
        assert result.status == "ok"
        assert len(store.snapshot()["marks"]) == 1

    def test_clear_all(self):
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        store.apply([_mark()])
        # user:“对代码进行审查，不要出错或者低级漏洞或问题”+(all 传字符串
        # "false" 时不能真值化成清空整屏)。
        rejected = overlay_tools.handle(_call(action="clear", all="false"))
        assert rejected.status == "failed"
        assert "布尔" in rejected.error
        assert len(store.snapshot()["marks"]) == 1

        rejected_ids = overlay_tools.handle(_call(action="clear", ids="mk-1234567890"))
        assert rejected_ids.status == "failed"
        assert "数组" in rejected_ids.error

        result = overlay_tools.handle(_call(action="clear", all=True))
        assert result.status == "ok"
        assert store.snapshot()["marks"] == []

    def test_list_reports_marks(self):
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        store.apply([_mark()])
        result = overlay_tools.handle(_call(action="list"))
        assert result.status == "ok"
        assert result.metadata["mark_count"] == 1

    def test_capture_action_requests_the_overlay_to_pick_a_region(self):
        active = overlay_store.current()
        active.set_window_resolver(lambda window_id: None)
        result = overlay_tools.handle(_call(action="capture"))
        assert result.status == "ok"
        assert active.snapshot()["capture_requested"] is True
        # 取走一次就清掉，避免页面每轮都进框选。
        assert active.take_capture_request() is True
        assert active.snapshot()["capture_requested"] is False

    def test_unknown_action_fails(self):
        result = overlay_tools.handle(_call(action="dance"))
        assert result.status == "failed"

    def test_tool_is_auto_allowed_and_ordered(self):
        from lamtools_core.tool.default_toolbox import (
            DEFAULT_TOOL_CATEGORIES,
            DEFAULT_TOOL_ORDER,
            DEFAULT_TOOL_PERMISSIONS,
        )
        from lamtools_core.tool.permission import AUTO_ALLOW

        assert DEFAULT_TOOL_PERMISSIONS["desktop_overlay"] == AUTO_ALLOW
        assert "desktop_overlay" in DEFAULT_TOOL_ORDER
        assert DEFAULT_TOOL_CATEGORIES["desktop_overlay"] == "computer"


# ---------------------------------------------------------------------------
# HTTP：覆盖层读状态、用户批注提交
# ---------------------------------------------------------------------------


class TestRoutes:
    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from lamtools_core.http.routes import create_core_router

        app = FastAPI()
        app.include_router(create_core_router(), prefix="/api/core")
        return TestClient(app)

    def test_state_endpoint_returns_empty_snapshot(self, client):
        response = client.get("/api/core/overlay/state")
        assert response.status_code == 200
        body = response.json()
        assert body["marks"] == []

    def test_clear_endpoint_removes_marks(self, client):
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        store.apply([_mark()])
        response = client.post("/api/core/overlay/control", json={"action": "clear", "all": True})
        assert response.status_code == 200
        assert response.json()["removed"] == 1
        assert store.snapshot()["marks"] == []

    def test_capture_endpoint_flags_one_request_and_ack_clears_it(self, client):
        # user:“对外开放API，可外部调用批注功能”+(外部程序请求圈选，页面取走一次就清掉)。
        created = client.post("/api/core/overlay/control", json={"action": "capture"})
        assert created.status_code == 200
        assert created.json()["capture_requested"] is True

        state = client.get("/api/core/overlay/state")
        assert state.json()["capture_requested"] is True

        acked = client.post("/api/core/overlay/control", json={"action": "capture_ack"})
        assert acked.status_code == 200
        assert acked.json()["capture_requested"] is False
        assert client.get("/api/core/overlay/state").json()["capture_requested"] is False

    def test_unknown_control_action_is_rejected(self, client):
        response = client.post("/api/core/overlay/control", json={"action": "nope"})
        assert response.status_code == 400

    def test_show_endpoint_draws_the_same_state_the_tool_sees(self, client):
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        response = client.post(
            "/api/core/overlay/control",
            json={"action": "show", "marks": [_mark(kind="rect")]},
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["ids"]) == 1
        assert [mark["kind"] for mark in body["marks"]] == ["rect"]


# ---------------------------------------------------------------------------
# SVG 标记：受控图形，不解析任意 SVG 字符串
# ---------------------------------------------------------------------------


class TestSvgMark:
    def test_svg_mark_keeps_shapes_and_viewbox(self):
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        ids = store.apply([
            _mark(
                kind="svg",
                points=[[100, 100], [400, 300]],
                viewBox=[0, 0, 300, 200],
                shapes=[
                    {"type": "path", "d": "M 0 0 L 300 200", "stroke": "#ff5c8a", "strokeWidth": 3},
                    {"type": "circle", "cx": 150, "cy": 100, "r": 40, "fill": "#7aa8ff", "opacity": 0.5},
                ],
            )
        ])
        mark = next(item for item in store.snapshot()["marks"] if item["id"] == ids[0])
        assert mark["kind"] == "svg"
        assert mark["viewBox"] == [0, 0, 300, 200]
        assert [shape["type"] for shape in mark["shapes"]] == ["path", "circle"]

    def test_svg_defaults_viewbox_to_bounding_box(self):
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        ids = store.apply([
            _mark(
                kind="svg",
                points=[[100, 100], [400, 300]],
                shapes=[{"type": "line", "x1": 0, "y1": 0, "x2": 300, "y2": 200, "stroke": "#fff"}],
            )
        ])
        mark = next(item for item in store.snapshot()["marks"] if item["id"] == ids[0])
        assert mark["viewBox"] == [0, 0, 300, 200]

    def test_svg_requires_shapes(self):
        store = overlay_store.current()
        with pytest.raises(ValueError):
            store.apply([_mark(kind="svg", points=[[0, 0], [100, 100]])])

    def test_svg_rejects_unknown_shape_type(self):
        store = overlay_store.current()
        with pytest.raises(ValueError):
            store.apply([_mark(kind="svg", points=[[0, 0], [100, 100]], shapes=[{"type": "script"}])])

    def test_svg_rejects_unknown_attribute(self):
        store = overlay_store.current()
        with pytest.raises(ValueError):
            store.apply([
                _mark(
                    kind="svg",
                    points=[[0, 0], [100, 100]],
                    shapes=[{"type": "rect", "x": 0, "y": 0, "width": 10, "height": 10, "onclick": "alert(1)"}],
                )
            ])

    def test_svg_rejects_external_url(self):
        store = overlay_store.current()
        with pytest.raises(ValueError):
            store.apply([
                _mark(
                    kind="svg",
                    points=[[0, 0], [100, 100]],
                    shapes=[{"type": "rect", "x": 0, "y": 0, "width": 10, "height": 10, "fill": "url(http://evil/x)"}],
                )
            ])

    def test_svg_rejects_script_text(self):
        store = overlay_store.current()
        with pytest.raises(ValueError):
            store.apply([
                _mark(
                    kind="svg",
                    points=[[0, 0], [100, 100]],
                    shapes=[{"type": "text", "x": 0, "y": 10, "text": "<script>alert(1)</script>"}],
                )
            ])

    def test_svg_limits_shape_count(self):
        store = overlay_store.current()
        shapes = [{"type": "line", "x1": 0, "y1": 0, "x2": 1, "y2": 1, "stroke": "#fff"} for _ in range(overlay_store.MAX_SVG_SHAPES + 1)]
        with pytest.raises(ValueError):
            store.apply([_mark(kind="svg", points=[[0, 0], [100, 100]], shapes=shapes)])


# ---------------------------------------------------------------------------
# 瞬时表演：弹幕、表情包、受控时长与逐渐画出
# ---------------------------------------------------------------------------


class TestMotionMark:
    def test_danmaku_default_lifetime_covers_the_whole_crossing(self):
        # user:“速度根据长度调整快慢，越长越慢”+(默认 3 秒时弹幕飘到三分之一就被
        # 抹掉，永远走不到左边；默认寿命必须按句子长度估出跨屏时间)。
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        short_id = store.apply([_mark(kind="danmaku", points=[[0, 300]], text="飘过去")])[0]
        long_id = store.apply([_mark(kind="danmaku", points=[[0, 300]], text="这句特别长" * 8)])[0]
        marks = {item["id"]: item for item in store.snapshot()["marks"]}
        short_mark = marks[short_id]
        long_mark = marks[long_id]
        assert short_mark["ttl"] >= 4.0
        assert long_mark["ttl"] > short_mark["ttl"]
        assert long_mark["ttl"] <= 60.0
        # 2560 宽的参考画布，240 px/s：十来秒要飘完，寿命必须比这个基准长。
        assert short_mark["ttl"] * overlay_store.DANMAKU_BASE_SPEED >= overlay_store.DANMAKU_REFERENCE_WIDTH
        assert short_mark["motion"]["type"] == "danmaku"
        assert short_mark["motion"]["from"] == "right"

    def test_danmaku_explicit_ttl_still_wins(self):
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        ids = store.apply([_mark(kind="danmaku", points=[[0, 300]], text="短命", ttl=1.5)])
        mark = next(item for item in store.snapshot()["marks"] if item["id"] == ids[0])
        assert mark["ttl"] == 1.5

    def test_asset_retention_outlives_the_longest_mark(self):
        from lamtools_core.overlay import assets as overlay_assets

        # 资源先过期的话，长 ttl 的图片标记会裂图。
        assert overlay_assets.ASSET_TTL_SECONDS >= overlay_store.MAX_TTL

    def test_sticker_defaults_to_three_seconds_and_pop(self):
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        ids = store.apply([_mark(kind="sticker", points=[[1200, 700]], text="🎉")])
        mark = next(item for item in store.snapshot()["marks"] if item["id"] == ids[0])
        assert mark["ttl"] == 3.0
        assert mark["motion"]["type"] == "pop"

    def test_sticker_requires_text_or_image(self):
        store = overlay_store.current()
        with pytest.raises(ValueError):
            store.apply([_mark(kind="sticker", points=[[1200, 700]])])

    def test_explicit_ttl_beats_the_default(self):
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        ids = store.apply([_mark(kind="sticker", points=[[1200, 700]], text="OK", ttl=7.5)])
        mark = next(item for item in store.snapshot()["marks"] if item["id"] == ids[0])
        assert mark["ttl"] == 7.5

    def test_motion_rejects_unknown_type(self):
        store = overlay_store.current()
        with pytest.raises(ValueError):
            store.apply([_mark(kind="text", points=[[10, 10]], text="hi", motion={"type": "explode"})])

    def test_svg_defaults_to_stroke_draw(self):
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        ids = store.apply([
            _mark(
                kind="svg",
                points=[[100, 100], [400, 300]],
                shapes=[{"type": "path", "d": "M 0 0 L 300 200", "stroke": "#fff", "strokeWidth": 2}],
            )
        ])
        mark = next(item for item in store.snapshot()["marks"] if item["id"] == ids[0])
        assert mark["draw"]["mode"] == "stroke"
        assert 0.05 <= mark["draw"]["duration"] <= 1.2
        assert mark["shapes"][0]["added_at"] > 0

    def test_svg_draw_can_be_disabled(self):
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        ids = store.apply([
            _mark(
                kind="svg",
                points=[[0, 0], [100, 100]],
                draw={"mode": "none"},
                shapes=[{"type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 10, "stroke": "#fff"}],
            )
        ])
        mark = next(item for item in store.snapshot()["marks"] if item["id"] == ids[0])
        assert mark["draw"]["mode"] == "none"


class TestImageAsset:
    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from lamtools_core.http.routes import create_core_router

        app = FastAPI()
        app.include_router(create_core_router(), prefix="/api/core")
        return TestClient(app)

    def test_tool_copies_workspace_image_and_route_serves_it(self, tmp_path, client):
        from PIL import Image

        source = tmp_path / "sticker.png"
        Image.new("RGBA", (64, 64), (255, 92, 138, 255)).save(source)
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        result = overlay_tools.handle(
            _call(
                action="show",
                marks=[_mark(kind="sticker", points=[[1200, 700]], image="sticker.png", image_width=120, ttl=3)],
            ),
            work_root=tmp_path,
        )
        assert result.status == "ok"
        mark = store.snapshot()["marks"][0]
        asset = mark["image"]["asset"]
        assert asset.endswith(".png")
        assert mark["image"]["width"] == 120

        response = client.get(f"/api/core/overlay/assets/{asset}")
        assert response.status_code == 200
        assert len(response.content) > 0

    def test_image_outside_workspace_is_rejected(self, tmp_path):
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        result = overlay_tools.handle(
            _call(action="show", marks=[_mark(kind="sticker", points=[[0, 0]], image="C:/Windows/win.ini")]),
            work_root=tmp_path,
        )
        assert result.status == "failed"
        assert "工作区" in result.error or "不存在" in result.error


class TestStreamAppend:
    def test_append_adds_shapes_with_arrival_time(self):
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        ids = store.apply([
            _mark(
                kind="svg",
                points=[[0, 0], [300, 200]],
                shapes=[{"type": "path", "d": "M 0 0 L 100 100", "stroke": "#fff", "strokeWidth": 2}],
            )
        ])
        added = store.append_shapes(ids[0], [{"type": "line", "x1": 100, "y1": 100, "x2": 200, "y2": 50, "stroke": "#fff"}])
        assert added == 1
        mark = store.snapshot()["marks"][0]
        assert len(mark["shapes"]) == 2
        assert mark["shapes"][1]["added_at"] >= mark["shapes"][0]["added_at"]

    def test_append_rejects_non_svg_mark(self):
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        ids = store.apply([_mark(kind="arrow")])
        with pytest.raises(ValueError):
            store.append_shapes(ids[0], [{"type": "line", "x1": 0, "y1": 0, "x2": 1, "y2": 1, "stroke": "#fff"}])

    def test_append_extends_lifetime(self):
        store = overlay_store.current()
        store.set_window_resolver(lambda window_id: None)
        ids = store.apply([
            _mark(
                kind="svg",
                points=[[0, 0], [100, 100]],
                ttl=2,
                shapes=[{"type": "line", "x1": 0, "y1": 0, "x2": 1, "y2": 1, "stroke": "#fff"}],
            )
        ])
        before = store.snapshot()["marks"][0]["expires_at"]
        time.sleep(0.05)
        store.append_shapes(ids[0], [{"type": "line", "x1": 1, "y1": 1, "x2": 2, "y2": 2, "stroke": "#fff"}])
        after = store.snapshot()["marks"][0]["expires_at"]
        assert after > before
