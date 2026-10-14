set -eu
printf 'SYNC_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
sh /usr/local/bin/sync-public-site.sh
sh /usr/local/bin/sync-public-site.sh --check
echo SYNC_CHECK_OK
printf 'SITE='; readlink -f /var/www/lamtools/site
systemctl is-active caddy-lamtools lamtools-relay
printf 'SYNC_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
