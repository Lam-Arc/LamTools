set -u
echo "=== the only settings explicitly stored (i.e. changed from defaults) ==="
docker exec lamtools-api-db psql -U lamtools_api -d lamtools_api -tAc \
  "select key || ' = ' || coalesce(nullif(value,''),'(empty)') from options order by key" | sed 's/^/  /'

cat > /tmp/paycheck.py <<'PEOF'
import http.cookiejar, json, time, urllib.error, urllib.request
BASE = "http://127.0.0.1:3000"
OP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def call(m, p, b=None, h=None):
    d = json.dumps(b).encode() if b is not None else None
    r = urllib.request.Request(BASE + p, data=d, method=m)
    r.add_header("Content-Type", "application/json")
    for k, v in (h or {}).items():
        r.add_header(k, v)
    try:
        with OP.open(r, timeout=40) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
pw = ""
for line in open("/opt/lamtools-api/admin-credentials.txt", encoding="utf-8"):
    if line.startswith("password :"):
        pw = line.split(":", 1)[1].strip()
uid = None
for _ in range(6):
    code, d = call("POST", "/api/user/login", {"username": "root", "password": pw})
    uid = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
    if uid:
        break
    time.sleep(10)
h = {"New-Api-User": str(uid)}
code, d = call("GET", "/api/user/token", headers=h)
t = d.get("data")
t = (t.get("token") or t.get("access_token")) if isinstance(t, dict) else t
if isinstance(t, str) and t:
    h["Authorization"] = "Bearer " + t
code, d = call("GET", "/api/option/", headers=h)
rows = d.get("data")
if isinstance(rows, dict):
    rows = [{"key": k, "value": v} for k, v in rows.items()]
print("  total settings visible through the API:", len(rows or []))
words = ("pay", "stripe", "epay", "alipay", "wechat", "topup", "top_up", "recharge",
         "subscription", "price", "currency", "money", "balance", "checkin",
         "redemption", "display", "quota_per_unit", "amount", "fee", "invoice", "shop")
hits = [(o.get("key"), str(o.get("value"))) for o in (rows or [])
        if isinstance(o, dict) and any(w in str(o.get("key")).lower() for w in words)]
print("  settings whose name hints at money or display:", len(hits))
for k, v in hits:
    print("    %-40s = %s" % (k, v[:60]))
PEOF
python3 /tmp/paycheck.py
rm -f /tmp/paycheck.py
echo "=== done ==="
