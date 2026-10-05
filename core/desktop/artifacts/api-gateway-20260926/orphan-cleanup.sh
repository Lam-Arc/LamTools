set -u
PUB=api.47.114.43.99.nip.io
echo "=== all live user rows ==="
docker exec lamtools-api-db psql -U lamtools_api -d lamtools_api -tAc \
  "select id || ' | username=' || coalesce(nullif(username,''),'(empty)') || ' | display=' || coalesce(display_name,'-') || ' | role=' || role || ' | quota=' || coalesce(quota::text,'NULL') from users where deleted_at is null order by id" | sed 's/^/  /'

echo "=== remove the orphan row left by my probing (never touches root) ==="
docker exec lamtools-api-db psql -U lamtools_api -d lamtools_api -tAc \
  "delete from users where deleted_at is null and (username is null or username = '') and username <> 'root' returning id" | sed 's/^/  deleted id /'

echo "=== final state ==="
docker exec lamtools-api-db psql -U lamtools_api -d lamtools_api -tAc \
  "select 'users=' || (select string_agg(coalesce(nullif(username,''),'(empty)'), ',') from users where deleted_at is null) || ' | live_tokens=' || (select coalesce(string_agg(name, ','), 'none') from tokens where deleted_at is null) || ' | channels=' || (select count(*) from channels) || ' | codes=' || (select coalesce(string_agg(name, ','), 'none') from redemptions where deleted_at is null)" | sed 's/^/  /'

echo "=== quota units and currency ==="
docker exec lamtools-api-db psql -U lamtools_api -d lamtools_api -tAc \
  "select coalesce(key || '=' || value, 'none') from options where key in ('QuotaPerUnit','Price','DisplayInCurrency')" | sed 's/^/  /'

echo "=== public service still healthy ==="
RES="--resolve $PUB:443:127.0.0.1"
printf '  console   -> '; curl -s -o /dev/null -w '%{http_code}\n' -m 20 $RES "https://$PUB/"
printf '  no-key API-> '; curl -s -o /dev/null -w '%{http_code}\n' -m 20 $RES "https://$PUB/v1/models"
docker compose -f /opt/lamtools-api/docker-compose.yml ps --format '  {{.Name}} {{.Status}}'
echo "=== done ==="
