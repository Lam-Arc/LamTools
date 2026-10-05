set -u
PUB=api.47.114.43.99.nip.io
RES="--resolve $PUB:443:127.0.0.1"
BRIDGE=$(ip -o -4 addr show | awk '$4 ~ /^172\.30\.0\./ {print $4}' | cut -d/ -f1 | head -1)
echo "  bridge gateway: $BRIDGE"

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

echo "=== admin API on the stable build ==="
cat > /tmp/admin.py <<'ADMINEOF'

import http.cookiejar, json, sys, time, urllib.error, urllib.request

BASE = "http://127.0.0.1:3000"
UPSTREAM = sys.argv[1]
OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
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
print("  login success:", d.get("success"), "| root id:", uid)
if not uid:
    print("  FATAL: login failed:", d.get("message"))
    sys.exit(1)
AH = {"New-Api-User": str(uid)}

code, d = call("GET", "/api/user/self", headers=AH)
print("  /api/user/self with session+user header ->", code,
      "success:", d.get("success"), "role:", (d.get("data") or {}).get("role"))

code, d = call("GET", "/api/user/token", headers=AH)
tok = d.get("data")
if isinstance(tok, dict):
    tok = tok.get("token") or tok.get("access_token")
if isinstance(tok, str) and tok:
    AH["Authorization"] = "Bearer " + tok
    print("  access token obtained (length %d); admin API now uses it" % len(tok))
else:
    print("  no access token; continuing with session only")

print("  --- close self-service registration ---")
for key, value in (("RegisterEnabled", "false"), ("PasswordRegisterEnabled", "false"),
                   ("EmailVerificationEnabled", "false"), ("TurnstileCheckEnabled", "false")):
    code, d = call("PUT", "/api/option/", {"key": key, "value": value}, AH)
    print("    %-26s -> %s success=%s %s" % (key, code, d.get("success"),
                                             str(d.get("message"))[:60]))

code, d = call("GET", "/api/option/", headers=AH)
rows = d.get("data")
if isinstance(rows, dict):
    rows = [{"key": k, "value": v} for k, v in rows.items()]
print("  --- registration options now ---")
for o in (rows or []):
    if isinstance(o, dict) and any(t in str(o.get("key")).lower()
                                   for t in ("register", "selfuse", "demo", "turnstile")):
        print("    %-34s = %s" % (o.get("key"), o.get("value")))


def items_of(d):
    data = d.get("data")
    if isinstance(data, dict):
        return data.get("items")
    return data


print("  --- channel ---")
channel = {"name": CH_NAME, "type": 1, "key": "sk-mock-upstream", "base_url": UPSTREAM,
           "models": MODEL, "group": "default", "status": 1, "weight": 1, "priority": 0}
made = False
for payload in (channel, {"mode": "single", "channel": channel}):
    code, d = call("POST", "/api/channel/", payload, AH)
    print("    payload %s -> %s success=%s msg=%s"
          % ("flat" if "name" in payload else "wrapped", code, d.get("success"),
             str(d.get("message"))[:90]))
    if d.get("success"):
        made = True
        break
code, d = call("GET", "/api/channel/?p=0&size=50", headers=AH)
ch = next((i for i in (items_of(d) or [])
           if isinstance(i, dict) and i.get("name") == CH_NAME), None)
if ch:
    print("    channel id=%s status=%s group=%s models=%s" % (ch.get("id"), ch.get("status"),
                                                              ch.get("group"), ch.get("models")))
    code, d = call("GET", "/api/channel/test/%s" % ch.get("id"), headers=AH)
    print("    connectivity test -> %s success=%s" % (code, d.get("success")))

print("  --- token ---")
code, d = call("POST", "/api/token/", {"name": TK_NAME, "remain_quota": 100000000,
                                      "expired_time": -1, "unlimited_quota": True,
                                      "model_limits_enabled": False, "group": "default",
                                      "status": 1}, AH)
