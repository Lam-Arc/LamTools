set -u
PUB=api.47.114.43.99.nip.io
RES="--resolve $PUB:443:127.0.0.1"
ROOT_PASS=$(sed -n 's/^password : //p' /opt/lamtools-api/admin-credentials.txt)

echo "=== gateway environment (names only) ==="
docker exec lamtools-api-gateway env 2>/dev/null | cut -d= -f1 | sort | sed 's/^/  /' || echo "  (cannot read env)"

probe() { # label baseurl extra-curl-args
  local label="$1" url="$2"; shift 2
  local jar=/tmp/probe-jar.txt
  rm -f "$jar"
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 20 "$@" -c "$jar" \
    -H 'Content-Type: application/json' \
    -d "$(python3 -c "
import json,sys
print(json.dumps({'username':'root','password':sys.argv[1]}))
" "$ROOT_PASS")" "$url/api/user/login")
  echo "  [$label] login -> $code"
  local lines
  lines=$(grep -c . "$jar" 2>/dev/null || echo 0)
  echo "  [$label] jar lines: $lines"
  for path in /api/user/self /api/user/token /api/option/; do
    c=$(curl -s -o /tmp/pr.json -w '%{http_code}' -m 25 "$@" -b "$jar" -c "$jar" "$url$path")
    msg=$(python3 -c "
import json
try:
    d = json.load(open('/tmp/pr.json'))
    print('success=%s msg=%s' % (d.get('success'), str(d.get('message'))[:70]))
except Exception:
    print('unparsable')
")
    echo "  [$label] $path -> $c | $msg"
  done
  if [ -s "$jar" ]; then cp "$jar" /tmp/working-jar.txt; fi
}

echo "=== loopback HTTP ==="
probe "loopback" "http://127.0.0.1:3000"

echo "=== public TLS ==="
probe "tls" "https://$PUB" $RES

echo "=== access token via the session, if any method worked ==="
if [ -s /tmp/working-jar.txt ]; then
  curl -s -o /tmp/tok.json -m 20 -b /tmp/working-jar.txt "$RES" "https://$PUB/api/user/token"
  python3 - <<'PYEOF'
import json
try:
    d = json.load(open('/tmp/tok.json'))
    data = d.get('data')
    if isinstance(data, dict):
        keys = sorted(data)
        print("  token response data keys:", keys)
    print("  success:", d.get('success'), "| message:", str(d.get('message'))[:80])
    tok = data if isinstance(data, str) else (data or {}).get('token') or (data or {}).get('access_token')
    if isinstance(tok, str) and tok:
        open('/tmp/admin-access-token', 'w').write(tok)
        print("  access token stored (length %d)" % len(tok))
    else:
        print("  no token value in response")
except Exception as exc:
    print("  unreadable:", type(exc).__name__)
PYEOF
else
  echo "  no working session; skipping"
fi
echo "=== done ==="
