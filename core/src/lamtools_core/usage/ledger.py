"""Per-model usage ledger backed by a small standalone SQLite file.

Why a separate DB: the config RPCs are file-backed and the app database is a
multi-gigabyte event store. Recording one row per model call must never contend
with either, so usage lives in its own ``usage.db`` next to the config root.

The kernel/LLM client only ever calls :func:`record_model_call`; aggregation is
read-only and returns plain dicts for the config RPC layer.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_WRITE_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    day TEXT NOT NULL,
    model_record_id TEXT NOT NULL DEFAULT '',
    model_id TEXT NOT NULL DEFAULT '',
    provider_id TEXT NOT NULL DEFAULT '',
    provider_name TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,
    calls INTEGER NOT NULL DEFAULT 1,
    usage_available INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_model_usage_ts ON model_usage(ts);
CREATE INDEX IF NOT EXISTS idx_model_usage_day ON model_usage(day);
CREATE INDEX IF NOT EXISTS idx_model_usage_model ON model_usage(model_record_id);
"""


def ledger_path() -> Path:
    """Resolve the usage ledger path.

    ``LAMTOOLS_CORE_USAGE_DB`` exists for tests and for users who want the
    ledger on a different volume; normal installs keep it next to the config
    root so a portable copy carries its usage with it.
    """
    env = os.environ.get("LAMTOOLS_CORE_USAGE_DB")
    if env:
        return Path(env)
    from lamtools_core.config.root import core_config_root

    return core_config_root() / "usage.db"


def _connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or ledger_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=2.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=2000")
    conn.executescript(_SCHEMA)
    return conn


def record_model_call(
    *,
    model_record_id: str,
    model_id: str = "",
    provider_id: str = "",
    provider_name: str = "",
    session_id: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_tokens: int = 0,
    usage_available: bool = True,
) -> None:
    """Append one model call.

    A call is recorded even when the provider omitted token usage: the call
    itself is a fact the user asked to see. Any local failure is logged and
    swallowed — bookkeeping must never break a running turn.
    """
    record_id = str(model_record_id or "").strip()
    if not record_id:
        return
    now = datetime.now().astimezone()
    row = (
        now.isoformat(timespec="seconds"),
        now.date().isoformat(),
        record_id,
        str(model_id or "").strip(),
        str(provider_id or "").strip(),
        str(provider_name or "").strip(),
        str(session_id or "").strip(),
        max(0, int(input_tokens or 0)),
        max(0, int(output_tokens or 0)),
        max(0, int(cached_tokens or 0)),
        1,
        1 if usage_available else 0,
    )
    try:
        with _WRITE_LOCK:
            conn = _connect()
            try:
                conn.execute(
                    "INSERT INTO model_usage (ts, day, model_record_id, model_id, provider_id,"
                    " provider_name, session_id, input_tokens, output_tokens, cached_tokens,"
                    " calls, usage_available) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    row,
                )
                conn.commit()
            finally:
                conn.close()
    except Exception:  # noqa: BLE001 - usage bookkeeping is best-effort
        logger.warning("failed to record model usage for %s", record_id, exc_info=True)


def _empty_bucket() -> dict[str, Any]:
    return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "tokens": 0}


def _add(bucket: dict[str, Any], row: sqlite3.Row | tuple[Any, ...]) -> None:
    calls, input_tokens, output_tokens, cached_tokens = row[0], row[1], row[2], row[3]
    bucket["calls"] += int(calls or 0)
    bucket["input_tokens"] += int(input_tokens or 0)
    bucket["output_tokens"] += int(output_tokens or 0)
    bucket["cached_tokens"] += int(cached_tokens or 0)
    bucket["tokens"] = bucket["input_tokens"] + bucket["output_tokens"]


