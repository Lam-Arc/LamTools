set -eu
printf 'CLEANUP_CHECK_UTC='; date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
printf 'AUTHORIZED_KEY_COUNT='; grep -Fc 'AAAAC3NzaC1lZDI1NTE5AAAAID45J4CxMJeeFTFb+FabOZC8YNcjdhBKaVwQWuWm2QO9' /root/.ssh/authorized_keys
printf 'AUTHORIZED_KEYS_LINES='; wc -l < /root/.ssh/authorized_keys
for path in /var/tmp/Sunday-desktop-0.3.17-20261013.upload.exe /var/tmp/Sunday-site-mobile-0.3.17-20261013.upload.tar.gz /var/tmp/dl-0.3.17-20261013T0935 /tmp/sunday-0317-public-versioned-20261013.exe /tmp/sunday-0317-public-latest-20261013.exe; do
  if [ -e "$path" ]; then ls -ld "$path"; else echo "ABSENT $path"; fi
done
if [ -d /var/tmp/dl-0.3.17-20261013T0935 ]; then find /var/tmp/dl-0.3.17-20261013T0935 -maxdepth 1 -type f -printf '%f %s bytes\n' | sort; fi
printf 'SITE='; readlink -f /var/www/lamtools/site
printf 'VERSIONED_SHA='; sha256sum /var/www/lamtools/Sunday_0.3.17_x64-setup.exe
