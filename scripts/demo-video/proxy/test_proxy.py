"""Self-test for the demo-video record/replay proxy.

Runs a fake upstream that streams SSE with realistic gaps, records a take
through the proxy, then replays it and checks:

1. the replayed bytes are identical to the recorded bytes;
2. the replay keeps the recorded ordering per stream (main loop vs aux calls);
3. replay speed actually scales the wall-clock duration;
4. running more calls than were recorded fails loudly (503), never silently;
5. strict mode rejects a request that differs from the cassette (409);
6. a provider that answers with a zstd-compressed body anyway (seen live on
   api.commandcode.ai, 2026-10-07) is recorded and forwarded decoded — the
   app must never receive compressed bytes without their encoding header.

Run directly:  py -3.14 scripts/demo-video/proxy/test_proxy.py
"""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse

HERE = Path(__file__).resolve().parent
PROXY = HERE / "proxy.py"

FAKE_TOKENS = 24
FAKE_GAP_S = 0.02
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

# Filled by the fake upstream: every accept-encoding header it saw.
UPSTREAM_SEEN_ACCEPT_ENCODING: list[str] = []


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _fake_upstream_app() -> FastAPI:
    app = FastAPI()

    @app.post("/provider/v1/chat/completions")
    async def chat(request: Request, payload: dict):
        UPSTREAM_SEEN_ACCEPT_ENCODING.append(
            request.headers.get("accept-encoding", "<missing>")
        )
        messages = payload.get("messages") or []
        tools = payload.get("tools") or []
        marker = str((messages or [{}])[-1].get("content") or "")

        if "compressed-please" in marker:
            # Misbehaving provider: answers a non-streaming JSON body compressed
            # with zstd even though the client asked for identity — exactly what
            # the real provider did during the 2026-10-07 demo run.
            from compression.zstd import compress

            completion = {
                "id": "fake-compressed",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_fake",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": "{\"path\": \"demo.txt\"}",
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            }
            return Response(
                content=compress(json.dumps(completion).encode("utf-8")),
                media_type="application/json",
                headers={"content-encoding": "zstd"},
            )

        if tools:
            flavour = "loop"
        elif len(messages) <= 3:
            flavour = "aux"
        else:
            flavour = "loop"

        async def stream():
            for index in range(FAKE_TOKENS):
                chunk = {
                    "id": f"fake-{flavour}",
                    "choices": [
                        {"index": 0, "delta": {"content": f"{flavour}-{index} "}}
                    ],
                }
                yield f"data: {json.dumps(chunk)}\n\n".encode()
                await asyncio.sleep(FAKE_GAP_S)
            yield b"data: [DONE]\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


class Upstream:
    def __init__(self) -> None:
        self.port = _free_port()
        self._server: uvicorn.Server | None = None
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self) -> None:
        config = uvicorn.Config(
            _fake_upstream_app(), host="127.0.0.1", port=self.port, log_level="error"
        )
        self._server = uvicorn.Server(config)
        self._server.run()

    def start(self) -> None:
        self._thread.start()
        self._wait_ready()

    def _wait_ready(self) -> None:
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                httpx.get(f"http://127.0.0.1:{self.port}/docs", timeout=0.5)
                return
            except httpx.HTTPError:
                time.sleep(0.1)
        raise RuntimeError("fake upstream did not start")

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        self._thread.join(timeout=10)


class ProxyProcess:
    def __init__(self, take: Path, mode: str, upstream: str, extra: list[str] | None = None):
        self.port = _free_port()
        self.take = take
        self.mode = mode
        self.upstream = upstream
        self.extra = extra or []
        self.proc: subprocess.Popen | None = None

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        cmd = [
            sys.executable,
            str(PROXY),
            "--mode",
            self.mode,
            "--take",
            str(self.take),
            "--port",
            str(self.port),
            "--upstream",
            self.upstream,
            "--max-ttfb-ms",
            "-1",
            *self.extra,
        ]
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8"
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.proc.poll() is not None:
                out = self.proc.stdout.read() if self.proc.stdout else ""
                raise RuntimeError(f"proxy exited early:\n{out}")
            try:
                httpx.get(f"{self.base}/__control/health", timeout=0.5)
                return
            except httpx.HTTPError:
                time.sleep(0.1)
        raise RuntimeError("proxy did not start")

    def stop(self) -> str:
        if self.proc is None:
            return ""
        self.proc.terminate()
        try:
            out = self.proc.stdout.read() if self.proc.stdout else ""
        except Exception:  # pragma: no cover - diagnostics only
            out = ""
        self.proc.wait(timeout=15)
        return out or ""


