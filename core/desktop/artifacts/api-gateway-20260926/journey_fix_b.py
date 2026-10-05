"""Journey part B: grant quota correctly, verify both key variants, account, clean up."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cloud import command  # noqa: E402

LIB = r'''import http.cookiejar, json, subprocess, time, urllib.error, urllib.request

BASE = "http://127.0.0.1:3000"
OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def call(method, path, body=None, headers=None, opener=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        with (opener or OPENER).open(r, timeout=40) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def items_of(d):
    if not isinstance(d, dict):
        return []
    data = d.get("data")
    return data.get("items") if isinstance(data, dict) else data


def pw_read():
    for line in open("/opt/lamtools-api/admin-credentials.txt", encoding="utf-8"):
        if line.startswith("password :"):
            return line.split(":", 1)[1].strip()
    return ""


def admin_headers():
    uid = None
    for _ in range(8):
        code, d = call("POST", "/api/user/login", {"username": "root", "password": pw_read()})
        uid = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
        if uid:
            break
        time.sleep(12)
    if not uid:
        raise SystemExit("admin login failed")
    h = {"New-Api-User": str(uid)}
    code, d = call("GET", "/api/user/token", headers=h)
    t = d.get("data")
    t = (t.get("token") or t.get("access_token")) if isinstance(t, dict) else t
    if isinstance(t, str) and t:
        h["Authorization"] = "Bearer " + t
    return h


def sql(q):
    out = subprocess.run(["docker", "exec", "lamtools-api-db", "psql", "-U", "lamtools_api",
                          "-d", "lamtools_api", "-tAc", q], capture_output=True, text=True)
    return (out.stdout or out.stderr).strip()


def find_user(ah, name):
    code, d = call("GET", "/api/user/?p=0&size=200", headers=ah)
    rows = items_of(d) or []
    for row in rows:
        if isinstance(row, dict) and row.get("username") == name:
            return row
    return None


def purge(prefix):
    """Delete users, tokens and channels whose identifying name starts with prefix."""
    ah = admin_headers()
    for label in ("user", "token", "channel"):
        field = "username" if label == "user" else "name"
        code, d = call("GET", "/api/%s/?p=0&size=200" % label, headers=ah)
        targets = []
        for row in (items_of(d) or []):
            if isinstance(row, dict) and str(row.get(field, "")).startswith(prefix):
                targets.append(row)
        for row in targets:
            code, r = call("DELETE", "/api/%s/%s" % (label, row.get("id")), headers=ah)
            print("    delete %s %s (%s) -> http %s success=%s"
                  % (label, row.get("id"), row.get(field), code, r.get("success")))
    return ah
'''

SCRIPT = (
    r"""set -u
PUB=api.47.114.43.99.nip.io
RES="--resolve $PUB:443:127.0.0.1"

cat > /tmp/jr/lib.py <<'LIBEOF'
"""
    + LIB
    + """LIBEOF

cat > /tmp/jr/quota.py <<'QUOTAEOF'
import http.cookiejar, json, os, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, '/tmp/jr')
from lib import *  # noqa

AH = admin_headers()
USER = "zztest2"
u = find_user(AH, USER)
print("  target user id=%s quota now=%s" % (u and u.get("id"), u and u.get("quota")))

print("  attempt 1: POST /api/user/manage with quota")
body = {"id": u.get("id"), "action": "", "quota": 2000000, "group": "default"}
code, d = call("POST", "/api/user/manage", body, AH)
print("    http %s success=%s %s" % (code, d.get("success"), str(d.get("message"))[:70]))
print("    quota in database:", sql("select quota from users where username='%s'" % USER))

if sql("select quota from users where username='%s'" % USER) in ("", "0"):
    print("  attempt 2: POST /api/user/topup")
    code, d = call("POST", "/api/user/topup",
                   {"user_id": u.get("id"), "quota": 2000000, "remark": "journey"}, AH)
    print("    http %s success=%s %s" % (code, d.get("success"), str(d.get("message"))[:70]))
    print("    quota in database:", sql("select quota from users where username='%s'" % USER))

