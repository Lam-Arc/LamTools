"""安卓设备控制：让 Sunday 读屏、点按、滑动、输入、返回桌面、打开应用。

user:“加，安卓控制，上模拟器里把它跑通”+(工具跑在 guest 的 Python Core 里，碰不到 Tauri
和 Kotlin，所以宿主会开一条本机回环通道并把端口与令牌写进 guest 的 userdata；这里只负责
把模型的动作翻译成一条请求)。

只在安卓宿主里注册：桌面与「远程模式」的 Core 碰不到手机，出现一个点了没反应的按钮比没有
这个工具更糟。
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from pathlib import Path
from typing import Any

from lamtools_core.tool import ToolCall, ToolResult

CONTROL_FILE = Path("/root/.sunday/device-control.json")

ACTIONS = frozenset(
    {
        "status",
        "snapshot",
        "tap",
        "long_press",
        "swipe",
        "tap_node",
        "set_text",
        "global",
        "open_app",
        "list_apps",
        # user:“读取能力加上”+(截图给模型自己看界面/验证码图片，通知给模型自己读短信与推送)。
        "screenshot",
        "notifications",
    }
)


def android_control_available() -> bool:
    """宿主会把这个变量写进 guest 的环境；没有它就不是安卓。"""
    return os.environ.get("SUNDAY_HOST_PLATFORM", "").strip().lower() == "android"


def _post(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        info = json.loads(CONTROL_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "ok": False,
            "error": "设备控制通道还没有准备好：把 Sunday 现在这一次启动走完再试",
        }
    except Exception as error:  # noqa: BLE001 - 读不到就是读不到，如实说
        return {"ok": False, "error": f"读不到设备控制通道：{error}"}
    port = int(info.get("port") or 0)
    token = str(info.get("token") or "")
    if port <= 0 or not token:
        return {"ok": False, "error": "设备控制通道的信息不完整，重启一次应用再试"}
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/device-control",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"content-type": "application/json", "x-sunday-token": token},
        method="POST",
    )
    # 本机回环不该走系统代理。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": f"设备控制没有回应：{error}"}


def _format_snapshot(result: dict[str, Any]) -> str:
    screen = result.get("screen") or []
    size = f"{screen[0]}x{screen[1]}" if len(screen) >= 2 else "?"
    lines = [f"{result.get('package') or '?'} {size}"]
    for node in result.get("nodes") or []:
        bounds = node.get("bounds") or [0, 0, 0, 0]
        flags = []
        if node.get("clickable"):
            flags.append("click")
        if node.get("editable"):
            flags.append("edit")
        if node.get("scrollable"):
            flags.append("scroll")
        if node.get("focused"):
            flags.append("focus")
        label = str(node.get("text") or node.get("desc") or "")
        part = f"{node.get('ref')} {node.get('class') or ''}"
        if label:
            part += f' "{label}"'
        part += f" [{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}]"
        if flags:
            part += " " + ",".join(flags)
        lines.append(part)
    if result.get("truncated"):
        lines.append("… 元素太多，只给了前面这些；要更细就再 snapshot 或直接用 ref 操作")
    return "\n".join(lines)


def make_android_use_handler():
    async def android_use(call: ToolCall) -> ToolResult:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        action = str(args.get("action") or "").strip().lower()
        if action not in ACTIONS:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error="action 不对。可用：" + ", ".join(sorted(ACTIONS)),
            )

        payload: dict[str, Any] = {"action": action}
        for key in (
            "x",
            "y",
            "ref",
            "text",
            "name",
            "package",
            "query",
            "duration_ms",
            "max_nodes",
            "max_width",
            "limit",
        ):
            value = args.get(key)
            if value is not None and value != "":
                payload[key] = value
        if action == "swipe":
            payload["from"] = args.get("from")
            payload["to"] = args.get("to")
        if action == "snapshot" and "max_nodes" not in payload:
            payload["max_nodes"] = 80

        reply = await asyncio.to_thread(_post, payload)
        if not reply.get("ok"):
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error=str(reply.get("error") or "设备控制返回了失败"),
            )

        result = reply.get("result") or {}
        if action == "snapshot":
            content = _format_snapshot(result)
            metadata = {
                "package": result.get("package") or "",
                "screen": result.get("screen") or [],
                "node_count": len(result.get("nodes") or []),
                "truncated": bool(result.get("truncated")),
            }
            return ToolResult(
                call_id=call.id,
                name=call.name,
                content=content,
                metadata=metadata,
            )
        if action == "list_apps":
            apps = result.get("apps") or []
            content = "\n".join(f"{app.get('label')}  {app.get('package')}" for app in apps)
            return ToolResult(
                call_id=call.id,
                name=call.name,
                content=content or "没有匹配的应用",
                metadata={"count": len(apps)},
            )
        if action == "screenshot":
            # user:“读取能力加上”+(把画面原样交给模型自己看；缩放压缩在手机侧做完，
            # 原图只挂在 model_image_data_url 上，不落盘)。
            data = str(result.get("image_base64") or "")
            if not data:
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="failed",
                    error="截图没有拿到画面",
                )
            mime = str(result.get("mime") or "image/jpeg")
            width = int(result.get("width") or 0)
            height = int(result.get("height") or 0)
            return ToolResult(
                call_id=call.id,
                name=call.name,
                content=f"[android_use] 截屏 {width}x{height}",
                metadata={"width": width, "height": height},
                model_image_data_url=f"data:{mime};base64,{data}",
            )
        if action == "notifications":
            connected = bool(result.get("connected"))
            items = result.get("notifications") or []
            if not items:
                hint = (
                    "最近没有收到通知"
                    if connected
                    else "通知读取没有开启：在系统设置 → 通知 → 通知使用权里把 Sunday 打开，然后重新调用"
                )
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    content=hint,
                    metadata={"count": 0, "connected": connected},
                )
            lines = []
            for item in items:
                title = str(item.get("title") or "").strip()
                text = str(item.get("text") or "").strip()
                body = " / ".join(part for part in (title, text) if part)
                lines.append(f"{item.get('package') or '?'}  {body}")
            return ToolResult(
                call_id=call.id,
                name=call.name,
                content="\n".join(lines),
                metadata={"count": len(items), "connected": connected},
            )
        if action == "status":
            return ToolResult(
                call_id=call.id,
                name=call.name,
                content="无障碍服务已连接" if result.get("connected") else "无障碍服务没有连接",
                metadata={"connected": bool(result.get("connected"))},
            )
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content=f"[android_use] {action} 完成",
            metadata=result if isinstance(result, dict) else {},
        )

    return android_use


__all__ = ["android_control_available", "make_android_use_handler"]
