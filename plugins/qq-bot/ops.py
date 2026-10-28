"""QQ bot operations (buttons, pages and external RPC).

The model cannot call operations; model-facing capabilities live in
``tools.py``.  Every handler returns an ``OperationResult`` with a
JSON-serialisable payload.

Operations accept an optional ``botId``.  When omitted they use the default
bot, so older UI/window calls keep working; the page and right panel pass an
explicit id when several bots exist.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lamtools_core.app import OperationResult  # noqa: E402

from qqbot.bubbles import BubbleOptions, split_bubbles  # noqa: E402
from qqbot.state import get_manager, get_runtime  # noqa: E402


def _ok(name: str, payload: dict) -> OperationResult:
    status = "ok" if payload.get("ok", True) else "error"
    return OperationResult(name=name, status=status, payload=payload)


def _payload(request) -> dict:
    payload = getattr(request, "payload", None)
    return payload if isinstance(payload, dict) else {}


def _bot_id(payload: dict) -> str:
    return str(payload.get("botId") or payload.get("bot_id") or "").strip()


def _runtime(name: str, request=None) -> tuple[object | None, OperationResult | None]:
    payload = _payload(request) if request is not None else {}
    manager = get_manager()
    if manager is not None:
        bot_id = _bot_id(payload)
        runtime = manager.get_bot(bot_id) if bot_id else manager.default_bot()
        if runtime is None:
            return None, _ok(
                name,
                {
                    "ok": False,
                    "error": "机器人不存在或未启动",
                    "botId": bot_id,
                },
            )
        return runtime, None
    runtime = get_runtime()
    if runtime is None:
        return None, _ok(name, {"ok": False, "error": "QQ 机器人后端未启动"})
    return runtime, None


async def bots_list(request, *, work_root=None, data_dir=None) -> OperationResult:
    del work_root, data_dir
    manager = get_manager()
    if manager is None:
        return _ok("qqbot.bots.list", {"ok": False, "error": "多机器人管理器未启动"})
    payload = _payload(request)
    session_id = str(payload.get("sessionId") or payload.get("session_id") or "").strip()
    return _ok("qqbot.bots.list", manager.list_bots(session_id))


async def bot_create(request, *, work_root=None, data_dir=None) -> OperationResult:
    del work_root, data_dir
    manager = get_manager()
    if manager is None:
        return _ok("qqbot.bot.create", {"ok": False, "error": "多机器人管理器未启动"})
    payload = _payload(request)
    session_id = str(payload.get("sessionId") or payload.get("session_id") or "").strip()
    project_id = str(payload.get("projectId") or payload.get("project_id") or "").strip()
    name = str(payload.get("name") or "").strip()
    return _ok(
        "qqbot.bot.create",
        await manager.create_bot(session_id=session_id, project_id=project_id, name=name),
    )


async def bot_delete(request, *, work_root=None, data_dir=None) -> OperationResult:
    del work_root, data_dir
    manager = get_manager()
    if manager is None:
        return _ok("qqbot.bot.delete", {"ok": False, "error": "多机器人管理器未启动"})
    bot_id = _bot_id(_payload(request))
    if not bot_id:
        return _ok("qqbot.bot.delete", {"ok": False, "error": "botId 不能为空"})
    return _ok("qqbot.bot.delete", await manager.delete_bot(bot_id))


async def bot_state(request, *, work_root=None, data_dir=None) -> OperationResult:
    del work_root, data_dir
    manager = get_manager()
    if manager is None:
        return _ok("qqbot.bot.state", {"ok": False, "error": "多机器人管理器未启动"})
    bot_id = _bot_id(_payload(request))
    if not bot_id:
        return _ok("qqbot.bot.state", {"ok": False, "error": "botId 不能为空"})
    if manager.get_bot(bot_id) is None and bot_id not in manager.metadata:
        return _ok("qqbot.bot.state", {"ok": False, "error": "机器人不存在", "botId": bot_id})
    return _ok("qqbot.bot.state", {"ok": True, "bot": manager.describe_bot(bot_id)})


async def status(request, *, work_root=None, data_dir=None) -> OperationResult:
    del work_root, data_dir
    runtime, error = _runtime("qqbot.status", request)
    if error:
        return error
    result = runtime.status()
    result["botId"] = str(getattr(runtime, "bot_id", "default"))
    return _ok("qqbot.status", result)


async def bind_state(request, *, work_root=None, data_dir=None) -> OperationResult:
    del work_root, data_dir
    runtime, error = _runtime("qqbot.bind.state", request)
    if error:
        return error
    return _ok("qqbot.bind.state", runtime.bind_state())


async def bind_refresh(request, *, work_root=None, data_dir=None) -> OperationResult:
    del work_root, data_dir
    runtime, error = _runtime("qqbot.bind.refresh", request)
    if error:
        return error
    return _ok("qqbot.bind.refresh", runtime.bind_refresh())


async def bind_manual(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = _payload(request)
    runtime, error = _runtime("qqbot.bind.manual", request)
    if error:
        return error
    result = await runtime.bind_manual(str(payload.get("appId") or ""), str(payload.get("appSecret") or ""))
    return _ok("qqbot.bind.manual", result)


async def bind_unbind(request, *, work_root=None, data_dir=None) -> OperationResult:
    del work_root, data_dir
    runtime, error = _runtime("qqbot.bind.unbind", request)
    if error:
        return error
    return _ok("qqbot.bind.unbind", await runtime.bind_unbind())


async def config_get(request, *, work_root=None, data_dir=None) -> OperationResult:
    del work_root, data_dir
    runtime, error = _runtime("qqbot.config.get", request)
    if error:
        return error
    return _ok("qqbot.config.get", runtime.config_get())


async def config_update(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = _payload(request)
    patch = payload.get("patch") if isinstance(payload.get("patch"), dict) else {
        key: value for key, value in payload.items() if key not in {"botId", "bot_id"}
    }
    runtime, error = _runtime("qqbot.config.update", request)
    if error:
        return error
    return _ok("qqbot.config.update", await runtime.config_update(patch))


async def session_list(request, *, work_root=None, data_dir=None) -> OperationResult:
    del work_root, data_dir
    runtime, error = _runtime("qqbot.session.list", request)
    if error:
        return error
    return _ok("qqbot.session.list", runtime.session_list())


async def targets(request, *, work_root=None, data_dir=None) -> OperationResult:
    del work_root, data_dir
    manager = get_manager()
    if manager is not None:
        return _ok("qqbot.targets", await manager.targets())
    runtime, error = _runtime("qqbot.targets", request)
    if error:
        return error
    return _ok("qqbot.targets", await runtime.targets())


async def session_send_file(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = _payload(request)
    runtime, error = _runtime("qqbot.session.send_file", request)
    if error:
        return error
    result = await runtime.session_send_file(
        str(payload.get("scope") or "c2c"),
        str(payload.get("peerId") or payload.get("targetId") or ""),
        str(payload.get("filePath") or payload.get("file_path") or ""),
    )
    return _ok("qqbot.session.send_file", result)


async def session_reset(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = _payload(request)
    runtime, error = _runtime("qqbot.session.reset", request)
    if error:
        return error
    result = runtime.session_reset(str(payload.get("scope") or "c2c"), str(payload.get("peerId") or ""))
    return _ok("qqbot.session.reset", result)


async def session_stop(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = _payload(request)
    runtime, error = _runtime("qqbot.session.stop", request)
    if error:
        return error
    result = await runtime.session_stop(str(payload.get("scope") or "c2c"), str(payload.get("peerId") or ""))
    return _ok("qqbot.session.stop", result)


async def models_list(request, *, work_root=None, data_dir=None) -> OperationResult:
    del work_root, data_dir
    manager = get_manager()
    if manager is not None:
        return _ok("qqbot.models.list", manager.models_list())
    runtime, error = _runtime("qqbot.models.list", request)
    if error:
        return error
    return _ok("qqbot.models.list", runtime.models_list())


async def test_send(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = _payload(request)
    runtime, error = _runtime("qqbot.test.send", request)
    if error:
        return error
    result = await runtime.test_send(
        str(payload.get("scope") or "c2c"),
        str(payload.get("targetId") or ""),
        str(payload.get("text") or ""),
        dry_run=bool(payload.get("dryRun") or payload.get("dry_run")),
    )
    return _ok("qqbot.test.send", result)


async def bubbles_preview(request, *, work_root=None, data_dir=None) -> OperationResult:
    del work_root, data_dir
    payload = _payload(request)
    runtime, error = _runtime("qqbot.bubbles.preview", request)
    if error:
        return error
    text = str(payload.get("text") or "")
    limit = int(payload.get("limit") or runtime.config.get("textChunkLimit") or 4500)
    profile = str(payload.get("profile") or "").strip()
    options = BubbleOptions.for_profile(profile) if profile else BubbleOptions.from_config(runtime.config)
    return _ok("qqbot.bubbles.preview", {"bubbles": split_bubbles(text, limit, options=options)})


async def gateway_restart(request, *, work_root=None, data_dir=None) -> OperationResult:
    del work_root, data_dir
    runtime, error = _runtime("qqbot.gateway.restart", request)
    if error:
        return error
    return _ok("qqbot.gateway.restart", await runtime.gateway_restart())


async def diagnose(request, *, work_root=None, data_dir=None) -> OperationResult:
    del work_root, data_dir
    runtime, error = _runtime("qqbot.diagnose", request)
    if error:
        return error
    return _ok("qqbot.diagnose", runtime.diagnose())


async def logs_tail(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = _payload(request)
    runtime, error = _runtime("qqbot.logs.tail", request)
    if error:
        return error
    return _ok("qqbot.logs.tail", runtime.logs_tail(int(payload.get("tail") or 80)))
