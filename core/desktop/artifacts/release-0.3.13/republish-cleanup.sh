set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
grep -vF 'AAAAC3NzaC1lZDI1NTE5AAAAIEKmdSrC1wHlmStLtTUZrCCiz2PPGw6ndyqe9UgOZ3FQ' /root/.ssh/authorized_keys > /root/.ssh/authorized_keys.tmp-rp || true
mv /root/.ssh/authorized_keys.tmp-rp /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
grep -cF 'AAAAC3NzaC1lZDI1NTE5AAAAIEKmdSrC1wHlmStLtTUZrCCiz2PPGw6ndyqe9UgOZ3FQ' /root/.ssh/authorized_keys || true
wc -l /root/.ssh/authorized_keys
ls -1 /var/tmp/Sunday-desktop-0.3.13-*republish* 2>/dev/null || echo 'no republish stages'
sha256sum /var/www/lamtools/Sunday_0.3.13_x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup-0.3.13-build1-before-republish-20261009.exe /var/www/lamtools/desktop-update.json
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
