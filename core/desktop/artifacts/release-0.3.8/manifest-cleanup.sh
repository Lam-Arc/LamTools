set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
grep -vF 'AAAAC3NzaC1lZDI1NTE5AAAAIJwAZQ8afRh3VJyuIa9vqCF67R8ceNJQV3ushUwQEz0y' /root/.ssh/authorized_keys > /root/.ssh/authorized_keys.tmp038 || true
mv /root/.ssh/authorized_keys.tmp038 /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
ls -1 /var/tmp/Sunday-desktop-0.3.8-*.desktop-update.json 2>/dev/null || echo 'no manifest stages'
sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe /var/www/lamtools/desktop-update.json
printf '%s  %s\n' 'cdaa2daace3a2e192f7651bb07bfd4d976f1a1592e2be3c51831b963e16345da' '/var/www/lamtools/desktop-update.json' | sha256sum -c -
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
