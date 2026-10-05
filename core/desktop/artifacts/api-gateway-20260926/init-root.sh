set -u
APP=/opt/lamtools-api
JAR=/tmp/gw-cookies.txt
rm -f "$JAR"

echo "=== 1) setup state before ==="
curl -s -m 8 http://127.0.0.1:3000/api/setup -o /tmp/setupstate.json
python3 -c "import json;print('  ',json.load(open('/tmp/setupstate.json')).get('data'))"

if [ -f "$APP/admin-credentials.txt" ]; then
  echo "REFUSING: $APP/admin-credentials.txt already exists; nothing changed"
  exit 1
fi

echo "=== 2) write root credential record (values not echoed) ==="
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
chown root:root "$APP/admin-credentials.txt"
echo "  credential file: mode $(stat -c %a "$APP/admin-credentials.txt"), $(wc -c < "$APP/admin-credentials.txt") bytes"

echo "=== 3) first-run setup ==="
BODY=$(python3 -c "
import json, sys
p = sys.argv[1]
print(json.dumps({'username':'root','password':p,'confirmPassword':p,
                  'SelfUseModeEnabled':False,'DemoSiteEnabled':False}))
" "$ROOT_PASS")
curl -s -o /tmp/setup-resp.json -w '  POST /api/setup -> %{http_code}\n' -m 20 -c "$JAR" \
  -H 'Content-Type: application/json' -d "$BODY" http://127.0.0.1:3000/api/setup
python3 -c "
import json
d = json.load(open('/tmp/setup-resp.json'))
print('  success:', d.get('success'), '| message:', str(d.get('message'))[:200])
"
unset BODY

echo "=== 4) authenticated login check ==="
BODY=$(python3 -c "
import json, sys
print(json.dumps({'username':'root','password':sys.argv[1]}))
" "$ROOT_PASS")
curl -s -o /tmp/login-resp.json -w '  POST /api/user/login -> %{http_code}\n' -m 20 -b "$JAR" -c "$JAR" \
  -H 'Content-Type: application/json' -d "$BODY" http://127.0.0.1:3000/api/user/login
python3 -c "
import json
d = json.load(open('/tmp/login-resp.json'))
print('  login success:', d.get('success'), '| message:', str(d.get('message'))[:200])
"
unset BODY ROOT_PASS

echo "=== 5) session cookie captured? ==="
if [ -s "$JAR" ]; then echo "  cookie jar populated: $(grep -c session "$JAR" 2>/dev/null || echo 0) session entries"; else echo "  cookie jar EMPTY"; fi

echo "=== 6) setup state after ==="
curl -s -m 8 http://127.0.0.1:3000/api/status -o /tmp/s2.json
python3 -c "
import json
d = json.load(open('/tmp/s2.json')).get('data', {})
for k in ('setup','register_enabled','password_register_enabled','self_use_mode_enabled','demo_site_enabled','turnstile_check'):
    print('  %s = %s' % (k, d.get(k)))
"

echo "=== 7) available option keys (security-relevant only) ==="
curl -s -b "$JAR" -c "$JAR" -m 15 http://127.0.0.1:3000/api/option/ -o /tmp/opts.json
python3 -c "
import json
d = json.load(open('/tmp/opts.json'))
data = d.get('data')
print('  GET /api/option/ success:', d.get('success'))
if isinstance(data, list):
    print('  total options:', len(data))
    keys = [o.get('key') for o in data if isinstance(o, dict)]
    for k in keys:
        if any(t in str(k).lower() for t in ('regist','turnstile','self_use','demo','email_ver','checkin','oauth','captcha','invite','quota_for','default')):
            print('   ', k)
elif isinstance(data, dict):
    print('  keys:', sorted(data)[:60])
else:
    print('  unexpected shape:', str(data)[:200])
"
echo "=== done ==="
