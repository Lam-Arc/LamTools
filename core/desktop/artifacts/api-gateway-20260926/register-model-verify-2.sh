set -u
BRIDGE=$(ip -o -4 addr show | awk '$4 ~ /^172\.30\.0\./ {print $4}' | cut -d/ -f1 | head -1)
echo "  bridge gateway: $BRIDGE"

cleanup() {
  echo "=== cleanup ==="
  cat > /tmp/cleanup_smoke.py <<'CLEANEOF'

import json, time, urllib.error, urllib.request
BASE = "http://127.0.0.1:3000"
def call(m, p, b=None, h=None):
    d = json.dumps(b).encode() if b is not None else None
    r = urllib.request.Request(BASE + p, data=d, method=m)
    r.add_header("Content-Type", "application/json")
    for k, v in (h or {}).items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read() or b"{}")
        except Exception:
            return {}
def pw_read():
    for line in open("/opt/lamtools-api/admin-credentials.txt", encoding="utf-8"):
        if line.startswith("password :"):
            return line.split(":", 1)[1].strip()
    return ""
AH = {}
for _ in range(5):
    d = call("POST", "/api/user/login", {"username": "root", "password": pw_read()})
    t = (d.get("data") or {}).get("access_token")
    if t:
        AH = {"Authorization": "Bearer " + t, "New-API-User": "1"}
        break
    time.sleep(15)
if not AH:
    print("  cleanup: login failed")
    raise SystemExit(0)
def items_of(d):
    data = d.get("data") or {}
    return data.get("items") if isinstance(data, dict) else data
for label in ("token", "channel"):
    d = call("GET", "/api/%s/?p=0&size=100" % label, h=AH)
    for it in [i for i in (items_of(d) or [])
               if isinstance(i, dict) and str(i.get("name","")).startswith("zz-smoke")]:
        r = call("DELETE", "/api/%s/%s" % (label, it.get("id")), h=AH)
        print("  delete %s %s -> success=%s" % (label, it.get("id"), r.get("success")))
    d = call("GET", "/api/%s/?p=0&size=100" % label, h=AH)
    print("  %s leftovers: %s" % (label, [i.get("name") for i in (items_of(d) or [])
          if isinstance(i, dict) and str(i.get("name","")).startswith("zz-smoke")] or "none"))
try:
    ids = json.load(open("/tmp/smoke-model"))
except Exception:
    ids = []
for mid in ids:
    r = call("DELETE", "/api/models/%s" % mid, h=AH)
    print("  delete model %s -> success=%s" % (mid, r.get("success")))
d = call("GET", "/api/models/?p=0&size=20", h=AH)
data = d.get("data") or {}
print("  model registry total now:", data.get("total"))
CLEANEOF
  python3 /tmp/cleanup_smoke.py
  [ -f /tmp/mock.pid ] && kill "$(cat /tmp/mock.pid)" 2>/dev/null && echo "  mock stopped"
  rm -f /tmp/mock.pid /tmp/mock_access.log /tmp/smoke-model
}
trap cleanup EXIT

REDIS_PASS=$(sed -n 's/^REDIS_PASSWORD=//p' /opt/lamtools-api/.env)
docker exec lamtools-api-cache redis-cli --no-auth-warning -a "$REDIS_PASS" --scan --pattern 'rateLimit*' 2>/dev/null   | while read -r k; do [ -n "$k" ] && docker exec lamtools-api-cache redis-cli --no-auth-warning -a "$REDIS_PASS" DEL "$k" >/dev/null; done
echo "  throttle cleared"

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

cat > /tmp/flow.py <<'FLOWEOF'

import json, sys, time, urllib.error, urllib.request

BASE = "http://127.0.0.1:3000"
UPSTREAM = sys.argv[1]
CH_NAME = "zz-smoke-mock-do-not-keep"
TK_NAME = "zz-smoke-key-do-not-keep"
MODEL = "gpt-4o-mini"


