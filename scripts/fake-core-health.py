#!/usr/bin/env python
"""一个假的 Core：只回答 GET /api/health。

P1 验收用它证明「Core 挂了要降级、Core 回来要自动恢复」：真的 Core 需要整套 Python
依赖，而我们要验的是「探测有没有应答」这一层，所以用一个 20 行的 HTTP 服务代替。

    python scripts/fake-core-health.py 5781
"""
import http.server
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 0
if PORT <= 0:
    raise SystemExit("usage: fake-core-health.py <port>")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.startswith("/api/health"):
            body = b'{"status":"ok","fake":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, *args):  # 静默：脚本只关心探测结果
        return


server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
print(f"READY {PORT}", flush=True)
server.serve_forever()
