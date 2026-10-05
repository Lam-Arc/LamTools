set -u
PUB=api.47.114.43.99.nip.io
echo "=== containers ==="
docker compose -f /opt/lamtools-api/docker-compose.yml ps --format '  {{.Name}} {{.Image}} {{.Status}}'
echo "=== no test artefacts left ==="
docker exec lamtools-api-db psql -U lamtools_api -d lamtools_api -tAc \
  "select 'channels=' || (select count(*) from channels) || ' abilities=' || (select count(*) from abilities) || ' tokens=' || (select count(*) from tokens)" 2>/dev/null | sed 's/^/  /'
echo "=== public reachability ==="
printf '  console   -> '
curl -s -o /dev/null -w '%{http_code}\n' -m 20 --resolve "$PUB:443:127.0.0.1" "https://$PUB/"
printf '  no-key API-> '
curl -s -o /dev/null -w '%{http_code}\n' -m 20 --resolve "$PUB:443:127.0.0.1" "https://$PUB/v1/models"
echo "=== registration state ==="
curl -s -m 15 --resolve "$PUB:443:127.0.0.1" "https://$PUB/api/status" | python3 -c "
import json,sys
d = json.load(sys.stdin).get('data', {})
for k in ('version','setup','self_use_mode_enabled'):
    print('  %s = %s' % (k, d.get(k)))
print('  register_enabled =', d.get('register_enabled'))
"
echo "=== credential file ==="
ls -l /opt/lamtools-api/admin-credentials.txt | sed 's/^/  /'
ls -l /usr/local/bin/lamtools-api-reload | sed 's/^/  /'
echo "=== caddy site present ==="
grep -c 'api.47.114.43.99.nip.io' /etc/caddy/Caddyfile | sed 's/^/  matches: /'
echo "=== done ==="
