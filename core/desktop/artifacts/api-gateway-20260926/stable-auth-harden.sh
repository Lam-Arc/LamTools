set -u
BASE=http://127.0.0.1:3000

echo "=== 1) why the cookie did not authenticate (names/attrs only) ==="
awk '!/^#/ && NF {print "  cookie: " $6 " domain=" $1 " path=" $3}' /tmp/cj.txt 2>/dev/null || echo "  no cookie jar"
curl -s -D /tmp/lh.txt -o /dev/null -m 15 -X POST -H 'Content-Type: application/json' \
  -d '{}' "$BASE/api/user/login" >/dev/null 2>&1 || true

echo "=== 2) locate the admin access token column ==="
docker exec lamtools-api-db psql -U lamtools_api -d lamtools_api -tAc \
  "select column_name from information_schema.columns where table_name='users' order by column_name" \
  2>/dev/null | sed 's/^/  /' || echo "  could not read users table"

echo "=== 3) authenticated admin probe (token never printed) ==="
TOKEN=$(docker exec lamtools-api-db psql -U lamtools_api -d lamtools_api -tAc \
  "select access_token from users where username='root' limit 1" 2>/dev/null | tr -d '[:space:]')
USER_ID=$(docker exec lamtools-api-db psql -U lamtools_api -d lamtools_api -tAc \
  "select id from users where username='root' limit 1" 2>/dev/null | tr -d '[:space:]')
echo "  token length: ${#TOKEN} | root user id: ${USER_ID:-unknown}"
if [ -z "$TOKEN" ]; then echo "  FATAL: no access token in database"; exit 1; fi

AH_AUTH="Authorization: Bearer $TOKEN"
AH_USER="New-API-User: $USER_ID"
curl -s -o /tmp/self.json -w '  GET /api/user/self -> %{http_code}\n' -m 20 \
  -H "$AH_AUTH" -H "$AH_USER" "$BASE/api/user/self"
python3 -c "
import json
d = json.load(open('/tmp/self.json'))
u = d.get('data') or {}
print('  success:', d.get('success'), '| role:', u.get('role'), '| username:', u.get('username'))
"

echo "=== 4) registration-related option keys ==="
curl -s -o /tmp/opts.json -m 25 -H "$AH_AUTH" -H "$AH_USER" "$BASE/api/option/"
python3 -c "
import json
d = json.load(open('/tmp/opts.json'))
data = d.get('data')
print('  read success:', d.get('success'))
rows = data if isinstance(data, list) else []
if isinstance(data, dict):
    rows = [{'key': k, 'value': v} for k, v in data.items()]
print('  option count:', len(rows))
for o in rows:
    k = str(o.get('key'))
    if any(t in k.lower() for t in ('register','selfuse','self_use','demo','turnstile','emailver','email_ver')):
        print('    %-40s = %s' % (k, str(o.get('value'))[:60]))
"

echo "=== 5) close self-service registration ==="
set_opt() {
  code=$(curl -s -o /tmp/opt_resp.json -w '%{http_code}' -m 20 -X PUT \
    -H "$AH_AUTH" -H "$AH_USER" -H 'Content-Type: application/json' \
    -d "{\"key\":\"$1\",\"value\":\"$2\"}" "$BASE/api/option/")
  msg=$(python3 -c "
import json
try:
    d = json.load(open('/tmp/opt_resp.json'))
    print('success=%s msg=%s' % (d.get('success'), str(d.get('message'))[:80]))
except Exception:
    print('unparsable')
")
  echo "  PUT $1=$2 -> $code | $msg"
}
set_opt RegisterEnabled false
set_opt PasswordRegisterEnabled false
set_opt EmailVerificationEnabled false
set_opt GitHubOAuthEnabled false
set_opt TurnstileCheckEnabled false

echo "=== 6) verify from the public status view ==="
curl -s -m 10 "$BASE/api/status" -o /tmp/st2.json
python3 -c "
import json
d = json.load(open('/tmp/st2.json')).get('data', {})
for k in sorted(d):
    if any(t in k.lower() for t in ('register','setup','self_use','demo','turnstile')):
        print('  %s = %s' % (k, d.get(k)))
"

echo "=== 7) live registration attempt (must be rejected) ==="
code=$(curl -s -o /tmp/reg.json -w '%{http_code}' -m 15 -H 'Content-Type: application/json' \
  -d '{"username":"zz_probe_registration","password":"Xy9-not-a-real-account","password2":"Xy9-not-a-real-account"}' \
  "$BASE/api/user/register")
python3 -c "
import json
try:
    d = json.load(open('/tmp/reg.json'))
    print('  POST /api/user/register -> $code | success=%s msg=%s' % (d.get('success'), str(d.get('message'))[:120]))
except Exception:
    print('  POST /api/user/register -> $code (unparsable)')
"
echo "=== done ==="
