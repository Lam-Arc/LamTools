set -eu
printf 'AUTHORIZE_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 1
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/0.3.17-mobile-0.1.48-20261013
test "$(python3 -c 'import json;print(json.load(open("/var/www/lamtools/desktop-update.json"))["version"])')" = 0.3.17
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = d25a030599b148d52c44021a89b487f4ccf1a695d7b7d19bedd4c1a7ab3015b1
test ! -e /var/www/lamtools/Sunday_0.3.18_x64-setup.exe
test ! -e /var/www/lamtools/site-releases/0.3.18-mobile-0.1.48-20261013
test ! -e /var/tmp/Sunday-desktop-0.3.18-20261013.upload.exe
test ! -e /var/tmp/Sunday-desktop-0.3.18-20261013.desktop-update.json
test ! -e /var/tmp/Sunday-site-mobile-0.3.18-20261013.upload.tar.gz
test ! -e /usr/local/bin/sync-public-site.sh-0.3.17-before-0.3.18-20261013
test "$(grep -Fc 'sunday-desktop-0.3.18-site-upload-20261013' /root/.ssh/authorized_keys || true)" -eq 0
printf '%s\n' 'restrict,command="internal-sftp" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIF9b1TSzWo+mNUI8AGQmdv/uDt6SgifW+npKG/YFSaro sunday-desktop-0.3.18-site-upload-20261013' >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
printf 'AUTHORIZED_KEYS_LINES='; wc -l < /root/.ssh/authorized_keys
printf 'AUTHORIZE_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
