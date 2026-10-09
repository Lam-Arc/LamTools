set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 1
printf '%s  %s\n' '69e63994851bb0152838b3d37f4612c9a061157f10594c6a60527a782eb52409' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
printf '%s  %s\n' '69e63994851bb0152838b3d37f4612c9a061157f10594c6a60527a782eb52409' '/var/www/lamtools/Sunday_0.3.13_x64-setup.exe' | sha256sum -c -
test ! -e /var/www/lamtools/Sunday-latest-x64-setup-0.3.13-build1-before-republish-20261009.exe
test ! -e /var/tmp/Sunday-desktop-0.3.13-20261009-republish.upload.exe
test ! -e /var/tmp/Sunday-desktop-0.3.13-20261009-republish.desktop-update.json
printf '%s\n' 'restrict,command="internal-sftp" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEKmdSrC1wHlmStLtTUZrCCiz2PPGw6ndyqe9UgOZ3FQ sunday-desktop-v0.3.13-upload' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
date -u +%Y-%m-%dT%H:%M:%SZ