def read_usage(*, days: int | None) -> dict[str, Any]:
    """Aggregate the ledger.

    ``days`` is a rolling window in days (``None`` = all time). The return value
    is deliberately config-agnostic: prices are applied by the RPC layer where
    the current model definitions are available.
    """
    now = datetime.now().astimezone()
    since = now - timedelta(days=days) if days else None
    since_day = since.date().isoformat() if since else None
    # Model sparklines always look 14 days back, independent of the selected
    # range, so a tile keeps its shape while the ribbon switches range.
    series_since = (now - timedelta(days=13)).date().isoformat()
    try:
        conn = _connect()
        conn.row_factory = sqlite3.Row
    except Exception:  # noqa: BLE001 - an unreadable ledger shows as empty
        logger.warning("failed to open usage ledger", exc_info=True)
        return _empty_summary(days, now)

    try:
        tracking_row = conn.execute("SELECT MIN(day) FROM model_usage").fetchone()
        tracking_since = str(tracking_row[0]) if tracking_row and tracking_row[0] else ""

        where = ""
        params: list[Any] = []
        if since:
            where = "WHERE ts >= ?"
            params.append(since.isoformat(timespec="seconds"))

        totals = _empty_bucket()
        by_model: dict[str, dict[str, Any]] = {}
        by_provider: dict[str, dict[str, Any]] = {}
        daily: dict[str, dict[str, Any]] = {}
        for row in conn.execute(
            "SELECT ts, day, model_record_id, model_id, provider_id, provider_name,"
            " SUM(calls), SUM(input_tokens), SUM(output_tokens), SUM(cached_tokens), MAX(ts)"
            " FROM model_usage " + where +
            " GROUP BY day, model_record_id, model_id, provider_id, provider_name",
            params,
        ):
            ts, day, model_record_id, model_id, provider_id, provider_name = row[0], row[1], row[2], row[3], row[4], row[5]
            calls, input_tokens, output_tokens, cached_tokens, last_ts = row[6], row[7], row[8], row[9], row[10]
            metrics = (calls, input_tokens, output_tokens, cached_tokens)
            _add(totals, metrics)

            model_bucket = by_model.setdefault(model_record_id, {
                **_empty_bucket(), "model_record_id": model_record_id,
                "model_id": model_id, "provider_id": provider_id,
                "provider_name": provider_name, "last_used_at": last_ts,
            })
            _add(model_bucket, metrics)
            if last_ts and str(last_ts) > str(model_bucket.get("last_used_at") or ""):
                model_bucket["last_used_at"] = last_ts

            provider_key = provider_id or provider_name or "unknown"
            provider_bucket = by_provider.setdefault(provider_key, {
                **_empty_bucket(), "provider_id": provider_id, "provider_name": provider_name,
            })
            _add(provider_bucket, metrics)

            day_bucket = daily.setdefault(day, {**_empty_bucket(), "date": day})
            _add(day_bucket, metrics)

        # Current calendar month per provider, for the user-set monthly budget.
        month_start = now.date().replace(day=1).isoformat()
        month_by_model: dict[str, dict[str, Any]] = {}
        for row in conn.execute(
            "SELECT model_record_id, provider_id, provider_name, SUM(input_tokens),"
            " SUM(output_tokens), SUM(cached_tokens)"
            " FROM model_usage WHERE day >= ?"
            " GROUP BY model_record_id, provider_id, provider_name",
            [month_start],
        ):
            bucket = month_by_model.setdefault(str(row[0] or ""), {
                "model_record_id": row[0], "provider_id": row[1], "provider_name": row[2],
                "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "tokens": 0,
            })
            bucket["input_tokens"] += int(row[3] or 0)
            bucket["output_tokens"] += int(row[4] or 0)
            bucket["cached_tokens"] += int(row[5] or 0)
            bucket["tokens"] = bucket["input_tokens"] + bucket["output_tokens"]

        # 14-day per-model series for the tile sparklines.
        series_days = [(now - timedelta(days=offset)).date() for offset in range(13, -1, -1)]
        model_series: dict[str, dict[str, int]] = {}
        for row in conn.execute(
            "SELECT day, model_record_id, SUM(input_tokens), SUM(output_tokens)"
            " FROM model_usage WHERE day >= ? GROUP BY day, model_record_id",
            [series_since],
        ):
            day = str(row[0])
            model = str(row[1])
            bucket = model_series.setdefault(model, {})
            bucket[day] = bucket.get(day, 0) + int(row[2] or 0) + int(row[3] or 0)
        series_index = {day.isoformat(): index for index, day in enumerate(series_days)}
        series: dict[str, list[int]] = {}
        for model, per_day in model_series.items():
            values = [0] * len(series_days)
            for day, tokens in per_day.items():
                position = series_index.get(day)
                if position is not None:
                    values[position] = tokens
            series[model] = values
    finally:
        conn.close()

    # The ribbon always shows a continuous axis ending today, zeros included.
    axis_days = days if days and days <= 90 else 14
    axis: list[dict[str, Any]] = []
    for offset in range(axis_days - 1, -1, -1):
        day = (now - timedelta(days=offset)).date().isoformat()
        bucket = daily.get(day) or {**_empty_bucket(), "date": day}
        axis.append(bucket)

    return {
        "totals": totals,
        "by_model": list(by_model.values()),
        "by_provider": list(by_provider.values()),
        "month_by_model": list(month_by_model.values()),
        "daily": axis,
        "series": series,
        "tracking_since": tracking_since,
        "since": since_day or "",
    }


def _empty_summary(days: int | None, now: datetime) -> dict[str, Any]:
    axis_days = days if days and days <= 90 else 14
    return {
        "totals": _empty_bucket(),
        "by_model": [],
        "by_provider": [],
        "daily": [
            {**_empty_bucket(), "date": (now - timedelta(days=offset)).date().isoformat()}
            for offset in range(axis_days - 1, -1, -1)
        ],
        "series": {},
        "month_by_model": [],
        "tracking_since": "",
        "since": "",
    }


__all__ = ["ledger_path", "read_usage", "record_model_call"]
