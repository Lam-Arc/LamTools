set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
grep -vF 'AAAAC3NzaC1lZDI1NTE5AAAAILzdSAuLo/7g7JGZ26WsL7p33wYsb0/jXb9hJOW9VxBk' /root/.ssh/authorized_keys > /root/.ssh/authorized_keys.tmp-manifest || true
mv /root/.ssh/authorized_keys.tmp-manifest /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
grep -cF 'AAAAC3NzaC1lZDI1NTE5AAAAILzdSAuLo/7g7JGZ26WsL7p33wYsb0/jXb9hJOW9VxBk' /root/.ssh/authorized_keys || true
wc -l /root/.ssh/authorized_keys
ls -1 /var/tmp/Sunday-desktop-update-*.json 2>/dev/null || echo 'no stages'
sha256sum /var/www/lamtools/desktop-update.json
date -u +%Y-%m-%dT%H:%M:%SZ
