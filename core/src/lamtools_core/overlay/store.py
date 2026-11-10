"""桌面交互层的状态：标记集合、过期、窗口绑定、用户批注队列。

user:“AI 直接在屏幕上标记、绘制、互动、发弹幕：箭头、框选、高亮、涂鸦、文字、
悬浮控件、动态提示。标记可跟随窗口和对象，用户能直接点击、圈选、批注，与
Agent 实时互动。”+(标注是屏幕上的临时表达，状态放进程内存即可；窗口跟随的
几何换算交给覆盖层做，这里只记住标记创建时窗口的原矩形)。

坐标一律是虚拟桌面的物理像素，和 ``computer_use``、桌宠覆盖层保持同一套约定。
"""

from __future__ import annotations

import functools
import re
import threading
import time
import uuid
from typing import Any, Callable, Iterable

# 单次工具调用最多画多少个，防止一次请求把屏幕铺满。
MAX_BATCH = 40
# 覆盖层同时存在的标记上限：超过就拒绝新的一批，而不是悄悄丢最旧的。
MAX_MARKS = 400
# 默认保留时间：静态标注活久一点，表情包是瞬时的，默认 3 秒。
# 弹幕没有固定默认值：它的寿命要够飘完一整屏，见 _danmaku_auto_ttl。
DEFAULT_TTL = 30.0
DEFAULT_TTL_BY_KIND = {"sticker": 3.0}
# 弹幕默认寿命的估算基准：最宽常见画布、默认字号、基准速度。页面拿到实际视口
# 之后还会再夹一次，这里只需要保证「默认不会半路消失」。
DANMAKU_REFERENCE_WIDTH = 2560.0
DANMAKU_BASE_SPEED = 240.0
DANMAKU_BASE_FONT = 24.0
MAX_TTL = 86_400.0
# 瞬时表演：进入方式、缓动与来源方向。
MOTION_TYPES = {"fade", "pop", "float", "drift", "danmaku"}
MOTION_EASINGS = {"linear", "ease-out", "ease-in-out"}
MOTION_FROM = {"right", "left", "center", "top", "bottom"}
# SVG 逐渐画出：按描边顺序画、整块揭开、或不画。
DRAW_MODES = {"stroke", "reveal", "none"}
# 自由涂鸦最多采多少点，避免一条线撑爆状态。
MAX_PEN_POINTS = 2_000
# 一个 SVG 标记里最多多少个图形，防止一次请求塞进整张画。
MAX_SVG_SHAPES = 200
# 圈选请求的有效期：交互层没开的时候不要等半小时再突然弹出来。
CAPTURE_REQUEST_TTL = 30.0

KIND_POINT_RULES: dict[str, tuple[int, int]] = {
    "arrow": (2, 2),
    "rect": (2, 2),
    "ellipse": (2, 2),
    "pen": (2, MAX_PEN_POINTS),
    "text": (1, 1),
    "svg": (2, 2),
    # 弹幕只给一条轨道的高度，表情包只给中心点。
    "danmaku": (1, 1),
    "sticker": (1, 1),
}

