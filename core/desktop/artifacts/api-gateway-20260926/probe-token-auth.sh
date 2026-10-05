set -u
BASE=http://127.0.0.1:3000
JAR=/tmp/gw3-cookies.txt
rm -f "$JAR"

ROOT_PASS=$(sed -n 's/^password : //p' /opt/lamtools-api/admin-credentials.txt)
BODY=$(python3 -c "
import json, sys
print(json.dumps({'username':'root','password':sys.argv[1]}))
" "$ROOT_PASS")
curl -s -o /tmp/login2.json -w 'login -> %{http_code}\n' -m 20 -c "$JAR" \
  -H 'Content-Type: application/json' -d "$BODY" "$BASE/api/user/login"
unset BODY

echo "=== login response shape (values redacted for token-like keys) ==="
python3 -c "
import json
d = json.load(open('/tmp/login2.json'))
print('  top keys:', sorted(d))
data = d.get('data')
if isinstance(data, dict):
    for k in sorted(data):
        v = data[k]
        if any(t in k.lower() for t in ('token', 'secret', 'key', 'session')):
            print('  %-22s <%s len=%d>' % (k, type(v).__name__, len(str(v))))
        else:
            print('  %-22s %s' % (k, str(v)[:60]))
else:
    print('  data:', str(data)[:200])
"

echo "=== try bearer auth with candidate fields ==="
TOKEN=$(python3 -c "
import json
d = json.load(open('/tmp/login2.json')).get('data') or {}
for name in ('access_token', 'token', 'accessToken'):
    v = d.get(name)
    if isinstance(v, str) and v:
        print(v); break
")
if [ -z "${TOKEN:-}" ]; then
  echo "  no token field found in login response"
else
  echo "  candidate token found (len ${#TOKEN})"
  for hdr in "-H Authorization:Bearer" ; do : ; done
  code=$(curl -s -o /tmp/self2.json -w '%{http_code}' -m 15 -b "$JAR" \
    -H "Authorization: Bearer $TOKEN" "$BASE/api/user/self")
  echo "  with Bearer only            -> $code"
  code2=$(curl -s -o /tmp/self3.json -w '%{http_code}' -m 15 -b "$JAR" \
    -H "Authorization: Bearer $TOKEN" -H "New-API-User: 1" "$BASE/api/user/self")
  echo "  with Bearer + New-API-User  -> $code2"
  python3 -c "
import json
for f in ('/tmp/self2.json','/tmp/self3.json'):
    try:
        d = json.load(open(f))
        u = d.get('data') or {}
        print('  %s success=%s role=%s user=%s msg=%s' % (f, d.get('success'),
              u.get('role') if isinstance(u,dict) else None,
              u.get('username') if isinstance(u,dict) else None,
              str(d.get('message'))[:80]))
    except Exception as e:
        print('  %s unparsable' % f)
"
  echo "=== option endpoint via bearer ==="
  code3=$(curl -s -o /tmp/opts2.json -w '%{http_code}' -m 15 \
    -H "Authorization: Bearer $TOKEN" -H "New-API-User: 1" "$BASE/api/option/")
  echo "  GET /api/option/ -> $code3"
  python3 -c "
import json
try:
    d = json.load(open('/tmp/opts2.json'))
    data = d.get('data')
    print('  success:', d.get('success'), '| message:', str(d.get('message'))[:120])
    if isinstance(data, list):
        print('  options:', len(data))
        for o in data:
            if isinstance(o, dict):
                k = str(o.get('key'))
                if any(t in k.lower() for t in ('regist','turnstile','self_use','demo','email_ver','quota_for','default')):
                    print('    %s = %s' % (k, o.get('value')))
    elif isinstance(data, dict):
        for k in sorted(data):
            if any(t in k.lower() for t in ('regist','turnstile','self_use','demo','email_ver','quota_for')):
                print('    %s = %s' % (k, data[k]))
    else:
        print('  data:', str(data)[:200])
except Exception as e:
    print('  unparsable')
"
fi
echo "=== done ==="