def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
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


AH = {}
for _ in range(6):
    code, d = call("POST", "/api/user/login", {"username": "root", "password": read_pw()})
    if code == 200 and (d.get("data") or {}).get("access_token"):
        AH = {"Authorization": "Bearer " + d["data"]["access_token"], "New-API-User": "1"}
        print("  login OK")
        break
    time.sleep(10)
if not AH:
    print("  FATAL: throttled")
    sys.exit(1)


def items_of(d):
    data = d.get("data") or {}
    return data.get("items") if isinstance(data, dict) else data


print("  --- register the model ---")
candidates = [
    {"model_name": MODEL, "vendor": "openai", "status": 1},
    {"model_name": MODEL},
    {"model": MODEL, "vendor": "openai"},
    {"model_name": MODEL, "vendor": "openai", "description": "smoke test entry",
     "tags": "", "status": 1},
]
for payload in candidates:
    code, d = call("POST", "/api/models/", payload, AH)
    print("    POST /api/models/ %s -> http=%s success=%s msg=%s"
          % (json.dumps(payload)[:70], code, d.get("success"), str(d.get("message"))[:140]))
    if d.get("success"):
        break

code, d = call("GET", "/api/models/?p=0&size=20", headers=AH)
data = d.get("data") or {}
print("    registry total:", data.get("total"), "| items:", str(data.get("items"))[:300])
if hasattr(data, "get"):
    open("/tmp/smoke-model", "w").write(json.dumps(
        [i.get("id") for i in (data.get("items") or []) if isinstance(i, dict)]))

print("  --- channel + token ---")
ch_payload = {"name": CH_NAME, "type": 1, "key": "sk-mock-upstream", "base_url": UPSTREAM,
              "models": MODEL, "group": "default", "groups": ["default"],
              "status": 1, "weight": 1, "priority": 0}
code, d = call("POST", "/api/channel/", {"mode": "single", "channel": ch_payload}, AH)
print("    channel success=%s msg=%s" % (d.get("success"), str(d.get("message"))[:90]))
code, d = call("POST", "/api/token/", {"name": TK_NAME, "remain_quota": 100000000,
                                      "expired_time": -1, "unlimited_quota": True,
                                      "model_limits_enabled": False, "group": "default",
                                      "status": 1}, AH)
code, d = call("GET", "/api/token/?p=0&size=50", headers=AH)
tk = next((i for i in (items_of(d) or [])
           if isinstance(i, dict) and i.get("name") == TK_NAME), None)
KEY = ""
if tk:
    for _ in range(4):
        code, d = call("POST", "/api/token/%s/key" % tk.get("id"), {}, headers=AH)
        cand = (d.get("data") or {})
        cand = cand.get("key") if isinstance(cand, dict) else cand
        if cand:
            KEY = cand if cand.startswith("sk-") else "sk-" + cand
            break
        time.sleep(6)
print("    key ready:", bool(KEY))
if not KEY:
    sys.exit(0)

print("  --- relay ---")
for stream in (False, True):
    code, d = call("POST", "/v1/chat/completions",
                   {"model": MODEL, "messages": [{"role": "user", "content": "ping"}],
                    "stream": stream}, {"Authorization": "Bearer " + KEY})
    detail = ""
    if isinstance(d, dict):
        if d.get("error"):
            detail = str(d["error"].get("message"))[:100]
        elif stream is False:
            detail = str(((d.get("choices") or [{}])[0].get("message") or {}).get("content"))
        else:
            detail = "stream body received"
    print("    stream=%-5s http=%s %s" % (stream, code, detail))
FLOWEOF
python3 /tmp/flow.py "http://$BRIDGE:8323"

echo "=== mock access log ==="
[ -f /tmp/mock_access.log ] && sed 's/^/  /' /tmp/mock_access.log || echo "  nothing reached the mock"
echo "=== done ==="
