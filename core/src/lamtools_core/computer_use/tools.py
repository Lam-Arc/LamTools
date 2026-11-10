"""computer_use 工具：把感知、动作、任务状态包成模型可调用的一套动作。

一次调用只做一件事。模型的工作流固定为：snapshot 看界面，click 或 type 操作，
screenshot 确认结果。工具不替模型做决策，只保证每个动作都过安全守卫，并把
截图留成证据。

user:“查一下 computer use 功能怎么做”+(Agent 像人一样操作电脑，用户能随时
接管；交互上要能看到操作目标、进度和结果)。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from lamtools_core.tool import ToolArtifact, ToolCall, ToolResult

from . import capture, session, win32
from .uia import UiaError, shared_helper

# 截图落盘目录，相对 work_root。
_ARTIFACT_DIR = Path(".lam") / "artifacts" / "computer_use"

# user:“无需做安全边界”+(不再按窗口归属、权限级别或点击落点做拦截，动作直接执行；
# 目标窗口只做存在性校验，剩下的交给用户自己掌握)。
_SELF_TITLES: set[str] = set()


def _arg(args: dict[str, Any], name: str, default: Any = None) -> Any:
    value = args.get(name, default)
    return default if value is None else value


def _int_arg(args: dict[str, Any], name: str, default: int | None = None) -> int | None:
    value = args.get(name, default)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"参数 {name} 需要整数，收到 {value!r}") from None


def _float_arg(args: dict[str, Any], name: str, default: float | None = None) -> float | None:
    value = args.get(name, default)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"参数 {name} 需要数字，收到 {value!r}") from None


def _result(call: ToolCall, *, content: str = "", error: str = "", status: str = "ok",
            artifacts: list[ToolArtifact] | None = None, metadata: dict[str, Any] | None = None,
            model_image: str = "") -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status=status,  # type: ignore[arg-type]
        content=content,
        error=error,
        artifacts=artifacts or [],
        metadata=metadata or {},
        model_image_data_url=model_image,
    )


# ---------------------------------------------------------------------------
# 目标窗口校验
# ---------------------------------------------------------------------------


def _is_self_window(info: win32.WindowInfo) -> bool:
    """仅用于诊断输出。user:“无需做安全边界”+(不再据此拒绝任何动作)。"""
    return False


def _ensure_target(hwnd: int, *, require_foreground: bool = False) -> win32.WindowInfo:
    """只确认窗口还在。不做权限、归属和前台拦截。"""
    info = win32.window_info(hwnd)
    if require_foreground and win32.foreground_window() != hwnd:
        win32.activate_window(hwnd)
    return info


# 实测不接收后台键盘消息的窗口类，命中直接走真实输入。
# Chromium 和传统 Win32 控件都能后台收键盘，所以这里只列确定不行的 WinUI 系。
_FOREGROUND_ONLY_KEYS = {
    "Notepad",                       # Windows 11 记事本，WinUI 3
    "ApplicationFrameWindow",        # UWP 外壳
    "WinUIDesktopWin32WindowClass",  # WinUI 3 桌面窗口
}

# user:“打开浏览器 然后打开 B 站，随便找一个视频 点一下收藏”+
# (实测 Chromium 网页内容不接收 PostMessage 点击：地址栏能点，网页里的卡片点了没反应，
#  所以点击对这些窗口直接走真实注入，键盘仍然走后台)。
_FOREGROUND_ONLY_CLICKS = _FOREGROUND_ONLY_KEYS | {
    "Chrome_WidgetWin_1",   # Chrome / Edge / Electron 的网页内容
    "MozillaWindowClass",   # Firefox
}


def _prefer_background(hwnd: int, *, action: str = "key") -> bool:
    try:
        info = win32.window_info(hwnd)
    except win32.Win32Error:
        return False
    table = _FOREGROUND_ONLY_CLICKS if action == "click" else _FOREGROUND_ONLY_KEYS
    return info.class_name not in table


def _active_session(action: str, *, mutating: bool = True) -> session.Session:
    current = session.current()
    if current is None:
        raise session.GuardError(
            "还没有开始桌面任务。先调用 computer_use action=start 并说明目标，再做动作。"
        )
    if mutating:
        current.guard(action)
    else:
        with current._lock:  # noqa: SLF001 - 只读状态判断，避免为读取类动作引入接管检查
            state = current.state
        if state != "running":
            raise session.GuardError(f"任务当前是 {state} 状态，不能继续。")
    return current


def _resolve_point(args: dict[str, Any], active: session.Session) -> tuple[int, int]:
    """把模型给的截图像素坐标换算成物理屏幕坐标。"""
    frame = active.last_frame
    if frame is None:
        raise ValueError("还没有截图，坐标无从换算。先调用 action=screenshot。")
    x = _float_arg(args, "x")
    y = _float_arg(args, "y")
    if x is None or y is None:
        raise ValueError("需要同时给 x 和 y，或者改用 ref。")
    if x < 0 or y < 0 or x > frame.image_width or y > frame.image_height:
        raise ValueError(
            f"坐标 {x},{y} 超出截图范围 {frame.image_width}x{frame.image_height}，"
            "坐标要按截图里的像素给。"
        )
    return frame.to_screen(x, y)


def _element_point(node: dict[str, Any]) -> tuple[int, int]:
    bounds = node.get("bounds") or [0, 0, 0, 0]
    return int(bounds[0] + bounds[2] / 2), int(bounds[1] + bounds[3] / 2)


def _target_hwnd(active: session.Session) -> int:
    return active.target_window or win32.foreground_window()


def _ensure_foreground(active: session.Session) -> None:
    """尽量把目标窗口拉到前台，失败也不阻断动作。"""
    target = active.target_window
    if not target:
        return
    if win32.foreground_window() == target:
        return
    try:
        win32.activate_window(target)
    except win32.Win32Error:
        pass


def _ensure_landing_not_self(x: int, y: int) -> None:
    """user:“无需做安全边界”+(落点不再做归属拦截，保留函数以便未来需要时恢复)。"""
    return None


# ---------------------------------------------------------------------------
# 截图
# ---------------------------------------------------------------------------


def _grab(args: dict[str, Any]) -> tuple[capture.Frame, str]:
    target = str(_arg(args, "target", "screen")).lower()
    max_width = _int_arg(args, "max_width", capture.MAX_MODEL_WIDTH) or capture.MAX_MODEL_WIDTH

    if target == "window":
        hwnd = _int_arg(args, "window_id")
        if hwnd is None:
            hwnd = win32.foreground_window()
        info = _ensure_target(hwnd)
        if info.width <= 0 or info.height <= 0:
            raise ValueError(f"窗口「{info.title}」没有可截区域，可能已最小化")
        x, y, width, height = info.x, info.y, info.width, info.height
        label = f"window-{hwnd}"
        # user:“不抢占真实鼠标的方式你可以看看 叫做 okww”+(窗口截图走 PrintWindow，
        # 被别的窗口遮住也能抓到内容，不需要把目标拉到前台)。
        raw_w, raw_h, rgba = win32.capture_window(hwnd)
    elif target == "monitor":
        monitor_id = str(_arg(args, "monitor_id", "")).strip()
        monitors = win32.monitors()
        monitor = next((m for m in monitors if m.id == monitor_id), None) if monitor_id else None
        if monitor is None:
            cx, cy = win32.cursor_position()
            monitor = win32.monitor_at(cx, cy)
        x, y, width, height = monitor.x, monitor.y, monitor.width, monitor.height
        label = f"monitor-{monitor.id}"
        raw_w, raw_h, rgba = win32.capture_rect(x, y, width, height)
    elif target == "region":
        region = _arg(args, "region")
        if not isinstance(region, (list, tuple)) or len(region) != 4:
            raise ValueError("target=region 需要 region: [x, y, width, height]，物理像素")
        x, y, width, height = (int(v) for v in region)
        label = "region"
        raw_w, raw_h, rgba = win32.capture_rect(x, y, width, height)
    else:
        x, y, width, height = win32.virtual_screen()
        label = "screen"
        raw_w, raw_h, rgba = win32.capture_rect(x, y, width, height)

    image = capture.rgba_to_image(raw_w, raw_h, rgba)

    annotate = str(_arg(args, "annotate", "none")).lower()
    if annotate == "grid":
        image = capture.annotate_grid(image)
    elif annotate == "target" and session.current() and session.current().last_action_point:
        ax, ay = session.current().last_action_point  # type: ignore[union-attr]
        image = capture.annotate_target(image, ax - x, ay - y)

    png, image_w, image_h = capture.encode_png(image, max_width=max_width)
    frame = capture.Frame(
        png=png,
        image_width=image_w,
        image_height=image_h,
        screen_width=width,
        screen_height=height,
        origin_x=x,
        origin_y=y,
    )
    return frame, label


def _save_frame(frame: capture.Frame, work_root: Path, label: str) -> str:
    directory = work_root / _ARTIFACT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{label}-{int(time.time() * 1000) % 1000:03d}.png"
    path = directory / name
    path.write_bytes(frame.png)
    try:
        return str(path.relative_to(work_root)).replace("\\", "/")
    except ValueError:
        return str(path)


def _frame_result(call: ToolCall, frame: capture.Frame, label: str, work_root: Path,
                  *, note: str = "", extra: dict[str, Any] | None = None) -> ToolResult:
    rel = _save_frame(frame, work_root, label)
    preview = capture.preview_data_url(frame.png)
    model_url = capture.to_data_url(frame.png)
    active = session.current()
    if active is not None:
        active.last_frame = frame
    meta = {
        "path": rel,
        "label": label,
        "image_width": frame.image_width,
        "image_height": frame.image_height,
        "screen_width": frame.screen_width,
        "screen_height": frame.screen_height,
        "origin": [frame.origin_x, frame.origin_y],
        "scale_x": round(frame.scale_x, 4),
        "scale_y": round(frame.scale_y, 4),
    }
    if extra:
        meta.update(extra)
    header = (
        f"[screenshot] {label} 截图 {frame.image_width}x{frame.image_height}，"
        f"对应屏幕 {frame.screen_width}x{frame.screen_height}，原点 {frame.origin_x},{frame.origin_y}。"
        "点击坐标按这张图的像素给。"
    )
    content = header + (f"\n{note}" if note else "")
    return _result(
        call,
        content=content,
        artifacts=[
            ToolArtifact(
                kind="image",
                uri=rel,
                metadata={"path": rel, "image_data_url": preview, "mime_type": "image/png"},
            )
        ],
        metadata=meta,
        model_image=model_url,
    )


# ---------------------------------------------------------------------------
# 快照
# ---------------------------------------------------------------------------


def _format_windows(windows: list[win32.WindowInfo], foreground: int) -> str:
    lines = []
    for info in windows[:24]:
        mark = "*" if info.hwnd == foreground else " "
        lines.append(
            f"{mark} window_id={info.hwnd} 「{info.title[:60]}」 {info.class_name} "
            f"{info.width}x{info.height}+{info.x}+{info.y}"
        )
    if len(windows) > 24:
        lines.append(f"... 还有 {len(windows) - 24} 个窗口")
    return "\n".join(lines)


def _format_nodes(nodes: list[dict[str, Any]]) -> str:
    lines = []
    for node in nodes:
        bounds = node.get("bounds") or [0, 0, 0, 0]
        if bounds[2] <= 0 or bounds[3] <= 0:
            continue
        flags = []
        if node.get("secure"):
            flags.append("secure")
        if node.get("offscreen"):
            flags.append("offscreen")
        if not node.get("enabled", True):
            flags.append("disabled")
        if node.get("focused"):
            flags.append("focused")
        suffix = f" ({','.join(flags)})" if flags else ""
        name = str(node.get("name") or "").strip()
        label = f' "{name[:70]}"' if name else ""
        lines.append(
            f"{node.get('ref')} {node.get('role')}{label} "
            f"[{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}]{suffix}"
        )
    return "\n".join(lines)


def _snapshot(args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    foreground = win32.foreground_window()
    windows = win32.list_windows(exclude_pids={os.getpid(), os.getppid()})
    hwnd = _int_arg(args, "window_id")
    if hwnd is None:
        hwnd = foreground or (windows[0].hwnd if windows else 0)
    if not hwnd:
        raise ValueError("找不到可用的目标窗口")

    info = _ensure_target(hwnd)
    # 记住这次快照看的是哪个窗口，后面的动作先把它拉回前台再执行。
    active = session.current()
    if active is not None:
        active.target_window = hwnd
    max_nodes = _int_arg(args, "max_nodes", 260) or 260
    include_tree = bool(_arg(args, "include_tree", True))

    parts = [
        f"[snapshot] 前台窗口 {foreground}，目标窗口「{info.title}」({hwnd}) "
        f"{info.width}x{info.height}+{info.x}+{info.y}",
        "窗口列表（* 为前台）：",
        _format_windows(windows, foreground),
    ]
    meta: dict[str, Any] = {
        "window_id": hwnd,
        "foreground": foreground,
        "window_count": len(windows),
        "tree_nodes": 0,
        "tree_truncated": False,
    }
    if include_tree:
        try:
            tree = shared_helper().tree(hwnd, max_nodes=max_nodes)
        except UiaError as exc:
            parts.append(
                f"元素树不可用：{exc}。这个应用可能没有暴露无障碍树，"
                "改用 action=screenshot 看界面，按截图像素坐标操作。"
            )
            meta["tree_error"] = str(exc)
        else:
            nodes = tree.get("nodes") or []
            body = _format_nodes(nodes)
            if body:
                parts.append("元素列表（ref 用于 click 的 ref 参数）：")
                parts.append(body)
            else:
                parts.append("元素树为空，改用截图坐标操作。")
            if tree.get("truncated"):
                parts.append(f"元素太多，只返回前 {len(nodes)} 个，可以给 max_nodes 调大或用 window_id 换窗口。")
            meta["tree_nodes"] = len(nodes)
            meta["tree_truncated"] = bool(tree.get("truncated"))
            meta["snapshot_id"] = tree.get("snapshot")
    return "\n".join(parts), meta


# ---------------------------------------------------------------------------
# 动作
# ---------------------------------------------------------------------------


def _click(args: dict[str, Any], active: session.Session) -> str:
    ref = str(_arg(args, "ref", "")).strip()
    button = str(_arg(args, "button", "left")).lower()
    count = _int_arg(args, "count", 1) or 1
    background = bool(_arg(args, "background", True))
    hwnd = _target_hwnd(active)

    if ref:
        helper = shared_helper()
        data = helper.invoke(ref)
        if data.get("invoked"):
            # 语义点击直接作用于元素，不动鼠标也不抢焦点，已经是最优路径。
            bounds = data.get("bounds") or [0, 0, 0, 0]
            active.last_action_point = _element_point(data)
            active.mark_injected()
            return f"已对元素 {ref} 执行语义点击，元素区域 {bounds}"
        x, y = _element_point(data)
    else:
        x, y = _resolve_point(args, active)

    if background and hwnd and _prefer_background(hwnd, action="click"):
        # 点击经常没有视觉反馈，按画面判断必然误判成失败，所以这里直接信任投递结果；
        # 真的没生效时，模型看截图会发现界面没动，可以传 background=false 重试。
        win32.background_click(hwnd, x, y, button=button, count=count)
        active.last_action_point = (x, y)
        active.mark_injected()
        return f"已在 {x},{y} 后台点击 {button}，没有移动你的鼠标"

    _ensure_foreground(active)
    win32.mouse_click(x, y, button=button, count=count)
    active.last_action_point = (x, y)
    active.mark_injected()
    return f"已在 {x},{y} 点击 {button}，{count} 次"


def _type(args: dict[str, Any], active: session.Session) -> str:
    text = str(_arg(args, "text", ""))
    if not text:
        raise ValueError("text 不能为空")
    if len(text) > 4000:
        raise ValueError("一次最多输入 4000 字符，长文本请分段")
    ref = str(_arg(args, "ref", "")).strip()
    mode = str(_arg(args, "mode", "unicode")).lower()
    background = bool(_arg(args, "background", True))
    hwnd = _target_hwnd(active)

    if ref:
        try:
            shared_helper().focus(ref)
        except UiaError:
            try:
                data = shared_helper().invoke(ref)
                x, y = _element_point(data)
                win32.mouse_click(x, y)
            except UiaError as exc:
                raise ValueError(f"无法聚焦元素 {ref}：{exc}") from None

    if background and hwnd and mode != "paste" and _prefer_background(hwnd):
        # 画面变化判断不可靠：有的应用输入了但界面延迟刷新，有的界面本来就在动。
        # 直接信任投递结果，模型下一步截图就能看出有没有进去；没进去可以传
        # background=false 重试，避免一次动作被重复执行两遍。
        win32.background_type(hwnd, text)
        active.mark_injected()
        return f"已后台输入 {len(text)} 个字符，没有移动你的鼠标；截图确认是否生效"

    _ensure_foreground(active)
    if mode == "paste":
        win32.set_clipboard_text(text)
        win32.press_keys(["ctrl", "v"])
    else:
        win32.type_text(text)
    active.mark_injected()
    return f"已输入 {len(text)} 个字符"


def _key(args: dict[str, Any], active: session.Session) -> str:
    keys = _arg(args, "keys")
    if isinstance(keys, str):
        keys = [part for part in keys.replace("+", " ").split() if part]
    if not isinstance(keys, (list, tuple)) or not keys:
        raise ValueError("keys 需要数组，例如 [\"ctrl\",\"shift\",\"t\"]")
    background = bool(_arg(args, "background", True))
    hwnd = _target_hwnd(active)
    if background and hwnd and _prefer_background(hwnd):
        pressed = win32.background_press_keys(hwnd, [str(k) for k in keys])
        active.mark_injected()
        return f"已后台按键 {'+'.join(pressed)}，没有移动你的鼠标；截图确认是否生效"
    _ensure_foreground(active)
    pressed = win32.press_keys([str(k) for k in keys])
    active.mark_injected()
    return f"已按键 {'+'.join(pressed)}"


def _scroll(args: dict[str, Any], active: session.Session) -> str:
    delta = _int_arg(args, "delta", 0) or 0
    if delta == 0:
        raise ValueError("delta 不能为 0，正数向下滚，负数向上滚")
    axis = str(_arg(args, "axis", "vertical")).lower()
    ref = str(_arg(args, "ref", "")).strip()
    background = bool(_arg(args, "background", True))
    hwnd = _target_hwnd(active)
    if ref:
        data = shared_helper().invoke(ref)
        x, y = _element_point(data)
    else:
        x, y = _resolve_point(args, active)
    if background and hwnd and _prefer_background(hwnd):
        win32.background_scroll(hwnd, x, y, delta, axis=axis)
        active.mark_injected()
        return f"已在 {x},{y} 后台滚动 {delta} 格，没有移动你的鼠标；截图确认是否生效"
    _ensure_foreground(active)
    win32.mouse_scroll(x, y, delta, axis=axis)
    active.mark_injected()
    return f"已在 {x},{y} 滚动 {delta} 格"


def _drag(args: dict[str, Any], active: session.Session) -> str:
    _ensure_foreground(active)
    from_ref = str(_arg(args, "from_ref", "")).strip()
    to_ref = str(_arg(args, "to_ref", "")).strip()
    if from_ref and to_ref:
        helper = shared_helper()
        start = _element_point(helper.invoke(from_ref))
        end = _element_point(helper.invoke(to_ref))
    else:
        frame = active.last_frame
        if frame is None:
            raise ValueError("拖拽前先截图，坐标要按截图给")
        fx = _float_arg(args, "from_x")
        fy = _float_arg(args, "from_y")
        tx = _float_arg(args, "to_x")
        ty = _float_arg(args, "to_y")
        if None in {fx, fy, tx, ty}:
            raise ValueError("需要 from_x/from_y/to_x/to_y，或者用 from_ref/to_ref")
        start = frame.to_screen(fx, fy)  # type: ignore[arg-type]
        end = frame.to_screen(tx, ty)  # type: ignore[arg-type]
    _ensure_landing_not_self(start[0], start[1])
    duration = _float_arg(args, "duration", 0.4) or 0.4
    win32.mouse_drag(start[0], start[1], end[0], end[1], duration=duration)
    active.last_action_point = end
    active.mark_injected()
    return f"已从 {start} 拖到 {end}"


def _focus(args: dict[str, Any], active: session.Session) -> str:
    hwnd = _int_arg(args, "window_id")
    if hwnd is None:
        raise ValueError("focus 需要 window_id")
    info = _ensure_target(hwnd, require_foreground=True)
    active.mark_injected()
    return f"已把「{info.title}」切到前台"


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


async def handle(call: ToolCall, *, work_root: str | Path) -> ToolResult:
    args = call.arguments if isinstance(call.arguments, dict) else {}
    action = str(args.get("action") or "").strip().lower()
    root = Path(work_root or ".")

    if not action:
        return _result(
            call,
            status="failed",
            error="缺少 action。常用流程：start → snapshot → click/type → screenshot → stop。",
        )

    try:
        if action == "start":
            goal = str(args.get("goal") or "").strip()
            if not goal:
                return _result(call, status="failed", error="start 需要 goal，说明这次要完成的桌面任务")
            active = session.start(
                goal,
                max_steps=_int_arg(args, "max_steps", 40) or 40,
                timeout_seconds=_int_arg(args, "timeout_seconds", 600) or 600,
            )
            return _result(
                call,
                content=(
                    f"[computer_use] 任务已开始 {active.task_id}：{active.goal}\n"
                    f"步数上限 {active.max_steps}。下一步先 snapshot 看界面，再动作。"
                ),
                metadata=active.status(),
            )

        if action == "status":
            active = session.current()
            if active is None:
                return _result(call, content="[computer_use] 当前没有桌面任务")
            return _result(call, content="[computer_use] " + json.dumps(active.status(), ensure_ascii=False), metadata=active.status())

        if action == "stop":
            active = session.current()
            if active is None:
                return _result(call, content="[computer_use] 当前没有桌面任务")
            active.stop(str(_arg(args, "reason", "用户要求结束")))
            return _result(call, content="[computer_use] 任务已结束", metadata=active.status())

        if action == "pause":
            active = session.current()
            if active is None:
                return _result(call, content="[computer_use] 当前没有桌面任务")
            active.pause(str(_arg(args, "reason", "主动暂停")))
            return _result(call, content="[computer_use] 任务已暂停", metadata=active.status())

        if action == "resume":
            active = session.current()
            if active is None:
                return _result(call, content="[computer_use] 当前没有桌面任务")
            active.resume()
            return _result(call, content="[computer_use] 任务已恢复", metadata=active.status())

        if action == "screenshot":
            active = _active_session(action, mutating=False)
            frame, label = await asyncio.to_thread(_grab, args)
            return await asyncio.to_thread(_frame_result, call, frame, label, root)

        if action == "snapshot":
            _active_session(action, mutating=False)
            content, meta = await asyncio.to_thread(_snapshot, args)
            return _result(call, content=content, metadata=meta)

        if action == "click":
            active = _active_session(action)
            detail = await asyncio.to_thread(_click, args, active)
            active.record("click", detail, ok=True)
            return _result(call, content=f"[computer_use] {detail}", metadata=active.status())

        if action == "type":
            active = _active_session(action)
            detail = await asyncio.to_thread(_type, args, active)
            active.record("type", detail, ok=True)
            return _result(call, content=f"[computer_use] {detail}", metadata=active.status())

        if action == "key":
            active = _active_session(action)
            detail = await asyncio.to_thread(_key, args, active)
            active.record("key", detail, ok=True)
            return _result(call, content=f"[computer_use] {detail}", metadata=active.status())

        if action == "scroll":
            active = _active_session(action)
            detail = await asyncio.to_thread(_scroll, args, active)
            active.record("scroll", detail, ok=True)
            return _result(call, content=f"[computer_use] {detail}", metadata=active.status())

        if action == "drag":
            active = _active_session(action)
            detail = await asyncio.to_thread(_drag, args, active)
            active.record("drag", detail, ok=True)
            return _result(call, content=f"[computer_use] {detail}", metadata=active.status())

        if action == "focus":
            active = _active_session(action)
            detail = await asyncio.to_thread(_focus, args, active)
            active.record("focus", detail, ok=True)
            return _result(call, content=f"[computer_use] {detail}", metadata=active.status())

        return _result(
            call,
            status="failed",
            error=f"未知 action: {action}。可用：start/status/stop/pause/resume/screenshot/snapshot/click/type/key/scroll/drag/focus",
        )

    except session.GuardError as exc:
        active = session.current()
        if active is not None:
            active.record(action, str(exc), ok=False, error=str(exc))
        return _result(call, status="blocked", error=str(exc))
    except (ValueError, win32.Win32Error, UiaError) as exc:
        active = session.current()
        if active is not None:
            active.record(action, str(exc), ok=False, error=str(exc))
        return _result(call, status="failed", error=str(exc))
    except Exception as exc:  # noqa: BLE001 - 工具不能把异常抛给回合
        active = session.current()
        if active is not None:
            active.record(action, str(exc), ok=False, error=str(exc))
        return _result(call, status="failed", error=f"computer_use 执行失败: {exc}")


def make_computer_use_handler(work_root: str | Path):
    async def computer_use(call: ToolCall) -> ToolResult:
        return await handle(call, work_root=work_root)

    return computer_use
