set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 1
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = 7b4860b9424c09bd34d310e77e7dd449ab16c2eb5bc8788bc7e3ac6a4fd9bca9
test ! -e /var/www/lamtools/Sunday_0.3.10_x64-setup.exe
test ! -e /var/www/lamtools/Sunday-latest-x64-setup-0.3.9-before-0.3.10-20260930.exe
test ! -e /var/tmp/Sunday-desktop-0.3.10-20260930.upload.exe
test ! -e /var/tmp/Sunday-desktop-0.3.10-20260930.desktop-update.json
printf '%s\n' 'restrict,command="internal-sftp" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGNzqTL09NdwtfrdtMH2fqa1koD35HjpY20Q+QimFjST sunday-desktop-037-upload' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
ls -l /var/www/lamtools/desktop-update.json
date -u +%Y-%m-%dT%H:%M:%SZ
