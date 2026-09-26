set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 1
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = 41fedc6c7f14ed7a6b5f9420dd2cda780cd386b499e915b85873f60091711343
test ! -e /var/www/lamtools/Sunday_0.3.7_x64-setup.exe
test ! -e /var/www/lamtools/Sunday-latest-x64-setup-0.3.6-before-0.3.7-20260926.exe
test ! -e /var/tmp/Sunday-desktop-0.3.7-20260926.upload.exe
test ! -e /var/tmp/Sunday-desktop-0.3.7-20260926.desktop-update.json
printf '%s\n' 'restrict,command="internal-sftp" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICSop9GZRPt7ajhR+EyQMWLWqaT+VqcguPX9HOFLu/gV sunday-desktop-037-upload' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
ls -l /var/www/lamtools/desktop-update.json
date -u +%Y-%m-%dT%H:%M:%SZ
