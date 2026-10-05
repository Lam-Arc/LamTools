"""Confirm the cache-refresh rule and tighten the interval so purchases are
usable within seconds instead of a minute.
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
                                 "message": {"role": "assistant", "content": "cache ok"},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 1000,
                              "total_tokens": 2000}})


ThreadingHTTPServer((sys.argv[1], int(sys.argv[2])), H).serve_forever()
'''

P1 = r'''
import http.cookiejar, json, os, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, '/tmp/pay')
from lib import *  # noqa
throttle_clear()
AH = admin_headers()
code, d = call("POST", "/api/channel/", {"mode": "single", "channel": {
    "name": "zzfast-ch1", "type": 1, "key": "sk-mock-upstream", "base_url": sys.argv[1],
    "models": "gpt-4o-mini", "group": "default", "status": 1, "weight": 1, "priority": 0}}, AH)
print("  channel zzfast-ch1 added:", d.get("success"))
code, d = call("POST", "/api/token/", {"name": "zzfast-root", "remain_quota": 0,
                                      "expired_time": -1, "unlimited_quota": True,
                                      "model_limits_enabled": False, "group": "default",
                                      "status": 1}, AH)
code, d = call("GET", "/api/token/?p=0&size=50", headers=AH)
tk = next((i for i in (items_of(d) or []) if isinstance(i, dict)
           and i.get("name") == "zzfast-root"), None)
KEY = ""
if tk:
    KEY = tk.get("key") or ""
    if not KEY or "*" in KEY:
        code, d2 = call("POST", "/api/token/%s/key" % tk.get("id"), {}, AH)
        c = (d2.get("data") or {})
        KEY = c.get("key") if isinstance(c, dict) else c
    if KEY and not KEY.startswith("sk-"):
        KEY = "sk-" + KEY
open("/tmp/pay/key1", "w").write(KEY or "")
print("  operator key ready:", bool(KEY))
'''

DELCH = r'''
import http.cookiejar, json, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, '/tmp/pay')
from lib import *  # noqa
throttle_clear()
AH = admin_headers()
code, d = call("GET", "/api/channel/?p=0&size=100", headers=AH)
for c in [x for x in (items_of(d) or []) if isinstance(x, dict)
          and str(x.get("name", "")).startswith("zzfast")]:
    call("DELETE", "/api/channel/%s" % c.get("id"), headers=AH)
    print("  removed channel %s" % c.get("id"))
print("  channels left:", sql("select count(*) from channels"))
'''

P2 = r'''
import http.cookiejar, json, os, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, '/tmp/pay')
from lib import *  # noqa
USER = "zzfast1"
PW = "Zz" + os.urandom(9).hex()
throttle_clear()
AH = admin_headers()
code, d = call("POST", "/api/channel/", {"mode": "single", "channel": {
    "name": "zzfast-ch2", "type": 1, "key": "sk-mock-upstream", "base_url": sys.argv[1],
    "models": "gpt-4o-mini", "group": "default", "status": 1, "weight": 1, "priority": 0}}, AH)
print("  channel zzfast-ch2 added (gateway already running):", d.get("success"))
code, d = call("POST", "/api/user/", {"username": USER, "password": PW,
                                     "display_name": "fast probe", "role": 1,
                                     "group": "default"}, AH)
print("  customer created:", d.get("success"))
UOP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
code, d = call("POST", "/api/user/login", {"username": USER, "password": PW}, opener=UOP)
uid = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
UH = {"New-Api-User": str(uid)}
code, d = call("POST", "/api/token/", {"name": "zzfast-key", "remain_quota": 0,
                                      "expired_time": -1, "unlimited_quota": True,
                                      "model_limits_enabled": False, "group": "default",
                                      "status": 1}, UH, opener=UOP)
code, d = call("GET", "/api/token/?p=0&size=20", headers=UH, opener=UOP)
tk = next((i for i in (items_of(d) or []) if isinstance(i, dict)
           and i.get("name") == "zzfast-key"), None)
KEY = ""
if tk:
    KEY = tk.get("key") or ""
    if not KEY or "*" in KEY:
        code, d2 = call("POST", "/api/token/%s/key" % tk.get("id"), {}, UH, opener=UOP)
        c = (d2.get("data") or {})
        KEY = c.get("key") if isinstance(c, dict) else c
    if KEY and not KEY.startswith("sk-"):
        KEY = "sk-" + KEY
open("/tmp/pay/key2", "w").write(KEY or "")
exp = int(time.time()) + 30 * 86400
code, d = call("POST", "/api/redemption/", {"name": "zzfast-code", "quota": 1000000,
                                           "count": 1, "expired_time": exp}, AH)
code, d = call("GET", "/api/redemption/?p=0&size=20", headers=AH)
rc = next((i for i in (items_of(d) or []) if isinstance(i, dict)
           and i.get("name") == "zzfast-code"), None)
code, d = call("POST", "/api/user/topup", {"key": (rc or {}).get("key") or ""}, UH, opener=UOP)
print("  customer purchased credit -> success=%s" % d.get("success"))
print("  credit:", sql("select quota from users where username='%s'" % USER))
'''

CLEANUP = r'''
import http.cookiejar, json, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, '/tmp/pay')
from lib import *  # noqa
throttle_clear()
AH = admin_headers()
for label in ("redemption", "channel", "user"):
    code, d = call("GET", "/api/%s/?p=0&size=200" % label, headers=AH)
    field = "username" if label == "user" else "name"
    for x in [i for i in (items_of(d) or []) if isinstance(i, dict)
              and str(i.get(field, "")).startswith("zzfast")]:
        call("DELETE", "/api/%s/%s" % (label, x.get("id")), headers=AH)
        print("    removed %s %s" % (label, x.get("id")))
code, d = call("GET", "/api/token/?p=0&size=200", headers=AH)
for t in [i for i in (items_of(d) or []) if isinstance(i, dict)
          and str(i.get("name", "")).startswith("zzfast")]:
    call("DELETE", "/api/token/%s" % t.get("id"), headers=AH)
print("  leftovers:", sql("delete from tokens where name like 'zzfast%' returning name"))
print("  final: users=%s | channels=%s | vouchers=%s | live tokens=%s" % (
    sql("select string_agg(username, ',') from users where deleted_at is null"),
    sql("select count(*) from channels"),
    sql("select coalesce(string_agg(name, ','), 'none') from redemptions where deleted_at is null"),
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
for stage in p1 delch p2 cleanup; do :; done
cat > /tmp/pay/p1.py <<'P1EOF'
"""
    + P1
    + """P1EOF
cat > /tmp/pay/delch.py <<'DEOF'
"""
    + DELCH
    + """DEOF
cat > /tmp/pay/p2.py <<'P2EOF'
"""
    + P2
    + """P2EOF
cat > /tmp/pay/cleanup.py <<'CLEOF'
"""
    + CLEANUP
    + """CLEOF

setsid nohup python3 /tmp/pay/mock.py "$BRIDGE" 8323 >/tmp/pay/mock.log 2>&1 < /dev/null &
echo $! > /tmp/pay/mock.pid
sleep 2
ss -tln | grep -q 8323 && echo "  mock provider listening" || echo "  MOCK FAILED"

callit() { # label keyfile
  printf '  %-38s -> ' "$1"
  curl -s -o /tmp/pay/r.json -w '%{http_code}' -m 45 $RES \
    -H "Authorization: Bearer $(cat "$2")" -H 'Content-Type: application/json' \
    -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}],"stream":false}' \
    "https://$PUB/v1/chat/completions"
  python3 -c "
import json
d = json.load(open('/tmp/pay/r.json'))
if d.get('error'):
    print(' |', str(d['error'].get('message'))[:60])
else:
    print(' |', ((d.get('choices') or [{}])[0].get('message') or {}).get('content'))
"
}

echo "=== phase 1: default sync interval (restart removed from the picture) ==="
python3 /tmp/pay/p1.py "http://$BRIDGE:8323"
callit "channel just added" /tmp/pay/key1
sleep 70
callit "70s later, no restart at all" /tmp/pay/key1

echo "=== phase 2: shorten the cache refresh interval to 5s ==="
python3 /tmp/pay/delch.py
cp -p /opt/lamtools-api/docker-compose.yml /opt/lamtools-api/docker-compose.yml.before-syncfreq-$(date -u +%Y%m%dT%H%M%SZ)
if grep -q 'SYNC_FREQUENCY' /opt/lamtools-api/docker-compose.yml; then
  sed -i "s/SYNC_FREQUENCY: .*/SYNC_FREQUENCY: \"5\"/" /opt/lamtools-api/docker-compose.yml
else
  sed -i "/^      NODE_TYPE: master$/i\\      SYNC_FREQUENCY: \"5\"" /opt/lamtools-api/docker-compose.yml
fi
grep -n 'SYNC_FREQUENCY\|NODE_TYPE' /opt/lamtools-api/docker-compose.yml | sed 's/^/  /'
docker compose -f /opt/lamtools-api/docker-compose.yml up -d gateway 2>&1 | tail -3
for i in $(seq 1 40); do
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:3000/api/status || true)
  [ "$c" = "200" ] && { echo "  gateway back after $((i*2))s"; break; }
  sleep 2
done
sleep 4

echo "=== phase 3: with the shorter interval, channel and purchase within ~15s ==="
python3 /tmp/pay/p2.py "http://$BRIDGE:8323"
sleep 15
callit "channel+credit live 15s after setup" /tmp/pay/key2

echo "=== cleanup ==="
python3 /tmp/pay/cleanup.py
[ -f /tmp/pay/mock.pid ] && kill "$(cat /tmp/pay/mock.pid)" 2>/dev/null && echo "  mock provider stopped"
rm -f /tmp/pay/key1 /tmp/pay/key2
echo "=== done ==="
"""
)

if __name__ == "__main__":
    command(
        "sync-interval",
        "Confirm the cache-refresh rule, shorten the interval to five seconds and verify channel and credit freshness",
        SCRIPT,
        timeout=900,
    )
