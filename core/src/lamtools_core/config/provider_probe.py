"""Provider connectivity probe.

The models page shows a live connection state per provider. Probing is an
explicit, bounded HTTP request (never a background poll) and the last result is
cached on disk so reopening the page does not hammer every provider.

State vocabulary (the UI maps one label per state):

* ``ok``             — reachable and the key was accepted
* ``no_model_list``  — reachable, but the gateway exposes no /models endpoint
* ``rate_limited``   — reachable, temporarily throttled
* ``unauthorized``   — key rejected
* ``missing_key``    — no key configured yet
* ``unreachable``    — network/DNS/timeout
* ``error``          — other HTTP failure
* ``invalid``        — no usable base URL
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

CACHE_FILENAME = "provider_status.json"
CACHE_TTL_SECONDS = 600
PROBE_TIMEOUT_SECONDS = 8.0
PROBE_CONCURRENCY = 4


def cache_path() -> Path:
    from lamtools_core.config.root import core_config_root

    return core_config_root() / "cache" / CACHE_FILENAME


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_cached_status() -> dict[str, Any]:
    path = cache_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"providers": {}, "updated_at": ""}
    providers = data.get("providers") if isinstance(data, dict) else {}
    return {
        "providers": providers if isinstance(providers, dict) else {},
        "updated_at": str(data.get("updated_at") or "") if isinstance(data, dict) else "",
    }


def save_cached_status(providers: dict[str, Any]) -> None:
    path = cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"providers": providers, "updated_at": _now_iso()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        # A read-only install still gets live results for this session.
        pass


def _models_url(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if base.endswith("/models"):
        return base
    return f"{base}/models"


def _headers(api_type: str, api_key: str) -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": "Sunday/1.0 (+provider-probe)"}
    if api_type.strip().lower() == "anthropic":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _state_for_status(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "ok"
    if status_code in (401, 403):
        return "unauthorized"
    if status_code in (404, 405):
        return "no_model_list"
    if status_code == 429:
        return "rate_limited"
    return "error"


async def probe_provider(provider: Any) -> dict[str, Any]:
    """Probe one ProviderConfig and return its status record."""
    base_url = str(getattr(provider, "base_url", "") or "").strip()
    api_key = str(getattr(provider, "api_key", "") or "").strip()
    checked_at = _now_iso()
    if not base_url.lower().startswith(("http://", "https://")):
        return {"state": "invalid", "detail": "接口地址不是有效的 HTTP(S) 地址", "latency_ms": 0,
                "http_status": 0, "model_count": 0, "checked_at": checked_at}
    if not api_key:
        return {"state": "missing_key", "detail": "尚未配置 API Key", "latency_ms": 0,
                "http_status": 0, "model_count": 0, "checked_at": checked_at}

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(PROBE_TIMEOUT_SECONDS, connect=5.0),
            follow_redirects=True,
        ) as client:
            response = await client.get(
                _models_url(base_url),
                headers=_headers(str(getattr(provider, "api_type", "") or ""), api_key),
            )
    except httpx.TimeoutException:
        return {"state": "unreachable", "detail": "连接超时", "latency_ms": round(
            (time.perf_counter() - started) * 1000), "http_status": 0, "model_count": 0,
            "checked_at": checked_at}
    except httpx.HTTPError as exc:
        return {"state": "unreachable", "detail": str(exc)[:180], "latency_ms": round(
            (time.perf_counter() - started) * 1000), "http_status": 0, "model_count": 0,
            "checked_at": checked_at}

    latency_ms = round((time.perf_counter() - started) * 1000)
    state = _state_for_status(response.status_code)
    model_count = 0
    detail = ""
    if state == "ok":
        try:
            payload = response.json()
            items = payload.get("data") if isinstance(payload, dict) else None
            model_count = len(items) if isinstance(items, list) else 0
        except ValueError:
            model_count = 0
    elif state == "unauthorized":
        detail = "API Key 被拒绝"
    elif state == "no_model_list":
        detail = "网关未提供模型列表接口"
    elif state == "rate_limited":
        detail = "请求被限流"
    else:
        detail = (response.text or "")[:160]
    return {
        "state": state,
        "detail": detail,
        "latency_ms": latency_ms,
        "http_status": response.status_code,
        "model_count": model_count,
        "checked_at": checked_at,
    }


async def probe_providers(providers: list[Any], *, force: bool = False) -> dict[str, Any]:
    """Probe providers, reusing fresh cache entries unless ``force``."""
    cached = load_cached_status()["providers"]
    now = time.time()
    results: dict[str, Any] = {}
    pending: list[Any] = []
    for provider in providers:
        record = cached.get(provider.id)
        if (
            not force
            and isinstance(record, dict)
            and record.get("checked_at_epoch")
            and now - float(record["checked_at_epoch"]) < CACHE_TTL_SECONDS
        ):
            results[provider.id] = {**record, "cached": True}
        else:
            pending.append(provider)

    semaphore = asyncio.Semaphore(PROBE_CONCURRENCY)

    async def run(provider: Any) -> tuple[str, dict[str, Any]]:
        async with semaphore:
            record = await probe_provider(provider)
        record["checked_at_epoch"] = now
        return provider.id, record

    if pending:
        for provider_id, record in await asyncio.gather(*(run(provider) for provider in pending)):
            results[provider_id] = record

    merged = {**cached, **results}
    save_cached_status(merged)
    return {"providers": results, "updated_at": _now_iso()}


__all__ = [
    "PROBE_TIMEOUT_SECONDS",
    "cache_path",
    "load_cached_status",
    "probe_provider",
    "probe_providers",
    "save_cached_status",
]
