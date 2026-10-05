set -u
BASE=http://127.0.0.1:3000
JAR=/tmp/gw4-cookies.txt
rm -f "$JAR"

login() {
  ROOT_PASS=$(sed -n 's/^password : //p' /opt/lamtools-api/admin-credentials.txt)
  BODY=$(python3 -c "
import json, sys
print(json.dumps({'username':'root','password':sys.argv[1]}))
" "$ROOT_PASS")
  curl -s -o /tmp/auth.json -m 20 -c "$JAR" -H 'Content-Type: application/json' -d "$BODY" "$BASE/api/user/login"
  unset BODY ROOT_PASS
  TOKEN=$(python3 -c "
import json
d = json.load(open('/tmp/auth.json')).get('data') or {}
print(d.get('access_token') or '')
")
  if [ -z "$TOKEN" ]; then echo "LOGIN FAILED"; exit 1; fi
  echo "  authenticated as root (token len ${#TOKEN})"
}

api() { # method path [json]
  if [ $# -ge 3 ]; then
    curl -s -X "$1" -o /tmp/api-resp.json -w '%{http_code}' -m 20 \
      -H "Authorization: Bearer $TOKEN" -H "New-API-User: 1" \
      -H 'Content-Type: application/json' -d "$3" "$BASE$2"
  else
    curl -s -X "$1" -o /tmp/api-resp.json -w '%{http_code}' -m 20 \
      -H "Authorization: Bearer $TOKEN" -H "New-API-User: 1" "$BASE$2"
  fi
}

echo "=== before ==="
login
for k in RegisterEnabled PasswordRegisterEnabled EmailVerificationEnabled TurnstileCheckEnabled SelfUseModeEnabled DemoSiteEnabled QuotaForNewUser; do
  api GET "/api/option/"
  python3 -c "
import json
d = json.load(open('/tmp/api-resp.json')).get('data') or []
want = '$k'
for o in d:
    if isinstance(o, dict) and o.get('key') == want:
        print('  %s = %s' % (want, o.get('value')))
        break
else:
    print('  %s = <absent>' % want)
"
done

echo "=== apply hardening ==="
set_opt() { # key value
  code=$(api PUT "/api/option/" "{\"key\":\"$1\",\"value\":\"$2\"}")
  msg=$(python3 -c "
import json
try:
    d = json.load(open('/tmp/api-resp.json'))
    print('success=%s msg=%s' % (d.get('success'), str(d.get('message'))[:80]))
except Exception:
    print('unparsable')
")
  echo "  PUT $1=$2 -> $code | $msg"
}
set_opt RegisterEnabled false
set_opt PasswordRegisterEnabled false

echo "=== after (re-read from server) ==="
for k in RegisterEnabled PasswordRegisterEnabled SelfUseModeEnabled QuotaForNewUser; do
  api GET "/api/option/"
  python3 -c "
import json
d = json.load(open('/tmp/api-resp.json')).get('data') or []
want = '$k'
for o in d:
    if isinstance(o, dict) and o.get('key') == want:
        print('  %s = %s' % (want, o.get('value')))
        break
else:
    print('  %s = <absent>' % want)
"
done

echo "=== public status flags after ==="
curl -s -m 8 "$BASE/api/status" -o /tmp/s3.json
python3 -c "
import json
d = json.load(open('/tmp/s3.json')).get('data', {})
for k in ('setup','register_enabled','password_register_enabled','self_use_mode_enabled','demo_site_enabled'):
    print('  %s = %s' % (k, d.get(k)))
"

echo "=== live registration attempt (must be rejected) ==="
code=$(curl -s -o /tmp/reg.json -w '%{http_code}' -m 15 -H 'Content-Type: application/json' \
  -d '{"username":"probe_registration_check","password":"Xy9-probe-not-a-real-account","password2":"Xy9-probe-not-a-real-account"}' \
  "$BASE/api/user/register")
python3 -c "
import json
try:
    d = json.load(open('/tmp/reg.json'))
    print('  POST /api/user/register -> $code | success=%s msg=%s' % (d.get('success'), str(d.get('message'))[:140]))
except Exception:
    print('  POST /api/user/register -> $code (unparsable)')
"
echo "=== done ==="