def loop_request(tag: str) -> dict:
    return {
        "model": "zai-org/GLM-5.3",
        "stream": True,
        "messages": [{"role": "user", "content": f"beat {tag}"}],
        "tools": [{"type": "function", "function": {"name": "read_file"}}],
    }


def aux_request() -> dict:
    return {
        "model": "zai-org/GLM-5.3",
        "stream": True,
        "messages": [{"role": "user", "content": "name this session"}],
    }


def compressed_request(tag: str) -> dict:
    """A loop call whose (misbehaving) upstream reply comes back zstd-encoded."""
    return {
        "model": "zai-org/GLM-5.3",
        "stream": True,
        "messages": [{"role": "user", "content": f"compressed-please {tag}"}],
        "tools": [{"type": "function", "function": {"name": "read_file"}}],
    }


def post_stream(
    client: httpx.Client, base: str, payload: dict
) -> tuple[bytes, int, float, float]:
    """Return (body, status, ttfb_ms, stream_window_ms).

    The stream window (first byte -> last byte) is what pacing actually shapes;
    connection setup and client construction would otherwise mask the ratio.
    """
    started = time.perf_counter()
    first_at: float | None = None
    last_at: float | None = None
    collected: list[bytes] = []
    with client.stream("POST", f"{base}/provider/v1/chat/completions", json=payload) as response:
        status = response.status_code
        for chunk in response.iter_raw():
            now = time.perf_counter()
            if first_at is None:
                first_at = now
            last_at = now
            collected.append(chunk)
    ttfb_ms = ((first_at or started) - started) * 1000.0
    window_ms = ((last_at or started) - (first_at or started)) * 1000.0
    return b"".join(collected), status, ttfb_ms, window_ms


