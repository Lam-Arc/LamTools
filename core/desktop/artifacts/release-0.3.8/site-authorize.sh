set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 1
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/0.3.7-mobile-0.1.45-20260928
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = c76b67615955c870a8cdaab61fecf4e1c08e4d29b04bb1a123dd74b45b8c5e6e
test "$(sha256sum /var/www/lamtools/Sunday-mobile-latest.apk | cut -d' ' -f1)" = fcf64cb9cd695d24b82c43e7fc64aae6afbbbc0b59dce4d9eae2cd598a2f571f
test ! -e /var/www/lamtools/site-releases/0.3.8-mobile-0.1.45-20260928
test ! -e /var/tmp/Sunday-site-0.3.8-20260928.upload.tar.gz
printf '%s\n' 'restrict,command="internal-sftp" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFQXbufH4zYLseTyBFJpAWJgQFgioJNKTEvuNXkadVUx sunday-desktop-0.3.8-site-upload' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
date -u +%Y-%m-%dT%H:%M:%SZ
