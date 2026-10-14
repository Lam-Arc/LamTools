set -eu
printf 'PRE_SITE_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
printf 'SITE='; readlink -f /var/www/lamtools/site
printf 'MANIFEST='; python3 -c 'import json;print(json.load(open("/var/www/lamtools/desktop-update.json")))'
printf 'AUTHORIZED_KEYS_LINES='; wc -l < /root/.ssh/authorized_keys
for path in /var/www/lamtools/site-releases/0.3.17-mobile-0.1.48-20261013 /var/www/lamtools/site.new0317 /var/tmp/Sunday-site-mobile-0.3.17-20261013.upload.tar.gz; do
  if [ -e "$path" ]; then echo "EXISTS $path"; else echo "ABSENT $path"; fi
done
printf 'PRE_SITE_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
