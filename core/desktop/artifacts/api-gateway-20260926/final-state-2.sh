set -u
PUB=api.47.114.43.99.nip.io
RES="--resolve $PUB:443:127.0.0.1"

echo "=== token rows ==="
docker exec lamtools-api-db psql -U lamtools_api -d lamtools_api -tAc \
  "select 'total=' || count(*) || ' live=' || count(*) filter (where deleted_at is null) from tokens" 2>/dev/null | sed 's/^/  /'
docker exec lamtools-api-db psql -U lamtools_api -d lamtools_api -tAc \
  "select coalesce(string_agg(name || ' [status=' || status || ', deleted=' || (deleted_at is not null)::text || ']', ', '), 'none') from tokens where deleted_at is null" 2>/dev/null | sed 's/^/  live tokens: /'

echo "=== registration control ==="
docker exec lamtools-api-db psql -U lamtools_api -d lamtools_api -tAc \
  "select coalesce(string_agg(key || '=' || value, ', '), 'none') from options where key in ('RegisterEnabled','PasswordRegisterEnabled','EmailVerificationEnabled','TurnstileCheckEnabled')" 2>/dev/null | sed 's/^/  /'

echo "=== live registration attempt (authoritative check) ==="
code=$(curl -s -o /tmp/reg.json -w '%{http_code}' -m 20 $RES -H 'Content-Type: application/json' \
  -d '{"username":"zzprobe2","password":"Xy9-not-a-real-account","password2":"Xy9-not-a-real-account"}' \
  "https://$PUB/api/user/register")
python3 -c "
import json
d = json.load(open('/tmp/reg.json'))
print('  http=$code success=%s msg=%s' % (d.get('success'), str(d.get('message'))[:110]))
"
echo "=== done ==="
