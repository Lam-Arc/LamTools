"""Read-only probe: find the working admin option endpoints and session mechanics."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cloud import command  # noqa: E402

SCRIPT = r"""set -u
JAR=/tmp/gw2-cookies.txt
rm -f "$JAR"
BASE=http://127.0.0.1:3000

# Re-authenticate using the stored credential, without echoing it.
ROOT_PASS=$(sed -n 's/^password : //p' /opt/lamtools-api/admin-credentials.txt)
BODY=$(python3 -c "
import json, sys
print(json.dumps({'username':'root','password':sys.argv[1]}))
" "$ROOT_PASS")
curl -s -o /dev/null -w 'login -> %{http_code}\n' -m 20 -c "$JAR" \
  -H 'Content-Type: application/json' -d "$BODY" "$BASE/api/user/login"
unset BODY ROOT_PASS

echo "=== cookie names captured ==="
awk '!/^#/ && NF {print "  " $6}' "$JAR" 2>/dev/null || true

echo "=== authenticated identity ==="
curl -s -b "$JAR" -o /tmp/self.json -w 'GET /api/user/self -> %{http_code}\n' -m 15 "$BASE/api/user/self"
python3 -c "
import json
d = json.load(open('/tmp/self.json'))
print('  success:', d.get('success'), '| message:', str(d.get('message'))[:200])
u = d.get('data') or {}
if isinstance(u, dict):
    print('  role:', u.get('role'), '| username:', u.get('username'), '| id:', u.get('id'))
    print('  keys:', sorted(u)[:40])
"

echo "=== option endpoint variants ==="
for path in /api/option/ /api/option /api/options/; do
  code=$(curl -s -b "$JAR" -o /tmp/o.json -w '%{http_code}' -m 15 "$BASE$path")
  msg=$(python3 -c "
import json
try:
    d = json.load(open('/tmp/o.json'))
    print('success=%s message=%s' % (d.get('success'), str(d.get('message'))[:120]))
except Exception as e:
    print('(unparsable)')
")
  echo "  GET $path -> $code | $msg"
done

echo "=== access token endpoint ==="
curl -s -b "$JAR" -o /tmp/tok.json -w 'GET /api/user/token -> %{http_code}\n' -m 15 "$BASE/api/user/token"
python3 -c "
import json
d = json.load(open('/tmp/tok.json'))
print('  success:', d.get('success'), '| message:', str(d.get('message'))[:120])
print('  data present:', bool(d.get('data')))
"
echo "=== done ==="
"""

if __name__ == "__main__":
    command(
        "probe-admin-api",
        "Read-only probe of admin identity, option endpoints and access token endpoint",
        SCRIPT,
        timeout=240,
    )