# 受控 SVG：只接受这些图形，每个图形只接受这些属性。
# user:“可以直接绘制 svg 上去吗”+(给 Agent 任意线条和图形，但不解析原始
# SVG 字符串：白名单形状 + 白名单属性，脚本、外链和事件处理器一律进不来)。
SVG_SHAPE_FIELDS: dict[str, set[str]] = {
    "path": {"d", "fill", "stroke", "strokeWidth", "opacity", "fillOpacity", "strokeOpacity", "transform"},
    "line": {"x1", "y1", "x2", "y2", "stroke", "strokeWidth", "opacity", "strokeDasharray", "transform"},
    "rect": {"x", "y", "width", "height", "rx", "ry", "fill", "stroke", "strokeWidth", "opacity", "fillOpacity", "strokeOpacity", "transform"},
    "circle": {"cx", "cy", "r", "fill", "stroke", "strokeWidth", "opacity", "fillOpacity", "strokeOpacity", "transform"},
    "ellipse": {"cx", "cy", "rx", "ry", "fill", "stroke", "strokeWidth", "opacity", "fillOpacity", "strokeOpacity", "transform"},
    "polyline": {"points", "fill", "stroke", "strokeWidth", "opacity", "strokeDasharray", "transform"},
    "polygon": {"points", "fill", "stroke", "strokeWidth", "opacity", "strokeDasharray", "transform"},
    "text": {"x", "y", "text", "fontSize", "fill", "stroke", "opacity", "textAnchor", "transform"},
}
SVG_NUMERIC_FIELDS = {
    "x", "y", "width", "height", "rx", "ry", "cx", "cy", "r", "x1", "y1", "x2", "y2",
    "fontSize", "strokeWidth", "opacity", "fillOpacity", "strokeOpacity",
}
SVG_STRING_FIELDS = {"d", "points", "text", "fill", "stroke", "transform", "textAnchor", "strokeDasharray"}

WindowResolver = Callable[[int], dict[str, Any] | None]


def _now() -> float:
    return time.time()


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} 需要数字，收到 {value!r}")
    return float(value)


def _point(raw: Any, index: int) -> list[float]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise ValueError(f"第 {index + 1} 个点需要 [x, y]，收到 {raw!r}")
    return [_number(raw[0], f"points[{index}][0]"), _number(raw[1], f"points[{index}][1]")]


def _normalize_points(raw: Any, kind: str) -> list[list[float]]:
    if not isinstance(raw, (list, tuple)):
        raise ValueError("points 需要 [[x, y], ...]")
    minimum, maximum = KIND_POINT_RULES[kind]
    if not minimum <= len(raw) <= maximum:
        if minimum == maximum:
            raise ValueError(f"{kind} 需要 {minimum} 个点，收到 {len(raw)} 个")
        raise ValueError(f"{kind} 需要 {minimum} 到 {maximum} 个点，收到 {len(raw)} 个")
    return [_point(item, index) for index, item in enumerate(raw)]


def _normalize_color(raw: Any) -> str:
    value = str(raw or "").strip()
    if not value:
        return "#ff5c8a"
    if len(value) > 32:
        raise ValueError("color 最长 32 个字符")
    return value


def _normalize_width(raw: Any) -> float:
    if raw is None or raw == "":
        return 3.0
    width = _number(raw, "width")
    if not 0.5 <= width <= 24:
        raise ValueError("width 需要在 0.5 到 24 之间")
    return width


def _danmaku_auto_ttl(text: str) -> float:
    """弹幕的默认寿命：按跨完一屏需要的时间估算。

    user:“速度根据长度调整快慢，越长越慢”+(默认 3 秒时，一句二十来字的弹幕在
    宽屏上要飘六到九秒，走到屏幕三分之一就被寿命抹掉，等于没飘完；默认寿命必须
    跟着句子长短走，长句给更久)。
    """
    width = 0.0
    for char in text or "":
        width += DANMAKU_BASE_FONT if ord(char) >= 0x2E80 else DANMAKU_BASE_FONT * 0.58
    width = max(DANMAKU_BASE_FONT * 1.6, width + 16)
    crossing = (DANMAKU_REFERENCE_WIDTH + width) / DANMAKU_BASE_SPEED
    return round(min(60.0, max(4.0, crossing)), 2)


def _locked(method):
    """串行化状态变更：HTTP 轮询和工具执行在两条线程上，字典不能边走边改。"""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


def _normalize_ttl(raw: Any, kind: str, text: str = "") -> float:
    if raw is None or raw == "":
        if kind == "danmaku":
            return _danmaku_auto_ttl(text)
        return DEFAULT_TTL_BY_KIND.get(kind, DEFAULT_TTL)
    ttl = _number(raw, "ttl")
    if not 0 < ttl <= MAX_TTL:
        raise ValueError(f"ttl 需要在 0 到 {MAX_TTL} 秒之间")
    return ttl


