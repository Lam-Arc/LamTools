set -u
echo "=== dump every option row, filter on the host ==="
docker exec lamtools-api-db psql -U lamtools_api -d lamtools_api -tAc \
  "select key || E'\t' || coalesce(value,'') from options order by key" > /tmp/allopts.tsv 2>/tmp/allopts.err
echo "  rows read: $(wc -l < /tmp/allopts.tsv)"
if [ -s /tmp/allopts.err ]; then echo "  psql stderr:"; sed 's/^/    /' /tmp/allopts.err; fi
python3 - <<'PYEOF'
import re
words = ("pay", "stripe", "epay", "alipay", "wechat", "topup", "top_up", "recharge",
         "subscription", "price", "currency", "money", "balance", "checkin",
         "redemption", "display", "unit", "fee", "cost", "bill", "order", "shop")
rows = []
for line in open("/tmp/allopts.tsv", encoding="utf-8"):
    line = line.rstrip("\n")
    if not line:
        continue
    key, _, value = line.partition("\t")
    rows.append((key, value))
print("  total options in the database:", len(rows))
hits = [(k, v) for k, v in rows if any(w in k.lower() for w in words)]
print("  options whose name hints at money/display:", len(hits))
for k, v in hits:
    print("    %-38s = %s" % (k, v[:70]))
print("  --- is there any key containing 'rice', 'urrency', 'isplay'? ---")
for k, v in rows:
    if re.search(r"rice|urrency|isplay|nit$", k):
        print("    %-38s = %s" % (k, v[:70]))
PYEOF
rm -f /tmp/allopts.tsv /tmp/allopts.err
echo "=== done ==="
