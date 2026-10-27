"""Model-facing tools: send a file, inspect an image, read status, start binding."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lamtools_core.tool import ToolResult  # noqa: E402

from qqbot.agent_bridge import current_session  # noqa: E402
from qqbot.media import download_url, path_is_allowed, send_media_file  # noqa: E402
from qqbot.protocol import ReplyTarget  # noqa: E402
from qqbot.state import get_runtime  # noqa: E402
from qqbot.util import data_url, format_file_size, sniff_image_media_type  # noqa: E402


def _args(call) -> dict:
    arguments = getattr(call, "arguments", None)
    return arguments if isinstance(arguments, dict) else {}


def _result(call, payload: dict, *, ok: bool | None = None, **extra) -> ToolResult:
    if ok is None:
        ok = bool(payload.get("ok", True))
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if ok:
        return ToolResult(call_id=call.id, name=call.name, status="ok", content=text, **extra)
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="failed",
        error=str(payload.get("error") or text),
        content=text,
        **extra,
    )


def _session_for_call(call, runtime):
    session = current_session()
    if session is not None:
        return session
    bridge = getattr(runtime, "_bridge", None)
    if bridge is None:
        return None
    current = asyncio.current_task()
    for candidate in bridge.all_sessions():
        if candidate.task is current:
            return candidate
    return None


def _parse_target(value: str) -> ReplyTarget | None:
    text = str(value or "").strip()
    if ":" not in text:
        return None
    scope, target_id = text.split(":", 1)
    if scope not in {"c2c", "group"} or not target_id:
        return None
    return ReplyTarget(scope, target_id)


async def send_file(call) -> ToolResult:
    runtime = get_runtime()
    if runtime is None:
        return _result(call, {"ok": False, "error": "QQ 机器人后端未启动"})
    args = _args(call)
    file_path = str(args.get("file_path") or "").strip()
    if not file_path:
        return _result(call, {"ok": False, "error": "file_path 不能为空"})
    session = _session_for_call(call, runtime)
    target = _parse_target(str(args.get("target") or ""))
    if target is None:
        if session is None:
            return _result(call, {"ok": False, "error": "无法确定发送目标；请显式传 target（c2c:openid / group:openid）"})
        target = session.reply_target
    path = Path(file_path).resolve()
    if not path_is_allowed(
        path,
        data_dir=runtime.data_dir,
        work_root=runtime.work_root,
        config=runtime.config,
    ):
        return _result(call, {"ok": False, "error": f"file_path 不在允许的目录内: {path}"})
    if not path.is_file():
        return _result(call, {"ok": False, "error": f"文件不存在: {path}"})
    api = getattr(runtime, "_api", None)
    if api is None:
        return _result(call, {"ok": False, "error": "QQ 网关未运行"})
    result = await send_media_file(api, target, path, logger=runtime.logger)
    if result.get("outcome") == "missing":
        return _result(call, {"ok": False, "error": f"文件不存在或不可读: {path}"})
    if result.get("outcome") == "failed":
        return _result(call, {"ok": False, "error": f"发送失败: {result.get('error')}"})
    return _result(
        call,
        {
            "ok": True,
            "fileName": path.name,
            "fileSize": result.get("size") or 0,
            "target": f"{target.scope}:{target.target_id}",
            "fileUuid": result.get("fileUuid") or "",
            "messageId": result.get("messageId") or "",
        },
    )


async def describe_image(call) -> ToolResult:
    runtime = get_runtime()
    if runtime is None:
        return _result(call, {"ok": False, "error": "QQ 机器人后端未启动"})
    args = _args(call)
    image = str(args.get("image") or "").strip()
    if not image:
        return _result(call, {"ok": False, "error": "image 不能为空"})
    vision = runtime.config.get("vision") or {}
    max_bytes = int(vision.get("maxBytes") or 10 * 1024 * 1024)
    try:
        if image.startswith("http://") or image.startswith("https://"):
            data = await download_url(image, max_bytes, allow_http=True)
            name = ""
        else:
            path = Path(image)
            if not path.is_file():
                return _result(call, {"ok": False, "error": f"图片文件不存在: {image}"})
            if path.stat().st_size > max_bytes:
                return _result(call, {"ok": False, "error": f"图片过大（上限 {format_file_size(max_bytes)}）"})
            data = await asyncio.to_thread(path.read_bytes)
            name = path.name
    except Exception as exc:
        return _result(call, {"ok": False, "error": f"读取图片失败: {exc}"})
    media_type = sniff_image_media_type(data)
    if media_type is None:
        return _result(call, {"ok": False, "error": "无法识别的图片格式（仅支持 png/jpeg/gif/webp/bmp）"})
    prompt = str(args.get("prompt") or vision.get("defaultPrompt") or "Describe this image in detail.")
    encoded = data_url(media_type, data)

    # Preferred path: the configured vision model (upstream behaviour).
    if vision.get("enabled") and vision.get("model"):
        client = getattr(runtime.context, "llm_client", None)
        if client is not None:
            try:
                from lamtools_core.llm import ChatMessage, LLMRequest

                request = LLMRequest(
                    messages=[
                        ChatMessage(
                            role="user",
                            content=[
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": encoded}},
                            ],
                        )
                    ],
                    model=str(vision["model"]),
                    max_tokens=int(vision.get("maxTokens") or 1024),
                    timeout=float(int(vision.get("timeoutMs") or 120000)) / 1000.0,
                )
                response = await asyncio.wait_for(
                    client.complete(request),
                    timeout=float(int(vision.get("timeoutMs") or 120000)) / 1000.0,
                )
                text = str(getattr(response, "content", "") or "").strip()
                if text:
                    return _result(
                        call,
                        {
                            "ok": True,
                            "text": text,
                            "model": str(vision["model"]),
                            "image": image,
                            "mimeType": media_type,
                            "bytes": len(data),
                        },
                    )
            except Exception as exc:
                runtime.logger.warning("vision model call failed, falling back to main model image: %s", exc)

    # Fallback: hand the image to the current model.  The host attaches it to
    # the next request; text-only models get its readable "cannot receive
    # images" message instead of a fake description.
    return _result(
        call,
        {
            "ok": True,
            "text": "已把图片交给当前模型查看。",
            "model": "current",
            "image": image,
            "mimeType": media_type,
            "bytes": len(data),
        },
        model_image_data_url=encoded,
    )


async def status(call) -> ToolResult:
    runtime = get_runtime()
    if runtime is None:
        return _result(call, {"ok": False, "error": "QQ 机器人后端未启动"})
    return _result(call, runtime.status())


async def bind_start(call) -> ToolResult:
    runtime = get_runtime()
    if runtime is None:
        return _result(call, {"ok": False, "error": "QQ 机器人后端未启动"})
    if runtime._app_id() and runtime._app_secret():
        return _result(call, {"ok": True, "phase": "bound", "appId": runtime._app_id()})
    runtime.bind_refresh()
    await asyncio.sleep(0.5)
    return _result(call, {"ok": True, **runtime.bind_state()})


__all__ = ["send_file", "describe_image", "status", "bind_start"]
