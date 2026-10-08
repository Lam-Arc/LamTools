set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
readlink -f /var/www/lamtools/site
ls -1 /var/www/lamtools/site-releases/ | tail -4
sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe
cat /var/www/lamtools/desktop-update.json
sha256sum /var/www/lamtools/Sunday-mobile-latest.apk
stat -c '%n %a %s' /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
for path in /var/www/lamtools/Sunday_0.3.8_x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup-0.3.7-before-0.3.8-20260928.exe /var/tmp/Sunday-desktop-0.3.8-20260928.upload.exe /var/tmp/Sunday-desktop-0.3.8-20260928.desktop-update.json; do
  if [ -e "$path" ]; then echo "PRESENT $path"; else echo "absent $path"; fi
done
date -u +%Y-%m-%dT%H:%M:%SZ
