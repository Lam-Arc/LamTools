"""Characterise the credit staleness: does a purchase take effect immediately,
after a delay, or only after the gateway restarts?
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cloud import command  # noqa: E402

MOCK = r'''import json, sys
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
                                 "message": {"role": "assistant", "content": "paid ok"},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 1000,
                              "total_tokens": 2000}})


ThreadingHTTPServer((sys.argv[1], int(sys.argv[2])), H).serve_forever()
'''

STEP = r'''
import http.cookiejar, json, os, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, '/tmp/pay')
from lib import *  # noqa

USER = "zzstal1"
PW = "Zz" + os.urandom(9).hex()
throttle_clear()
AH = admin_headers()

code, d = call("POST", "/api/channel/", {"mode": "single", "channel": {
    "name": "zzstal-channel", "type": 1, "key": "sk-mock-upstream", "base_url": sys.argv[1],
    "models": "gpt-4o-mini", "group": "default", "status": 1, "weight": 1, "priority": 0}}, AH)
print("  channel added:", d.get("success"))

code, d = call("POST", "/api/user/", {"username": USER, "password": PW,
                                     "display_name": "staleness probe", "role": 1,
                                     "group": "default"}, AH)
print("  customer created:", d.get("success"))
code, d = call("GET", "/api/user/?p=0&size=200", headers=AH)
u = next((i for i in (items_of(d) or []) if isinstance(i, dict)
          and i.get("username") == USER), None)
print("  customer id:", u and u.get("id"), "| credit:", u and u.get("quota"))
open("/tmp/pay/uid", "w").write(str(u and u.get("id")))
open("/tmp/pay/user-pw", "w").write(PW)

UOP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
code, d = call("POST", "/api/user/login", {"username": USER, "password": PW}, opener=UOP)
uid = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
UH = {"New-Api-User": str(uid)}
code, d = call("POST", "/api/token/", {"name": "zzstal-key", "remain_quota": 0,
                                      "expired_time": -1, "unlimited_quota": True,
                                      "model_limits_enabled": False, "group": "default",
                                      "status": 1}, UH, opener=UOP)
code, d = call("GET", "/api/token/?p=0&size=20", headers=UH, opener=UOP)
tk = next((i for i in (items_of(d) or []) if isinstance(i, dict)
           and i.get("name") == "zzstal-key"), None)
KEY = ""
if tk:
    cand = tk.get("key") or ""
    if not cand or "*" in cand:
        code, d2 = call("POST", "/api/token/%s/key" % tk.get("id"), {}, UH, opener=UOP)
        c = (d2.get("data") or {})
        cand = c.get("key") if isinstance(c, dict) else c
    if cand:
        KEY = cand if cand.startswith("sk-") else "sk-" + cand
if KEY:
    open("/tmp/pay/key", "w").write(KEY)
print("  key minted:", bool(KEY))

exp = int(time.time()) + 30 * 86400
code, d = call("POST", "/api/redemption/", {"name": "zzstal-code", "quota": 1000000,
                                           "count": 1, "expired_time": exp}, AH)
code, d = call("GET", "/api/redemption/?p=0&size=20", headers=AH)
rc = next((i for i in (items_of(d) or []) if isinstance(i, dict)
           and i.get("name") == "zzstal-code"), None)
open("/tmp/pay/code", "w").write((rc or {}).get("key") or "")
print("  voucher ready:", bool(rc))
'''

REDEEM = r'''
import http.cookiejar, json, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, '/tmp/pay')
from lib import *  # noqa
USER = "zzstal1"
PW = open("/tmp/pay/user-pw").read().strip()
CODE = open("/tmp/pay/code").read().strip()
UOP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
code, d = call("POST", "/api/user/login", {"username": USER, "password": PW}, opener=UOP)
uid = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
UH = {"New-Api-User": str(uid)}
code, d = call("POST", "/api/user/topup", {"key": CODE}, UH, opener=UOP)
print("  redeemed -> success=%s" % d.get("success"))
print("  credit in database:", sql("select quota from users where username='%s'" % USER))
print("  credit as the API reports it to the customer:")
code, d = call("GET", "/api/user/self", headers=UH, opener=UOP)
self_data = d.get("data") or {}
print("   ", {k: self_data.get(k) for k in ("quota", "used_quota", "group") if k in self_data})
'''

CLEANUP = r'''
import http.cookiejar, json, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, '/tmp/pay')
from lib import *  # noqa
throttle_clear()
AH = admin_headers()
code, d = call("GET", "/api/redemption/?p=0&size=50", headers=AH)
for c in [x for x in (items_of(d) or []) if isinstance(x, dict)
          and str(x.get("name", "")).startswith("zzstal")]:
    call("DELETE", "/api/redemption/%s" % c.get("id"), headers=AH)
    print("  removed voucher %s" % c.get("id"))
code, d = call("GET", "/api/channel/?p=0&size=100", headers=AH)
for c in [x for x in (items_of(d) or []) if isinstance(x, dict)
          and str(x.get("name", "")).startswith("zzstal")]:
    call("DELETE", "/api/channel/%s" % c.get("id"), headers=AH)
    print("  removed channel %s" % c.get("id"))
code, d = call("GET", "/api/user/?p=0&size=200", headers=AH)
for u in [x for x in (items_of(d) or []) if isinstance(x, dict)
          and str(x.get("username", "")).startswith("zzstal")]:
    call("DELETE", "/api/user/%s" % u.get("id"), headers=AH)
    print("  removed customer %s" % u.get("id"))
print("  leftover tokens:", sql("delete from tokens where name like 'zzstal%' returning name"))
print("  final: users=%s | channels=%s | live tokens=%s" % (
    sql("select string_agg(username, ',') from users where deleted_at is null"),
    sql("select count(*) from channels"),
    sql("select coalesce(string_agg(name, ','), 'none') from tokens where deleted_at is null")))
'''

SCRIPT = (
    r"""set -u
