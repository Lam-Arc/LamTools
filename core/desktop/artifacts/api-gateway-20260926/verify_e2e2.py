"""End-to-end verification of the published gateway (corrected API shapes).

Registers a temporary mock upstream as a channel, mints a throwaway key, drives
the real public HTTPS path (non-streaming and streaming), then removes every
temporary artefact including leftovers from earlier attempts.
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
CH_NAME = "zz-smoke-mock-do-not-keep"
TK_NAME = "zz-smoke-key-do-not-keep"


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


def items_of(d):
    data = d.get("data") or {}
    return data.get("items") if isinstance(data, dict) else data


# --- channel: the payload nests the channel under "channel" ---
channel = {
    "name": CH_NAME,
    "type": 1,
    "key": "sk-mock-upstream",
    "base_url": UPSTREAM,
    "models": "gpt-4o-mini",
    "group": "default",
    "groups": ["default"],
    "status": 1,
}
made = False
for payload in ({"mode": "single", "channel": channel},
                {"channel": channel},
                {"mode": "batch", "channel": channel}):
    code, d = call("POST", "/api/channel/", payload, AH)
    print("  create channel %s -> %s success=%s msg=%s"
          % (payload.get("mode", "(no mode)"), code, d.get("success"),
             str(d.get("message"))[:120]))
    if d.get("success"):
        made = True
        break

ch = None
code, d = call("GET", "/api/channel/?p=0&size=50", headers=AH)
for it in (items_of(d) or []):
    if isinstance(it, dict) and it.get("name") == CH_NAME:
        ch = it
        break
if ch:
    open("/tmp/smoke-channel-id", "w").write(str(ch.get("id")))
    print("  channel id=%s group=%s models=%s" % (ch.get("id"), ch.get("group"), ch.get("models")))
    code, d = call("GET", "/api/channel/test/%s" % ch.get("id"), headers=AH)
    print("  connectivity test -> %s success=%s msg=%s"
          % (code, d.get("success"), str(d.get("message"))[:160]))
elif made:
    print("  FATAL: channel created but not listed")

# --- token ---
code, d = call("POST", "/api/token/", {
    "name": TK_NAME,
    "remain_quota": 1000000,
    "expired_time": -1,
    "unlimited_quota": False,
    "model_limits_enabled": False,
    "group": "default",
    "status": 1,
}, AH)
print("  create token -> %s success=%s msg=%s"
      % (code, d.get("success"), str(d.get("message"))[:120]))

tk = None
code, d = call("GET", "/api/token/?p=0&size=50", headers=AH)
for it in (items_of(d) or []):
    if isinstance(it, dict) and it.get("name") == TK_NAME:
        tk = it
        break
if not tk:
    print("  FATAL: token not listed")
    sys.exit(1)
open("/tmp/smoke-token-id", "w").write(str(tk.get("id")))
print("  token id=%s status=%s masked_key=%s"
      % (tk.get("id"), tk.get("status"), str(tk.get("key"))[:12] + "..."))

# Full key comes from a dedicated POST endpoint; lists only ever return a mask.
full = ""
for method in ("POST", "GET"):
    code, d = call(method, "/api/token/%s/key" % tk.get("id"), {}, headers=AH)
    cand = (d.get("data") or {})
    cand = cand.get("key") if isinstance(cand, dict) else cand
    if isinstance(cand, str) and cand:
        full = cand
        break
    print("  full-key %s -> %s success=%s msg=%s"
          % (method, code, d.get("success"), str(d.get("message"))[:100]))
if full:
    if not full.startswith("sk-"):
        full = "sk-" + full
    open("/tmp/smoke-key", "w").write(full)
    print("  full key retrieved, length", len(full))
else:
    print("  FATAL: could not retrieve the full key")
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


def items_of(d):
    data = d.get("data") or {}
    return data.get("items") if isinstance(data, dict) else data


for label, prefix in (("token", "zz-smoke"), ("channel", "zz-smoke")):
    code, d = call("GET", "/api/%s/?p=0&size=100" % label, headers=AH)
    caught = [i for i in (items_of(d) or [])
              if isinstance(i, dict) and str(i.get("name", "")).startswith(prefix)]
    for it in caught:
        code, r = call("DELETE", "/api/%s/%s" % (label, it.get("id")), headers=AH)
        print("  delete %s id=%s name=%s -> success=%s"
              % (label, it.get("id"), it.get("name"), r.get("success")))
    code, d = call("GET", "/api/%s/?p=0&size=100" % label, headers=AH)
    left = [i.get("name") for i in (items_of(d) or [])
            if isinstance(i, dict) and str(i.get("name", "")).startswith(prefix)]
    print("  %s leftovers: %s" % (label, left or "none"))
'''

SCRIPT = (
    r"""set -u
PUB=api.47.114.43.99.nip.io
RESOLVE="--resolve $PUB:443:127.0.0.1"

echo "=== 0) bridge address ==="
BRIDGE=$(ip -o -4 addr show | awk '$4 ~ /^172\.30\.0\./ {print $4}' | cut -d/ -f1 | head -1)
echo "  bridge gateway: ${BRIDGE:-NOT FOUND}"

