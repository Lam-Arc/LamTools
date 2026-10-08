"""Record/replay proxy for Sunday's model traffic.

Why this exists
---------------
The demo runs must look smooth and take a predictable amount of time, while the
real provider is slow and jittery.  So: point the demo project's provider at
this proxy, run the take once in ``record`` mode (real responses, every byte and
every inter-chunk gap saved), then run the same take as many times as needed in
``replay`` mode (identical bytes, controlled pace).

Design rules
------------
* Byte fidelity: replay returns the exact recorded body bytes, so the UI parses
  and renders precisely what it rendered during the real run.  Recorded bodies
  are stored decoded: the app always parsed the *uncompressed* body, so that is
  the canonical byte stream a replay must reproduce.
* Loud failure: a replay miss or a request that does not match the cassette
  fails visibly (503 / 409) and is written to a log next to the take.  A take
  that cannot be reproduced must never silently produce bad footage.
* Independent streams: the agent loop, auto-title and background summaries are
  replayed from separate ordered queues, so an interleaved call cannot steal
  another stream's response.

Usage
-----
    py -3.14 scripts/demo-video/proxy/proxy.py --mode record --take <take-dir>
    py -3.14 scripts/demo-video/proxy/proxy.py --mode replay --take <take-dir> --speed 3
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cassette import (  # noqa: E402  (path bootstrap above)
    CallRecord,
    Cassette,
    classify_request,
    redact_body,
    redact_headers,
)

# Headers that describe a single hop and must not be forwarded or replayed.
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
    "accept-encoding",
}


def chunk_char_counts(record: CallRecord, body: bytes | None = None) -> list[int]:
    """Approximate the visible text each streamed chunk carries.

    Used for reading-speed pacing: a chunk boundary is a transport detail, but
    "how many characters appear per second" is what a viewer perceives.
    """
    source = record.response_body if body is None else body
    counts: list[int] = []
    cursor = 0
    for chunk_meta in record.chunks:
        size = int(chunk_meta["n"])
        payload = source[cursor : cursor + size]
        cursor += size
        text = 0
        try:
            body = payload.decode("utf-8", errors="ignore")
            for line in body.splitlines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]" or not data:
                    continue
                parsed = json.loads(data)
                for choice in parsed.get("choices") or []:
                    delta = choice.get("delta") or choice.get("message") or {}
                    text += len(str(delta.get("content") or ""))
                    text += len(str(delta.get("reasoning_content") or ""))
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            text = 0
        counts.append(text if text else max(1, size // 4))
    return counts


class Recorder:
    """State shared by the HTTP handlers for one proxy process."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.take_dir = Path(args.take).resolve()
        self.take_dir.mkdir(parents=True, exist_ok=True)
        self.cassette = Cassette(self.take_dir, mode=args.mode)
        self.log_path = self.take_dir / "proxy.log"
        self.miss_path = self.take_dir / "replay-misses.jsonl"
        self.mismatch_path = self.take_dir / "replay-mismatches.jsonl"
        self.served: dict[str, int] = {}
        self.missed: dict[str, int] = {}
        self.by_kind: dict[str, list[CallRecord]] = {}
        self.pointers: dict[str, int] = {}
        self.upstream_via_env_proxy = not args.no_env_proxy
        self.client = self._new_upstream_client()
        if args.mode == "replay":
            records = self.cassette.load()
            for record in records:
                self.by_kind.setdefault(record.kind, []).append(record)
            self.pointers = {kind: 0 for kind in self.by_kind}
            self.log(
                f"replay ready: {len(records)} calls, streams="
                + ", ".join(f"{k}:{len(v)}" for k, v in self.by_kind.items())
            )

    # -- logging ----------------------------------------------------------

    def log(self, message: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {message}"
        print(line, flush=True)
        try:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # -- upstream client --------------------------------------------------

    def _new_upstream_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self.args.timeout, connect=30.0),
            follow_redirects=False,
            trust_env=self.upstream_via_env_proxy,
        )

    async def set_upstream_proxy_mode(self, via_env_proxy: bool) -> None:
        """Rebuild the upstream client with a different proxy mode, live.

        The recorded take does not care how the bytes travelled, so the route
        can be switched mid-take: a session that started on the slow direct
        path (37% packet loss to the provider's Cloudflare edge, stalls of
        30-96s mid-stream on 2026-10-07) keeps recording without a cassette
        split.  The old client is closed after the swap; an in-flight request
        on it fails and is retried by the app.
        """
        self.upstream_via_env_proxy = bool(via_env_proxy)
        old = self.client
        self.client = self._new_upstream_client()
        try:
            await old.aclose()
        except Exception:  # pragma: no cover - best effort teardown
            pass
        self.log(
            "upstream proxy mode -> "
            + ("environment proxy (system proxy settings)"
               if self.upstream_via_env_proxy else "direct, proxy bypassed")
        )

    # -- shared helpers ---------------------------------------------------

    @staticmethod
    def _filter_headers(headers: Any, *, for_response: bool = False) -> dict[str, str]:
        out: dict[str, str] = {}
        for name, value in headers.items():
            if name.lower() in _HOP_BY_HOP:
                continue
            out[name] = value
        if for_response:
            out.pop("content-length", None)
            out.pop("content-encoding", None)
        else:
            # Ask the upstream for an identity body explicitly.  Dropping the
            # header is not enough: httpx re-adds its own default (gzip,
            # deflate, zstd) when it is absent, and a compressed body forwarded
            # with its encoding header stripped is unreadable to the app
            # ('utf-8' codec can't decode byte 0xb5 in position 1 — the zstd
            # magic number, seen live on 2026-10-07).
            out["accept-encoding"] = "identity"
        return out

    @staticmethod
    def _signature(body: bytes) -> str:
        return hashlib.sha256(body).hexdigest()[:16]

    # -- record -----------------------------------------------------------

    async def record(self, request: Request) -> StreamingResponse | JSONResponse:
        raw_body = await request.body()
        try:
            parsed_body: Any = json.loads(raw_body) if raw_body else None
        except json.JSONDecodeError:
            parsed_body = None
        kind = classify_request(parsed_body, request.url.path)
        upstream_url = self.args.upstream.rstrip("/") + request.url.path
        if request.url.query:
            upstream_url += f"?{request.url.query}"

        headers = self._filter_headers(request.headers)
        started = time.time()
        dispatch = time.perf_counter()

        record = CallRecord(
            index=-1,
            kind=kind,
            method=request.method,
            path=request.url.path,
            request_headers=redact_headers(dict(request.headers)),
            request_body=raw_body,
            request_json=redact_body(parsed_body),
            status=200,
            response_headers={},
            response_body=b"",
            chunks=[],
            started_at=started,
        )

        upstream_request = self.client.build_request(
            request.method, upstream_url, headers=headers, content=raw_body
        )
        chunks: list[bytes] = []
        offsets: list[dict[str, int]] = []
        first_at: float | None = None
        status_headers: dict[str, str] = {}

        try:
            response = await self.client.send(upstream_request, stream=True)
        except httpx.HTTPError as exc:  # upstream unreachable: still record it
            self.log(f"upstream call failed: {exc!r}")
            await self.client.aclose()
            self.client = self._new_upstream_client()
            record.status = 599
            record.response_headers = {"content-type": "text/plain; charset=utf-8"}
            message = f"proxy upstream error: {exc}\n".encode()
            record.response_body = message
            record.total_ms = (time.perf_counter() - dispatch) * 1000
            self.cassette.append(record)
            return JSONResponse(
                {"error": "upstream_unreachable", "detail": str(exc)}, status_code=599
            )

        status_headers = self._filter_headers(response.headers, for_response=True)
        record.status = response.status_code
        # The body is stored decoded (the generator reads aiter_bytes, so any
        # content-encoding the provider added despite the identity request is
        # removed here), therefore the stored envelope must not claim an
        # encoding that no longer applies — replay would otherwise try to
        # decompress the plain bytes a second time.
        record.response_headers = {
            name: value
            for name, value in response.headers.items()
            if name.lower() not in ("content-encoding", "content-length")
        }
        upstream_encoding = (response.headers.get("content-encoding") or "").strip().lower()
        if upstream_encoding not in ("", "identity"):
            self.log(
                f"upstream sent a {upstream_encoding}-encoded body; "
                "recording decoded bytes"
            )
            if upstream_encoding not in ("zstd", "gzip", "deflate"):
                # httpx cannot decode this streaming (e.g. brotli without the
                # optional package): the raw bytes would flow through with the
                # encoding header stripped.  Say so loudly instead of recording
                # an unreadable body.
                self.log(
                    f"WARNING: no streaming decoder for '{upstream_encoding}'; "
                    "recorded body may be unreadable to the app"
                )

        async def generator():
            nonlocal first_at
            try:
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    now = time.perf_counter()
                    if first_at is None:
                        first_at = now
                        record.ttfb_ms = (now - dispatch) * 1000
                    chunks.append(chunk)
                    offsets.append(
                        {
                            "o": int((now - first_at) * 1000),
                            "n": len(chunk),
                        }
                    )
                    yield chunk
            finally:
                await response.aclose()
                record.response_body = b"".join(chunks)
                record.chunks = offsets
                record.total_ms = (time.perf_counter() - dispatch) * 1000
                self.cassette.append(record)
                self.log(
                    f"record #{record.index} kind={kind} status={record.status} "
                    f"bytes={len(record.response_body)} chunks={len(offsets)} "
                    f"ttfb={record.ttfb_ms:.0f}ms total={record.total_ms:.0f}ms"
                )

        return StreamingResponse(
            generator(), status_code=response.status_code, headers=status_headers
        )

    # -- replay -----------------------------------------------------------

    async def replay(self, request: Request) -> StreamingResponse | JSONResponse:
        raw_body = await request.body()
        try:
            parsed_body: Any = json.loads(raw_body) if raw_body else None
        except json.JSONDecodeError:
            parsed_body = None
        kind = classify_request(parsed_body, request.url.path)
        stream = self.by_kind.get(kind, [])
        pointer = self.pointers.get(kind, 0)

        if pointer >= len(stream):
            self.missed[kind] = self.missed.get(kind, 0) + 1
            payload = {
                "at": time.time(),
                "kind": kind,
                "path": request.url.path,
                "reason": "cassette exhausted",
                "served_of_kind": pointer,
                "recorded_of_kind": len(stream),
                "summary": self._request_summary(parsed_body),
            }
            self._append_jsonl(self.miss_path, payload)
            self.log(f"REPLAY MISS kind={kind}: no more recorded calls")
            return JSONResponse(
                {
                    "error": "cassette_exhausted",
                    "kind": kind,
                    "detail": "the take ran more calls than were recorded",
                },
                status_code=503,
            )

        record = stream[pointer]
        self.pointers[kind] = pointer + 1
        self.served[kind] = self.served.get(kind, 0) + 1

        if self.args.strict and record.request_body:
            expected = json.loads(record.request_body) if record.request_body else None
            if expected != parsed_body:
                payload = {
                    "at": time.time(),
                    "kind": kind,
                    "index": record.index,
                    "expected_signature": self._signature(record.request_body),
                    "actual_signature": self._signature(raw_body),
                    "actual_summary": self._request_summary(parsed_body),
                    "expected_summary": self._request_summary(expected),
                }
                self._append_jsonl(self.mismatch_path, payload)
                self.log(f"REPLAY MISMATCH kind={kind} index={record.index}")
                return JSONResponse(
                    {"error": "request_mismatch", "kind": kind, "index": record.index},
                    status_code=409,
                )

        headers = self._filter_headers(record.response_headers, for_response=True)
        body, headers = self._decode_if_encoded(record, headers)
        self.log(
            f"replay #{record.index} kind={kind} status={record.status} "
            f"bytes={len(record.response_body)} chunks={len(record.chunks)}"
        )
        return StreamingResponse(
            self._paced_body(record, body),
            status_code=record.status,
            headers=headers,
        )

    def _request_summary(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            return {}
        messages = body.get("messages")
        return {
            "model": body.get("model"),
            "stream": body.get("stream"),
            "message_count": len(messages) if isinstance(messages, list) else None,
            "tool_count": len(body.get("tools") or []),
        }

    def _decode_if_encoded(
        self, record: CallRecord, headers: dict[str, str]
    ) -> tuple[bytes, dict[str, str]]:
        """Serve the body decoded when the provider compressed it.

        Non-streaming replies can come back zstd-compressed (the provider does
        this even though the client never asked for it), and a client that
        cannot read that encoding silently drops the payload — which is exactly
        how an auto-generated session title goes missing.  The recorded bytes
        stay untouched on disk; only the replayed envelope is made readable.
        """
        encoding = (record.response_headers.get("content-encoding") or "").lower()
        if not encoding or not self.args.decompress_replay:
            return record.response_body, headers
        try:
            if "zstd" in encoding:
                from compression.zstd import decompress as decode
            elif "gzip" in encoding:
                import gzip

                decode = gzip.decompress
            elif "deflate" in encoding:
                import zlib

                decode = zlib.decompress
            else:
                return record.response_body, headers
            body = decode(record.response_body)
        except Exception as exc:  # keep replay working even if decoding fails
            self.log(f"decode of #{record.index} ({encoding}) failed: {exc!r}")
            return record.response_body, headers
        headers = dict(headers)
        headers.pop("content-encoding", None)
        headers.pop("content-length", None)
        return body, headers

    async def _paced_body(self, record: CallRecord, body: bytes | None = None):
        source = record.response_body if body is None else body
        args = self.args
        speed = args.title_speed if record.kind == "aux" and args.title_speed else args.speed
        speed = max(speed, 0.05)

        # Cinematic pacing: ignore the recorded rhythm and emit on a fixed
        # cadence.  Recorded streams are bursty (long silence, then a flood),
        # which on video reads as either dead air or an unreadable flash.
        uniform_ms = args.chunk_interval_ms
        if record.kind == "aux" and args.title_chunk_interval_ms:
            uniform_ms = args.title_chunk_interval_ms

        def head_delay_ms() -> float:
            if args.ttfb_ms >= 0:
                return float(args.ttfb_ms)
            delay = record.ttfb_ms / speed
            if args.max_ttfb_ms >= 0:
                delay = min(delay, args.max_ttfb_ms)
            return delay

        if not record.chunks:
            # Non-streaming body: one shot, paced by the head delay.
            delay = head_delay_ms() / 1000.0
            if delay > 0:
                await asyncio.sleep(delay)
            if source:
                yield source
            return

        head_ms = head_delay_ms()
        start = time.perf_counter()
        cursor = 0
        last_ms = 0.0
        char_counts = (
            chunk_char_counts(record, source) if args.chars_per_second > 0 else None
        )
        emitted_chars = 0
        for index, chunk_meta in enumerate(record.chunks):
            size = int(chunk_meta["n"])
            payload = source[cursor : cursor + size]
            cursor += size
            if index == 0:
                target_ms = head_ms
            elif char_counts is not None:
                target_ms = head_ms + (emitted_chars / args.chars_per_second) * 1000.0
            elif uniform_ms:
                target_ms = head_ms + index * uniform_ms
            else:
                target_ms = chunk_meta["o"] / speed
                if args.min_chunk_ms > 0:
                    target_ms = max(target_ms, last_ms + args.min_chunk_ms)
            if char_counts is not None:
                emitted_chars += char_counts[index]
            last_ms = target_ms
            wait = target_ms / 1000.0 - (time.perf_counter() - start)
            if wait > 0:
                await asyncio.sleep(wait)
            if payload:
                yield payload


def build_app(recorder: Recorder) -> FastAPI:
    app = FastAPI(title="LamTools demo proxy", docs_url=None, redoc_url=None)

    @app.get("/__control/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "mode": recorder.args.mode,
            "take": str(recorder.take_dir),
            "served": recorder.served,
            "missed": recorder.missed,
            "upstream_via_env_proxy": recorder.upstream_via_env_proxy,
        }

    @app.post("/__control/upstream")
    async def set_upstream(via_env_proxy: bool) -> dict[str, Any]:
        """Switch the upstream route mid-take (see set_upstream_proxy_mode)."""
        if via_env_proxy == recorder.upstream_via_env_proxy:
            return {"ok": True, "upstream_via_env_proxy": via_env_proxy, "changed": False}
        await recorder.set_upstream_proxy_mode(via_env_proxy)
        return {"ok": True, "upstream_via_env_proxy": via_env_proxy, "changed": True}

    @app.get("/__control/stats")
    async def stats() -> dict[str, Any]:
        recorded: dict[str, int] = {}
        for record in recorder.cassette.records():
            recorded[record.kind] = recorded.get(record.kind, 0) + 1
        return {
            "mode": recorder.args.mode,
            "served": recorder.served,
            "missed": recorder.missed,
            "recorded": recorded,
            "replay_streams": {k: len(v) for k, v in recorder.by_kind.items()},
            "cassette_calls": len(recorder.cassette.records()),
        }

    @app.api_route(
        "/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
    )
    async def passthrough(request: Request, path: str):
        if path.startswith("__control/"):
            return JSONResponse({"error": "not_found"}, status_code=404)
        if recorder.args.mode == "record":
            return await recorder.record(request)
        return await recorder.replay(request)

    return app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("record", "replay"), required=True)
    parser.add_argument("--take", required=True, help="take directory")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument(
        "--host", default="127.0.0.1", help="bind address (loopback by default)"
    )
    parser.add_argument(
        "--upstream",
        default="https://api.commandcode.ai",
        help="real provider origin used in record mode",
    )
    parser.add_argument(
        "--speed", type=float, default=1.0, help="replay speed multiplier"
    )
    parser.add_argument(
        "--title-speed",
        type=float,
        default=8.0,
        help="replay speed for auxiliary (title/summary) calls",
    )
    parser.add_argument(
        "--min-chunk-ms",
        type=float,
        default=0.0,
        help="floor on the gap between two streamed chunks",
    )
    parser.add_argument(
        "--chunk-interval-ms",
        type=float,
        default=0.0,
        help="fixed gap between streamed chunks (0 keeps the recorded rhythm)",
    )
    parser.add_argument(
        "--title-chunk-interval-ms",
        type=float,
        default=0.0,
        help="fixed gap for auxiliary calls (defaults to --chunk-interval-ms)",
    )
    parser.add_argument(
        "--tokens-per-second",
        type=float,
        default=0.0,
        help="convenience: derive the chunk interval from a target reading speed",
    )
    parser.add_argument(
        "--chars-per-second",
        type=float,
        default=0.0,
        help="pace by visible characters per second (content-aware, best for reading)",
    )
    parser.add_argument(
        "--ttfb-ms",
        type=float,
        default=-1.0,
        help="fixed time to the first byte in replay (-1 keeps the recorded one)",
    )
    parser.add_argument(
        "--max-ttfb-ms",
        type=float,
        default=600.0,
        help="cap on the first-token delay in replay (-1 disables)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="reject a replay request whose body differs from the cassette",
    )
    parser.add_argument(
        "--no-decompress-replay",
        dest="decompress_replay",
        action="store_false",
        help="replay bodies exactly as recorded, including any content-encoding",
    )
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--no-env-proxy", action="store_true")
    parser.set_defaults(decompress_replay=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.tokens_per_second > 0 and args.chunk_interval_ms <= 0:
        args.chunk_interval_ms = 1000.0 / args.tokens_per_second
    recorder = Recorder(args)
    if args.mode == "record":
        # Record mode numbers calls from zero, so starting over an old take
        # silently overwrites its cassette (this destroyed a take once).  A
        # take directory that still holds traffic must be moved or cleared.
        existing = sorted(recorder.cassette.dir.glob("*.request.json"))
        if existing:
            print(
                f"error: {recorder.cassette.dir} already holds {len(existing)} recorded "
                "calls; record mode never overwrites.  Use a fresh --take, or move/"
                "clear the cassette directory first.",
                file=sys.stderr,
            )
            return 1
    app = build_app(recorder)
    mode_line = (
        f"proxy {args.mode} on http://{args.host}:{args.port} "
        f"take={recorder.take_dir}"
    )
    recorder.log(mode_line)
    if args.mode == "record":
        recorder.log(f"upstream={args.upstream}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
