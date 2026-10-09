set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
printf '%s  %s\n' '69e63994851bb0152838b3d37f4612c9a061157f10594c6a60527a782eb52409' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
printf '%s  %s\n' '69e63994851bb0152838b3d37f4612c9a061157f10594c6a60527a782eb52409' '/var/www/lamtools/Sunday_0.3.13_x64-setup.exe' | sha256sum -c -
printf '%s  %s\n' '0016a410549484de8b8e22777891e977a98b49645f778e94f8c0a40befa197ce' '/var/www/lamtools/desktop-update.json' | sha256sum -c -
cat /var/www/lamtools/desktop-update.json
wc -l /root/.ssh/authorized_keys
for path in /var/www/lamtools/Sunday-latest-x64-setup-0.3.13-build1-before-republish-20261009.exe /var/tmp/Sunday-desktop-0.3.13-20261009-republish.upload.exe /var/tmp/Sunday-desktop-0.3.13-20261009-republish.desktop-update.json; do
  if [ -e "$path" ]; then echo "PRESENT $path"; else echo "absent $path"; fi
done
date -u +%Y-%m-%dT%H:%M:%SZ
