set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 1
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = c0af83099da29797ffdc3ed5f33ce0eac8b17dbe662e0c762eda5028af3d0548
test ! -e /var/www/lamtools/Sunday_0.3.11_x64-setup.exe
test ! -e /var/www/lamtools/Sunday-latest-x64-setup-0.3.10-before-0.3.11-20261008.exe
test ! -e /var/tmp/Sunday-desktop-0.3.11-20261008.desktop-update.json
# This release's stage is written by the fetch step (the CI asset), not by the
# upload: the bytes are already there and must hash to the published digest.
test -e /var/tmp/Sunday-desktop-0.3.11-20261008.upload.exe
printf '%s  %s
' '8f823e3e3b58ac86c6e10ec38a39129953ff99358911511f3bd9c105b2aec6ef' '/var/tmp/Sunday-desktop-0.3.11-20261008.upload.exe' | sha256sum -c -
printf '%s\n' 'restrict,command="internal-sftp" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBK9/luzo20nF8HYUojPmY/Wh/Sd0i+7bxdaOLqsheTL sunday-desktop-v0.3.11-upload' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
ls -l /var/www/lamtools/desktop-update.json
date -u +%Y-%m-%dT%H:%M:%SZ