def _normalize_motion(raw: Any, kind: str, ttl: float) -> dict[str, Any]:
    default_type = "danmaku" if kind == "danmaku" else ("pop" if kind == "sticker" else "fade")
    default_from = "right" if kind == "danmaku" else "center"
    source = raw if isinstance(raw, dict) else {}
    motion_type = str(source.get("type") or default_type).strip().lower()
    if motion_type not in MOTION_TYPES:
        raise ValueError(f"不支持的 motion.type {motion_type!r}，可选：{', '.join(sorted(MOTION_TYPES))}")
    easing = str(source.get("easing") or ("linear" if motion_type == "danmaku" else "ease-out")).strip().lower()
    if easing not in MOTION_EASINGS:
        raise ValueError(f"不支持的 easing {easing!r}")
    origin = str(source.get("from") or default_from).strip().lower()
    if origin not in MOTION_FROM:
        raise ValueError(f"不支持的 from {origin!r}")
    duration = source.get("duration")
    if duration in (None, ""):
        duration = ttl if motion_type == "danmaku" else min(ttl, 0.8)
    else:
        duration = _number(duration, "motion.duration")
    fade = source.get("fade")
    if fade in (None, ""):
        fade = min(0.5, ttl * 0.3)
    else:
        fade = _number(fade, "motion.fade")
    if not 0.05 <= duration <= MAX_TTL:
        raise ValueError("motion.duration 需要在 0.05 秒以上")
    if not 0 <= fade <= duration:
        raise ValueError("motion.fade 需要在 0 到 duration 之间")
    return {
        "type": motion_type,
        "duration": round(duration, 3),
        "fade": round(fade, 3),
        "easing": easing,
        "from": origin,
    }


def _normalize_draw(raw: Any, kind: str, ttl: float) -> dict[str, Any] | None:
    if raw in (None, "", False):
        if kind != "svg":
            return None
        raw = {}
    if raw is True:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("draw 需要对象或 true")
    mode = str(raw.get("mode") or "stroke").strip().lower()
    if mode not in DRAW_MODES:
        raise ValueError(f"不支持的 draw.mode {mode!r}")
    if mode == "none":
        return {"mode": "none", "duration": 0.0}
    duration = raw.get("duration")
    duration = min(ttl * 0.6, 0.8) if duration in (None, "") else _number(duration, "draw.duration")
    if not 0.05 <= duration <= MAX_TTL:
        raise ValueError("draw.duration 需要 0.05 秒以上")
    # user:“不用专门分段，而是做流式渲染”+(每个图形从它到达屏幕的那一刻开始画，
    # 后续追加的图形接着画；不加人为的整批延迟)。
    return {"mode": mode, "duration": round(duration, 3)}


def _normalize_image(raw: Any) -> dict[str, Any] | None:
    if raw in (None, "", {}):
        return None
    if not isinstance(raw, dict):
        raise ValueError("image 需要 {asset, width, height}")
    asset = str(raw.get("asset") or "").strip()
    if not re.fullmatch(r"[a-z0-9]{8,40}\.(png|jpg|jpeg|webp|gif|bmp)", asset):
        raise ValueError("image.asset 需要服务端生成的资源名")
    width = raw.get("width")
    height = raw.get("height")
    result: dict[str, Any] = {"asset": asset}
    if width not in (None, ""):
        result["width"] = _number(width, "image.width")
    if height not in (None, ""):
        result["height"] = _number(height, "image.height")
    return result


def _normalize_text(raw: Any) -> str:
    return str(raw or "").strip()[:400]


