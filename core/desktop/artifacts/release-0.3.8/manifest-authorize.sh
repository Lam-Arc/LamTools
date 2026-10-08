set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 1
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = c76b67615955c870a8cdaab61fecf4e1c08e4d29b04bb1a123dd74b45b8c5e6e
test "$(sha256sum /var/www/lamtools/desktop-update.json | cut -d' ' -f1)" = 0beae41aad6dc93bab932f90c7109aba93e8c7bd23cfa083652be782f687c725
test ! -e /var/tmp/Sunday-desktop-0.3.8-20260928.desktop-update.json
printf '%s\n' 'restrict,command="internal-sftp" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJwAZQ8afRh3VJyuIa9vqCF67R8ceNJQV3ushUwQEz0y sunday-desktop-037-upload' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
date -u +%Y-%m-%dT%H:%M:%SZ