print("    create -> %s success=%s msg=%s" % (code, d.get("success"), str(d.get("message"))[:80]))
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
print("    client key ready:", bool(KEY))
if KEY:
    open("/tmp/smoke-key", "w").write(KEY)
ADMINEOF
python3 /tmp/admin.py "http://$BRIDGE:8323"

echo "=== public status ==="
curl -s -m 10 "https://$PUB/api/status" $RES | python3 -c "
import json,sys
d = json.load(sys.stdin).get('data', {})
for k in sorted(d):
    if any(t in k.lower() for t in ('register','setup','self_use','demo','turnstile','version')):
        print('  %s = %s' % (k, d.get(k)))
" 2>/dev/null || echo "  (status unreadable)"

echo "=== registration attempt (must be rejected) ==="
code=$(curl -s -o /tmp/reg.json -w '%{http_code}' -m 20 $RES -H 'Content-Type: application/json'   -d '{"username":"zzprobe1","password":"Xy9-not-a-real-account","password2":"Xy9-not-a-real-account"}'   "https://$PUB/api/user/register")
python3 -c "
import json
try:
    d = json.load(open('/tmp/reg.json'))
    print('  http=$code success=%s msg=%s' % (d.get('success'), str(d.get('message'))[:110]))
except Exception:
    print('  http=$code unparsable')
"

if [ ! -s /tmp/smoke-key ]; then echo "=== no client key; skipping relay tests ==="; exit 0; fi
KEY=$(cat /tmp/smoke-key)

echo "=== without a key (must be rejected) ==="
echo -n "  GET /v1/models -> "
curl -s -o /dev/null -w '%{http_code}
' -m 20 $RES "https://$PUB/v1/models"

echo "=== with a key, over public TLS ==="
echo -n "  GET /v1/models -> "
curl -s -o /tmp/models.json -w '%{http_code}
' -m 25 $RES -H "Authorization: Bearer $KEY" "https://$PUB/v1/models"
python3 -c "
import json
try:
    d = json.load(open('/tmp/models.json'))
    print('    models:', [m.get('id') for m in (d.get('data') or [])])
except Exception:
    print('    body:', open('/tmp/models.json').read()[:200])
"

echo -n "  POST /v1/chat/completions (non-streaming) -> "
curl -s -o /tmp/chat.json -w '%{http_code}
' -m 60 $RES   -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json'   -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"ping"}],"stream":false}'   "https://$PUB/v1/chat/completions"
python3 -c "
import json
try:
    d = json.load(open('/tmp/chat.json'))
    if d.get('error'):
        print('    error:', str(d['error'])[:200])
    else:
        print('    reply:', ((d.get('choices') or [{}])[0].get('message') or {}).get('content'),
              '| usage:', d.get('usage'))
except Exception:
    print('    body:', open('/tmp/chat.json').read()[:200])
"

echo "  POST /v1/chat/completions (streaming) ->"
curl -s -N -m 60 $RES   -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json'   -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"ping"}],"stream":true}'   "https://$PUB/v1/chat/completions" -o /tmp/stream.txt -w '    http=%{http_code}
'
python3 -c "
import json
raw = open('/tmp/stream.txt', encoding='utf-8', errors='replace').read()
if raw.lstrip().startswith('{'):
    print('    json body:', raw[:200]); raise SystemExit(0)
lines = [l for l in raw.splitlines() if l.startswith('data:')]
text = ''
for l in lines:
    if l.strip() == 'data: [DONE]':
        continue
    try:
        text += ((json.loads(l[5:].strip()).get('choices') or [{}])[0].get('delta') or {}).get('content') or ''
    except Exception:
        pass
print('    sse lines:', len(lines), '| [DONE]:', 'data: [DONE]' in raw, '| text:', repr(text))
"

echo "=== mock access log ==="
[ -f /tmp/mock_access.log ] && sed 's/^/  /' /tmp/mock_access.log || echo "  nothing reached the mock"
echo "=== done ==="
