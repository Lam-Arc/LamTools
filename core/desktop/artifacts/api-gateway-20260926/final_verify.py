"""Final end-to-end verification on the stable build, with the routing-index
reload step the gateway requires, plus a helper for the operator.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cloud import command  # noqa: E402

MOCK = r'''
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
'''

ADMIN = r'''
import http.cookiejar, json, sys, urllib.error, urllib.request

BASE = "http://127.0.0.1:3000"
UPSTREAM = sys.argv[1]
CH_NAME = "zz-smoke-mock-do-not-keep"
TK_NAME = "zz-smoke-key-do-not-keep"
MODEL = "gpt-4o-mini"
OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        with OPENER.open(r, timeout=40) as resp:
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


code, d = call("POST", "/api/user/login", {"username": "root", "password": read_pw()})
uid = (d.get("data") or {}).get("id")
AH = {"New-Api-User": str(uid)}
code, d = call("GET", "/api/user/token", headers=AH)
tok = d.get("data")
if isinstance(tok, dict):
    tok = tok.get("token") or tok.get("access_token")
if isinstance(tok, str) and tok:
    AH["Authorization"] = "Bearer " + tok

channel = {"name": CH_NAME, "type": 1, "key": "sk-mock-upstream", "base_url": UPSTREAM,
           "models": MODEL, "group": "default", "status": 1, "weight": 1, "priority": 0}
code, d = call("POST", "/api/channel/", {"mode": "single", "channel": channel}, AH)
print("  channel created:", d.get("success"))
code, d = call("POST", "/api/token/", {"name": TK_NAME, "remain_quota": 100000000,
                                      "expired_time": -1, "unlimited_quota": True,
                                      "model_limits_enabled": False, "group": "default",
                                      "status": 1}, AH)


def items_of(d):
    data = d.get("data")
    return data.get("items") if isinstance(data, dict) else data


code, d = call("GET", "/api/token/?p=0&size=50", headers=AH)
tk = next((i for i in (items_of(d) or [])
           if isinstance(i, dict) and i.get("name") == TK_NAME), None)
KEY = ""
if tk:
    cand = tk.get("key") or ""
    if cand and "*" not in cand:
        KEY = cand if cand.startswith("sk-") else "sk-" + cand
    else:
        code, d = call("POST", "/api/token/%s/key" % tk.get("id"), {}, AH)
        cand = (d.get("data") or {})
        cand = cand.get("key") if isinstance(cand, dict) else cand
        if cand:
            KEY = cand if cand.startswith("sk-") else "sk-" + cand
if KEY:
    open("/tmp/smoke-key", "w").write(KEY)
print("  client key ready:", bool(KEY))
'''

CLEANUP = r'''
import http.cookiejar, json, urllib.error, urllib.request
BASE = "http://127.0.0.1:3000"
OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def call(m, p, b=None, h=None):
    d = json.dumps(b).encode() if b is not None else None
    r = urllib.request.Request(BASE + p, data=d, method=m)
    r.add_header("Content-Type", "application/json")
    for k, v in (h or {}).items():
        r.add_header(k, v)
    try:
        with OPENER.open(r, timeout=30) as resp:
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
d = call("POST", "/api/user/login", {"username": "root", "password": pw_read()})
uid = (d.get("data") or {}).get("id")
if not uid:
    print("  cleanup: login failed"); raise SystemExit(0)
h = {"New-Api-User": str(uid)}
d = call("GET", "/api/user/token", h=h)
t = d.get("data")
t = (t.get("token") or t.get("access_token")) if isinstance(t, dict) else t
if isinstance(t, str) and t:
    h["Authorization"] = "Bearer " + t
def items_of(d):
    data = d.get("data")
    return data.get("items") if isinstance(data, dict) else data
for label in ("token", "channel"):
    d = call("GET", "/api/%s/?p=0&size=100" % label, h=h)
    for it in [i for i in (items_of(d) or [])
               if isinstance(i, dict) and str(i.get("name","")).startswith("zz-smoke")]:
        r = call("DELETE", "/api/%s/%s" % (label, it.get("id")), h=h)
        print("  delete %s %s -> success=%s" % (label, it.get("id"), r.get("success")))
    d = call("GET", "/api/%s/?p=0&size=100" % label, h=h)
    print("  %s leftovers: %s" % (label, [i.get("name") for i in (items_of(d) or [])
          if isinstance(i, dict) and str(i.get("name","")).startswith("zz-smoke")] or "none"))
'''

SCRIPT = (
    r"""set -u
PUB=api.47.114.43.99.nip.io
RES="--resolve $PUB:443:127.0.0.1"
BRIDGE=$(ip -o -4 addr show | awk '$4 ~ /^172\.30\.0\./ {print $4}' | cut -d/ -f1 | head -1)
echo "  bridge gateway: $BRIDGE"

cleanup() {
  echo "=== cleanup ==="
  cat > /tmp/cleanup_smoke.py <<'CLEANEOF'
"""
    + CLEANUP
    + """CLEANEOF
  python3 /tmp/cleanup_smoke.py
  [ -f /tmp/mock.pid ] && kill "$(cat /tmp/mock.pid)" 2>/dev/null && echo "  mock stopped"
  rm -f /tmp/mock.pid /tmp/mock_access.log /tmp/smoke-key
}
trap cleanup EXIT

