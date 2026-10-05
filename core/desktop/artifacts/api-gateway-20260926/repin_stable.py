"""Re-pin the gateway to the latest stable release and reinitialise.

The v1.0.0-rc line introduced a model-governance layer that would not route.
v0.13.2 is the current stable release. The database holds nothing but the root
account created minutes ago, so the volume is recreated rather than migrated.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cloud import command  # noqa: E402

IMAGE = "calciumion/new-api:v0.13.2"

SCRIPT = r"""set -u
APP=/opt/lamtools-api
IMG=__IMAGE__
cd "$APP"

echo "=== 1) pull the stable image ==="
if timeout 600 docker pull "$IMG" >/tmp/pull2.log 2>&1; then
  echo "  pulled $IMG"
  docker image inspect --format '  digest: {{index .RepoDigests 0}}' "$IMG"
else
  echo "  PULL FAILED"; tail -5 /tmp/pull2.log; exit 1
fi

echo "=== 2) current (rc) state, for the record ==="
docker compose ps --format '  {{.Name}} {{.Image}} {{.Status}}' || true

echo "=== 3) stop the stack and drop the rc-era database ==="
cp -p "$APP/docker-compose.yml" "$APP/docker-compose.yml.before-stable-$(date -u +%Y%m%dT%H%M%SZ)"
docker compose down -v 2>&1 | tail -8

echo "=== 4) re-pin the image tag ==="
sed -i "s|image: calciumion/new-api:[^ ]*|image: $IMG|" "$APP/docker-compose.yml"
grep -n 'image:' "$APP/docker-compose.yml" | sed 's/^/  /'
sha256sum "$APP/docker-compose.yml" | sed 's/^/  compose sha256: /'

echo "=== 5) rotate the administrator password ==="
rm -f "$APP/admin-credentials.txt"
umask 077
ROOT_PASS=$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-28)
cat > "$APP/admin-credentials.txt" <<CREDEOF
LamTools API gateway - administrator account
console  : https://api.47.114.43.99.nip.io
username : root
password : $ROOT_PASS
generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)

Change this password in the console after the first login.
CREDEOF
chmod 600 "$APP/admin-credentials.txt"
echo "  credential file rotated: mode $(stat -c %a "$APP/admin-credentials.txt")"

echo "=== 6) start the stable stack ==="
docker compose up -d --wait 2>&1 | tail -12
docker compose ps --format '  {{.Name}} {{.Image}} {{.Status}}'

echo "=== 7) wait for the API ==="
code=""
for i in $(seq 1 40); do
  code=$(curl -s -o /tmp/st.json -w '%{http_code}' -m 5 http://127.0.0.1:3000/api/status || true)
  [ "$code" = "200" ] && { echo "  HTTP 200 after $((i*3))s"; break; }
  sleep 3
done
echo "  last code: ${code:-none}"
python3 -c "
import json
d = json.load(open('/tmp/st.json')).get('data') or {}
print('  version:', d.get('version'))
print('  setup:', d.get('setup'))
print('  register_enabled:', d.get('register_enabled'))
" 2>/dev/null || head -c 300 /tmp/st.json

echo "=== 8) first-run setup on the stable build ==="
curl -s -m 10 http://127.0.0.1:3000/api/setup -o /tmp/setupst.json
python3 -c "
import json
d = json.load(open('/tmp/setupst.json'))
print('  setup state:', d.get('data'), '| success:', d.get('success'))
"
BODY=$(python3 -c "
import json, sys
p = sys.argv[1]
print(json.dumps({'username':'root','password':p,'confirmPassword':p,
                  'SelfUseModeEnabled':False,'DemoSiteEnabled':False}))
" "$ROOT_PASS")
curl -s -o /tmp/setupresp.json -w '  POST /api/setup -> %{http_code}\n' -m 20 -c /tmp/cj.txt \
  -H 'Content-Type: application/json' -d "$BODY" http://127.0.0.1:3000/api/setup
python3 -c "
import json
d = json.load(open('/tmp/setupresp.json'))
print('  success:', d.get('success'), '| message:', str(d.get('message'))[:150])
"
unset BODY

echo "=== 9) determine the working auth method ==="
BODY=$(python3 -c "
import json, sys
print(json.dumps({'username':'root','password':sys.argv[1]}))
" "$ROOT_PASS")
curl -s -o /tmp/login2.json -w '  POST /api/user/login -> %{http_code}\n' -m 20 -c /tmp/cj.txt -b /tmp/cj.txt \
  -H 'Content-Type: application/json' -d "$BODY" http://127.0.0.1:3000/api/user/login
unset BODY ROOT_PASS
python3 -c "
import json
d = json.load(open('/tmp/login2.json'))
print('  login success:', d.get('success'), '| message:', str(d.get('message'))[:120])
data = d.get('data')
print('  login data keys:', sorted(data) if isinstance(data, dict) else type(data).__name__)
"
echo "  --- session cookie attempt ---"
curl -s -o /tmp/self_c.txt -w '  cookie /api/user/self -> %{http_code}\n' -m 15 -b /tmp/cj.txt http://127.0.0.1:3000/api/user/self
TOKEN=$(python3 -c "
import json
d = json.load(open('/tmp/login2.json')).get('data') or {}
for n in ('access_token','token','accessToken'):
    v = d.get(n)
    if isinstance(v, str) and v:
        print(v); break
")
if [ -n "${TOKEN:-}" ]; then
  curl -s -o /tmp/self_b.txt -w '  bearer /api/user/self -> %{http_code}\n' -m 15 \
    -H "Authorization: Bearer $TOKEN" -H "New-API-User: 1" http://127.0.0.1:3000/api/user/self
else
  echo "  no token in login response (session-cookie build)"
fi

echo "=== 10) registration-related option keys ==="
if [ -n "${TOKEN:-}" ]; then
  curl -s -o /tmp/opts.json -m 20 -H "Authorization: Bearer $TOKEN" -H "New-API-User: 1" http://127.0.0.1:3000/api/option/
else
  curl -s -o /tmp/opts.json -m 20 -b /tmp/cj.txt http://127.0.0.1:3000/api/option/
fi
python3 -c "
import json
d = json.load(open('/tmp/opts.json'))
data = d.get('data')
print('  option read success:', d.get('success'))
rows = data if isinstance(data, list) else []
if isinstance(data, dict):
    rows = [{'key': k, 'value': v} for k, v in data.items()]
print('  count:', len(rows))
for o in rows:
    k = str(o.get('key'))
    if any(t in k.lower() for t in ('register','selfuse','self_use','demo','turnstile','emailver','email_ver')):
        print('    %-40s = %s' % (k, str(o.get('value'))[:60]))
"
echo "=== done ==="
""".replace("__IMAGE__", IMAGE)

if __name__ == "__main__":
    command(
        "repin-stable",
        "Re-pin gateway to the latest stable release, recreate the database, initialise root and probe auth and options",
        SCRIPT,
        timeout=900,
    )
