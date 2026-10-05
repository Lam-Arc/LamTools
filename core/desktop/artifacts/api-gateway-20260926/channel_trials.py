"""Pin down why the channel is not selected by the distributor.

Creates the mock channel with several candidate scheduling configurations and
probes the relayed chat completion after each, then removes every artefact.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cloud import command  # noqa: E402

MOCK = r'''
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
'''

TRIAL = r'''
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


pw = ""
for line in open("/opt/lamtools-api/admin-credentials.txt", encoding="utf-8"):
    if line.startswith("password :"):
        pw = line.split(":", 1)[1].strip()
code, d = call("POST", "/api/user/login", {"username": "root", "password": pw})
pw = ""
AH = {"Authorization": "Bearer " + ((d.get("data") or {}).get("access_token") or ""),
      "New-API-User": "1"}


def items_of(d):
    data = d.get("data") or {}
    return data.get("items") if isinstance(data, dict) else data


def find(label, name):
    code, d = call("GET", "/api/%s/?p=0&size=100" % label, headers=AH)
    return next((i for i in (items_of(d) or [])
                 if isinstance(i, dict) and i.get("name") == name), None)


# one throwaway key, reused across trials
code, d = call("POST", "/api/token/", {"name": TK_NAME, "remain_quota": 100000000,
                                      "expired_time": -1, "unlimited_quota": True,
                                      "model_limits_enabled": False, "group": "default",
                                      "status": 1}, AH)
tk = find("token", TK_NAME)
code, d = call("POST", "/api/token/%s/key" % tk.get("id"), {}, headers=AH)
cand = (d.get("data") or {})
cand = cand.get("key") if isinstance(cand, dict) else cand
KEY = cand if cand.startswith("sk-") else "sk-" + cand
print("  key ready (len %d)" % len(KEY))

base = {"name": CH_NAME, "type": 1, "key": "sk-mock-upstream", "base_url": UPSTREAM,
        "models": "gpt-4o-mini", "group": "default", "groups": ["default"], "status": 1}

trials = [
    ("weight=1", {"weight": 1, "priority": 0}),
    ("weight=1 priority=1", {"weight": 1, "priority": 1}),
    ("weight=10 priority=10", {"weight": 10, "priority": 10}),
    ("weight=1 + model_mapping", {"weight": 1, "priority": 0, "model_mapping": ""}),
]

for label, extra in trials:
    payload = dict(base)
    payload.update(extra)
    code, d = call("POST", "/api/channel/", {"mode": "single", "channel": payload}, AH)
    ch = find("channel", CH_NAME)
    if not ch:
        print("  [%s] channel not created (%s)" % (label, str(d.get("message"))[:80]))
        continue
    code, d = call("GET", "/api/channel/test/%s" % ch.get("id"), headers=AH)
    print("  [%s] created id=%s weight=%s priority=%s | test success=%s"
          % (label, ch.get("id"), ch.get("weight"), ch.get("priority"), d.get("success")))

    code, d = call("POST", "/v1/chat/completions",
                   {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "ping"}],
                    "stream": False},
                   {"Authorization": "Bearer " + KEY})
    msg = ""
    if isinstance(d, dict) and isinstance(d.get("error"), dict):
        msg = str(d["error"].get("message"))[:110]
    print("      relay http=%s msg=%s" % (code, msg or "OK"))
    code, d = call("DELETE", "/api/channel/%s" % ch.get("id"), headers=AH)
    print("      channel deleted: %s" % d.get("success"))
'''

SCRIPT = (
    r"""set -u
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
pw = ""
for line in open("/opt/lamtools-api/admin-credentials.txt", encoding="utf-8"):
    if line.startswith("password :"):
        pw = line.split(":", 1)[1].strip()
d = call("POST", "/api/user/login", {"username": "root", "password": pw})
AH = {"Authorization": "Bearer " + ((d.get("data") or {}).get("access_token") or ""),
      "New-API-User": "1"}
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
"""
    + MOCK
    + """MOCKEOF
setsid nohup python3 /tmp/mock_upstream.py "$BRIDGE" 8323 >/tmp/mock.log 2>&1 < /dev/null &
echo $! > /tmp/mock.pid
sleep 2
ss -tln | grep -q 8323 && echo "  mock listening on $BRIDGE:8323" || { echo "  MOCK FAILED"; exit 1; }

echo "=== trials ==="
cat > /tmp/trial.py <<'TRIALEOF'
"""
    + TRIAL
    + """TRIALEOF
python3 /tmp/trial.py "http://$BRIDGE:8323"

echo "=== mock access log ==="
[ -f /tmp/mock_access.log ] && sed 's/^/  /' /tmp/mock_access.log || echo "  nothing reached the mock"
echo "=== done ==="
"""
)

if __name__ == "__main__":
    command(
        "channel-trials",
        "Determine which channel scheduling configuration makes the distributor select the channel",
        SCRIPT,
        timeout=700,
    )