def _safe_svg_string(raw: Any, field: str, *, max_length: int = 2_000) -> str:
    value = str(raw if raw is not None else "").strip()
    if not value:
        return ""
    if len(value) > max_length:
        raise ValueError(f"{field} 最长 {max_length} 个字符")
    lowered = value.lower()
    for token in ("<", ">", "javascript:", "url(", "&#"):
        if token in lowered:
            raise ValueError(f"{field} 含有不安全的片段 {token!r}")
    if field == "transform":
        allowed = set("0123456789 .,()abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-")
        if any(char not in allowed for char in value):
            raise ValueError("transform 只允许 SVG 变换函数与数字")
    return value


def _normalize_svg_shape(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"SVG 图形需要对象，收到 {raw!r}")
    shape_type = str(raw.get("type") or "").strip().lower()
    fields = SVG_SHAPE_FIELDS.get(shape_type)
    if fields is None:
        raise ValueError(
            f"不支持的 SVG 图形 {shape_type!r}，可选：{', '.join(SVG_SHAPE_FIELDS)}"
        )
    unknown = {str(key) for key in raw if str(key) not in fields and str(key) != "type"}
    if unknown:
        raise ValueError(f"{shape_type} 不支持这些属性：{', '.join(sorted(unknown))}")

    shape: dict[str, Any] = {"type": shape_type}
    for key, value in raw.items():
        if key == "type":
            continue
        name = str(key)
        if name in SVG_NUMERIC_FIELDS:
            number = _number(value, f"{shape_type}.{name}")
            if name in {"opacity", "fillOpacity", "strokeOpacity"}:
                if not 0 <= number <= 1:
                    raise ValueError(f"{name} 需要在 0 到 1 之间")
            elif name == "fontSize":
                if not 1 <= number <= 400:
                    raise ValueError("fontSize 需要在 1 到 400 之间")
            elif name == "strokeWidth":
                if not 0 <= number <= 100:
                    raise ValueError("strokeWidth 需要在 0 到 100 之间")
            elif not -100_000 <= number <= 100_000:
                raise ValueError(f"{name} 超出可绘制范围")
            shape[name] = number
        elif name in SVG_STRING_FIELDS:
            shape[name] = _safe_svg_string(value, f"{shape_type}.{name}")
        else:
            raise ValueError(f"{shape_type} 不支持属性 {name}")
    if shape_type == "path" and not shape.get("d"):
        raise ValueError("path 需要非空 d")
    if shape_type == "text" and not shape.get("text"):
        raise ValueError("text 需要非空 text")
    return shape


def _normalize_svg(item: dict[str, Any], points: list[list[float]]) -> dict[str, Any]:
    raw_shapes = item.get("shapes")
    if not isinstance(raw_shapes, (list, tuple)) or not raw_shapes:
        raise ValueError("svg 标记需要非空 shapes")
    if len(raw_shapes) > MAX_SVG_SHAPES:
        raise ValueError(f"一个 svg 最多 {MAX_SVG_SHAPES} 个图形，收到 {len(raw_shapes)} 个")

    width = abs(points[1][0] - points[0][0])
    height = abs(points[1][1] - points[0][1])
    raw_view_box = item.get("viewBox", item.get("view_box"))
    if raw_view_box in (None, "", []):
        view_box = [0.0, 0.0, width or 1.0, height or 1.0]
    else:
        if not isinstance(raw_view_box, (list, tuple)) or len(raw_view_box) != 4:
            raise ValueError("viewBox 需要 [minX, minY, width, height]")
        view_box = [_number(value, "viewBox") for value in raw_view_box]
        if view_box[2] <= 0 or view_box[3] <= 0:
            raise ValueError("viewBox 的宽高需要大于 0")
    return {"viewBox": view_box, "shapes": [_normalize_svg_shape(shape) for shape in raw_shapes]}