cleanup() {
  echo "=== 8) cleanup ==="
  cat > /tmp/cleanup_smoke.py <<'CLEANEOF'
"""
    + CLEANUP
    + """CLEANEOF
  python3 /tmp/cleanup_smoke.py
  if [ -f /tmp/mock.pid ]; then kill "$(cat /tmp/mock.pid)" 2>/dev/null && echo "  mock upstream stopped"; fi
  rm -f /tmp/smoke-key /tmp/smoke-token-id /tmp/smoke-channel-id /tmp/mock.pid
  ss -tln 2>/dev/null | grep -q 8323 && echo "  WARNING: 8323 still listening" || echo "  port 8323 released"
}
trap cleanup EXIT

echo "=== 1) start temporary mock upstream on the bridge (not public) ==="
cat > /tmp/mock_upstream.py <<'MOCKEOF'
"""
    + MOCK
    + """MOCKEOF
setsid nohup python3 /tmp/mock_upstream.py "$BRIDGE" 8323 >/tmp/mock.log 2>&1 < /dev/null &
echo $! > /tmp/mock.pid
sleep 2
ss -tln | grep -q 8323 && echo "  listening on $BRIDGE:8323" || { echo "  MOCK FAILED"; tail -5 /tmp/mock.log; }

echo "=== 2) admin API: channel + token ==="
cat > /tmp/admin_smoke.py <<'ADMINEOF'
"""
    + ADMIN
    + """ADMINEOF
python3 /tmp/admin_smoke.py "http://$BRIDGE:8323"

echo "=== 3) without a key (must be rejected) ==="
echo -n "  GET /v1/models -> "
curl -s -o /dev/null -w '%{http_code}\n' -m 20 $RESOLVE "https://$PUB/v1/models"

if [ ! -s /tmp/smoke-key ]; then
  echo "=== ABORT: no throwaway key; skipping live call tests ==="
  exit 0
fi
KEY=$(cat /tmp/smoke-key)

echo "=== 4) with a key, over public TLS ==="
echo -n "  GET /v1/models -> "
curl -s -o /tmp/models.json -w '%{http_code}\n' -m 25 $RESOLVE -H "Authorization: Bearer $KEY" "https://$PUB/v1/models"
python3 -c "
import json
try:
    d = json.load(open('/tmp/models.json'))
    print('    models visible:', [m.get('id') for m in (d.get('data') or [])])
except Exception:
    print('    body:', open('/tmp/models.json').read()[:180])
"

echo -n "  POST /v1/chat/completions non-streaming -> "
curl -s -o /tmp/chat.json -w '%{http_code}\n' -m 60 $RESOLVE \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"ping"}],"stream":false}' \
  "https://$PUB/v1/chat/completions"
python3 -c "
import json
try:
    d = json.load(open('/tmp/chat.json'))
    ch = (d.get('choices') or [{}])[0]
    print('    reply:', (ch.get('message') or {}).get('content'), '| usage:', d.get('usage'))
except Exception:
    print('    body:', open('/tmp/chat.json').read()[:200])
"

echo "  POST /v1/chat/completions streaming ->"
curl -s -N -m 60 $RESOLVE \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"ping"}],"stream":true}' \
  "https://$PUB/v1/chat/completions" -o /tmp/stream.txt -w '    http=%{http_code}\n'
python3 -c "
raw = open('/tmp/stream.txt', encoding='utf-8', errors='replace').read()
lines = [l for l in raw.splitlines() if l.startswith('data:')]
print('    sse data lines:', len(lines), '| saw [DONE]:', 'data: [DONE]' in raw)
text = ''
import json
for l in lines:
    if l.strip() == 'data: [DONE]':
        continue
    try:
        text += ((json.loads(l[5:].strip()).get('choices') or [{}])[0].get('delta') or {}).get('content') or ''
    except Exception:
        pass
print('    reassembled text:', repr(text))
"

echo "=== 5) X-Forwarded-For spoofing check ==="
curl -s -o /dev/null -m 20 $RESOLVE -H 'X-Forwarded-For: 203.0.113.7' \
  -H "Authorization: Bearer $KEY" "https://$PUB/api/user/self" || true
sleep 2
LOGF=$(ls -t /opt/lamtools-api/logs/oneapi-*.log | head -1)
if grep -q '203\.0\.113\.7' "$LOGF"; then
  echo "  FAIL: forged client address reached the gateway log"
else
  echo "  PASS: forged client address absent from the gateway log"
fi

echo "=== 6) leak check: key material must not appear in container logs ==="
if docker logs lamtools-api-gateway 2>&1 | grep -qF "$KEY"; then
  echo "  FAIL: a client key was written to container logs"
else
  echo "  PASS: no client key in container logs"
fi

echo "=== 7) container state ==="
docker compose -f /opt/lamtools-api/docker-compose.yml ps
"""
)

if __name__ == "__main__":
    command(
        "verify-e2e-3",
        "End-to-end verification of published gateway with corrected channel and token API shapes, including cleanup",
        SCRIPT,
        timeout=900,
    )
