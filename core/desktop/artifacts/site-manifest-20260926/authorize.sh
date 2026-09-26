set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 1
test ! -e /var/tmp/Sunday-desktop-update-20260926.json
ls -l /var/www/lamtools/desktop-update.json 2>/dev/null || echo 'no manifest published yet'
printf '%s\n' 'restrict,command="internal-sftp" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILzdSAuLo/7g7JGZ26WsL7p33wYsb0/jXb9hJOW9VxBk sunday-desktop-manifest-20260926' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
date -u +%Y-%m-%dT%H:%M:%SZ
