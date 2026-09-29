set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 1
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/0.3.8-mobile-0.1.45-20260928
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = 7b4860b9424c09bd34d310e77e7dd449ab16c2eb5bc8788bc7e3ac6a4fd9bca9
test "$(sha256sum /var/www/lamtools/Sunday-mobile-latest.apk | cut -d' ' -f1)" = a02c14bce04c5a4738948621bde6f00dfe8a2211529f1d50a75bb87550c3db1e
test ! -e /var/www/lamtools/site-releases/0.3.9-mobile-0.1.46-20260929
test ! -e /var/tmp/Sunday-site-0.3.9-20260929.upload.tar.gz
printf '%s\n' 'restrict,command="internal-sftp" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIII1sUDeWqB8COFz1SJJFlApGsUkSK5V1G73qccP2D5F sunday-desktop-0.3.9-site-upload' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
date -u +%Y-%m-%dT%H:%M:%SZ
