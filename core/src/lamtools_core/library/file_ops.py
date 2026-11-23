"""文件操作：直接作用于原文件，并把冲突与失败逐项说清楚。

user:“普通文件操作直接作用于原始文件”“跨磁盘移动、同名冲突、文件占用、
权限不足等情况必须有明确处理流程”+(这一层不猜用户意图：目标已存在时按
调用方给的策略处理；默认不覆盖；永久删除必须显式确认；删除到回收站走
Windows 自己的撤销机制)。
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Iterable

from .identity import normalize_path

_CREATE_NO_WINDOW = 0x08000000

# Shell 文件操作（回收站）常量
_FO_DELETE = 0x0003
_FOF_SILENT = 0x0004
_FOF_NOCONFIRMATION = 0x0010
_FOF_ALLOWUNDO = 0x0040
_FOF_NOERRORUI = 0x0400


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", ctypes.c_int),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


def _send_to_recycle_bin(paths: list[str]) -> tuple[bool, str]:
    if os.name != "nt":
        return False, "当前系统不支持回收站"
    if not paths:
        return True, ""
    # SHFileOperation 的 pFrom 需要双 NUL 结尾的路径串；一次调用处理整批，
    # 用户在资源管理器里可以整体撤销。
    buffer = "\0".join(paths) + "\0\0"
    operation = _SHFILEOPSTRUCTW()
    operation.wFunc = _FO_DELETE
    operation.pFrom = buffer
    operation.fFlags = _FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT | _FOF_NOERRORUI
    try:
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))  # type: ignore[attr-defined]
    except (AttributeError, OSError) as exc:
        return False, str(exc)
    if result != 0:
        return False, f"回收站操作失败（代码 {result}）"
    if operation.fAnyOperationsAborted:
        return False, "操作被系统中止"
    return True, ""


def unique_target(target: Path) -> Path:
    """同名冲突时给出 "名称 (1).扩展名" 这样的新名字。"""
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    for index in range(1, 10000):
        candidate = target.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"无法为重名文件找到可用名称: {target}")


def resolve_conflict(target: Path, policy: str) -> tuple[Path | None, str]:
    """返回最终目标；None 表示按策略跳过。"""
    if not target.exists():
        return target, "ok"
    if policy == "overwrite":
        return target, "overwrite"
    if policy == "skip":
        return None, "skipped"
    return unique_target(target), "renamed"


def _copy_one(source: Path, target: Path, policy: str) -> dict[str, Any]:
    final, decision = resolve_conflict(target, policy)
    if final is None:
        return {"path": str(source), "target": str(target), "status": "skipped", "message": "目标已存在，已跳过"}
    try:
        final.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            if final.exists() and decision == "overwrite":
                shutil.rmtree(final)
            shutil.copytree(source, final, dirs_exist_ok=False)
        else:
            if final.exists() and decision == "overwrite":
                final.unlink()
            shutil.copy2(source, final)
    except OSError as exc:
        return {"path": str(source), "target": str(final), "status": "failed", "message": str(exc)}
    return {"path": str(source), "target": str(final), "status": "ok", "decision": decision}


def _move_one(source: Path, target: Path, policy: str) -> dict[str, Any]:
    final, decision = resolve_conflict(target, policy)
    if final is None:
        return {"path": str(source), "target": str(target), "status": "skipped", "message": "目标已存在，已跳过"}
    try:
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists() and decision == "overwrite":
            if final.is_dir():
                shutil.rmtree(final)
            else:
                final.unlink()
        shutil.move(str(source), str(final))
    except OSError as exc:
        return {"path": str(source), "target": str(final), "status": "failed", "message": str(exc)}
    return {"path": str(source), "target": str(final), "status": "ok", "decision": decision}


def operate(
    op: str,
    *,
    paths: Iterable[str] = (),
    target_dir: str = "",
    new_name: str = "",
    conflict: str = "rename",
    confirm: bool = False,
) -> dict[str, Any]:
    """执行一次文件操作，逐项返回结果；单项失败不影响其余项。"""
    action = str(op or "").strip().lower()
    policy = str(conflict or "rename").strip().lower()
    if policy not in {"rename", "skip", "overwrite"}:
        policy = "rename"
    sources = [Path(normalize_path(item)) for item in paths if str(item).strip()]
    results: list[dict[str, Any]] = []

    if action == "mkdir":
        for source in sources:
            try:
                source.mkdir(parents=True, exist_ok=True)
                results.append({"path": str(source), "status": "ok"})
            except OSError as exc:
                results.append({"path": str(source), "status": "failed", "message": str(exc)})
        return _summary(results)

    if action == "touch":
        for source in sources:
            try:
                source.parent.mkdir(parents=True, exist_ok=True)
                if source.exists():
                    results.append({"path": str(source), "status": "skipped", "message": "文件已存在"})
                else:
                    source.write_bytes(b"")
                    results.append({"path": str(source), "status": "ok"})
            except OSError as exc:
                results.append({"path": str(source), "status": "failed", "message": str(exc)})
        return _summary(results)

    if action == "rename":
        if len(sources) != 1:
            return _summary([{"path": "", "status": "failed", "message": "重命名一次只能处理一个文件"}])
        source = sources[0]
        cleaned = str(new_name or "").strip()
        if not cleaned or any(sep in cleaned for sep in ("/", "\\")):
            return _summary([{"path": str(source), "status": "failed", "message": "新名称不能包含路径分隔符"}])
        if not source.exists():
            return _summary([{"path": str(source), "status": "failed", "message": "文件不存在"}])
        target = source.with_name(cleaned)
        if target == source:
            return _summary([{"path": str(source), "target": str(source), "status": "ok"}])
        try:
            final, decision = resolve_conflict(target, policy)
            if final is None:
                return _summary([{"path": str(source), "status": "skipped", "message": "目标已存在，已跳过"}])
            source.rename(final)
            results.append({"path": str(source), "target": str(final), "status": "ok", "decision": decision})
        except OSError as exc:
            results.append({"path": str(source), "status": "failed", "message": str(exc)})
        return _summary(results)

    if action in {"move", "copy"}:
        if not target_dir:
            return _summary([{"path": "", "status": "failed", "message": "缺少目标目录"}])
        destination = Path(normalize_path(target_dir))
        if destination.exists() and not destination.is_dir():
            return _summary([{"path": "", "status": "failed", "message": "目标不是文件夹"}])
        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _summary([{"path": "", "status": "failed", "message": str(exc)}])
        for source in sources:
            if not source.exists():
                results.append({"path": str(source), "status": "failed", "message": "文件不存在"})
                continue
            if source.resolve() == destination.resolve() and action == "move":
                results.append({"path": str(source), "status": "skipped", "message": "已在目标目录"})
                continue
            target = destination / source.name
            handler = _copy_one if action == "copy" else _move_one
            results.append(handler(source, target, policy))
        return _summary(results)

    if action in {"trash", "delete"}:
        permanent = action == "delete"
        if permanent and not confirm:
            return _summary([{
                "path": "",
                "status": "failed",
                "message": "永久删除需要明确确认",
            }])
        if not sources:
            return _summary([{"path": "", "status": "failed", "message": "没有选中文件"}])
        # 不存在的项先标出来，剩下的按回收站/永久删除分别处理。
        existing = [source for source in sources if source.exists()]
        for source in sources:
            if not source.exists():
                results.append({"path": str(source), "status": "failed", "message": "文件不存在"})
        if not existing:
            return _summary(results)
        if not permanent:
            ok, message = _send_to_recycle_bin([str(source) for source in existing])
            for source in existing:
                results.append({
                    "path": str(source),
                    "status": "ok" if ok else "failed",
                    "message": "" if ok else message,
                })
            return _summary(results)
        for source in existing:
            try:
                if source.is_dir():
                    shutil.rmtree(source)
                else:
                    source.unlink()
                results.append({"path": str(source), "status": "ok"})
            except OSError as exc:
                results.append({"path": str(source), "status": "failed", "message": str(exc)})
        return _summary(results)

    return _summary([{"path": "", "status": "failed", "message": f"不支持的操作: {op}"}])


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    ok = sum(1 for item in items if item.get("status") == "ok")
    skipped = sum(1 for item in items if item.get("status") == "skipped")
    failed = sum(1 for item in items if item.get("status") == "failed")
    return {"items": items, "ok": ok, "skipped": skipped, "failed": failed}


def open_with_system(path: str) -> None:
    normalized = normalize_path(path)
    if not os.path.exists(normalized):
        raise FileNotFoundError(normalized)
    os.startfile(normalized)  # type: ignore[attr-defined]


def reveal_in_explorer(path: str) -> None:
    normalized = normalize_path(path)
    if not os.path.exists(normalized):
        raise FileNotFoundError(normalized)
    if os.path.isdir(normalized):
        subprocess.Popen(["explorer", normalized], creationflags=_CREATE_NO_WINDOW)
    else:
        subprocess.Popen(["explorer", f"/select,{normalized}"], creationflags=_CREATE_NO_WINDOW)
