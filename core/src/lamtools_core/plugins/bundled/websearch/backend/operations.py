from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from lamtools_core.app import OperationRequest, OperationResult
from lamtools_core.tool.search.factory import _default_config, get_provider


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def widget_snapshot(
    request: OperationRequest, *, work_root: Path | None, data_dir: Path | None
) -> OperationResult:
    del request
    config = _default_config(str(work_root) if work_root else None, data_dir=data_dir)
    provider = str(config.get("provider") or "ddg")
    fallbacks = config.get("fallback_providers")
    fallbacks = [str(item) for item in fallbacks] if isinstance(fallbacks, list) else []
    return OperationResult(
        name="websearch.widget.snapshot",
        payload={
            "schema_version": 1,
            "state": "ok",
            "summary": f"Configured engine: {provider}",
            "updated_at": _now(),
            "blocks": [
                {"type": "status", "label": "Engine", "value": provider, "state": "ok"},
                {"type": "metric", "label": "Result limit", "value": int(config.get("limit") or 5)},
                {"type": "metric", "label": "Timeout", "value": float(config.get("timeout") or 15), "unit": "s"},
                {"type": "list", "label": "Fallback engines", "items": fallbacks},
            ],
            "actions": [{"id": "test", "enabled": True}],
        },
    )


async def widget_health(
    request: OperationRequest, *, work_root: Path | None, data_dir: Path | None
) -> OperationResult:
    config = _default_config(str(work_root) if work_root else None, data_dir=data_dir)
    try:
        provider = get_provider(str(config.get("provider") or "ddg"), config)
    except ValueError as exc:
        # 内核名不被支持是"这个引擎不可用"的状态，不是宿主错误：返回 error
        # 状态让右侧栏把原因显示出来（原先直接抛出，界面上看不到任何解释）。
        return OperationResult(
            name="websearch.widget.health",
            status="error",
            payload={
                "state": "error",
                "provider": str(config.get("provider") or ""),
                "error": str(exc),
                "checked_at": _now(),
            },
        )
    query = str(request.payload.get("query") or "OpenAI").strip()
    if not query or len(query) > 200:
        return OperationResult(
            name="websearch.widget.health", status="error", payload={"error": "query must be 1-200 characters"}
        )
    try:
        timeout = max(1.0, min(float(config.get("timeout") or 15), 30.0))
        results = await asyncio.wait_for(provider.search(query, limit=1, domains=[]), timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - provider failures are widget status, not host failures
        return OperationResult(
            name="websearch.widget.health",
            status="error",
            payload={"state": "error", "provider": provider.name, "error": str(exc), "checked_at": _now()},
        )
    return OperationResult(
        name="websearch.widget.health",
        payload={
            "state": "ok",
            "provider": provider.name,
            "result_count": len(results),
            "checked_at": _now(),
        },
    )
