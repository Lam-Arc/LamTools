set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 1
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = c76b67615955c870a8cdaab61fecf4e1c08e4d29b04bb1a123dd74b45b8c5e6e
test ! -e /var/www/lamtools/Sunday_0.3.9_x64-setup.exe
test ! -e /var/www/lamtools/Sunday-latest-x64-setup-0.3.8-before-0.3.9-20260929.exe
test ! -e /var/tmp/Sunday-desktop-0.3.9-20260929.upload.exe
test ! -e /var/tmp/Sunday-desktop-0.3.9-20260929.desktop-update.json
printf '%s\n' 'restrict,command="internal-sftp" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOTYaNFDUWfn46dxKiwHPLz9ridEvDEywPwykguQW0iD sunday-desktop-037-upload' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
ls -l /var/www/lamtools/desktop-update.json
date -u +%Y-%m-%dT%H:%M:%SZ
