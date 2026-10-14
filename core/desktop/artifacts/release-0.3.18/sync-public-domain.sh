set -eu
printf 'SYNC_DOMAIN_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/0.3.18-mobile-0.1.48-20261013
test "$(sha256sum /usr/local/bin/sync-public-site.sh | cut -d' ' -f1)" = 94eb52fb953221223786c070fecea5ceba639ef9c5a3936665a1207ccf780030
python3 - <<'PY'
import json
m=json.load(open('/var/www/lamtools/desktop-update.json'))
mobile=json.load(open('/var/www/lamtools/mobile-update.json'))
assert (m['version'],m['linux_version'],mobile['version']) == ('0.3.18','0.3.17','0.1.48')
print('CHANNELS_OK desktop={} Linux={} mobile={}'.format(m['version'],m['linux_version'],mobile['version']))
PY
sh /usr/local/bin/sync-public-site.sh
sh /usr/local/bin/sync-public-site.sh --check
printf 'SITE_POINTER='; readlink -f /var/www/lamtools/site
systemctl is-active caddy-lamtools lamtools-relay
printf 'SYNC_DOMAIN_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
