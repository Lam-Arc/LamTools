"""Test API proxy: hijack point for Core LLM streaming comparison.

Core's provider base_url is pointed at this proxy (http://127.0.0.1:8899/v2).
Every request is forwarded verbatim to the real API; each SSE chunk is logged
with its arrival time and character count so we can tell whether the real API
streams small chunks slowly (API cadence) or Core/FE drop cadence.

Run: python testapi_proxy.py [port] [real_base_url]
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import Counter

import httpx

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
REAL_BASE = sys.argv[2] if len(sys.argv) > 2 else "https://maas-coding-api.cn-huabei-1.xf-yun.com/v2"

_log_lock = asyncio.Lock()


async def log_line(line: str) -> None:
    async with _log_lock:
        print(line, flush=True)


async def handle(scope, receive, send) -> None:
    if scope["type"] != "http":
        return
    path = scope["path"]
    if scope["method"] != "POST" or not path.endswith("/chat/completions"):
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b"not found"})
        return

    body = b""
    while True:
        msg = await receive()
        if msg["type"] == "http.request":
            body += msg.get("body", b"")
            if not msg.get("more_body"):
                break
        elif msg["type"] == "http.disconnect":
            return
    headers = [(k.decode().lower(), v.decode()) for k, v in scope.get("headers", [])]
    header_map = {k: v for k, v in headers}
    try:
        req = json.loads(body)
    except Exception:
        await send({"type": "http.response.start", "status": 400, "headers": []})
        await send({"type": "http.response.body", "body": b"bad json"})
        return

    messages = req.get("messages") or []
    total_chars = sum(len(str(m.get("content") or "")) for m in messages)
    model = str(req.get("model") or "?")
    stream = bool(req.get("stream"))
    t0 = time.monotonic()
    await log_line(
        f"[req] t={t0:.3f} model={model} stream={stream} messages={len(messages)} total_chars={total_chars}"
    )

    forward_headers = {
        "Authorization": header_map.get("authorization", ""),
        "Content-Type": "application/json",
    }
    chunks: list[tuple[float, int, int]] = []

    try:
        async with httpx.AsyncClient(timeout=600) as client:
            async with client.stream(
                "POST", f"{REAL_BASE}/chat/completions", headers=forward_headers, json=req
            ) as resp:
                if not stream:
                    data = await resp.aread()
                    await send({"type": "http.response.start", "status": resp.status_code,
                                "headers": [(b"content-type", b"application/json")]})
                    await send({"type": "http.response.body", "body": data})
                    await log_line(f"[done] non-stream total={len(data)}B status={resp.status_code}")
                    return

                await send({"type": "http.response.start", "status": 200,
                            "headers": [(b"content-type", b"text/event-stream"),
                                        (b"cache-control", b"no-cache")]})
                async for line in resp.aiter_lines():
                    wire = (line + "\n").encode()
                    if line.startswith("data: "):
                        payload = line[6:]
                        if payload.strip() == "[DONE]":
                            await send({"type": "http.response.body", "body": wire, "more_body": True})
                            continue
                        try:
                            obj = json.loads(payload)
                        except Exception:
                            pass
                        else:
                            delta = ((obj.get("choices") or [{}])[0].get("delta") or {})
                            content = delta.get("content") or ""
                            reasoning = delta.get("reasoning_content") or ""
                            if content or reasoning:
                                chunks.append((time.monotonic() - t0, len(content), len(reasoning)))
                                await log_line(
                                    f"[chunk] t={chunks[-1][0]:.3f} c={len(content)} r={len(reasoning)}"
                                )
                    await send({"type": "http.response.body", "body": wire, "more_body": True})
                await send({"type": "http.response.body", "body": b"", "more_body": False})
    except Exception as exc:  # noqa: BLE001
        await log_line(f"[error] {type(exc).__name__}: {exc}")
        return

    if chunks:
        gaps = [chunks[i][0] - chunks[i - 1][0] for i in range(1, len(chunks))]
        total_c = sum(c for _, c, _ in chunks)
        total_r = sum(r for _, _, r in chunks)
        avg_gap = sum(gaps) / len(gaps) if gaps else 0
        gap_buckets: Counter[int] = Counter()
        for g in gaps:
            gap_buckets[min(int(g * 1000 / 100), 30)] += 1
        cs = sorted(c for _, c, _ in chunks)
        await log_line(
            f"[done] chunks={len(chunks)} total_c={total_c} total_r={total_r} "
            f"span={chunks[-1][0]:.3f}s avg_gap={avg_gap * 1000:.0f}ms "
            f"gap100ms_buckets={dict(sorted(gap_buckets.items()))}"
        )
        await log_line(
            f"[summary] chars_per_chunk median={cs[len(cs) // 2]} max={cs[-1]}"
        )


async def main() -> None:
    from uvicorn import Config, Server

    config = Config(handle, host="127.0.0.1", port=PORT, log_level="warning")
    await log_line(f"[proxy] listening on 127.0.0.1:{PORT} -> {REAL_BASE}")
    await Server(config).serve()


if __name__ == "__main__":
    asyncio.run(main())
