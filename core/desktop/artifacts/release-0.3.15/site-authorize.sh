set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 1
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/0.3.14-mobile-0.1.48-20261009
test "$(sha256sum /var/www/lamtools/Sunday-mobile-latest.apk | cut -d' ' -f1)" = fc18f4c0676822d52884b490a2beb196ea3fb978dc4640e4e8acfc8904f5684a
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = 4267eac33b34698f85875f1c9e464194748d8e30ec0e381d3f10bbddac0efbed
test ! -e /var/www/lamtools/site-releases/0.3.15-mobile-0.1.48-20261009
test ! -e /var/tmp/Sunday-site-mobile-0.3.15-20261009.upload.tar.gz
printf '%s\n' 'restrict,command="internal-sftp" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEPtjtbHeXrJ/KqPgycLjMiiKy70ay7PvcSuPua1s7zF sunday-mobile-0.3.15-site-upload' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
date -u +%Y-%m-%dT%H:%M:%SZ
