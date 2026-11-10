"""desktop_overlay 工具：让 Agent 在真实桌面上画标记，并读回用户的圈选批注。

user:“AI 直接在屏幕上标记、绘制、互动、发弹幕：箭头、框选、高亮、涂鸦、文字、
悬浮控件、动态提示。标记可跟随窗口和对象，用户能直接点击、圈选、批注，与
Agent 实时互动。”+(模型负责决定画什么、画在哪；工具只做校验、落状态和回读，
不替模型猜坐标)。

一次调用做一类事：
- ``show``     画一组标记，返回 id，后续可以按 id 清掉
- ``clear``    按 id 清掉，或 ``all=true`` 清空
- ``list``     看当前屏幕上有哪些标记、有没有用户批注
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lamtools_core.tool import ToolCall, ToolResult

from . import assets as overlay_assets
from . import store as store_module

DESKTOP_OVERLAY_TOOL_NAME = "desktop_overlay"

DESKTOP_OVERLAY_TOOL_DESCRIPTION = (
    "在真实桌面上画标记，让用户一眼看到你说的是哪个位置。这一层叫交互层。"
    "支持箭头、矩形框、椭圆高亮、自由涂鸦、文字标签；标记可以绑定窗口，窗口移动时跟着走。"
    "画之前先想清楚要指什么：一次最多 40 个标记，默认 30 秒后自动消失。"
    "用户框选批注走 Ping 的截图编辑器，会直接作为会话消息到达；这里只负责画标记。"
    "交互体验优先：文字可以做成弹幕从右往左飘，只占屏幕上方三成，句子越长飘得越慢；"
    "表情包可以弹出后停留指定秒数；svg 默认会逐段描边画出来而不是直接贴上去。"
    "capture 动作会请用户自己圈一块区域，圈完同样进截图编辑器。"
    "ttl 就是它活多久，到点淡出消失。"
)

DESKTOP_OVERLAY_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["show", "append", "clear", "list", "capture"],
            "description": "要做的动作。show 画标记，append 给已有 svg 续画，clear 清除，list 看现状，capture 请用户圈一块区域。",
        },
        "marks": {
            "type": "array",
            "description": "show 时的标记列表。",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["arrow", "rect", "ellipse", "pen", "text", "svg", "danmaku", "sticker"],
                        "description": (
                            "标记形状。danmaku 是弹幕，sticker 是表情包，svg 是受控矢量图形。"
                        ),
                    },
                    "points": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "number"}},
                        "description": (
                            "屏幕物理像素坐标。arrow/rect/ellipse/svg 需要两个点（外接矩形），"
                            "pen 是完整轨迹，text/sticker 一个点，danmaku 一个点且 y 是轨道高度。"
                        ),
                    },
                    "text": {"type": "string", "description": "text 标记的文字，其他地方可留空。"},
                    "color": {"type": "string", "description": "颜色，默认 #ff5c8a。"},
                    "width": {"type": "number", "description": "线宽，默认 3。"},
                    "ttl": {
                        "type": "number",
                        "description": "活多久，秒。弹幕和表情包默认 3 秒，到点淡出；静态标注默认 30 秒。",
                    },
                    "window_id": {
                        "type": "integer",
                        "description": "绑定到这个窗口句柄（来自 computer_use snapshot），窗口移动时标记跟着走。",
                    },
                    "label": {"type": "string", "description": "给标记起的名字，方便之后按含义引用。"},
                    "motion": {
                        "type": "object",
                        "description": "进入和退出动画。默认弹幕是 danmaku，表情包是 pop，其它是 fade。",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["fade", "pop", "float", "drift", "danmaku"],
                                "description": "动画类型。",
                            },
                            "duration": {"type": "number", "description": "动画时长，秒。弹幕默认占满 ttl。"},
                            "fade": {"type": "number", "description": "结尾淡出时长，秒。"},
                            "easing": {
                                "type": "string",
                                "enum": ["linear", "ease-out", "ease-in-out"],
                                "description": "缓动。",
                            },
                            "from": {
                                "type": "string",
                                "enum": ["right", "left", "center", "top", "bottom"],
                                "description": "从哪边进入。弹幕默认 right。",
                            },
                        },
                    },
                    "draw": {
                        "type": "object",
                        "description": "svg 逐渐画出。默认 stroke，按图形顺序逐段描边。",
                        "properties": {
                            "mode": {
                                "type": "string",
                                "enum": ["stroke", "reveal", "none"],
                                "description": "stroke 逐段描边，reveal 整块从左到右揭开，none 直接显示。",
                            },
                            "duration": {"type": "number", "description": "画完需要多少秒，默认不超过 1.2 秒。"},
                        },
                    },
                    "image": {
                        "type": "string",
                        "description": "表情包或弹幕用的图片，工作区内 png/jpg/webp/gif 路径。",
                    },
                    "image_width": {"type": "number", "description": "图片显示宽度，屏幕像素。"},
                    "image_height": {"type": "number", "description": "图片显示高度，屏幕像素。"},
                },
                "required": ["kind", "points"],
            },
        },
        "id": {"type": "string", "description": "append 时续画的 svg 标记 id。"},
        "shapes": {
            "type": "array",
            "description": "append 时追加的图形，结构和 show 里 svg 的 shapes 相同。",
            "items": {"type": "object"},
        },
        "ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "clear 时要清掉的标记 id。",
        },
        "all": {"type": "boolean", "description": "clear 时是否清空屏幕上所有标记。"},
    },
    "required": ["action"],
}


def _arg(args: dict[str, Any], name: str, default: Any = None) -> Any:
    value = args.get(name, default)
    return default if value is None else value


def _result(call: ToolCall, *, content: str = "", error: str = "", status: str = "ok",
            metadata: dict[str, Any] | None = None) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status=status,  # type: ignore[arg-type]
        content=content,
        error=error,
        artifacts=[],
        metadata=metadata or {},
    )


def _describe_mark(mark: dict[str, Any]) -> str:
    label = mark.get("label") or ""
    target = mark.get("window")
    place = f"绑定窗口「{target.get('title') or target.get('id')}」" if target else "屏幕坐标"
    if mark.get("window_missing"):
        place = "窗口已找不到，已降级到屏幕坐标"
    text = f" 文字「{mark['text']}」" if mark.get("text") else ""
    return f"{mark['id']} {mark['kind']} {place}{text}" + (f" ({label})" if label else "")


def _copy_image(raw: str, work_root: str | Path | None) -> dict[str, Any]:
    """工作区图片 → 临时资源目录，返回 {asset, width?, height?}。"""
    root = Path(work_root or ".").resolve()
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError("图片必须在工作区内") from None
    if not resolved.is_file():
        raise ValueError(f"图片不存在：{raw}")
    asset = overlay_assets.save_image(resolved)
    return {"asset": asset["asset"]}


def _prepare_marks(marks: Any, work_root: str | Path | None) -> list[Any]:
    prepared: list[Any] = []
    for mark in marks:
        if not isinstance(mark, dict):
            prepared.append(mark)
            continue
        item = dict(mark)
        image = item.get("image")
        if isinstance(image, str) and image.strip():
            converted = _copy_image(image.strip(), work_root)
            width = item.pop("image_width", None)
            height = item.pop("image_height", None)
            if width not in (None, ""):
                converted["width"] = width
            if height not in (None, ""):
                converted["height"] = height
            item["image"] = converted
        prepared.append(item)
    return prepared


def handle(call: ToolCall, *, store: store_module.Store | None = None,
           work_root: str | Path | None = None) -> ToolResult:
    active = store or store_module.current()
    args = call.arguments or {}
    action = str(args.get("action") or "").strip().lower()

    try:
        if action == "show":
            marks = _arg(args, "marks", None)
            if marks is None:
                return _result(call, status="failed", error="show 需要 marks")
            if not isinstance(marks, (list, tuple)):
                return _result(call, status="failed", error="marks 需要数组")
            if not marks:
                return _result(call, status="failed", error="marks 不能为空")
            ids = active.apply(_prepare_marks(marks, work_root))
            state = active.snapshot()
            lines = [f"已画 {len(ids)} 个标记（共 {len(state['marks'])} 个在屏幕上）："]
            for mark in state["marks"]:
                if mark["id"] in ids:
                    lines.append(f"- {_describe_mark(mark)}")
            return _result(call, content="\n".join(lines), metadata={"ids": ids, **state})

        if action == "append":
            mark_id = str(_arg(args, "id", "") or "").strip()
            shapes = _arg(args, "shapes", None)
            if not mark_id:
                return _result(call, status="failed", error="append 需要 id")
            if not isinstance(shapes, (list, tuple)) or not shapes:
                return _result(call, status="failed", error="append 需要非空 shapes")
            added = active.append_shapes(mark_id, shapes)
            return _result(
                call,
                content=f"已续画 {added} 个图形，标记 {mark_id} 继续生长。",
                metadata={"id": mark_id, "added": added, **active.snapshot()},
            )

        if action == "clear":
            # user:“对代码进行审查，不要出错或者低级漏洞或问题”+(参数类型必须
            # 先校验：字符串 "false" 真值化之后会把整屏清掉)。
            all_marks = _arg(args, "all", False)
            if not isinstance(all_marks, bool):
                return _result(call, status="failed", error="all 需要布尔值 true/false")
            ids = _arg(args, "ids", None) or []
            if isinstance(ids, (str, bytes)):
                return _result(call, status="failed", error="ids 需要字符串数组")
            removed = active.clear(ids=ids, all_marks=all_marks)
            if not removed and not all_marks and not ids:
                return _result(call, status="failed", error="clear 需要 ids，或者 all=true 清空")
            return _result(
                call,
                content=f"已清除 {removed} 个标记。",
                metadata={"removed": removed, **active.snapshot()},
            )

        if action == "capture":
            # user:“对外开放API，可外部调用批注功能”+(同一套请求：工具让用户圈一块，
            # 交互层轮询到就进框选，拖完进 Ping 的截图编辑器)。
            active.request_capture()
            return _result(call, content="已请求用户在屏幕上圈选一块区域。")

        if action == "list":
            state = active.snapshot()
            lines = [f"屏幕上有 {len(state['marks'])} 个标记。"]
            lines.extend(f"- {_describe_mark(mark)}" for mark in state["marks"])
            return _result(
                call,
                content="\n".join(lines),
                metadata={**state, "mark_count": len(state["marks"])},
            )

        return _result(call, status="failed", error=f"不支持的 action: {action or '(空)'}")
    except ValueError as exc:
        return _result(call, status="failed", error=str(exc))
    except OSError as exc:
        # user:“对代码进行审查，不要出错或者低级漏洞或问题”+(读写图片时的系统
        # 错误不能直接冒到工具层，转成能看懂的中文错误)。
        return _result(call, status="failed", error=f"读写图片失败：{exc}")


def make_desktop_overlay_handler(work_root: str | Path = ""):
    """返回 async handler；work_root 用来解析表情包图片路径。"""

    async def handler(call: ToolCall) -> ToolResult:
        return handle(call, work_root=work_root)

    return handler