PUB=api.47.114.43.99.nip.io
RES="--resolve $PUB:443:127.0.0.1"
BRIDGE=$(ip -o -4 addr show | awk '$4 ~ /^172\.30\.0\./ {print $4}' | cut -d/ -f1 | head -1)
echo "  bridge gateway: $BRIDGE"

cat > /tmp/pay/mock.py <<'MOCKEOF'
"""
    + MOCK
    + """MOCKEOF
cat > /tmp/pay/step.py <<'STEPEOF'
"""
    + STEP
    + """STEPEOF
cat > /tmp/pay/redeem.py <<'REDEOF'
"""
    + REDEEM
    + """REDEOF
cat > /tmp/pay/cleanup.py <<'CLEOF'
"""
    + CLEANUP
    + """CLEOF

setsid nohup python3 /tmp/pay/mock.py "$BRIDGE" 8323 >/tmp/pay/mock.log 2>&1 < /dev/null &
echo $! > /tmp/pay/mock.pid
sleep 2
ss -tln | grep -q 8323 && echo "  mock provider listening" || echo "  MOCK FAILED"

echo "=== set up channel, customer, key, voucher ==="
python3 /tmp/pay/step.py "http://$BRIDGE:8323"

echo "=== make the channel routable first, so this test isolates credit ==="
/usr/local/bin/lamtools-api-reload >/dev/null 2>&1
for i in $(seq 1 40); do
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:3000/api/status || true)
  [ "$c" = "200" ] && break
  sleep 2
done
sleep 5

KEY=$(cat /tmp/pay/key)
callit() { # label
  printf '  %-34s -> ' "$1"
  curl -s -o /tmp/pay/r.json -w '%{http_code}' -m 45 $RES \
    -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
    -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}],"stream":false}' \
    "https://$PUB/v1/chat/completions"
  python3 -c "
import json
d = json.load(open('/tmp/pay/r.json'))
if d.get('error'):
    print(' |', str(d['error'].get('message'))[:70])
else:
    print(' |', ((d.get('choices') or [{}])[0].get('message') or {}).get('content'))
"
}

echo "=== 1. before purchase (expect refusal) ==="
callit "unpaid"

echo "=== 2. purchase, then call straight away ==="
python3 /tmp/pay/redeem.py
callit "immediately after purchase"

echo "=== 3. wait 70s and call again (is it a timed cache?) ==="
sleep 70
callit "70s after purchase"

echo "=== 4. restart the gateway, then call (in-process cache?) ==="
/usr/local/bin/lamtools-api-reload >/dev/null 2>&1
for i in $(seq 1 40); do
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:3000/api/status || true)
  [ "$c" = "200" ] && break
  sleep 2
done
sleep 6
callit "after gateway restart"

echo "=== cleanup ==="
python3 /tmp/pay/cleanup.py
[ -f /tmp/pay/mock.pid ] && kill "$(cat /tmp/pay/mock.pid)" 2>/dev/null && echo "  mock provider stopped"
rm -f /tmp/pay/key /tmp/pay/code /tmp/pay/user-pw /tmp/pay/uid
echo "=== done ==="
"""
)

if __name__ == "__main__":
    command(
        "credit-staleness",
        "Characterise how quickly a purchased credit becomes usable: immediately, after a delay, or after a gateway restart",
        SCRIPT,
        timeout=900,
    )