def _default_window_resolver(window_id: int) -> dict[str, Any] | None:
    """用 computer_use 的窗口查询拿真实矩形；拿不到就返回 None 降级。"""
    try:
        from lamtools_core.computer_use import win32

        info = win32.window_info(window_id)
    except Exception:  # noqa: BLE001 - 窗口查询失败不能阻断画标记
        return None
    if info is None or info.width <= 0 or info.height <= 0:
        return None
    return {
        "id": window_id,
        "title": str(info.title or ""),
        "bounds": [int(info.x), int(info.y), int(info.width), int(info.height)],
    }


class Store:
    """标注集合与批注队列。所有变更都让版本号前进，覆盖层按版本刷新。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._marks: dict[str, dict[str, Any]] = {}
        self._version = 0
        self._window_resolver: WindowResolver = _default_window_resolver
        # 外部程序可以让交互层进框选态：这里只记一个请求，桌面端页面轮询到就执行。
        self._capture_requested_at: float | None = None

    @property
    def _capture_requested(self) -> bool:
        at = self._capture_requested_at
        # 交互层没开时不要把这个请求一直挂着：过期就当没发生过。
        return at is not None and _now() - at <= CAPTURE_REQUEST_TTL

    @_locked
    def request_capture(self) -> None:
        """请求交互层进入框选态（外部 API 与工具共用）。"""
        self._capture_requested_at = _now()
        self._touch()

    @_locked
    def take_capture_request(self) -> bool:
        """页面取走请求：取一次就清掉，避免重复进框选。"""
        if not self._capture_requested:
            self._capture_requested_at = None
            return False
        self._capture_requested_at = None
        self._touch()
        return True

    # -- 窗口绑定 ---------------------------------------------------------

    def set_window_resolver(self, resolver: WindowResolver) -> None:
        self._window_resolver = resolver

    # -- 标记 -------------------------------------------------------------

    @_locked
    def apply(self, marks: Iterable[Any]) -> list[str]:
        raw_marks = list(marks or [])
        if not raw_marks:
            raise ValueError("marks 不能为空")
        if len(raw_marks) > MAX_BATCH:
            raise ValueError(f"一次最多画 {MAX_BATCH} 个标记，收到 {len(raw_marks)} 个")
        if len(self._marks) + len(raw_marks) > MAX_MARKS:
            raise ValueError(f"屏幕上最多同时有 {MAX_MARKS} 个标记，先清掉一些再画")

        prepared: list[dict[str, Any]] = []
        for item in raw_marks:
            if not isinstance(item, dict):
                raise ValueError(f"每个标记需要对象，收到 {item!r}")
            kind = str(item.get("kind") or "").strip().lower()
            if kind not in KIND_POINT_RULES:
                raise ValueError(f"不支持的标记类型 {kind!r}，可选：{', '.join(KIND_POINT_RULES)}")
            points = _normalize_points(item.get("points"), kind)
            text = _normalize_text(item.get("text"))
            if kind == "text" and not text:
                raise ValueError("text 标记需要非空 text")
            image = _normalize_image(item.get("image"))
            if kind in {"danmaku", "sticker"} and not text and not image:
                raise ValueError(f"{kind} 需要 text 或 image")
            svg = _normalize_svg(item, points) if kind == "svg" else None
            ttl = _normalize_ttl(item.get("ttl"), kind, text)
            motion = _normalize_motion(item.get("motion"), kind, ttl)
            draw = _normalize_draw(item.get("draw"), kind, ttl)
            window_id = item.get("window_id")
            window: dict[str, Any] | None = None
            window_missing = False
            if window_id not in (None, "", 0, "0"):
                try:
                    numeric_id = int(window_id)
                except (TypeError, ValueError):
                    raise ValueError(f"window_id 需要整数，收到 {window_id!r}") from None
                window = self._window_resolver(numeric_id)
                window_missing = window is None
            prepared.append(
                {
                    "kind": kind,
                    "points": points,
                    "color": _normalize_color(item.get("color")),
                    "width": _normalize_width(item.get("width")),
                    "text": text,
                    "ttl": ttl,
                    "motion": motion,
                    "window": window,
                    "window_missing": window_missing,
                    "label": _normalize_text(item.get("label")),
                    **({"viewBox": svg["viewBox"], "shapes": svg["shapes"]} if svg else {}),
                    **({"draw": draw} if draw else {}),
                    **({"image": image} if image else {}),
                }
            )

        now = _now()
        ids: list[str] = []
        for item in prepared:
            mark_id = f"mk-{uuid.uuid4().hex[:10]}"
            mark = {
                "id": mark_id,
                **item,
                "created_at": now,
                "expires_at": now + item["ttl"],
                "source": "agent",
            }
            if "shapes" in mark:
                mark["shapes"] = [{**shape, "added_at": now} for shape in mark["shapes"]]
            self._marks[mark_id] = mark
            ids.append(mark_id)
        self._touch()
        return ids

    @_locked
    def append_shapes(self, mark_id: str, shapes: Iterable[Any]) -> int:
        """给已有 svg 标记追加图形，前端按到达时间接着画。"""
        mark = self._marks.get(str(mark_id))
        if mark is None:
            raise ValueError(f"找不到标记 {mark_id}")
        if mark.get("kind") != "svg":
            raise ValueError("只能给 svg 标记追加图形")
        raw_shapes = list(shapes or [])
        if not raw_shapes:
            raise ValueError("shapes 不能为空")
        if len(mark["shapes"]) + len(raw_shapes) > MAX_SVG_SHAPES:
            raise ValueError(f"一个 svg 最多 {MAX_SVG_SHAPES} 个图形")
        now = _now()
        normalized = []
        for shape in raw_shapes:
            item = _normalize_svg_shape(shape)
            item["added_at"] = now
            normalized.append(item)
        mark["shapes"] = [*mark["shapes"], *normalized]
        # 追加会让标记重新活一会儿，避免画到一半整条过期。
        mark["expires_at"] = now + float(mark["ttl"])
        self._touch()
        return len(normalized)

    @_locked
    def clear(self, *, ids: Iterable[str] | None = None, all_marks: bool = False) -> int:
        # user:“对代码进行审查，不要出错或者低级漏洞或问题”+(外部调用者传字符串
        # ids 时会被按字符迭代误删，传字符串 "false" 会被当成真清空整屏)。
        if not isinstance(all_marks, bool):
            raise ValueError("all 需要布尔值 true/false")
        if isinstance(ids, (str, bytes)):
            raise ValueError("ids 需要字符串数组")
        if all_marks:
            removed = len(self._marks)
            self._marks.clear()
            if removed:
                self._touch()
            return removed
        wanted = {str(item) for item in (ids or [])}
        if not wanted:
            raise ValueError("清除需要 ids，或者 all=true 清空")
        removed = 0
        for mark_id in list(self._marks):
            if mark_id in wanted:
                self._marks.pop(mark_id, None)
                removed += 1
        if removed:
            self._touch()
        return removed

    @_locked
    def prune_expired(self, *, now: float | None = None) -> int:
        moment = _now() if now is None else now
        expired = [
            mark_id
            for mark_id, mark in self._marks.items()
            if float(mark.get("expires_at") or 0) <= moment
        ]
        for mark_id in expired:
            self._marks.pop(mark_id, None)
        if expired:
            self._touch()
        return len(expired)

    # -- 快照 -------------------------------------------------------------

    @_locked
    def snapshot(self) -> dict[str, Any]:
        self.prune_expired()
        return {
            "version": self._version,
            "server_time": _now(),
            "marks": [dict(mark) for mark in self._marks.values()],
            # 外部 API 触发的一次圈选请求：页面读走之后这里变回 False。
            "capture_requested": self._capture_requested,
        }

    def _touch(self) -> None:
        self._version += 1


_STORE = Store()


def current() -> Store:
    return _STORE


def clear() -> None:
    """测试与进程清理用：状态归零，窗口解析函数恢复默认。"""
    global _STORE
    _STORE = Store()
