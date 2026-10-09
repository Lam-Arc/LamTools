set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 1
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = 285e0b2f3e38b320dd342313d33f6949d48f6d975f74f447b8eaee2e0b1429d6
test ! -e /var/www/lamtools/Sunday_0.3.13_x64-setup.exe
test ! -e /var/www/lamtools/Sunday-latest-x64-setup-0.3.12-before-0.3.13-20261009.exe
test ! -e /var/tmp/Sunday-desktop-0.3.13-20261009.desktop-update.json
# This release's stage is written by the fetch step (the CI asset), not by the
# upload: the bytes are already there and must hash to the published digest.
test -e /var/tmp/Sunday-desktop-0.3.13-20261009.upload.exe
printf '%s  %s
' '69e63994851bb0152838b3d37f4612c9a061157f10594c6a60527a782eb52409' '/var/tmp/Sunday-desktop-0.3.13-20261009.upload.exe' | sha256sum -c -
printf '%s\n' 'restrict,command="internal-sftp" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEKmdSrC1wHlmStLtTUZrCCiz2PPGw6ndyqe9UgOZ3FQ sunday-desktop-v0.3.13-upload' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
ls -l /var/www/lamtools/desktop-update.json
date -u +%Y-%m-%dT%H:%M:%SZ
