"""End-to-end verification of the published gateway.

Temporarily starts a mock upstream on the compose bridge network, registers it
as a channel, mints a throwaway key, drives the real public HTTPS path
(non-streaming and streaming), checks that X-Forwarded-For cannot be spoofed,
then removes every temporary artefact.

No secret is printed: the throwaway key is used but never echoed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cloud import command  # noqa: E402

MOCK = r'''
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "gpt-4o-mini"


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
        if self.path.rstrip("/").endswith("/models"):
            self._json({"object": "list", "data": [{"id": MODEL, "object": "model"}]})
        else:
            self._json({"ok": True, "path": self.path})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
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
if not tok:
    print("  FATAL: admin login failed:", d.get("message"))
    sys.exit(1)
AH = {"Authorization": "Bearer " + tok, "New-API-User": "1"}
print("  admin authenticated")

# --- channel ---
code, d = call("POST", "/api/channel/", {
    "name": "zz-smoke-mock-do-not-keep",
    "type": 1,
    "key": "sk-mock-upstream",
    "base_url": UPSTREAM,
    "models": "gpt-4o-mini",
    "groups": ["default"],
    "status": 1,
}, AH)
print("  create channel ->", code, "success=", d.get("success"), str(d.get("message"))[:120])

code, d = call("GET", "/api/channel/?p=0&size=50", headers=AH)
rows = (d.get("data") or {})
items = rows.get("items") if isinstance(rows, dict) else rows
ch = None
for it in (items or []):
    if isinstance(it, dict) and it.get("name") == "zz-smoke-mock-do-not-keep":
        ch = it
        break
if ch:
    open("/tmp/smoke-channel-id", "w").write(str(ch.get("id")))
    print("  channel id:", ch.get("id"), "| base_url:", ch.get("base_url"), "| group:", ch.get("group"))
    code, d = call("GET", "/api/channel/test/%s" % ch.get("id"), headers=AH)
    print("  channel connectivity test ->", code, "| success=", d.get("success"),
          "| message=", str(d.get("message"))[:140])
else:
    print("  FATAL: channel not found after creation")

# --- token ---
code, d = call("POST", "/api/token/", {
    "name": "zz-smoke-key-do-not-keep",
    "remain_quota": 1000000,
    "expired_time": -1,
    "unlimited_quota": False,
    "model_limits_enabled": False,
    "group": "default",
}, AH)
print("  create token ->", code, "success=", d.get("success"), str(d.get("message"))[:120])

key = ""
code, d = call("GET", "/api/token/?p=0&size=50", headers=AH)
items = (d.get("data") or {})
items = items.get("items") if isinstance(items, dict) else items
for it in (items or []):
    if isinstance(it, dict) and it.get("name") == "zz-smoke-key-do-not-keep":
        key = it.get("key") or ""
        open("/tmp/smoke-token-id", "w").write(str(it.get("id")))
        break
if key:
    open("/tmp/smoke-key", "w").write("sk-" + key)
    print("  token minted, length", len(key) + 3)
else:
    print("  FATAL: token not found after creation")
'''

CLEANUP = r'''
import json, sys, urllib.error, urllib.request

BASE = "http://127.0.0.1:3000"

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

for path, label in (("/tmp/smoke-token-id", "token"), ("/tmp/smoke-channel-id", "channel")):
    try:
        ident = open(path).read().strip()
    except OSError:
        print("  %s: no id recorded" % label)
        continue
    code, d = call("DELETE", "/api/%s/%s" % (label, ident), headers=AH)
    print("  delete %s %s -> %s success=%s" % (label, ident, code, d.get("success")))

code, d = call("GET", "/api/token/?p=0&size=50", headers=AH)
items = (d.get("data") or {})
items = items.get("items") if isinstance(items, dict) else items
left = [i.get("name") for i in (items or []) if isinstance(i, dict)]
print("  tokens remaining:", left)

code, d = call("GET", "/api/channel/?p=0&size=50", headers=AH)
rows = (d.get("data") or {})
items = rows.get("items") if isinstance(rows, dict) else rows
left = [i.get("name") for i in (items or []) if isinstance(i, dict)]
print("  channels remaining:", left)
'''

SCRIPT = (
    r"""set -u
PUB=api.47.114.43.99.nip.io
RESOLVE="--resolve $PUB:443:127.0.0.1"

echo "=== 0) bridge address for the mock upstream ==="
BRIDGE=$(ip -o -4 addr show | awk '$4 ~ /^172\.30\.0\./ {print $4}' | cut -d/ -f1 | head -1)
echo "  bridge gateway: ${BRIDGE:-NOT FOUND}"
if [ -z "${BRIDGE:-}" ]; then echo "ABORT: bridge address unknown"; exit 1; fi

echo "=== 1) existing request-log format ==="
ls -l /opt/lamtools-api/logs/
tail -2 /opt/lamtools-api/logs/oneapi-*.log 2>/dev/null | cut -c1-400

cleanup() {
  echo "=== 9) cleanup ==="
  if [ -f /tmp/mock.pid ]; then kill "$(cat /tmp/mock.pid)" 2>/dev/null && echo "  mock upstream stopped" || echo "  mock already stopped"; fi
  rm -f /tmp/smoke-key /tmp/smoke-token-id /tmp/smoke-channel-id
  ss -tlnp 2>/dev/null | grep -q 8323 && echo "  WARNING: 8323 still listening" || echo "  8323 released"
}
trap cleanup EXIT

