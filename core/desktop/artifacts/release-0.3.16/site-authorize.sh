set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 1
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/0.3.15-mobile-0.1.48-20261009
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = "$(python3 -c 'import json;print(json.load(open("/var/www/lamtools/desktop-update.json"))["sha256"])')"
test ! -e /var/www/lamtools/site-releases/0.3.16-mobile-0.1.48-20261009
test ! -e /var/tmp/Sunday-site-mobile-0.3.16-20261009.upload.tar.gz
printf '%s\n' 'restrict,command="internal-sftp" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGslucPESqt758J0JCxkqRrSrXTf+3wXkjjU6pmuKr+j sunday-0.3.16-site-upload' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
date -u +%Y-%m-%dT%H:%M:%SZ
