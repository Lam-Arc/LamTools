"""Diagnose the 503 on the relayed chat completion: full body, mock access log,
gateway log and channel state."""
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
        note("GET %s auth=%s" % (self.path, bool(self.headers.get("Authorization"))))
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
        note("POST %s stream=%s model=%s bytes=%d" % (self.path, body.get("stream"),
                                                      body.get("model"), len(raw)))
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for chunk in ("Hel", "lo ", "from ", "mock"):
                ev = {"id": "chatcmpl-mock", "object": "chat.completion.chunk",
                      "created": 0, "model": MODEL,
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

ADMIN = r'''
import json, sys, urllib.error, urllib.request

BASE = "http://127.0.0.1:3000"
UPSTREAM = sys.argv[1]


def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
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
tok = (d.get("data") or {}).get("access_token") or ""
AH = {"Authorization": "Bearer " + tok, "New-API-User": "1"}


def items_of(d):
    data = d.get("data") or {}
    return data.get("items") if isinstance(data, dict) else data


channel = {"name": "zz-smoke-mock-do-not-keep", "type": 1, "key": "sk-mock-upstream",
           "base_url": UPSTREAM, "models": "gpt-4o-mini", "group": "default",
           "groups": ["default"], "status": 1}
code, d = call("POST", "/api/channel/", {"mode": "single", "channel": channel}, AH)
print("  create channel success=%s msg=%s" % (d.get("success"), str(d.get("message"))[:100]))

code, d = call("GET", "/api/channel/?p=0&size=50", headers=AH)
ch = next((i for i in (items_of(d) or [])
           if isinstance(i, dict) and i.get("name") == "zz-smoke-mock-do-not-keep"), None)
if ch:
    open("/tmp/smoke-channel-id", "w").write(str(ch.get("id")))
    print("  channel id=%s status=%s group=%s models=%s base_url=%s priority=%s weight=%s"
          % (ch.get("id"), ch.get("status"), ch.get("group"), ch.get("models"),
             ch.get("base_url"), ch.get("priority"), ch.get("weight")))

code, d = call("POST", "/api/token/", {"name": "zz-smoke-key-do-not-keep",
                                      "remain_quota": 1000000, "expired_time": -1,
                                      "unlimited_quota": False, "model_limits_enabled": False,
                                      "group": "default", "status": 1}, AH)
print("  create token success=%s" % d.get("success"))

code, d = call("GET", "/api/token/?p=0&size=50", headers=AH)
tk = next((i for i in (items_of(d) or [])
           if isinstance(i, dict) and i.get("name") == "zz-smoke-key-do-not-keep"), None)
if tk:
    open("/tmp/smoke-token-id", "w").write(str(tk.get("id")))
    print("  token id=%s group=%s status=%s" % (tk.get("id"), tk.get("group"), tk.get("status")))
    code, d = call("POST", "/api/token/%s/key" % tk.get("id"), {}, headers=AH)
    cand = (d.get("data") or {})
    cand = cand.get("key") if isinstance(cand, dict) else cand
    if cand:
        key = cand if cand.startswith("sk-") else "sk-" + cand
        open("/tmp/smoke-key", "w").write(key)
        print("  full key retrieved")

print("  --- user record ---")
code, d = call("GET", "/api/user/self", headers=AH)
u = d.get("data") or {}
print("  group=%s quota=%s role=%s" % (u.get("group"), u.get("quota"), u.get("role")))
'''

SCRIPT = (
    r"""set -u
PUB=api.47.114.43.99.nip.io
RESOLVE="--resolve $PUB:443:127.0.0.1"

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
  rm -f /tmp/smoke-key /tmp/smoke-token-id /tmp/smoke-channel-id /tmp/mock.pid /tmp/mock_access.log
}
trap cleanup EXIT

echo "=== setup ==="
cat > /tmp/mock_upstream.py <<'MOCKEOF'
"""
    + MOCK
    + """MOCKEOF
setsid nohup python3 /tmp/mock_upstream.py "$BRIDGE" 8323 >/tmp/mock.log 2>&1 < /dev/null &
echo $! > /tmp/mock.pid
sleep 2
ss -tln | grep -q 8323 && echo "  mock listening" || { echo "  MOCK FAILED"; tail -5 /tmp/mock.log; exit 1; }

cat > /tmp/admin_smoke.py <<'ADMINEOF'
"""
    + ADMIN
    + """ADMINEOF
python3 /tmp/admin_smoke.py "http://$BRIDGE:8323"

if [ ! -s /tmp/smoke-key ]; then echo "no key; aborting"; exit 0; fi
KEY=$(cat /tmp/smoke-key)

echo "=== relayed chat completion: full response body ==="
curl -s -o /tmp/chat.json -w '  http=%{http_code}\n' -m 60 $RESOLVE \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"ping"}],"stream":false}' \
  "https://$PUB/v1/chat/completions"
echo "  body: $(head -c 600 /tmp/chat.json)"

echo "=== did the mock upstream receive anything? ==="
if [ -f /tmp/mock_access.log ]; then sed 's/^/  /' /tmp/mock_access.log; else echo "  NO REQUESTS REACHED THE MOCK"; fi

echo "=== gateway log tail ==="
tail -25 /opt/lamtools-api/logs/oneapi-*.log | cut -c1-300 | sed 's/^/  /'

echo "=== mock error log ==="
tail -10 /tmp/mock.log | sed 's/^/  /'

echo "=== channel state after the attempt ==="
python3 - <<'CHKEOF'
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
d = call("GET", "/api/channel/?p=0&size=50", h=AH)
data = d.get("data") or {}
for it in (data.get("items") if isinstance(data, dict) else data) or []:
    if isinstance(it, dict) and str(it.get("name","")).startswith("zz-smoke"):
        print("  id=%s status=%s group=%s models=%s" % (it.get("id"), it.get("status"),
              it.get("group"), it.get("models")))
d = call("GET", "/api/log/?p=0&size=10&type=0", h=AH)
data = d.get("data") or {}
items = data.get("items") if isinstance(data, dict) else data
print("  recent logs:", len(items or []))
for it in (items or [])[:6]:
    if isinstance(it, dict):
        print("    %s | model=%s | %s | %s" % (it.get("created_at"), it.get("model_name"),
              str(it.get("content"))[:200], str(it.get("other"))[:300]))
CHKEOF
echo "=== done ==="
"""
)

if __name__ == "__main__":
    command(
        "diagnose-chat",
        "Diagnose the 503 on relayed chat completion: full body, mock access log, gateway log and channel state",
        SCRIPT,
        timeout=600,
    )
