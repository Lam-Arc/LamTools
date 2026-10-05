set -u
cat > /tmp/inspect_opts.py <<'PYEOF'
import json, urllib.error, urllib.request

BASE = "http://127.0.0.1:3000"


def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=40) as resp:
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
code, d = call("POST", "/api/user/login", {"username": "root", "password": pw})
tok = (d.get("data") or {}).get("access_token") or ""
print("  login ok:", bool(tok), "| http", code, "|", str(d.get("message"))[:80])
AH = {"Authorization": "Bearer " + tok, "New-API-User": "1"}

code, d = call("GET", "/api/option/", headers=AH)
opts = d.get("data") or []
print("  options:", len(opts), "| success:", d.get("success"))
WORDS = ("distribut", "route", "routing", "affinity", "schedul", "cache", "sync",
         "channel", "priority", "weight", "auto_group", "retry", "model_limit",
         "group", "abnormal", "disable")
for o in opts:
    if not isinstance(o, dict):
        continue
    k = str(o.get("key"))
    if any(w in k.lower() for w in WORDS):
        print("    %-46s = %s" % (k, str(o.get("value"))[:110]))

print("  --- pricing: is gpt-4o-mini a known model? ---")
code, d = call("GET", "/api/pricing")
data = d.get("data")
names = []
if isinstance(data, list):
    names = [m.get("model_name") for m in data if isinstance(m, dict)]
elif isinstance(data, dict):
    names = list(data.keys())
print("    priced models:", len(names))
hits = [n for n in names if "4o" in str(n) or "mini" in str(n)]
print("    gpt-4o-like entries:", hits[:12])
print("    gpt-4o-mini present:", "gpt-4o-mini" in names)
PYEOF
python3 /tmp/inspect_opts.py

echo "=== full channel record (all fields of the most recent channel) ==="
cat > /tmp/inspect_ch.py <<'PYEOF'
import json, urllib.error, urllib.request
BASE = "http://127.0.0.1:3000"
def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=40) as resp:
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
code, d = call("POST", "/api/user/login", {"username": "root", "password": pw})
AH = {"Authorization": "Bearer " + ((d.get("data") or {}).get("access_token") or ""),
      "New-API-User": "1"}
code, d = call("GET", "/api/channel/?p=0&size=100", headers=AH)
data = d.get("data") or {}
items = data.get("items") if isinstance(data, dict) else data
print("  channels on record:", len(items or []))
for it in (items or []):
    for k in sorted(it):
        if k in ("key",):
            print("    %-24s <%s len=%d>" % (k, type(it[k]).__name__, len(str(it[k]))))
        else:
            print("    %-24s %s" % (k, str(it[k])[:120]))
PYEOF
python3 /tmp/inspect_ch.py
echo "=== done ==="
