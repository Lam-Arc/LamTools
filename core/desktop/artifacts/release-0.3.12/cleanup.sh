set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
grep -vF 'AAAAC3NzaC1lZDI1NTE5AAAAIP93jdvRVmS0t5SJ4/2qtPR+QvExNsOIraYWo8t8h1XM' /root/.ssh/authorized_keys > /root/.ssh/authorized_keys.tmpv0.3.12 || true
mv /root/.ssh/authorized_keys.tmpv0.3.12 /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
grep -cF 'AAAAC3NzaC1lZDI1NTE5AAAAIP93jdvRVmS0t5SJ4/2qtPR+QvExNsOIraYWo8t8h1XM' /root/.ssh/authorized_keys || true
wc -l /root/.ssh/authorized_keys
ls -1 /var/tmp/Sunday-desktop-0.3.12-*.upload.exe 2>/dev/null || echo 'no stages'
sha256sum /var/www/lamtools/Sunday_0.3.12_x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup-0.3.11-before-0.3.12-20261009.exe /var/www/lamtools/desktop-update.json
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
