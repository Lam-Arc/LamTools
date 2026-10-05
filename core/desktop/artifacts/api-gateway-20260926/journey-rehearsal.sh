set -u
PUB=api.47.114.43.99.nip.io
RES="--resolve $PUB:443:127.0.0.1"
BRIDGE=$(ip -o -4 addr show | awk '$4 ~ /^172\.30\.0\./ {print $4}' | cut -d/ -f1 | head -1)
echo "  bridge gateway: $BRIDGE"

cleanup() {
  rm -f /tmp/mock.pid /tmp/journey-key /tmp/journey-user-id
  [ -f /tmp/mock.pid ] || true
}
trap cleanup EXIT

cat > /tmp/settings.py <<'SETEOF'

import http.cookiejar, json, re, sys, time, urllib.error, urllib.request

BASE = "http://127.0.0.1:3000"
PUB = "api.47.114.43.99.nip.io"
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
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw.strip().startswith(b"{") else raw)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def pw_read():
    for line in open("/opt/lamtools-api/admin-credentials.txt", encoding="utf-8"):
        if line.startswith("password :"):
            return line.split(":", 1)[1].strip()
    return ""


uid = None
for _ in range(6):
    code, d = call("POST", "/api/user/login", {"username": "root", "password": pw_read()})
    if isinstance(d, dict) and (d.get("data") or {}).get("id"):
        uid = d["data"]["id"]
        break
    time.sleep(12)
if not uid:
    print("  FATAL: admin login failed")
    sys.exit(1)
AH = {"New-Api-User": str(uid)}
code, d = call("GET", "/api/user/token", headers=AH)
t = d.get("data")
t = (t.get("token") or t.get("access_token")) if isinstance(t, dict) else t
if isinstance(t, str) and t:
    AH["Authorization"] = "Bearer " + t

print("=== settings that shape the flow ===")
code, d = call("GET", "/api/option/", headers=AH)
rows = d.get("data")
if isinstance(rows, dict):
    rows = [{"key": k, "value": v} for k, v in rows.items()]
want = ("quota_per_unit", "QuotaForNewUser", "RegisterEnabled", "PasswordRegisterEnabled",
        "EmailVerificationEnabled", "TurnstileCheckEnabled", "Language", "DefaultGroup",
        "UserDefaultGroup", "SelfUseModeEnabled", "DisplayInCurrency", "Price")
for o in (rows or []):
    if isinstance(o, dict) and str(o.get("key")) in want:
        print("  %-28s = %s" % (o.get("key"), str(o.get("value"))[:80]))

print("=== groups available ===")
code, d = call("GET", "/api/group/", headers=AH)
print("  ", json.dumps(d.get("data"))[:200])

print("=== console menu labels (as the operator will see them) ===")
code, html = call("GET", "/")
if isinstance(html, bytes):
    text = html.decode("utf-8", "replace")
    labels = re.findall(r'>\s*([A-Za-z\u4e00-\u9fff][^<>{}]{1,24})\s*<', text)
    seen = []
    for label in labels:
        label = label.strip()
        if label and label not in seen and not label.startswith("$"):
            seen.append(label)
    print("  http:", code, "| distinct labels found:", len(seen))
    print("  ", " | ".join(seen[:60]))
else:
    print("  console returned:", code, str(html)[:120])
