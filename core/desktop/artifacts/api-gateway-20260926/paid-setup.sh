set -u
PUB=api.47.114.43.99.nip.io
RES="--resolve $PUB:443:127.0.0.1"
mkdir -p /tmp/pay

cat > /tmp/pay/lib.py <<'LIBEOF'
import http.cookiejar, json, subprocess, time, urllib.error, urllib.request

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
    for _ in range(6):
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
LIBEOF

cat > /tmp/pay/setup.py <<'SEOF'
import http.cookiejar, json, os, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, '/tmp/pay')
from lib import *  # noqa

throttle_clear()
AH = admin_headers()
code, d = call("GET", "/api/option/", headers=AH)
rows = d.get("data")
if isinstance(rows, dict):
    rows = [{"key": k, "value": v} for k, v in rows.items()]
opts = {str(o.get("key")): str(o.get("value")) for o in (rows or []) if isinstance(o, dict)}
print("  settings available:", len(opts))

print("=== the knobs that decide what a user pays ===")
for k in ("GroupRatio", "TopupGroupRatio", "QuotaPerUnit", "DisplayInCurrencyEnabled",
          "Price", "MinTopUp", "payment_setting.amount_options", "PayMethods",
          "EpayId", "PayAddress", "StripePriceId"):
    if k in opts:
        print("  %-34s = %s" % (k, opts[k][:110]))

print("=== is there a per-model price table? ===")
mr = opts.get("ModelRatio") or ""
cr = opts.get("CompletionRatio") or ""
try:
    mrj = json.loads(mr)
    print("  models with a set ratio:", len(mrj))
    for name in list(mrj)[:6]:
        print("    %-36s ratio=%s" % (name, mrj[name]))
except Exception:
    print("  ModelRatio not parseable, length:", len(mr))
try:
    crj = json.loads(cr)
    print("  completion ratios set for:", len(crj), "models")
except Exception:
    print("  CompletionRatio not parseable, length:", len(cr))

print("=== switch registration on for a self-service station ===")
for key, value in (("RegisterEnabled", "true"), ("PasswordRegisterEnabled", "true")):
    code, d = call("PUT", "/api/option/", {"key": key, "value": value}, AH)
    print("    %-26s -> success=%s" % (key, d.get("success")))
print("  stored now:", sql("select string_agg(key || '=' || value, ', ') from options"
                          " where key ~ 'Register' order by key"))
SEOF
python3 /tmp/pay/setup.py

echo "=== a stranger registers through the public endpoint ==="
PW="Zz$(openssl rand -hex 6)"
code=$(curl -s -o /tmp/pay/reg.json -w '%{http_code}' -m 25 $RES \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"zzpay1\",\"password\":\"$PW\",\"password2\":\"$PW\"}" \
  "https://$PUB/api/user/register")
python3 -c "
import json
d = json.load(open('/tmp/pay/reg.json'))
print('  register -> http $code success=%s msg=%s' % (d.get('success'), str(d.get('message'))[:80]))
"
printf '%s' "$PW" > /tmp/pay/user-pw
echo "  account quota right after registering:"
docker exec lamtools-api-db psql -U lamtools_api -d lamtools_api -tAc \
  "select '    username=' || username || ' quota=' || coalesce(quota::text,'NULL') || ' group=' || \"group\" from users where username='zzpay1'" | sed 's/^/  /'
echo "=== part 1 done ==="
