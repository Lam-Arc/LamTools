"""bili-scroll 的操作处理器（RPC 面）。

user:“命令与面板都走 operation”+值班参数、日报列表从这里出，
与斜杠命令共用同一条通道。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from lamtools_core.app import OperationRequest, OperationResult
from lamtools_core.plugin_system.jsonc import load_jsonc_text

_PLUGIN_ROOT = Path(__file__).resolve().parent
_OUT_DIR = _PLUGIN_ROOT / "data" / "out"


def _config() -> dict[str, Any]:
    try:
        data = load_jsonc_text(_PLUGIN_ROOT / "data" / "config.jsonc")
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _dedup_rows() -> list[dict[str, Any]]:
    path = _PLUGIN_ROOT / "data" / "dedup.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return rows if isinstance(rows, list) else []


async def duty_brief(request: OperationRequest) -> OperationResult:
    cfg = _config()
    today = datetime.now().strftime("%Y-%m-%d")
    today_report = _OUT_DIR / f"{today}.md"
    seen = list(reversed(_dedup_rows()))[:40]
    return OperationResult(
        name=request.name,
        payload={
            "keywords": cfg.get("keywords") or [],
            "per_day": cfg.get("per_day", 5),
            "comment_per_round": cfg.get("comment_per_round", 1),
            "auto_comment": bool(cfg.get("auto_comment")),
            "mention_name": cfg.get("mention_name") or "",
            "report_level": cfg.get("report_level") or "full",
            "logged_in": bool(cfg.get("sessdata")),
            "seen_recent": seen,
            "seen_total": len(_dedup_rows()),
            "today_report": str(today_report) if today_report.exists() else "",
        },
    )


async def reports_list(request: OperationRequest) -> OperationResult:
    reports = []
    if _OUT_DIR.is_dir():
        for path in sorted(_OUT_DIR.glob("*.md"), reverse=True):
            reports.append(
                {
                    "file": path.name,
                    "path": str(path),
                    "bytes": path.stat().st_size,
                }
            )
    return OperationResult(name=request.name, payload={"reports": reports, "count": len(reports)})
