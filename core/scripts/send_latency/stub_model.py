"""Minimal OpenAI-compatible model endpoint for the send-latency harness.

Sunday's real send path is measured against a stub model so the numbers never
include a paid provider's network time. The stub answers instantly with one
short message and a terminal finish reason, which is exactly what a real turn
needs to reach its terminal state; the harness reads the send-confirmation
timings, separately from this first-token latency.

Run:  python core/scripts/send_latency/stub_model.py --port 5919
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: D102 - quiet server
        return

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server contract
        if self.path.rstrip("/").endswith("/models"):
            self._json({"object": "list", "data": [{"id": "stub-chat", "object": "model"}]})
            return
        self._json({"ok": True})

    def do_POST(self) -> None:  # noqa: N802 - http.server contract
        length = int(self.headers.get("Content-Length") or 0)
        try:
            raw = self.rfile.read(length) if length else b"{}"
            request = json.loads(raw or b"{}")
        except ValueError:
            request = {}
        stream = bool(request.get("stream"))
        created = int(time.time())
        chunk = {
            "id": "chatcmpl-stub",
            "object": "chat.completion.chunk",
            "created": created,
            "model": str(request.get("model") or "stub-chat"),
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": "stub answer"},
                "finish_reason": None,
            }],
        }
        finish = {
            "id": "chatcmpl-stub",
            "object": "chat.completion.chunk",
            "created": created,
            "model": str(request.get("model") or "stub-chat"),
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 3, "total_tokens": 103},
        }
        if not stream:
            self._json({
                "id": "chatcmpl-stub",
                "object": "chat.completion",
                "created": created,
                "model": str(request.get("model") or "stub-chat"),
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "stub answer"},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 100, "completion_tokens": 3, "total_tokens": 103},
            })
            return
        body = bytearray()
        for item in (chunk, finish):
            body += f"data: {json.dumps(item)}\n\n".encode("utf-8")
        body += b"data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(bytes(body))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5919)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), _Handler)
    server.daemon_threads = True
    print(f"stub model on http://127.0.0.1:{args.port}/v1", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
