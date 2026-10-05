"""Diagnose the stable build's session handling: raw headers, cookie jar, logs.

All gateway passwords are masked in the output before printing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cloud import command  # noqa: E402

SCRIPT = r"""set -u
PUB=api.47.114.43.99.nip.io
RES="--resolve $PUB:443:127.0.0.1"
JAR=/tmp/diag-cookies.txt
rm -f "$JAR"

# Mask every configured secret before anything reaches the log.
mask() {
  python3 - "$@" <<'PYEOF'
import re, sys
text = sys.stdin.read()
try:
    for line in open('/opt/lamtools-api/.env', encoding='utf-8'):
        if '=' not in line:
            continue
        val = line.split('=', 1)[1].strip()
        if len(val) >= 8:
            text = text.replace(val, '***MASKED***')
except OSError:
    pass
sys.stdout.write(text)
PYEOF
}

echo "=== 1) raw login response headers (cookie values masked) ==="
ROOT_PASS=$(sed -n 's/^password : //p' /opt/lamtools-api/admin-credentials.txt)
curl -s -D /tmp/dh.txt -o /tmp/db.json -m 25 $RES -c "$JAR" -b "$JAR" \
  -H 'Content-Type: application/json' \
  -d "$(python3 -c "
import json,sys
print(json.dumps({'username':'root','password':sys.argv[1]}))
" "$ROOT_PASS")" \
  "https://$PUB/api/user/login" -w '  http=%{http_code}\n'
grep -i '^set-cookie\|^authorization\|^x-\|^content-type' /tmp/dh.txt | sed 's/=[^;]*/=<redacted>/' | sed 's/^/  /' || echo "  (no interesting headers)"
echo "  --- all header names present ---"
tr -d '\r' < /tmp/dh.txt | grep -E '^[A-Za-z-]+:' | cut -d: -f1 | sort -u | sed 's/^/    /'

echo "=== 2) cookie jar contents (values masked) ==="
if [ -s "$JAR" ]; then sed 's/\([0-9]\{10\}\)[^\t]*$/\1  <redacted>/' "$JAR" | sed 's/^/  /'; else echo "  jar empty"; fi

echo "=== 3) gateway log tail (secrets masked) ==="
docker logs lamtools-api-gateway 2>&1 | tail -40 | mask | sed 's/^/  /'

echo "=== 4) redis reachability from the gateway container ==="
REDIS_PASS=$(sed -n 's/^REDIS_PASSWORD=//p' /opt/lamtools-api/.env)
docker exec lamtools-api-gateway sh -c 'echo "  container has sh"' 2>/dev/null || echo "  (no shell in gateway image)"
docker exec lamtools-api-cache redis-cli --no-auth-warning -a "$REDIS_PASS" PING 2>&1 | sed 's/^/  redis: /'
echo "  redis keys: $(docker exec lamtools-api-cache redis-cli --no-auth-warning -a "$REDIS_PASS" DBSIZE 2>/dev/null)"

echo "=== 5) login over plain HTTP on loopback, jar check ==="
rm -f /tmp/jar2.txt
ROOT_PASS=$(sed -n 's/^password : //p' /opt/lamtools-api/admin-credentials.txt)
curl -s -o /dev/null -m 20 -c /tmp/jar2.txt \
  -H 'Content-Type: application/json' \
  -d "$(python3 -c "
import json,sys
print(json.dumps({'username':'root','password':sys.argv[1]}))
" "$ROOT_PASS")" \
  http://127.0.0.1:3000/api/user/login -w '  http=%{http_code}\n'
if [ -s /tmp/jar2.txt ]; then echo "  loopback jar has $(grep -c . /tmp/jar2.txt) lines"; else echo "  loopback jar EMPTY"; fi

echo "=== 6) does the app consider the session enabled? ==="
curl -s -m 10 http://127.0.0.1:3000/api/status | python3 -c "
import json,sys
d = json.load(sys.stdin).get('data', {})
print('  session_secret set:', bool(d.get('session_secret')))
print('  version:', d.get('version'))
" 2>/dev/null || true
mask < /dev/null
echo "=== done ==="
"""

if __name__ == "__main__":
    command(
        "session-diagnose",
        "Diagnose stable-build session handling: response headers, cookie jar, gateway logs and redis reachability",
        SCRIPT,
        timeout=400,
    )
