set -u
PUB=api.47.114.43.99.nip.io
RES="--resolve $PUB:443:127.0.0.1"
BRIDGE=$(ip -o -4 addr show | awk '$4 ~ /^172\.30\.0\./ {print $4}' | cut -d/ -f1 | head -1)
echo "  bridge gateway: $BRIDGE"

cat > /tmp/pay/mock.py <<'MOCKEOF'
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
                                 "message": {"role": "assistant", "content": "paid station ok"},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 1000,
                              "total_tokens": 2000}})


ThreadingHTTPServer((sys.argv[1], int(sys.argv[2])), H).serve_forever()
MOCKEOF
cat > /tmp/pay/step.py <<'STEPEOF'

import http.cookiejar, json, os, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, '/tmp/pay')
from lib import *  # noqa

USER = "zzpay1"
PW = open("/tmp/pay/user-pw").read().strip()
UOP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

throttle_clear()
AH = admin_headers()

# operator: provider channel
code, d = call("POST", "/api/channel/", {"mode": "single", "channel": {
    "name": "zzpay-channel", "type": 1, "key": "sk-mock-upstream", "base_url": sys.argv[1],
    "models": "gpt-4o-mini", "group": "default", "status": 1, "weight": 1, "priority": 0}}, AH)
print("  provider channel added:", d.get("success"))

# customer: sign in and mint a key before paying anything
code, d = call("POST", "/api/user/login", {"username": USER, "password": PW}, opener=UOP)
uid = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
print("  customer signs in:", d.get("success"), "| id:", uid)
UH = {"New-Api-User": str(uid)}
code, d = call("POST", "/api/token/", {"name": "zzpay-key", "remain_quota": 0,
                                      "expired_time": -1, "unlimited_quota": True,
                                      "model_limits_enabled": False, "group": "default",
                                      "status": 1}, UH, opener=UOP)
code, d = call("GET", "/api/token/?p=0&size=20", headers=UH, opener=UOP)
tk = next((i for i in (items_of(d) or []) if isinstance(i, dict)
           and i.get("name") == "zzpay-key"), None)
KEY = ""
if tk:
    cand = tk.get("key") or ""
    if not cand or "*" in cand:
        code, d2 = call("POST", "/api/token/%s/key" % tk.get("id"), {}, UH, opener=UOP)
        c = (d2.get("data") or {})
        cand = c.get("key") if isinstance(c, dict) else c
    if cand:
        KEY = cand if cand.startswith("sk-") else "sk-" + cand
print("  key minted before any payment:", bool(KEY))
if KEY:
    open("/tmp/pay/key", "w").write(KEY)

# operator: sell credit as a redemption code
exp = int(time.time()) + 30 * 86400
code, d = call("POST", "/api/redemption/", {"name": "zzpay-code", "quota": 1000000,
                                           "count": 1, "expired_time": exp}, AH)
print("  credit voucher created (worth 1000000 = US$2):", d.get("success"))
code, d = call("GET", "/api/redemption/?p=0&size=20", headers=AH)
rc = next((i for i in (items_of(d) or []) if isinstance(i, dict)
           and i.get("name") == "zzpay-code"), None)
if rc:
    open("/tmp/pay/code", "w").write(rc.get("key") or "")
    print("    voucher id=%s" % rc.get("id"))

print("  customer credit before paying:", sql("select quota from users where username='%s'" % USER))
STEPEOF
cat > /tmp/pay/redeem.py <<'REDEOF'

import http.cookiejar, json, os, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, '/tmp/pay')
from lib import *  # noqa

USER = "zzpay1"
PW = open("/tmp/pay/user-pw").read().strip()
CODE = open("/tmp/pay/code").read().strip()
UOP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
code, d = call("POST", "/api/user/login", {"username": USER, "password": PW}, opener=UOP)
uid = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
UH = {"New-Api-User": str(uid)}
print("  credit before redeeming:", sql("select quota from users where username='%s'" % USER))
code, d = call("POST", "/api/user/topup", {"key": CODE}, UH, opener=UOP)
print("  customer redeems the purchased voucher -> success=%s msg=%s"
      % (d.get("success"), str(d.get("message"))[:60]))
print("  credit after redeeming:", sql("select quota from users where username='%s'" % USER))
REDEOF
cat > /tmp/pay/after.py <<'AFTEREOF'

import http.cookiejar, json, os, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, '/tmp/pay')
from lib import *  # noqa

USER = "zzpay1"
print("  metering: user quota / used / requests")
print("   ", sql("select 'quota=' || quota || ' used=' || used_quota || ' reqs=' || request_count"
                  " from users where username='%s'" % USER))