echo "=== 1) operator helper for the routing-index reload ==="
cat > /usr/local/bin/lamtools-api-reload <<'HELPEOF'
#!/bin/sh
# Rebuild the API gateway's routing index after channels are added or changed.
# The running process only re-reads channels for this purpose on start, so a
# newly added channel is not routable until this runs.
set -e
docker compose -f /opt/lamtools-api/docker-compose.yml restart gateway
echo "gateway restarted; new channels are now routable"
HELPEOF
chmod 755 /usr/local/bin/lamtools-api-reload
ls -l /usr/local/bin/lamtools-api-reload | sed 's/^/  /'

cat > /tmp/mock_upstream.py <<'MOCKEOF'
"""
    + MOCK
    + """MOCKEOF
setsid nohup python3 /tmp/mock_upstream.py "$BRIDGE" 8323 >/tmp/mock.log 2>&1 < /dev/null &
echo $! > /tmp/mock.pid
sleep 2
ss -tln | grep -q 8323 && echo "=== 2) mock upstream listening ===" || { echo "MOCK FAILED"; exit 1; }

cat > /tmp/admin.py <<'ADMINEOF'
"""
    + ADMIN
    + """ADMINEOF
echo "=== 3) register a temporary channel and key ==="
python3 /tmp/admin.py "http://$BRIDGE:8323"

if [ ! -s /tmp/smoke-key ]; then echo "no key; aborting"; exit 0; fi
KEY=$(cat /tmp/smoke-key)

echo "=== 4) apply the routing-index reload ==="
/usr/local/bin/lamtools-api-reload 2>&1 | tail -2
for i in $(seq 1 40); do
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:3000/api/status || true)
  [ "$c" = "200" ] && { echo "  gateway back after $((i*2))s"; break; }
  sleep 2
done
sleep 5

echo "=== 5) client surface without a key (must be rejected) ==="
echo -n "  GET /v1/models -> "
curl -s -o /dev/null -w '%{http_code}\n' -m 25 $RES "https://$PUB/v1/models"

echo "=== 6) client surface with a key over public TLS ==="
echo -n "  GET /v1/models -> "
curl -s -o /tmp/models.json -w '%{http_code}\n' -m 25 $RES -H "Authorization: Bearer $KEY" "https://$PUB/v1/models"
python3 -c "
import json
d = json.load(open('/tmp/models.json'))
print('    models:', [m.get('id') for m in (d.get('data') or [])])
"
echo -n "  POST /v1/chat/completions non-streaming -> "
curl -s -o /tmp/chat.json -w '%{http_code}\n' -m 60 $RES \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"ping"}],"stream":false}' \
  "https://$PUB/v1/chat/completions"
python3 -c "
import json
d = json.load(open('/tmp/chat.json'))
print('    reply:', ((d.get('choices') or [{}])[0].get('message') or {}).get('content'),
      '| usage:', d.get('usage'))
"
echo "  POST /v1/chat/completions streaming:"
curl -s -N -m 60 $RES \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"ping"}],"stream":true}' \
  "https://$PUB/v1/chat/completions" -o /tmp/stream.txt -w '    http=%{http_code}\n'
python3 -c "
import json
raw = open('/tmp/stream.txt', encoding='utf-8', errors='replace').read()
lines = [l for l in raw.splitlines() if l.startswith('data:')]
text = ''
for l in lines:
    if l.strip() == 'data: [DONE]':
        continue
    try:
        text += ((json.loads(l[5:].strip()).get('choices') or [{}])[0].get('delta') or {}).get('content') or ''
    except Exception:
        pass
print('    sse data lines:', len(lines), '| saw [DONE]:', 'data: [DONE]' in raw)
print('    reassembled:', repr(text))
"

echo "=== 7) X-Forwarded-For spoofing check ==="
curl -s -o /dev/null -m 25 $RES -H 'X-Forwarded-For: 203.0.113.7' \
  -H "Authorization: Bearer $KEY" "https://$PUB/api/user/self" || true
sleep 2
LOGF=$(ls -t /opt/lamtools-api/logs/oneapi-*.log 2>/dev/null | head -1)
if [ -n "${LOGF:-}" ]; then
  if grep -q '203\.0\.113\.7' "$LOGF"; then echo "  FAIL: forged address reached the log"; else echo "  PASS: forged address absent from the log"; fi
else
  echo "  (no request log on this build)"
fi

echo "=== 8) key material must not appear in container logs ==="
docker logs lamtools-api-gateway 2>&1 | grep -qF "$KEY" && echo "  FAIL: key found in logs" || echo "  PASS: no client key in container logs"

echo "=== 9) console over TLS + security headers ==="
curl -s -D /tmp/h.txt -o /dev/null -m 25 $RES "https://$PUB/"
tr -d '\r' < /tmp/h.txt | grep -iE '^HTTP/|^server:|^strict-transport|^x-content-type|^referrer-policy' | sed 's/^/  /'

echo "=== 10) resources ==="
docker compose -f /opt/lamtools-api/docker-compose.yml ps --format '  {{.Name}} {{.Image}} {{.Status}}'
free -m | head -2 | sed 's/^/  /'
df -h / | tail -1 | sed 's/^/  /'
echo "=== mock access log ==="
[ -f /tmp/mock_access.log ] && sed 's/^/  /' /tmp/mock_access.log || echo "  nothing reached the mock"
echo "=== done ==="
"""
)

if __name__ == "__main__":
    command(
        "final-verify",
        "Final end-to-end verification: channel, key, index reload, streaming and non-streaming relay calls, header and leak checks",
        SCRIPT,
        timeout=900,
    )
