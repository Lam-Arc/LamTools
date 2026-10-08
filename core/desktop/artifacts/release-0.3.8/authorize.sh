set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 1
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = 93338593d1cc06456fecc4bdff5d05fccbe7e5ca09a76c48c1b355e286eda2d1
test ! -e /var/www/lamtools/Sunday_0.3.8_x64-setup.exe
test ! -e /var/www/lamtools/Sunday-latest-x64-setup-0.3.7-before-0.3.8-20260928.exe
test ! -e /var/tmp/Sunday-desktop-0.3.8-20260928.upload.exe
test ! -e /var/tmp/Sunday-desktop-0.3.8-20260928.desktop-update.json
printf '%s\n' 'restrict,command="internal-sftp" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJwAZQ8afRh3VJyuIa9vqCF67R8ceNJQV3ushUwQEz0y sunday-desktop-037-upload' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
ls -l /var/www/lamtools/desktop-update.json
date -u +%Y-%m-%dT%H:%M:%SZ