print("  call log (what the operator can see per request):")
print("   ", sql("select coalesce(string_agg(model_name || ' tokens=' || coalesce(prompt_tokens+completion_tokens,0)"
                  " || ' quota=' || quota, ' | '), 'none') from logs"))
throttle_clear()
AH = admin_headers()
print("  cleanup")
code, d = call("GET", "/api/redemption/?p=0&size=50", headers=AH)
for c in [x for x in (items_of(d) or []) if isinstance(x, dict)
          and str(x.get("name", "")).startswith("zzpay")]:
    call("DELETE", "/api/redemption/%s" % c.get("id"), headers=AH)
    print("    removed voucher %s" % c.get("id"))
code, d = call("GET", "/api/channel/?p=0&size=100", headers=AH)
for c in [x for x in (items_of(d) or []) if isinstance(x, dict)
          and str(x.get("name", "")).startswith("zzpay")]:
    call("DELETE", "/api/channel/%s" % c.get("id"), headers=AH)
    print("    removed provider channel %s" % c.get("id"))
code, d = call("GET", "/api/user/?p=0&size=200", headers=AH)
for u in [x for x in (items_of(d) or []) if isinstance(x, dict)
          and str(x.get("username", "")).startswith("zzpay")]:
    call("DELETE", "/api/user/%s" % u.get("id"), headers=AH)
    print("    removed customer %s (%s)" % (u.get("id"), u.get("username")))
print("  leftover token rows:", sql("delete from tokens where name like 'zzpay%' returning name"))
print("  final: users=%s | live tokens=%s | channels=%s | vouchers=%s" % (
    sql("select string_agg(username, ',') from users where deleted_at is null"),
    sql("select coalesce(string_agg(name, ','), 'none') from tokens where deleted_at is null"),
    sql("select count(*) from channels"),
    sql("select coalesce(string_agg(name, ','), 'none') from redemptions where deleted_at is null")))
print("  registration state:", sql("select string_agg(key || '=' || value, ', ') from"
                                   " (select key, value from options where key ~ 'Register'"
                                   " order by key) t"))
AFTEREOF

echo "=== set up: provider channel, unpaid customer, voucher ==="
setsid nohup python3 /tmp/pay/mock.py "$BRIDGE" 8323 >/tmp/pay/mock.log 2>&1 < /dev/null &
echo $! > /tmp/pay/mock.pid
sleep 2
ss -tln | grep -q 8323 && echo "  mock provider listening" || { echo "MOCK FAILED"; cat /tmp/pay/mock.log; }
python3 /tmp/pay/step.py "http://$BRIDGE:8323"

echo "=== reload so the channel is routable ==="
/usr/local/bin/lamtools-api-reload >/dev/null 2>&1
for i in $(seq 1 40); do
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:3000/api/status || true)
  [ "$c" = "200" ] && break
  sleep 2
done
sleep 5

if [ -s /tmp/pay/key ]; then
  KEY=$(cat /tmp/pay/key)
  echo "=== before paying: must be refused ==="
  printf '  call with the customer key -> '
  curl -s -o /tmp/pay/r1.json -w '%{http_code}
' -m 45 $RES     -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json'     -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}],"stream":false}'     "https://$PUB/v1/chat/completions"
  python3 -c "
import json
d = json.load(open('/tmp/pay/r1.json'))
print('    ', str(d.get('error') or d.get('choices'))[:150])
"
fi

echo "=== customer pays: redeems the voucher ==="
python3 /tmp/pay/redeem.py

if [ -s /tmp/pay/key ]; then
  KEY=$(cat /tmp/pay/key)
  echo "=== after paying: must work ==="
  printf '  call with the customer key -> '
  curl -s -o /tmp/pay/r2.json -w '%{http_code}
' -m 45 $RES     -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json'     -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}],"stream":false}'     "https://$PUB/v1/chat/completions"
  python3 -c "
import json
d = json.load(open('/tmp/pay/r2.json'))
if d.get('error'):
    print('    error:', str(d['error'])[:150])
else:
    print('    reply:', ((d.get('choices') or [{}])[0].get('message') or {}).get('content'))
"
  printf '  second call (metering) -> '
  curl -s -o /dev/null -w '%{http_code}
' -m 45 $RES     -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json'     -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"again"}],"stream":false}'     "https://$PUB/v1/chat/completions"
fi

echo "=== metering, call log, cleanup ==="
python3 /tmp/pay/after.py
[ -f /tmp/pay/mock.pid ] && kill "$(cat /tmp/pay/mock.pid)" 2>/dev/null && echo "  mock provider stopped"
rm -f /tmp/pay/key /tmp/pay/code /tmp/pay/user-pw
echo "=== done ==="