print("  operator-friendly path: give new users quota by default")
code, d = call("PUT", "/api/option/", {"key": "QuotaForNewUser", "value": "1000000"}, AH)
print("    set QuotaForNewUser -> http %s success=%s" % (code, d.get("success")))
print("    option now:", sql("select value from options where key='QuotaForNewUser'"))
code, d = call("POST", "/api/user/", {"username": "zznewuser", "password": "Zz" + os.urandom(9).hex(),
                                     "display_name": "default quota check", "role": 1,
                                     "group": "default"}, AH)
print("    create zznewuser -> http %s success=%s" % (code, d.get("success")))
print("    its quota:", sql("select quota from users where username='zznewuser'"))
QUOTAEOF
python3 /tmp/jr/quota.py

cat > /tmp/jr/call.py <<'CALLEOF'
import http.cookiejar, json, os, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, '/tmp/jr')
from lib import *  # noqa

PUB = "api.47.114.43.99.nip.io"
AH = admin_headers()
print("  quota before the calls:")
print("   ", sql("select 'user=' || username || ' quota=' || quota || ' used=' || used_quota"
                  " from users where username like 'zz%' order by id"))
CALLEOF
python3 /tmp/jr/call.py

echo "=== reload so the staged channel is routable ==="
/usr/local/bin/lamtools-api-reload >/dev/null 2>&1
for i in $(seq 1 40); do
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:3000/api/status || true)
  [ "$c" = "200" ] && break
  sleep 2
done
sleep 5

echo "=== call with each key the user made ==="
for k in zz-key-a zz-key-b; do
  if [ -s "/tmp/$k" ]; then
    KEY=$(cat "/tmp/$k")
    printf '  %-10s -> ' "$k"
    curl -s -o /tmp/jr/resp.json -w '%{http_code}\n' -m 60 $RES \
      -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
      -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}],"stream":false}' \
      "https://$PUB/v1/chat/completions"
    python3 -c "
import json
d = json.load(open('/tmp/jr/resp.json'))
if d.get('error'):
    print('      error:', str(d['error'])[:150])
else:
    print('      reply:', ((d.get('choices') or [{}])[0].get('message') or {}).get('content'))
"
  else
    echo "  $k: not staged"
  fi
done

cat > /tmp/jr/account.py <<'ACCTEOF'
import http.cookiejar, json, os, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, '/tmp/jr')
from lib import *  # noqa
print("  quota after the calls:")
print("   ", sql("select string_agg(username || ': quota=' || quota || ' used=' || used_quota"
                  " || ' reqs=' || request_count, ' | ' order by id) from users where username like 'zz%'"))
print("   ", sql("select coalesce(string_agg(name || ': remain=' || remain_quota"
                  " || ' unlimited=' || unlimited_quota || ' used=' || used_quota, ' | '), 'none')"
                  " from tokens where deleted_at is null and name like 'zz-key%'"))
ACCTEOF
python3 /tmp/jr/account.py

echo "=== cleanup ==="
cat > /tmp/jr/purge.py <<'PURGEEOF'
import http.cookiejar, json, os, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, '/tmp/jr')
from lib import *  # noqa
print("  restoring the default quota for new users")
AH = admin_headers()
code, d = call("PUT", "/api/option/", {"key": "QuotaForNewUser", "value": "0"}, AH)
print("    QuotaForNewUser back to:", sql("select value from options where key='QuotaForNewUser'"))
purge("zz")
print("  database state: users=%s tokens=%s channels=%s" % (
    sql("select count(*) from users where deleted_at is null"),
    sql("select count(*) from tokens where deleted_at is null"),
    sql("select count(*) from channels where deleted_at is null")))
print("  live usernames:", sql("select string_agg(username, ',') from users where deleted_at is null"))
print("  live tokens:", sql("select coalesce(string_agg(name, ','), 'none') from tokens where deleted_at is null"))
PURGEEOF
python3 /tmp/jr/purge.py

[ -f /tmp/jr/mock.pid ] && kill "$(cat /tmp/jr/mock.pid)" 2>/dev/null && echo "  mock provider stopped"
rm -f /tmp/zz-key-a /tmp/zz-key-b /tmp/journey-user-pw /tmp/journey-user-id
echo "=== done ==="
"""
)

if __name__ == "__main__":
    command(
        "journey-b",
        "Journey part B: grant quota correctly, verify both key variants end to end, account for usage and clean up",
        SCRIPT,
        timeout=900,
    )
