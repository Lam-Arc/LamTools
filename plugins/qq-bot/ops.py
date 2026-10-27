"""QQ bot operations (buttons, pages and external RPC).

The model cannot call operations; model-facing capabilities live in
``tools.py``.  Every handler returns an ``OperationResult`` with a
JSON-serialisable payload.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lamtools_core.app import OperationResult  # noqa: E402

from qqbot.state import get_runtime  # noqa: E402


def _ok(name: str, payload: dict) -> OperationResult:
    status = "ok" if payload.get("ok", True) else "error"
    return OperationResult(name=name, status=status, payload=payload)


def _runtime(name: str) -> tuple[object | None, OperationResult | None]:
    runtime = get_runtime()
    if runtime is None:
        return None, _ok(name, {"ok": False, "error": "QQ 机器人后端未启动"})
    return runtime, None


def _payload(request) -> dict:
    payload = getattr(request, "payload", None)
    return payload if isinstance(payload, dict) else {}


async def status(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    runtime, error = _runtime("qqbot.status")
    if error:
        return error
    return _ok("qqbot.status", runtime.status())


async def bind_state(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    runtime, error = _runtime("qqbot.bind.state")
    if error:
        return error
    return _ok("qqbot.bind.state", runtime.bind_state())


async def bind_refresh(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    runtime, error = _runtime("qqbot.bind.refresh")
    if error:
        return error
    return _ok("qqbot.bind.refresh", runtime.bind_refresh())


async def bind_manual(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = _payload(request)
    runtime, error = _runtime("qqbot.bind.manual")
    if error:
        return error
    result = await runtime.bind_manual(str(payload.get("appId") or ""), str(payload.get("appSecret") or ""))
    return _ok("qqbot.bind.manual", result)


async def bind_unbind(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    runtime, error = _runtime("qqbot.bind.unbind")
    if error:
        return error
    return _ok("qqbot.bind.unbind", await runtime.bind_unbind())


async def config_get(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    runtime, error = _runtime("qqbot.config.get")
    if error:
        return error
    return _ok("qqbot.config.get", runtime.config_get())


async def config_update(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = _payload(request)
    patch = payload.get("patch") if isinstance(payload.get("patch"), dict) else payload
    runtime, error = _runtime("qqbot.config.update")
    if error:
        return error
    return _ok("qqbot.config.update", await runtime.config_update(patch))


async def session_list(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    runtime, error = _runtime("qqbot.session.list")
    if error:
        return error
    return _ok("qqbot.session.list", runtime.session_list())


async def session_reset(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = _payload(request)
    runtime, error = _runtime("qqbot.session.reset")
    if error:
        return error
    result = runtime.session_reset(str(payload.get("scope") or "c2c"), str(payload.get("peerId") or ""))
    return _ok("qqbot.session.reset", result)


async def session_stop(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = _payload(request)
    runtime, error = _runtime("qqbot.session.stop")
    if error:
        return error
    result = await runtime.session_stop(str(payload.get("scope") or "c2c"), str(payload.get("peerId") or ""))
    return _ok("qqbot.session.stop", result)


async def models_list(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    runtime, error = _runtime("qqbot.models.list")
    if error:
        return error
    return _ok("qqbot.models.list", runtime.models_list())


async def test_send(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = _payload(request)
    runtime, error = _runtime("qqbot.test.send")
    if error:
        return error
    result = await runtime.test_send(
        str(payload.get("scope") or "c2c"),
        str(payload.get("targetId") or ""),
        str(payload.get("text") or ""),
    )
    return _ok("qqbot.test.send", result)


async def gateway_restart(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    runtime, error = _runtime("qqbot.gateway.restart")
    if error:
        return error
    return _ok("qqbot.gateway.restart", await runtime.gateway_restart())


async def diagnose(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    runtime, error = _runtime("qqbot.diagnose")
    if error:
        return error
    return _ok("qqbot.diagnose", runtime.diagnose())


async def logs_tail(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = _payload(request)
    runtime, error = _runtime("qqbot.logs.tail")
    if error:
        return error
    return _ok("qqbot.logs.tail", runtime.logs_tail(int(payload.get("tail") or 80)))
