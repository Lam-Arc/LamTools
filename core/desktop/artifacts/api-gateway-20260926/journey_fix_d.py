"""Prove the redemption-code path, then remove every rehearsal artefact."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cloud import command  # noqa: E402

LIB = r'''import http.cookiejar, json, os, subprocess, time, urllib.error, urllib.request

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


def throttle_clear():
    pw = subprocess.run(["sed", "-n", "s/^REDIS_PASSWORD=//p", "/opt/lamtools-api/.env"],
                        capture_output=True, text=True).stdout.strip()
    if not pw:
        return
    keys = subprocess.run(["docker", "exec", "lamtools-api-cache", "redis-cli",
                           "--no-auth-warning", "-a", pw, "--scan", "--pattern",
                           "rateLimit*"], capture_output=True, text=True).stdout.split()
    for k in keys:
        subprocess.run(["docker", "exec", "lamtools-api-cache", "redis-cli",
                        "--no-auth-warning", "-a", pw, "DEL", k], capture_output=True)


def admin_headers():
    uid = None
    for attempt in range(6):
        code, d = call("POST", "/api/user/login", {"username": "root", "password": pw_read()})
        uid = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
        if uid:
            break
        throttle_clear()
        time.sleep(10)
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
'''

SCRIPT = (
    r"""set -u
mkdir -p /tmp/jr
cat > /tmp/jr/lib.py <<'LIBEOF'
"""
    + LIB
    + """LIBEOF

cat > /tmp/jr/redeem.py <<'REOF'
import http.cookiejar, json, os, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, '/tmp/jr')
from lib import *  # noqa

throttle_clear()
AH = admin_headers()
USER = "zzfin1"
PW = "Zz" + os.urandom(9).hex()

code, d = call("POST", "/api/user/", {"username": USER, "password": PW,
                                     "display_name": "final check", "role": 1,
                                     "group": "default"}, AH)
print("  created %s -> http %s success=%s" % (USER, code, d.get("success")))
print("    starts at quota:", sql("select quota from users where username='%s'" % USER))

exp = int(time.time()) + 7 * 86400
code, d = call("POST", "/api/redemption/", {"name": "zzfin-code", "quota": 1000000,
                                           "count": 1, "expired_time": exp}, AH)
print("  created a redemption code worth 1000000 -> http %s success=%s msg=%s"
      % (code, d.get("success"), str(d.get("message"))[:60]))
code, d = call("GET", "/api/redemption/?p=0&size=20", headers=AH)
codes = [c for c in (items_of(d) or []) if isinstance(c, dict)
         and str(c.get("name", "")).startswith("zz")]
RC = codes[0] if codes else None
print("    codes on record:", len(codes), "| code id:", RC and RC.get("id"))

if RC and RC.get("key"):
    UOP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    code, d = call("POST", "/api/user/login", {"username": USER, "password": PW}, opener=UOP)
    uid = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
    print("  user signs in:", d.get("success"), "| id:", uid)
    print("    quota before redeeming:", sql("select quota from users where username='%s'" % USER))
    code, d = call("POST", "/api/user/topup", {"key": RC.get("key")}, {"New-Api-User": str(uid)},
                   opener=UOP)
    print("  user redeems the code -> http %s success=%s msg=%s"
          % (code, d.get("success"), str(d.get("message"))[:60]))
    print("    quota after redeeming:", sql("select quota from users where username='%s'" % USER))

    # with quota in place, the user's own key must now route
    code, d = call("POST", "/api/token/", {"name": "zzfin-key", "remain_quota": 0,
                                          "expired_time": -1, "unlimited_quota": True,
                                          "model_limits_enabled": False, "group": "default",
                                          "status": 1}, {"New-Api-User": str(uid)}, opener=UOP)
    code, d = call("GET", "/api/token/?p=0&size=20", headers={"New-Api-User": str(uid)}, opener=UOP)
    tk = next((i for i in (items_of(d) or []) if isinstance(i, dict)
               and i.get("name") == "zzfin-key"), None)
    if tk:
        key = tk.get("key") or ""
        if not key or "*" in key:
            code, d2 = call("POST", "/api/token/%s/key" % tk.get("id"), {},
                            {"New-Api-User": str(uid)}, opener=UOP)
            cand = (d2.get("data") or {})
            key = cand.get("key") if isinstance(cand, dict) else cand
        if key:
            if not key.startswith("sk-"):
                key = "sk-" + key
            open("/tmp/zzfin-key", "w").write(key)
            print("  key minted by the funded user: length %d" % len(key))
