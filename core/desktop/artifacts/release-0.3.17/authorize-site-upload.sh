set -eu
printf 'AUTHORIZE_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 1
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/0.3.16-mobile-0.1.48-20261009
test "$(python3 -c 'import json;print(json.load(open("/var/www/lamtools/desktop-update.json"))["version"])')" = 0.3.17
test ! -e /var/www/lamtools/site-releases/0.3.17-mobile-0.1.48-20261013
test ! -e /var/tmp/Sunday-site-mobile-0.3.17-20261013.upload.tar.gz
printf '%s\n' 'restrict,command="internal-sftp" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAID45J4CxMJeeFTFb+FabOZC8YNcjdhBKaVwQWuWm2QO9 sunday-0.3.17-site-upload-20261013' >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
printf 'AUTHORIZED_KEYS_LINES='; wc -l < /root/.ssh/authorized_keys
printf 'AUTHORIZE_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
