"""Operation catalog for the ``update.*`` RPCs (GUI / CLI shared entry points).

``update.check`` reads the manifest; ``update.download`` and ``update.install``
are the in-app path that replaced "open a browser and run the installer
yourself". Both are host-authoritative: the download re-reads the manifest for
its URL and digest rather than trusting the caller, and only a file this process
verified can be run.
"""

from __future__ import annotations

import asyncio
from typing import Any

from lamtools_core.app.operation_catalog import (
    OperationCatalog,
    OperationRequest,
    OperationResult,
)
from lamtools_core.update.checker import check_update
from lamtools_core.update.installer import (
    UpdateInstallError,
    cancel_download,
    progress_snapshot,
    run_installer,
    start_download,
)


def build_update_operation_catalog() -> OperationCatalog:
    """Build an OperationCatalog exposing ``update.check/download/install``.

    ``update.check`` mirrors :func:`lamtools_core.update.checker.check_update`:
    ``status`` is one of ``update_available`` / ``up_to_date`` / ``check_failed``.
    The other two answer ``{"ok": bool, ...}`` and never raise.
    """

    catalog = OperationCatalog()

    async def update_check(request: OperationRequest) -> OperationResult:
        del request  # no payload expected
        # The sync HTTP check can block for up to ~10s on a slow network —
        # never let it stall the event loop (audit 11).
        payload: dict[str, Any] = await asyncio.to_thread(check_update)
        return OperationResult(name="update.check", payload=payload)

    async def update_download(request: OperationRequest) -> OperationResult:
        del request  # no payload: the host decides what may be downloaded
        checked: dict[str, Any] = await asyncio.to_thread(check_update)
        if checked.get("status") != "update_available":
            return OperationResult(
                name="update.download",
                payload={"ok": False, "error": "当前没有可安装的更新，请先检查更新"},
            )
        digest = str(checked.get("sha256") or "")
        if not digest:
            return OperationResult(
                name="update.download",
                payload={"ok": False, "error": "发布清单没有提供 sha256，无法校验安装包"},
            )
        # Returns immediately: a 90 MB download must not hold the request open.
        # The caller polls update.status for progress.
        snapshot = await asyncio.to_thread(
            start_download, str(checked.get("download_url") or ""), digest
        )
        return OperationResult(
            name="update.download",
            payload={
                "ok": True,
                **snapshot,
                "version": str(checked.get("latest_version") or ""),
                "message": _download_message(snapshot),
            },
        )

    async def update_status(request: OperationRequest) -> OperationResult:
        del request
        snapshot = progress_snapshot()
        return OperationResult(
            name="update.status",
            payload={"ok": True, **snapshot, "message": _download_message(snapshot)},
        )

    async def update_cancel(request: OperationRequest) -> OperationResult:
        # Cancelling is a normal end to a download, not an error: the card asks,
        # the worker stops between chunks, and the state becomes 'cancelled'.
        del request
        snapshot = await asyncio.to_thread(cancel_download)
        return OperationResult(
            name="update.cancel",
            payload={"ok": True, **snapshot, "message": _download_message(snapshot)},
        )

    async def update_install(request: OperationRequest) -> OperationResult:
        del request  # no payload: the verified file is host-held state
        try:
            result = await asyncio.to_thread(run_installer)
        except UpdateInstallError as exc:
            return OperationResult(name="update.install", payload={"ok": False, "error": str(exc)})
        return OperationResult(name="update.install", payload={"ok": True, **result})

    catalog.register("update.check", update_check)
    catalog.register("update.download", update_download)
    catalog.register("update.status", update_status)
    catalog.register("update.cancel", update_cancel)
    catalog.register("update.install", update_install)
    return catalog


def _download_message(snapshot: dict[str, Any]) -> str:
    """One line the UI can show verbatim, in the same shape both hosts use."""
    state = str(snapshot.get("state") or "idle")
    received = int(snapshot.get("received") or 0)
    total = int(snapshot.get("total") or 0)
    megabytes = received / (1024 * 1024)
    if state == "downloading":
        if total > 0:
            percent = min(100, int(received * 100 / total))
            return f"正在下载 {percent}%（{megabytes:.1f} MB / {total / (1024 * 1024):.1f} MB）"
        return f"正在下载（{megabytes:.1f} MB）"
    if state == "verified":
        return f"已下载并校验 {snapshot.get('name') or '安装包'}"
    if state == "cancelled":
        return "已取消下载"
    if state == "failed":
        return ""
    return ""


__all__ = ["build_update_operation_catalog"]