REOF
python3 /tmp/jr/redeem.py

if [ -s /tmp/zzfin-key ]; then
  echo "=== the funded user calls through the gateway ==="
  KEY=$(cat /tmp/zzfin-key)
  RES="--resolve api.47.114.43.99.nip.io:443:127.0.0.1"
  printf '  chat completion -> '
  curl -s -o /tmp/jr/resp.json -w '%{http_code}\n' -m 60 $RES \
    -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
    -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}],"stream":false}' \
    "https://api.47.114.43.99.nip.io/v1/chat/completions"
  python3 -c "
import json
d = json.load(open('/tmp/jr/resp.json'))
if d.get('error'):
    print('    error:', str(d['error'])[:160])
else:
    print('    reply:', ((d.get('choices') or [{}])[0].get('message') or {}).get('content'))
"
fi

echo "=== final cleanup and state ==="
cat > /tmp/jr/final.py <<'FEOF'
import http.cookiejar, json, os, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, '/tmp/jr')
from lib import *  # noqa

throttle_clear()
AH = admin_headers()
code, d = call("GET", "/api/redemption/?p=0&size=50", headers=AH)
for c in [x for x in (items_of(d) or []) if isinstance(x, dict)
          and str(x.get("name", "")).startswith("zz")]:
    r = call("DELETE", "/api/redemption/%s" % c.get("id"), headers=AH)[1]
    print("  delete redemption code %s" % c.get("id"))
code, d = call("GET", "/api/channel/?p=0&size=100", headers=AH)
for c in [x for x in (items_of(d) or []) if isinstance(x, dict)
          and str(x.get("name", "")).startswith("zz")]:
    r = call("DELETE", "/api/channel/%s" % c.get("id"), headers=AH)[1]
    print("  delete channel %s" % c.get("id"))
code, d = call("GET", "/api/user/?p=0&size=200", headers=AH)
for u in [x for x in (items_of(d) or []) if isinstance(x, dict)
          and str(x.get("username", "")).startswith("zz")]:
    call("DELETE", "/api/user/%s" % u.get("id"), headers=AH)
    print("  delete user %s (%s)" % (u.get("id"), u.get("username")))
print("  remove rehearsal token rows:", sql("delete from tokens where name like 'zz%' returning name"))
print("  FINAL users:", sql("select string_agg(username, ',') from users where deleted_at is null"))
print("  FINAL live tokens:", sql("select coalesce(string_agg(name, ','), 'none') from tokens where deleted_at is null"))
print("  FINAL channels:", sql("select count(*) from channels"))
print("  FINAL redemption codes:", sql("select coalesce(string_agg(name, ','), 'none') from redemptions where deleted_at is null"))
print("  credential file mode:", subprocess.run(["stat", "-c", "%a %U", "/opt/lamtools-api/admin-credentials.txt"], capture_output=True, text=True).stdout.strip())
FEOF
python3 /tmp/jr/final.py
rm -rf /tmp/jr /tmp/zzfin-key
echo "=== done ==="
"""
)

if __name__ == "__main__":
    command(
        "journey-d",
        "Prove the redemption-code path end to end, then remove every rehearsal artefact and report the final state",
        SCRIPT,
        timeout=800,
    )
