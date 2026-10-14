set -eu
printf 'PREFLIGHT_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
printf 'SITE_POINTER='; readlink -f /var/www/lamtools/site
printf 'DESKTOP_MANIFEST='; cat /var/www/lamtools/desktop-update.json
printf 'MOBILE_MANIFEST='; cat /var/www/lamtools/mobile-update.json
printf 'LATEST_SHA='; sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe
printf 'SITE_RELEASES='; ls -1 /var/www/lamtools/site-releases | tail -8
printf 'AUTHORIZED_KEYS_LINES='; wc -l < /root/.ssh/authorized_keys
for path in \
  /var/www/lamtools/Sunday_0.3.18_x64-setup.exe \
  /var/www/lamtools/Sunday-latest-x64-setup-0.3.17-before-0.3.18-20261013.exe \
  /var/www/lamtools/desktop-update-0.3.17-before-0.3.18-20261013.json \
  /var/www/lamtools/site-releases/0.3.18-mobile-0.1.48-20261013 \
  /var/www/lamtools/site.new0318 \
  /usr/local/bin/sync-public-site.sh-0.3.17-before-0.3.18-20261013 \
  /usr/local/bin/sync-public-site.sh.new0318 \
  /var/tmp/Sunday-desktop-0.3.18-20261013.upload.exe \
  /var/tmp/Sunday-desktop-0.3.18-20261013.desktop-update.json \
  /var/tmp/Sunday-site-mobile-0.3.18-20261013.upload.tar.gz; do
  if [ -e "$path" ]; then echo "EXISTS $path"; else echo "ABSENT $path"; fi
done
printf 'SYNC_SCRIPT='; test -x /usr/local/bin/sync-public-site.sh && echo present
printf 'SYNC_SHA256='; sha256sum /usr/local/bin/sync-public-site.sh
printf 'SYNC_HAS_LINUX_VERSION='; if grep -q 'linux_version' /usr/local/bin/sync-public-site.sh; then echo yes; else echo no; fi
printf 'PREFLIGHT_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
