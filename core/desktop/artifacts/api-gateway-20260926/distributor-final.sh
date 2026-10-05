set -u
BRIDGE=$(ip -o -4 addr show | awk '$4 ~ /^172\.30\.0\./ {print $4}' | cut -d/ -f1 | head -1)
echo "  bridge gateway: $BRIDGE"

cleanup() {
  echo "=== cleanup ==="
  cat > /tmp/cleanup_smoke.py <<'CLEANEOF'

import json, urllib.error, urllib.request
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
import time
for _ in range(5):
    d = call("POST", "/api/user/login", {"username": "root", "password": pw_read()})
    t = (d.get("data") or {}).get("access_token")
    if t:
        AH = {"Authorization": "Bearer " + t, "New-API-User": "1"}
        break
    time.sleep(20)
if not AH:
    print("  cleanup: login failed; leaving artefacts for manual removal")
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
CLEANEOF
  python3 /tmp/cleanup_smoke.py
  [ -f /tmp/mock.pid ] && kill "$(cat /tmp/mock.pid)" 2>/dev/null && echo "  mock stopped"
  rm -f /tmp/mock.pid /tmp/mock_access.log
}
trap cleanup EXIT

cat > /tmp/mock_upstream.py <<'MOCKEOF'

import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "gpt-4o-mini"
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
        if self.path.rstrip("/").endswith("/models"):
            self._json({"object": "list", "data": [{"id": MODEL, "object": "model"}]})
        else:
            self._json({"ok": True})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) or b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            body = {}
        note("POST %s stream=%s model=%s" % (self.path, body.get("stream"), body.get("model")))
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for chunk in ("Hel", "lo ", "from ", "mock"):
                ev = {"id": "chatcmpl-mock", "object": "chat.completion.chunk", "created": 0,
                      "model": MODEL,
                      "choices": [{"index": 0, "delta": {"content": chunk},
                                   "finish_reason": None}]}
                self.wfile.write(("data: " + json.dumps(ev) + "\n\n").encode())
                self.wfile.flush()
            tail = {"id": "chatcmpl-mock", "object": "chat.completion.chunk", "created": 0,
                    "model": MODEL,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            self.wfile.write(("data: " + json.dumps(tail) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            self._json({"id": "chatcmpl-mock", "object": "chat.completion", "created": 0,
                        "model": MODEL,
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


# ---- single login, with backoff for the login rate limiter ----
AH = {}
for attempt in range(8):
    code, d = call("POST", "/api/user/login", {"username": "root", "password": read_pw()})
    if code == 200 and (d.get("data") or {}).get("access_token"):
        AH = {"Authorization": "Bearer " + d["data"]["access_token"], "New-API-User": "1"}
        print("  login OK on attempt %d" % (attempt + 1))
        break
    print("  login attempt %d -> http=%s msg=%s" % (attempt + 1, code, str(d.get("message"))[:60]))
    time.sleep(25)
if not AH:
    print("  FATAL: could not authenticate")
    sys.exit(1)


def items_of(d):
    data = d.get("data") or {}
    return data.get("items") if isinstance(data, dict) else data


# ---- 1. settings that could gate the distributor ----
code, d = call("GET", "/api/option/", headers=AH)
opts = d.get("data") or []
print("  options read:", len(opts))
WORDS = ("distribut", "affinity", "schedul", "route", "channel", "priority", "weight",
         "cache", "sync", "auto_group", "abnormal")
for o in opts:
    if isinstance(o, dict) and any(w in str(o.get("key")).lower() for w in WORDS):
        print("    %-46s = %s" % (o.get("key"), str(o.get("value"))[:100]))

# ---- 2. is the model known to the pricing table? ----
code, d = call("GET", "/api/pricing/")
data = d.get("data")
names = []
if isinstance(data, list):
    names = [m.get("model_name") for m in data if isinstance(m, dict)]
elif isinstance(data, dict):
    names = list(data.keys())
print("  pricing entries:", len(names))
print("  gpt-4o-mini priced:", "gpt-4o-mini" in names,
      "| similar:", [n for n in names if "mini" in str(n)][:8])

# ---- 3. channel + token ----
ch_payload = {"name": CH_NAME, "type": 1, "key": "sk-mock-upstream", "base_url": UPSTREAM,
              "models": "gpt-4o-mini", "group": "default", "groups": ["default"],
              "status": 1, "weight": 1, "priority": 0}
code, d = call("POST", "/api/channel/", {"mode": "single", "channel": ch_payload}, AH)
print("  create channel http=%s success=%s msg=%s" % (code, d.get("success"), str(d.get("message"))[:90]))
code, d = call("GET", "/api/channel/?p=0&size=50", headers=AH)
ch = next((i for i in (items_of(d) or [])
           if isinstance(i, dict) and i.get("name") == CH_NAME), None)
if ch:
    print("  channel fields:", json.dumps({k: (v if k != "key" else "<masked>")
                                           for k, v in ch.items()}, ensure_ascii=False)[:700])

code, d = call("POST", "/api/token/", {"name": TK_NAME, "remain_quota": 100000000,
                                      "expired_time": -1, "unlimited_quota": True,
                                      "model_limits_enabled": False, "group": "default",
                                      "status": 1}, AH)
print("  create token http=%s success=%s" % (code, d.get("success")))
code, d = call("GET", "/api/token/?p=0&size=50", headers=AH)
tk = next((i for i in (items_of(d) or [])
           if isinstance(i, dict) and i.get("name") == TK_NAME), None)
KEY = ""
if tk:
    for attempt in range(4):
        code, d = call("POST", "/api/token/%s/key" % tk.get("id"), {}, headers=AH)
        cand = (d.get("data") or {})
        cand = cand.get("key") if isinstance(cand, dict) else cand
        if cand:
            KEY = cand if cand.startswith("sk-") else "sk-" + cand
            break
        print("    key attempt %d http=%s success=%s msg=%s"
              % (attempt + 1, code, d.get("success"), str(d.get("message"))[:90]))
        time.sleep(8)
print("  key ready:", bool(KEY))
if not KEY:
    sys.exit(0)


def relay(label):
    code, d = call("POST", "/v1/chat/completions",
                   {"model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "ping"}], "stream": False},
                   {"Authorization": "Bearer " + KEY})
    ok = ""
    if code == 200 and isinstance(d, dict):
        ok = str(((d.get("choices") or [{}])[0].get("message") or {}).get("content"))
    print("  [%-20s] http=%s %s%s" % (label, code, ok,
          str((d.get("error") or {}).get("message") or "")[:95]))
    return code


# ---- 4. timeline ----
relay("immediately")
time.sleep(75)
relay("after 75s")
code, d = call("GET", "/api/channel/?p=0&size=50", headers=AH)
ch = next((i for i in (items_of(d) or [])
           if isinstance(i, dict) and i.get("name") == CH_NAME), None)
if ch:
    print("  channel status/weight/priority now: %s / %s / %s"
          % (ch.get("status"), ch.get("weight"), ch.get("priority")))
print("  RESTART_NOW")
FLOWEOF
cat > /tmp/after.py <<'AFTEREOF'

import json, sys, urllib.error, urllib.request

BASE = "http://127.0.0.1:3000"


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


pw = ""
for line in open("/opt/lamtools-api/admin-credentials.txt", encoding="utf-8"):
    if line.startswith("password :"):
        pw = line.split(":", 1)[1].strip()
AH = {}
for _ in range(4):
    code, d = call("POST", "/api/user/login", {"username": "root", "password": pw})
    if code == 200 and (d.get("data") or {}).get("access_token"):
        AH = {"Authorization": "Bearer " + d["data"]["access_token"], "New-API-User": "1"}
        break
    import time
    time.sleep(20)
if not AH:
    print("  login failed after restart")
    raise SystemExit(0)


def items_of(d):
    data = d.get("data") or {}
    return data.get("items") if isinstance(data, dict) else data


code, d = call("GET", "/api/token/?p=0&size=50", headers=AH)
tk = next((i for i in (items_of(d) or [])
           if isinstance(i, dict) and i.get("name") == "zz-smoke-key-do-not-keep"), None)
if not tk:
    print("  token gone; skipping post-restart relay check")
    raise SystemExit(0)
code, d = call("POST", "/api/token/%s/key" % tk.get("id"), {}, headers=AH)
cand = (d.get("data") or {})
cand = cand.get("key") if isinstance(cand, dict) else cand
key = cand if cand.startswith("sk-") else "sk-" + cand
code, d = call("POST", "/v1/chat/completions",
               {"model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "ping"}], "stream": False},
               {"Authorization": "Bearer " + key})
ok = ""
if code == 200:
    ok = str(((d.get("choices") or [{}])[0].get("message") or {}).get("content"))
print("  [%-20s] http=%s %s%s" % ("after restart", code, ok,
      str((d.get("error") or {}).get("message") or "")[:95]))
AFTEREOF

echo "=== settings, pricing, channel, relay timeline ==="
python3 /tmp/flow.py "http://$BRIDGE:8323" | tee /tmp/flow.out
if grep -q RESTART_NOW /tmp/flow.out; then
  echo "=== restarting gateway ==="
  docker compose -f /opt/lamtools-api/docker-compose.yml restart gateway 2>&1 | tail -2
  for i in $(seq 1 40); do
    c=$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:3000/api/status || true)
    [ "$c" = "200" ] && { echo "  gateway back after $((i*2))s"; break; }
    sleep 2
  done
  sleep 5
  python3 /tmp/after.py
fi

echo "=== mock access log ==="
[ -f /tmp/mock_access.log ] && sed 's/^/  /' /tmp/mock_access.log || echo "  nothing reached the mock"
echo "=== done ==="