SETEOF
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
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for chunk in ("ok",):
                ev = {"id": "chatcmpl-mock", "object": "chat.completion.chunk", "created": 0,
                      "model": model,
                      "choices": [{"index": 0, "delta": {"content": chunk},
                                   "finish_reason": None}]}
                self.wfile.write(("data: " + json.dumps(ev) + "\n\n").encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            self._json({"id": "chatcmpl-mock", "object": "chat.completion", "created": 0,
                        "model": model,
                        "choices": [{"index": 0,
                                     "message": {"role": "assistant", "content": "journey ok"},
                                     "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})


ThreadingHTTPServer((sys.argv[1], int(sys.argv[2])), H).serve_forever()
MOCKEOF
cat > /tmp/journey.py <<'JOURNEYEOF'

import http.cookiejar, json, os, subprocess, sys, time, urllib.error, urllib.request

BASE = "http://127.0.0.1:3000"
UPSTREAM = sys.argv[1]
CH = "zz-journey-channel"
USER = "zztest1"
TK = "zz-journey-user-token"
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


def items_of(d):
    data = d.get("data")
    return data.get("items") if isinstance(data, dict) else data


def pw_read():
    for line in open("/opt/lamtools-api/admin-credentials.txt", encoding="utf-8"):
        if line.startswith("password :"):
            return line.split(":", 1)[1].strip()
    return ""


uid = None
for _ in range(6):
    code, d = call("POST", "/api/user/login", {"username": "root", "password": pw_read()})
    uid = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
    if uid:
        break
    time.sleep(12)
AH = {"New-Api-User": str(uid)}
code, d = call("GET", "/api/user/token", headers=AH)
t = d.get("data")
t = (t.get("token") or t.get("access_token")) if isinstance(t, dict) else t
if isinstance(t, str) and t:
    AH["Authorization"] = "Bearer " + t
print("  1. admin authenticated")

# --- operator step: register the provider ---
channel = {"name": CH, "type": 1, "key": "sk-mock-upstream", "base_url": UPSTREAM,
           "models": "gpt-4o-mini", "group": "default", "status": 1, "weight": 1, "priority": 0}
code, d = call("POST", "/api/channel/", {"mode": "single", "channel": channel}, AH)
print("  2. provider added:", d.get("success"))
code, d = call("GET", "/api/channel/?p=0&size=50", headers=AH)
ch = next((i for i in (items_of(d) or [])
           if isinstance(i, dict) and i.get("name") == CH), None)
print("     channel id=%s group=%s models=%s" % (ch and ch.get("id"), ch and ch.get("group"),
                                                 ch and ch.get("models")))

# --- operator step: create a user with quota ---
USER_PW = "Zz" + os.urandom(9).hex()
code, d = call("POST", "/api/user/", {"username": USER, "password": USER_PW,
                                     "display_name": "journey test", "role": 1,
                                     "quota": 1000000, "group": "default"}, AH)
print("  3. user created ->", code, "success:", d.get("success"), str(d.get("message"))[:70])
code, d = call("GET", "/api/user/?p=0&size=50", headers=AH)
created = next((i for i in (items_of(d) or [])
                if isinstance(i, dict) and i.get("username") == USER), None)
if created:
    print("     user id=%s group=%s remaining quota=%s" % (created.get("id"),
                                                            created.get("group"),
                                                            created.get("quota")))

# --- user step: sign in and mint a key ---
USER_OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def user_call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        with USER_OPENER.open(r, timeout=40) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


code, d = user_call("POST", "/api/user/login", {"username": USER, "password": USER_PW})
u_id = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
print("  4. user signed in ->", code, "success:", d.get("success"), "| user id:", u_id)
UH = {"New-Api-User": str(u_id)}

code, d = user_call("POST", "/api/token/", {"name": TK, "remain_quota": 0,
                                           "expired_time": -1, "unlimited_quota": False,
                                           "model_limits_enabled": False,
                                           "group": "default", "status": 1}, UH)
print("  5. user minted own key ->", code, "success:", d.get("success"),
      str(d.get("message"))[:70])
code, d = user_call("GET", "/api/token/?p=0&size=50", headers=UH)
tk = next((i for i in (items_of(d) or [])
           if isinstance(i, dict) and i.get("name") == TK), None)
KEY = ""
if tk:
    cand = tk.get("key") or ""
    if cand and "*" not in cand:
        KEY = cand if cand.startswith("sk-") else "sk-" + cand
    else:
        code, d = user_call("POST", "/api/token/%s/key" % tk.get("id"), {}, UH)
        cand = (d.get("data") or {})
        cand = cand.get("key") if isinstance(cand, dict) else cand
        if cand:
            KEY = cand if cand.startswith("sk-") else "sk-" + cand
    print("     token id=%s token quota=%s (0 means it draws on the user's quota)"
          % (tk.get("id"), tk.get("remain_quota")))
print("  6. user key ready:", bool(KEY))
if KEY:
    open("/tmp/journey-key", "w").write(KEY)
    open("/tmp/journey-user-id", "w").write(str(created.get("id")))
JOURNEYEOF
cat > /tmp/after.py <<'AFTEREOF'

import http.cookiejar, json, sys, time, urllib.error, urllib.request

BASE = "http://127.0.0.1:3000"
USER = "zztest1"
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


def items_of(d):
    data = d.get("data")
    return data.get("items") if isinstance(data, dict) else data


def pw_read():
    for line in open("/opt/lamtools-api/admin-credentials.txt", encoding="utf-8"):
        if line.startswith("password :"):
            return line.split(":", 1)[1].strip()
    return ""


uid = None
for _ in range(6):
    code, d = call("POST", "/api/user/login", {"username": "root", "password": pw_read()})
    uid = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
    if uid:
        break
    time.sleep(12)
AH = {"New-Api-User": str(uid)}
code, d = call("GET", "/api/user/token", headers=AH)
t = d.get("data")
t = (t.get("token") or t.get("access_token")) if isinstance(t, dict) else t
if isinstance(t, str) and t:
    AH["Authorization"] = "Bearer " + t

code, d = call("GET", "/api/user/?p=0&size=50", headers=AH)
u = next((i for i in (items_of(d) or [])
          if isinstance(i, dict) and i.get("username") == USER), None)
if u:
    print("  8. after the call: user quota=%s used=%s" % (u.get("quota"), u.get("used_quota")))

print("  9. cleanup")
code, d = call("GET", "/api/token/?p=0&size=100", headers=AH)
for it in [i for i in (items_of(d) or [])
           if isinstance(i, dict) and str(i.get("name","")).startswith("zz-journey")]:
    r = call("DELETE", "/api/token/%s" % it.get("id"), headers=AH)
    print("     delete token %s -> %s" % (it.get("id"), r.get("success")))
code, d = call("DELETE", "/api/user/%s" % (u or {}).get("id"), headers=AH)
print("     delete user -> %s" % d.get("success"))
code, d = call("GET", "/api/channel/?p=0&size=100", headers=AH)
for it in [i for i in (items_of(d) or [])
           if isinstance(i, dict) and str(i.get("name","")).startswith("zz-journey")]:
    r = call("DELETE", "/api/channel/%s" % it.get("id"), headers=AH)
    print("     delete channel %s -> %s" % (it.get("id"), r.get("success")))
code, d = call("GET", "/api/user/?p=0&size=50", headers=AH)
print("     users remaining: %s" % [i.get("username") for i in (items_of(d) or [])
      if isinstance(i, dict)])
code, d = call("GET", "/api/token/?p=0&size=100", headers=AH)
live = [i.get("name") for i in (items_of(d) or []) if isinstance(i, dict)]
print("     live tokens remaining: %s" % (live or "none"))
AFTEREOF

echo "=== part 1: settings and console labels (read-only) ==="
python3 /tmp/settings.py

echo "=== part 2: rehearse the operator and user journey ==="
setsid nohup python3 /tmp/mock_upstream.py "$BRIDGE" 8323 >/tmp/mock.log 2>&1 < /dev/null &
echo $! > /tmp/mock.pid
sleep 2
ss -tln | grep -q 8323 && echo "  mock provider listening" || { echo "MOCK FAILED"; exit 1; }

python3 /tmp/journey.py "http://$BRIDGE:8323"

if [ ! -s /tmp/journey-key ]; then
  echo "  no user key produced; ending here"
  python3 /tmp/after.py
  exit 0
fi

echo "=== part 3: the routing-index reload the operator must run ==="
/usr/local/bin/lamtools-api-reload 2>&1 | tail -1
for i in $(seq 1 40); do
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:3000/api/status || true)
  [ "$c" = "200" ] && { echo "  gateway back after $((i*2))s"; break; }
  sleep 2
done
sleep 5

echo "=== part 4: the user calls with their own key ==="
KEY=$(cat /tmp/journey-key)
printf '  user key length: %s
' "${#KEY}"
printf '  chat completion -> '
curl -s -o /tmp/jc.json -w '%{http_code}
' -m 60 $RES   -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json'   -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}],"stream":false}'   "https://$PUB/v1/chat/completions"
python3 -c "
import json
d = json.load(open('/tmp/jc.json'))
if d.get('error'):
    print('    error:', str(d['error'])[:160])
else:
    print('    reply:', ((d.get('choices') or [{}])[0].get('message') or {}).get('content'))
"
printf '  streaming -> '
curl -s -N -m 60 $RES -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json'   -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}],"stream":true}'   "https://$PUB/v1/chat/completions" -o /tmp/js.txt -w '%{http_code}
'
python3 -c "
raw = open('/tmp/js.txt', encoding='utf-8', errors='replace').read()
print('    sse frames:', len([l for l in raw.splitlines() if l.startswith('data:')]),
      '| [DONE]:', 'data: [DONE]' in raw)
"

echo "=== part 5: accounting and cleanup ==="
python3 /tmp/after.py
kill "$(cat /tmp/mock.pid)" 2>/dev/null && echo "  mock provider stopped"
echo "=== done ==="
