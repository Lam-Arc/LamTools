set -u
PUB=api.47.114.43.99.nip.io
RES="--resolve $PUB:443:127.0.0.1"
BRIDGE=$(ip -o -4 addr show | awk '$4 ~ /^172\.30\.0\./ {print $4}' | cut -d/ -f1 | head -1)
echo "  bridge gateway: $BRIDGE"

mask_key() {
  python3 - "$1" <<'PYEOF'
import sys
key = sys.argv[1]
text = sys.stdin.read()
if key:
    text = text.replace(key, '***CLIENT-KEY-REDACTED***')
    body = key[3:] if key.startswith('sk-') else key
    text = text.replace(body, '***CLIENT-KEY-BODY-REDACTED***')
print(text)
PYEOF
}

cleanup() {
  echo "=== cleanup ==="
  cat > /tmp/cleanup_smoke.py <<'CLEANEOF'
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
CLEANEOF
  python3 /tmp/cleanup_smoke.py
  [ -f /tmp/mock.pid ] && kill "$(cat /tmp/mock.pid)" 2>/dev/null && echo "  mock stopped"
  rm -f /tmp/mock.pid /tmp/mock_access.log /tmp/smoke-key
}
trap cleanup EXIT

cat > /tmp/mock_upstream.py <<'MOCKEOF'

import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
        self._json({"object": "list", "data": [{"id": "gpt-4o-mini", "object": "model"}]})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        model = body.get("model") or "gpt-4o-mini"
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

cat > /tmp/admin.py <<'ADMINEOF'

import http.cookiejar, json, sys, urllib.error, urllib.request

BASE = "http://127.0.0.1:3000"
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


def items_of(d):
    data = d.get("data")
    return data.get("items") if isinstance(data, dict) else data


code, d = call("POST", "/api/user/login", {"username": "root", "password": read_pw()})
uid = (d.get("data") or {}).get("id")
AH = {"New-Api-User": str(uid)}
code, d = call("GET", "/api/user/token", headers=AH)
tok = d.get("data")
if isinstance(tok, dict):
    tok = tok.get("token") or tok.get("access_token")
if isinstance(tok, str) and tok:
    AH["Authorization"] = "Bearer " + tok

channel = {"name": "zz-smoke-mock-do-not-keep", "type": 1, "key": "sk-mock-upstream",
           "base_url": sys.argv[1], "models": "gpt-4o-mini", "group": "default",
           "status": 1, "weight": 1, "priority": 0}
code, d = call("POST", "/api/channel/", {"mode": "single", "channel": channel}, AH)
code, d = call("POST", "/api/token/", {"name": "zz-smoke-key-do-not-keep",
                                      "remain_quota": 100000000, "expired_time": -1,
                                      "unlimited_quota": True, "model_limits_enabled": False,
                                      "group": "default", "status": 1}, AH)
code, d = call("GET", "/api/token/?p=0&size=50", headers=AH)
tk = next((i for i in (items_of(d) or [])
           if isinstance(i, dict) and i.get("name") == "zz-smoke-key-do-not-keep"), None)
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
print("  key ready:", bool(KEY))
ADMINEOF
python3 /tmp/admin.py "http://$BRIDGE:8323"
if [ ! -s /tmp/smoke-key ]; then echo "no key; aborting"; exit 0; fi
KEY=$(cat /tmp/smoke-key)

/usr/local/bin/lamtools-api-reload >/dev/null 2>&1
for i in $(seq 1 40); do
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:3000/api/status || true)
  [ "$c" = "200" ] && break
  sleep 2
done
sleep 5

echo "=== baseline: does the key appear in logs BEFORE any relay call? ==="
docker logs lamtools-api-gateway 2>&1 | grep -cF "$KEY" | sed 's/^/  occurrences: /'

echo "=== make exactly one relayed call ==="
curl -s -o /dev/null -m 45 $RES -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json'   -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"ping"}],"stream":false}'   "https://$PUB/v1/chat/completions"
sleep 2

echo "=== occurrences after the call ==="
docker logs lamtools-api-gateway 2>&1 | grep -cF "$KEY" | sed 's/^/  occurrences: /'

echo "=== the offending lines, key redacted ==="
docker logs lamtools-api-gateway 2>&1 | grep -F "$KEY" | tail -5 | mask_key "$KEY" | cut -c1-400 | sed 's/^/  /'

echo "=== also check the on-disk log files ==="
if grep -rlF "$KEY" /opt/lamtools-api/logs/ 2>/dev/null | head -3 | grep -q .; then
  echo "  key present in on-disk logs:"
  grep -rlF "$KEY" /opt/lamtools-api/logs/ 2>/dev/null | sed 's/^/    /'
  grep -hF "$KEY" /opt/lamtools-api/logs/* 2>/dev/null | tail -3 | mask_key "$KEY" | cut -c1-400 | sed 's/^/    /'
else
  echo "  on-disk logs are clean"
fi
echo "=== done ==="
