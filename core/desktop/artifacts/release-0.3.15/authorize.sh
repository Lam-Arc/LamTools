set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 1
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = c421d41eb452ae80c7d79a6a5fb06e4ab36c2ea1750c46774bd6c4ff4f3c1dc8
test ! -e /var/www/lamtools/Sunday_0.3.15_x64-setup.exe
test ! -e /var/www/lamtools/Sunday-latest-x64-setup-0.3.14-before-0.3.15-20261009.exe
test ! -e /var/tmp/Sunday-desktop-0.3.15-20261009.desktop-update.json
# This release's stage is written by the fetch step (the CI asset), not by the
# upload: the bytes are already there and must hash to the published digest.
test -e /var/tmp/Sunday-desktop-0.3.15-20261009.upload.exe
printf '%s  %s
' '4267eac33b34698f85875f1c9e464194748d8e30ec0e381d3f10bbddac0efbed' '/var/tmp/Sunday-desktop-0.3.15-20261009.upload.exe' | sha256sum -c -
printf '%s\n' 'restrict,command="internal-sftp" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPWI3hEXMCZWgx/S8FC1zx9vc919unNhPcMx19t5j3da sunday-desktop-v0.3.15-upload' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
ls -l /var/www/lamtools/desktop-update.json
date -u +%Y-%m-%dT%H:%M:%SZ
