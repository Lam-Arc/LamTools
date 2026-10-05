set -u
echo "=== every option whose name hints at payment, currency or charging ==="
docker exec lamtools-api-db psql -U lamtools_api -d lamtools_api -tAc \
  "select key || ' = ' || coalesce(nullif(value,''), '(empty)') from options
   where key ~* 'pay|stripe|epay|alipay|wechat|topup|top_up|recharge|subscription|price|currency|amount|money|balance|checkin|redemption'
   order by key" | sed 's/^/  /'

echo "=== is money-style display switched on? ==="
docker exec lamtools-api-db psql -U lamtools_api -d lamtools_api -tAc \
  "select key || ' = ' || coalesce(nullif(value,''), '(empty)') from options
   where key ~* 'display|unit' order by key" | sed 's/^/  /'

echo "=== any configured payment provider at all? ==="
docker exec lamtools-api-db psql -U lamtools_api -d lamtools_api -tAc \
  "select 'payment rows in top_ups: ' || (select count(*) from top_ups)
   || ' | subscription orders: ' || (select count(*) from subscription_orders)
   || ' | subscription plans: ' || (select count(*) from subscription_plans)
   || ' | redemption codes: ' || (select count(*) from redemptions)
   || ' | users with a stripe customer id: ' || (select count(*) from users where coalesce(stripe_customer,'') <> '')" | sed 's/^/  /'

echo "=== who currently holds quota, and how much ==="
docker exec lamtools-api-db psql -U lamtools_api -d lamtools_api -tAc \
  "select username || ' quota=' || coalesce(quota::text,'NULL') from users where deleted_at is null order by id" | sed 's/^/  /'
echo "=== done ==="
