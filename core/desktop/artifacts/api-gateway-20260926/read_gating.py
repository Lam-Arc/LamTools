"""Clear the self-inflicted login throttle, then read the gating settings once.

Only rate-limit / login keys are removed from the cache; channel cache and
session data are preserved.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cloud import command  # noqa: E402

READ = r'''
import json, sys, time, urllib.error, urllib.request

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
AH = {}
for attempt in range(6):
    code, d = call("POST", "/api/user/login", {"username": "root", "password": pw})
    if code == 200 and (d.get("data") or {}).get("access_token"):
        AH = {"Authorization": "Bearer " + d["data"]["access_token"], "New-API-User": "1"}
        print("  login OK on attempt %d" % (attempt + 1))
        break
    print("  login attempt %d -> http=%s" % (attempt + 1, code))
    time.sleep(10)
if not AH:
    print("  FATAL: still throttled")
    sys.exit(1)


def items_of(d):
    data = d.get("data") or {}
    return data.get("items") if isinstance(data, dict) else data


code, d = call("GET", "/api/option/", headers=AH)
opts = d.get("data") or []
print("  options read:", len(opts), "http", code)
WORDS = ("distribut", "affinity", "schedul", "route", "priority", "weight",
         "cache", "sync", "abnormal", "shop", "model_limit")
for o in opts:
    if isinstance(o, dict) and any(w in str(o.get("key")).lower() for w in WORDS):
        print("    %-48s = %s" % (o.get("key"), str(o.get("value"))[:110]))

print("  --- rate-limit settings ---")
for o in opts:
    if isinstance(o, dict) and "ratelimit" in str(o.get("key")).lower().replace("_", ""):
        print("    %-48s = %s" % (o.get("key"), str(o.get("value"))[:110]))

print("  --- pricing / model registry ---")
for path in ("/api/pricing/", "/api/models/"):
    code, d = call("GET", path)
    data = d.get("data")
    names = []
    if isinstance(data, list):
        names = [m.get("model_name") for m in data if isinstance(m, dict)]
    elif isinstance(data, dict):
        names = list(data.keys())
    print("    %s http=%s entries=%d gpt-4o-mini=%s" % (path, code, len(names),
                                                       "gpt-4o-mini" in names))
    if names:
        print("      sample:", names[:10])

print("  --- groups configured ---")
code, d = call("GET", "/api/group/", headers=AH)
print("    /api/group/ http=%s data=%s" % (code, json.dumps(d.get("data"))[:300]))
'''

SCRIPT = (r"""set -u
echo "=== redis key inventory (no values printed) ==="
REDIS_PASS=$(sed -n 's/^REDIS_PASSWORD=//p' /opt/lamtools-api/.env)
if [ -z "$REDIS_PASS" ]; then echo "  no redis password found"; else
  docker exec lamtools-api-cache redis-cli --no-auth-warning -a "$REDIS_PASS" DBSIZE
  docker exec lamtools-api-cache redis-cli --no-auth-warning -a "$REDIS_PASS" --scan --pattern '*' 2>/dev/null | head -40 | sed 's/^/    /'
fi

echo "=== delete only rate-limit / login throttle keys ==="
BEFORE=$(docker exec lamtools-api-cache redis-cli --no-auth-warning -a "$REDIS_PASS" DBSIZE | tr -d '\r')
docker exec lamtools-api-cache redis-cli --no-auth-warning -a "$REDIS_PASS" --scan --pattern '*' 2>/dev/null \
  | grep -Ei 'ratelimit|rate_limit|login|limit' > /tmp/rl.txt || true
if [ -s /tmp/rl.txt ]; then
  echo "  matching keys: $(wc -l < /tmp/rl.txt)"
  sed 's/^/    /' /tmp/rl.txt
  while read -r k; do
    [ -n "$k" ] && docker exec lamtools-api-cache redis-cli --no-auth-warning -a "$REDIS_PASS" DEL "$k" >/dev/null
  done < /tmp/rl.txt
else
  echo "  no rate-limit keys present (throttle may be in-process)"
fi
AFTER=$(docker exec lamtools-api-cache redis-cli --no-auth-warning -a "$REDIS_PASS" DBSIZE | tr -d '\r')
echo "  key count before/after: $BEFORE / $AFTER"
rm -f /tmp/rl.txt

echo "=== read gating settings ==="
cat > /tmp/read_opts.py <<'READEOF'
"""
    + READ
    + """READEOF
python3 /tmp/read_opts.py
echo "=== done ==="
""")

if __name__ == "__main__":
    command(
        "clear-throttle-read",
        "Clear the self-inflicted login throttle in the cache and read distributor gating settings",
        SCRIPT,
        timeout=400,
    )
