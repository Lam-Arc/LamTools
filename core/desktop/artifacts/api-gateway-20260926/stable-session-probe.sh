set -u
BRIDGE=$(ip -o -4 addr show | awk '$4 ~ /^172\.30\.0\./ {print $4}' | cut -d/ -f1 | head -1)
echo "  bridge gateway: $BRIDGE"

cleanup() {
  echo "=== cleanup ==="
  rm -f /tmp/pub-cookies.txt /tmp/pub-admin-token /tmp/pub_login.json /tmp/pub_resp.json
  [ -f /tmp/mock.pid ] && kill "$(cat /tmp/mock.pid)" 2>/dev/null && echo "  mock stopped"
  rm -f /tmp/mock.pid /tmp/mock_access.log
}
trap cleanup EXIT

cat > /tmp/mock_upstream.py <<'MOCKEOF'

import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ACCESS = "/tmp/mock_access.log"


def note(line):
    with open(ACCESS, "a") as fh:
        fh.write(line + "\n")
        fh.flush()


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, obj):
        d = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)

    def do_GET(self):
        note("GET %s" % self.path)
        self._json({"object": "list", "data": [{"id": "gpt-4o-mini", "object": "model"}]})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) or b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            body = {}
        note("POST %s stream=%s model=%s" % (self.path, body.get("stream"), body.get("model")))
        model = body.get("model") or "gpt-4o-mini"
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for chunk in ("Hel", "lo ", "from ", "mock"):
                ev = {"id": "chatcmpl-mock", "object": "chat.completion.chunk", "created": 0,
                      "model": model,
                      "choices": [{"index": 0, "delta": {"content": chunk},
                                   "finish_reason": None}]}
                self.wfile.write(("data: " + json.dumps(ev) + "\n\n").encode())
                self.wfile.flush()
            tail = {"id": "chatcmpl-mock", "object": "chat.completion.chunk", "created": 0,
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            self.wfile.write(("data: " + json.dumps(tail) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            self._json({"id": "chatcmpl-mock", "object": "chat.completion", "created": 0,
                        "model": model,
                        "choices": [{"index": 0,
                                     "message": {"role": "assistant", "content": "Hello from mock"},
                                     "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})


ThreadingHTTPServer((sys.argv[1], int(sys.argv[2])), H).serve_forever()
MOCKEOF
setsid nohup python3 /tmp/mock_upstream.py "$BRIDGE" 8323 >/tmp/mock.log 2>&1 < /dev/null &
echo $! > /tmp/mock.pid
sleep 2
ss -tln | grep -q 8323 && echo "  mock listening" || { echo "MOCK FAILED"; exit 1; }

echo "=== admin session over TLS ==="
cat > /tmp/flow.py <<'FLOWEOF'

import json, os, subprocess, sys, time, urllib.error, urllib.request

BASE = "http://127.0.0.1:3000"
PUB = "api.47.114.43.99.nip.io"
UPSTREAM = sys.argv[1]
CH_NAME = "zz-smoke-mock-do-not-keep"
TK_NAME = "zz-smoke-key-do-not-keep"
MODEL = "gpt-4o-mini"
JAR = "/tmp/pub-cookies.txt"


def call(method, path, body=None, headers=None, base=BASE):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=40) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def read_pw():
    for line in open("/opt/lamtools-api/admin-credentials.txt", encoding="utf-8"):
        if line.startswith("password :"):
            return line.split(":", 1)[1].strip()
    return ""


# The session cookie is Secure, so the login must happen over TLS.
if os.path.exists(JAR):
    os.remove(JAR)
code, d = call("POST", "/api/user/login", {"username": "root", "password": read_pw()})
print("  public TLS login path not used directly; using curl for cookie capture")


def curl_login():
    pw = read_pw()
    body = json.dumps({"username": "root", "password": pw})
    out = subprocess.run([
        "curl", "-s", "-o", "/tmp/pub_login.json", "-w", "%{http_code}", "-m", "25",
        "--resolve", "%s:443:127.0.0.1" % PUB,
        "-c", JAR, "-b", JAR,
        "-H", "Content-Type: application/json",
        "-d", body,
        "https://%s/api/user/login" % PUB,
    ], capture_output=True, text=True)
    return out.stdout.strip()


code = curl_login()
print("  TLS login http:", code)
d = json.load(open("/tmp/pub_login.json"))
print("  login success:", d.get("success"))
names = []
try:
    for line in open(JAR, encoding="utf-8"):
        if not line.startswith("#") and line.strip():
            names.append(line.split("\t")[5])
except OSError:
    pass
print("  cookies captured:", names)


def curl(path, method="GET", payload=None):
    cmd = ["curl", "-s", "-o", "/tmp/pub_resp.json", "-w", "%{http_code}", "-m", "40",
           "--resolve", "%s:443:127.0.0.1" % PUB, "-b", JAR, "-c", JAR]
    if method != "GET":
        cmd += ["-X", method]
    if payload is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(payload)]
    cmd.append("https://%s%s" % (PUB, path))
    out = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return out.stdout.strip(), json.load(open("/tmp/pub_resp.json"))
    except Exception:
        return out.stdout.strip(), {}


code, d = curl("/api/user/self")
print("  /api/user/self over TLS ->", code, "success:", d.get("success"),
      "role:", (d.get("data") or {}).get("role"))

code, d = curl("/api/user/token")
tok = (d.get("data") if isinstance(d.get("data"), (str, dict)) else None)
if isinstance(tok, dict):
    tok = tok.get("token") or tok.get("access_token")
print("  /api/user/token ->", code, "success:", d.get("success"), "| token obtained:", bool(tok))
if not tok:
    print("  FATAL: no access token; stopping")
    raise SystemExit(1)
open("/tmp/pub-admin-token", "w").write(tok if isinstance(tok, str) else str(tok))
AH = {"Authorization": "Bearer " + (tok if isinstance(tok, str) else str(tok))}
FLOWEOF
python3 /tmp/flow.py "http://$BRIDGE:8323"