def main() -> int:
    failures: list[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        state = "PASS" if condition else "FAIL"
        print(f"  [{state}] {label}{(' — ' + detail) if detail else ''}")
        if not condition:
            failures.append(label)

    upstream = Upstream()
    upstream.start()
    upstream_base = f"http://127.0.0.1:{upstream.port}"
    print(f"fake upstream on {upstream_base}")

    with tempfile.TemporaryDirectory(prefix="lamdemo-proxy-test-") as tmp:
        take = Path(tmp) / "take"
        take.mkdir(parents=True, exist_ok=True)

        # ---------- record ----------
        print("record mode:")
        http = httpx.Client(timeout=60.0)
        recorder = ProxyProcess(take, "record", upstream_base)
        recorder.start()
        recorded_bodies: list[bytes] = []
        recorded_windows: list[float] = []
        for tag in ("one", "two"):
            body, status, _ttfb, window = post_stream(http, recorder.base, loop_request(tag))
            recorded_bodies.append(body)
            recorded_windows.append(window)
            check(f"record loop {tag} -> 200", status == 200, f"status={status}")
        aux_body, aux_status, _, _ = post_stream(http, recorder.base, aux_request())
        check("record aux -> 200", aux_status == 200, f"status={aux_status}")
        compressed_body, compressed_status, _, _ = post_stream(
            http, recorder.base, compressed_request("cz")
        )
        check("record compressed -> 200", compressed_status == 200, f"status={compressed_status}")
        check(
            "compressed body stored decoded",
            compressed_body.startswith(b"{")
            and not compressed_body.startswith(ZSTD_MAGIC),
            f"head={compressed_body[:16]!r}",
        )
        try:
            parsed_compressed = json.loads(compressed_body)
            decoded_ok = parsed_compressed["choices"][0]["message"]["tool_calls"][0][
                "function"
            ]["name"] == "read_file"
        except Exception as exc:
            decoded_ok = False
            print(f"    diagnostics: compressed body parse error: {exc}")
        check("compressed body parses as the real completion", decoded_ok)
        check(
            "proxy asked upstream for identity encoding",
            bool(UPSTREAM_SEEN_ACCEPT_ENCODING)
            and all(enc == "identity" for enc in UPSTREAM_SEEN_ACCEPT_ENCODING),
            json.dumps(UPSTREAM_SEEN_ACCEPT_ENCODING),
        )
        compressed_meta = json.loads(
            (take / "cassette" / "0003.meta.json").read_text(encoding="utf-8")
        )
        compressed_disk = (take / "cassette" / "0003.response.bin").read_bytes()
        check(
            "cassette stores no stale content-encoding",
            "content-encoding" not in compressed_meta["response_headers"],
            json.dumps(compressed_meta["response_headers"].get("content-type", "")),
        )
        check(
            "cassette bytes on disk are decoded",
            not compressed_disk.startswith(ZSTD_MAGIC),
            f"head={compressed_disk[:8]!r}",
        )
        stats = httpx.get(f"{recorder.base}/__control/stats", timeout=5).json()
        check(
            "record classified streams",
            stats["recorded"].get("loop") == 3 and stats["recorded"].get("aux") == 1,
            json.dumps(stats["recorded"]),
        )
        manifest = json.loads((take / "cassette" / "manifest.json").read_text(encoding="utf-8"))
        check("manifest call_count == 4", manifest["call_count"] == 4, str(manifest["call_count"]))
        check(
            "cassette files written",
            len(list((take / "cassette").glob("*.response.bin"))) == 4,
        )
        first_meta = json.loads(
            (take / "cassette" / "0000.meta.json").read_text(encoding="utf-8")
        )
        first_chunks = json.loads(
            (take / "cassette" / "0000.chunks.json").read_text(encoding="utf-8")
        )
        print(
            "    diagnostics: record#0 ttfb={:.0f}ms total={:.0f}ms chunks={} "
            "first_offset={}ms last_offset={}ms".format(
                first_meta["ttfb_ms"],
                first_meta["total_ms"],
                first_meta["chunk_count"],
                first_chunks[0]["o"],
                first_chunks[-1]["o"],
            )
        )
        recorder.stop()

        # ---------- replay ----------
        print("replay mode (speed 4x):")
        replayer = ProxyProcess(take, "replay", upstream_base, extra=["--speed", "4"])
        replayer.start()
        replay_bodies: list[bytes] = []
        replay_windows: list[float] = []
        for tag in ("one", "two"):
            body, status, _ttfb, window = post_stream(http, replayer.base, loop_request(tag))
            replay_bodies.append(body)
            replay_windows.append(window)
            check(f"replay loop {tag} -> 200", status == 200, f"status={status}")
        replay_aux, _, _, _ = post_stream(http, replayer.base, aux_request())
        replay_compressed, replay_compressed_status, _, _ = post_stream(
            http, replayer.base, compressed_request("cz")
        )
        check("replay compressed -> 200", replay_compressed_status == 200,
              f"status={replay_compressed_status}")
        check("replay compressed bytes identical", compressed_body == replay_compressed,
              f"{len(compressed_body)} vs {len(replay_compressed)} bytes")

        for index, (recorded, replayed) in enumerate(zip(recorded_bodies, replay_bodies)):
            check(
                f"replay loop {index} bytes identical",
                recorded == replayed,
                f"{len(recorded)} vs {len(replayed)} bytes",
            )
        check("replay aux bytes identical", aux_body == replay_aux)

        ratio = recorded_windows[0] / replay_windows[0] if replay_windows[0] else 0.0
        check(
            "replay speed scales the stream window",
            2.8 <= ratio <= 6.0,
            f"record window {recorded_windows[0]:.0f}ms -> replay {replay_windows[0]:.0f}ms "
            f"(requested x4, measured x{ratio:.2f})",
        )

        # ---------- loud failure ----------
        _, status, _, _ = post_stream(http, replayer.base, loop_request("three"))
        check("replay miss -> 503", status == 503, f"status={status}")
        check(
            "replay miss logged",
            (take / "replay-misses.jsonl").exists(),
        )
        replayer.stop()

        # ---------- strict mismatch ----------
        print("strict mode:")
        strict = ProxyProcess(
            take, "replay", upstream_base, extra=["--speed", "8", "--strict"]
        )
        strict.start()
        _, status, _, _ = post_stream(http, strict.base, loop_request("changed-prompt"))
        check("strict mismatch -> 409", status == 409, f"status={status}")
        check("strict mismatch logged", (take / "replay-mismatches.jsonl").exists())
        strict.stop()
        http.close()

    upstream.stop()

    print()
    if failures:
        print(f"FAILED ({len(failures)}): " + "; ".join(failures))
        return 1
    print("all proxy checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
