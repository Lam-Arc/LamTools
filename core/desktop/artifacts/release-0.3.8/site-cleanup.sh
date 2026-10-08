set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
grep -vF 'AAAAC3NzaC1lZDI1NTE5AAAAIFQXbufH4zYLseTyBFJpAWJgQFgioJNKTEvuNXkadVUx' /root/.ssh/authorized_keys > /root/.ssh/authorized_keys.tmp038 || true
mv /root/.ssh/authorized_keys.tmp038 /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
ls -1 /var/tmp/Sunday-site-0.3.8-*.upload.tar.gz 2>/dev/null || echo 'no stages'
readlink -f /var/www/lamtools/site
sha256sum /var/www/lamtools/Sunday-mobile-latest.apk /var/www/lamtools/mobile-update.json
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
