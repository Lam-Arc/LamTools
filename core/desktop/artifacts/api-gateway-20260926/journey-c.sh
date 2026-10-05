set -u
cat > /tmp/jr/lib.py <<'LIBEOF'
import http.cookiejar, json, os, subprocess, time, urllib.error, urllib.request

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
    for row in (items_of(d) or []):
        if isinstance(row, dict) and row.get("username") == name:
            return row
    return None
LIBEOF

cat > /tmp/jr/quota2.py <<'QEOF'
import http.cookiejar, json, os, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, '/tmp/jr')
from lib import *  # noqa

AH = admin_headers()
USER = "zzquota1"
code, d = call("POST", "/api/user/", {"username": USER, "password": "Zz" + os.urandom(9).hex(),
                                     "display_name": "quota probe", "role": 1,
                                     "group": "default"}, AH)
u = find_user(AH, USER)
uid = u.get("id")
print("  probe user id=%s starts at quota %s" % (uid, u.get("quota")))

def q():
    return sql("select quota from users where username='%s'" % USER)

trials = [
    ("POST", "/api/user/manage", {"id": uid, "action": "add_quota", "quota": 1000000}),
    ("POST", "/api/user/manage", {"id": uid, "quota": "1000000"}),
    ("PUT", "/api/user/", {"id": uid, "quota": 1000000}),
    ("POST", "/api/user/quota", {"id": uid, "quota": 1000000}),
]
for method, path, body in trials:
    code, d = call(method, path, body, AH)
    print("  %-6s %-20s -> http %s success=%s msg=%s | quota now=%s"
          % (method, path, code, d.get("success"), str(d.get("message"))[:45], q()))

# the console shows the upstream's own quota field; check what a redemption
# code round-trip does, which is the built-in mechanism for granting quota
print("  redemption-code route (the built-in way to hand somebody quota):")
code, d = call("POST", "/api/redemption/", {"name": "zz-code", "quota": 1000000,
                                           "count": 1, "expired_time": -1}, AH)
print("    create code -> http %s success=%s msg=%s" % (code, d.get("success"), str(d.get("message"))[:50]))
code, d = call("GET", "/api/redemption/?p=0&size=20", headers=AH)
codes = items_of(d) or []
print("    codes on record:", len(codes))
if codes:
    key = codes[0].get("key")
    UOP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    code, d = call("POST", "/api/user/login", {"username": USER, "password": "wrong"},
                   opener=UOP)
    # redeem using the probe user's own session
    pw = sql("select password from users where username='%s'" % USER)
    print("    (redemption needs the user's session; skipping live redeem)")

code, d = call("POST", "/api/user/logout", {}, AH)
codes = items_of(call("GET", "/api/redemption/?p=0&size=20", headers=AH)[1]) or []
for c in codes:
    if isinstance(c, dict) and str(c.get("name", "")).startswith("zz"):
        r = call("DELETE", "/api/redemption/%s" % c.get("id"), headers=AH)[1]
        print("    delete code %s -> success=%s" % (c.get("id"), r.get("success")))
QEOF
python3 /tmp/jr/quota2.py

echo "=== final cleanup ==="
cat > /tmp/jr/final.py <<'FEOF'
import http.cookiejar, json, os, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, '/tmp/jr')
from lib import *  # noqa
AH = admin_headers()
code, d = call("GET", "/api/user/?p=0&size=200", headers=AH)
for row in (items_of(d) or []):
    if isinstance(row, dict) and str(row.get("username", "")).startswith("zz"):
        r = call("DELETE", "/api/user/%s" % row.get("id"), headers=AH)
        print("  delete user %s (%s)" % (row.get("id"), row.get("username")))
print("  removing stray token rows left behind by the rehearsal (they belong to a deleted user)")
print("   ", sql("delete from tokens where name like 'zz%' and deleted_at is null returning name"))
print("  final state: users=%s | live tokens=%s | channels=%s" % (
    sql("select string_agg(username, ',') from users where deleted_at is null"),
    sql("select coalesce(string_agg(name, ','), 'none') from tokens where deleted_at is null"),
    sql("select count(*) from channels")))
print("  credential file still root-only:",
      subprocess.run(["stat", "-c", "%a %U", "/opt/lamtools-api/admin-credentials.txt"],
                     capture_output=True, text=True).stdout.strip())
print("  currency unit: quota_per_unit=%s price=%s" % (
    sql("select coalesce(value,'(unset)') from options where key='QuotaPerUnit'"),
    sql("select coalesce(value,'(unset)') from options where key='Price'")))
FEOF
python3 /tmp/jr/final.py
rm -rf /tmp/jr
echo "=== done ==="
