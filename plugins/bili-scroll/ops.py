# user:“对比原版，能力应当只增不减”+(保留完整移植能力，并使用宿主独立模块空间)。
"""bili-scroll —— 操作层（按钮 / 命令 / 面板的 RPC 入口）。

模型不能调操作；要给模型的能力在 tools.py 里（同一份 service 实现）。
每个操作都返回 OperationResult，payload 是可序列化的 dict。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

from lamtools_core.app import OperationResult  # noqa: E402

from . import service  # noqa: E402


def _ok(name: str, payload: dict) -> OperationResult:
    status = "ok" if payload.get("ok", True) else "error"
    return OperationResult(name=name, status=status, payload=payload)


async def status(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    return _ok("bili-scroll.status", await service.run_io(service.status))


async def run_round(request, *, work_root=None, data_dir=None) -> OperationResult:
    why = str((getattr(request, "payload", {}) or {}).get("why") or "manual")
    return _ok("bili-scroll.run_round", service.run_round(why))


async def round_instruction(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    return _ok("bili-scroll.round_instruction", await service.run_io(service.run_instruction))


async def setup(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    return _ok("bili-scroll.setup", await service.run_io(service.setup_deps))


async def install_asr(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    return _ok("bili-scroll.install_asr", await service.run_io(service.install_asr))


async def install_log(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = getattr(request, "payload", {}) or {}
    kind = "asr" if str(payload.get("kind") or "") == "asr" else "main"
    return _ok("bili-scroll.install_log", await service.run_io(service.install_log,kind, int(payload.get("tail") or 40)))


async def login_start(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    return _ok("bili-scroll.login_start", await service.run_io(service.login_start))


async def login_poll(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = getattr(request, "payload", {}) or {}
    return _ok("bili-scroll.login_poll", await service.run_io(service.login_poll,str(payload.get("key") or "")))


async def import_cookie(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = getattr(request, "payload", {}) or {}
    return _ok(
        "bili-scroll.import_cookie",
        await service.run_io(service.import_cookie,
            str(payload.get("sessdata") or ""),
            str(payload.get("bili_jct") or ""),
            str(payload.get("dedeuserid") or ""),
            str(payload.get("buvid3") or ""),
        ),
    )


async def config_get(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    return _ok("bili-scroll.config_get", await service.run_io(service.config_get))


async def config_update(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = getattr(request, "payload", {}) or {}
    patch = payload.get("patch") if isinstance(payload.get("patch"), dict) else payload
    return _ok("bili-scroll.config_update", await service.run_io(service.config_update,patch))


async def report_read(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = getattr(request, "payload", {}) or {}
    return _ok("bili-scroll.report_read", await service.run_io(service.report_read,str(payload.get("day") or "")))


async def reports_list(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    return _ok("bili-scroll.reports_list", await service.run_io(service.reports_list))


async def pick_cards(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = getattr(request, "payload", {}) or {}
    return _ok("bili-scroll.pick_cards", await service.run_io(service.pick_cards,str(payload.get("day") or "")))


async def seen_list(request, *, work_root=None, data_dir=None) -> OperationResult:
    payload = getattr(request, "payload", {}) or {}
    return _ok("bili-scroll.seen_list", await service.run_io(service.seen_list,
        str(payload.get("day") or ""), str(payload.get("status") or ""), int(payload.get("limit") or 200)))


async def diagnose(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    return _ok("bili-scroll.diagnose", await service.run_io(service.diagnose))


async def open_home(request, *, work_root=None, data_dir=None) -> OperationResult:
    return _ok("bili-scroll.open_home", await service.run_io(service.open_home, str((request.payload or {}).get("what") or "home")))


async def cover_data(request, **kwargs):
    return _ok(request.name, await service.run_io(service.cover_data, str((request.payload or {}).get("bvid") or "")))


async def fav_folders(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    return _ok("bili-scroll.fav_folders", await service.run_io(service.fav_call,["folders"]))


async def fav_add_today(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    return _ok("bili-scroll.fav_add_today", await service.run_io(service.fav_add_today))


async def dm_scan(request, *, work_root=None, data_dir=None) -> OperationResult:
    del request, work_root, data_dir
    return _ok("bili-scroll.dm_scan", await service.run_io(service.dm_scan))


async def watched(request, **kwargs):
    p = request.payload
    return _ok(request.name, await service.run_io(service.watched,p.get("tier", ""), p.get("state", ""), p.get("offset", 0), p.get("limit", 60)))


async def verify(request, **kwargs):
    import asyncio
    return _ok(request.name, await asyncio.to_thread(service.verify))


async def selfcheck(request, **kwargs):
    return _ok(request.name, await service.run_io(service.selfcheck))


async def check(request, **kwargs):
    import asyncio
    return _ok(request.name, await asyncio.to_thread(service.check))


async def update_check(request, **kwargs):
    import asyncio
    return _ok(request.name, await asyncio.to_thread(service.update_check))


async def stop_round(request, **kwargs):
    if service.RUNTIME is None:
        return _ok(request.name, {"ok": True, "stopped": True})
    return _ok(request.name, await service.RUNTIME.stop_round())