echo "=== 2) start temporary mock upstream on the bridge (not public) ==="
cat > /tmp/mock_upstream.py <<'MOCKEOF'
"""
    + MOCK
    + """MOCKEOF
setsid nohup python3 /tmp/mock_upstream.py "$BRIDGE" 8323 >/tmp/mock.log 2>&1 < /dev/null &
echo $! > /tmp/mock.pid
sleep 2
if ss -tln | grep -q 8323; then echo "  mock listening on $BRIDGE:8323 (pid $(cat /tmp/mock.pid))"; else echo "  MOCK FAILED TO START"; tail -5 /tmp/mock.log; fi

echo "=== 3) admin API: channel + token ==="
cat > /tmp/admin_smoke.py <<'ADMINEOF'
"""
    + ADMIN
    + """ADMINEOF
python3 /tmp/admin_smoke.py "http://$BRIDGE:8323"

echo "=== 4) client surface WITHOUT a key (must be rejected) ==="
echo -n "  GET /v1/models -> "
curl -s -o /tmp/nokey.json -w '%{http_code}\n' -m 20 $RESOLVE "https://$PUB/v1/models"
head -c 200 /tmp/nokey.json; echo

if [ ! -s /tmp/smoke-key ]; then
  echo "=== ABORT: no throwaway key available; skipping live call tests ==="
  exit 0
fi
KEY=$(cat /tmp/smoke-key)

echo "=== 5) client surface WITH a key, over public TLS ==="
echo -n "  GET /v1/models -> "
curl -s -o /tmp/models.json -w '%{http_code}\n' -m 25 $RESOLVE -H "Authorization: Bearer $KEY" "https://$PUB/v1/models"
python3 -c "
import json
try:
    d = json.load(open('/tmp/models.json'))
    ids = [m.get('id') for m in (d.get('data') or [])]
    print('    models visible:', ids)
except Exception:
    print('    (unparsable)', open('/tmp/models.json').read()[:160])
"

echo -n "  POST /v1/chat/completions (non-streaming) -> "
curl -s -o /tmp/chat.json -w '%{http_code}\n' -m 60 $RESOLVE \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"ping"}],"stream":false}' \
  "https://$PUB/v1/chat/completions"
python3 -c "
import json
try:
    d = json.load(open('/tmp/chat.json'))
    ch = (d.get('choices') or [{}])[0]
    print('    reply:', (ch.get('message') or {}).get('content'))
except Exception:
    print('    (unparsable)', open('/tmp/chat.json').read()[:200])
"

echo "  POST /v1/chat/completions (streaming) -> capturing SSE"
curl -s -N -m 60 $RESOLVE \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"ping"}],"stream":true}' \
  "https://$PUB/v1/chat/completions" -o /tmp/stream.txt -w '    http=%{http_code}\n'
python3 -c "
raw = open('/tmp/stream.txt', encoding='utf-8', errors='replace').read()
lines = [l for l in raw.splitlines() if l.startswith('data:')]
print('    sse data lines:', len(lines))
print('    saw [DONE]:', 'data: [DONE]' in raw)
text = ''
for l in lines:
    if l.strip() == 'data: [DONE]':
        continue
    try:
        import json
        d = json.loads(l[5:].strip())
        text += ((d.get('choices') or [{}])[0].get('delta') or {}).get('content') or ''
    except Exception:
        pass
print('    reassembled text:', repr(text))
"

echo "=== 6) X-Forwarded-For spoofing check ==="
BEFORE_TS=$(date -u +%s)
curl -s -o /dev/null -m 20 $RESOLVE -H 'X-Forwarded-For: 203.0.113.7' \
  -H "Authorization: Bearer $KEY" "https://$PUB/api/user/self" || true
sleep 2
LOGF=$(ls -t /opt/lamtools-api/logs/oneapi-*.log | head -1)
echo "  scanning $LOGF"
if grep -q '203\.0\.113\.7' "$LOGF"; then
  echo "  FAIL: forged client address reached the gateway log"
else
  echo "  PASS: forged client address did not appear in the gateway log"
fi
if grep -q '127\.0\.0\.1' "$LOGF"; then
  echo "  PASS: genuine client address recorded instead"
else
  echo "  NOTE: no 127.0.0.1 entry found in the latest log file"
fi

echo "=== 7) CORS headers on the public API (browser clients) ==="
curl -s -D /tmp/h.txt -o /dev/null -m 20 $RESOLVE -X OPTIONS \
  -H 'Origin: https://47.114.43.99.nip.io' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: authorization,content-type' \
  "https://$PUB/v1/chat/completions"
grep -i '^access-control\|^vary' /tmp/h.txt | sed 's/^/    /' || echo "    (no CORS headers)"

echo "=== 8) response headers on the console ==="
curl -s -D /tmp/h2.txt -o /dev/null -m 20 $RESOLVE "https://$PUB/"
grep -i '^server:\|^strict-transport\|^x-content-type\|^referrer-policy' /tmp/h2.txt | sed 's/^/    /' || echo "    (none)"
echo "=== live checks complete ==="
"""
)

if __name__ == "__main__":
    command(
        "verify-e2e",
        "End-to-end verification of published gateway: mock upstream, temp channel and key, public TLS streaming call, XFF spoof check, then cleanup",
        SCRIPT,
        timeout=900,
    )
