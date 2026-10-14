set -eu
printf 'FINAL_CONFIRM_UTC='; date -u +%Y-%m-%dT%H:%M:%SZ
printf 'AUTHORIZED_KEYS_LINES='; wc -l < /root/.ssh/authorized_keys
if grep -Fq 'AAAAC3NzaC1lZDI1NTE5AAAAID45J4CxMJeeFTFb+FabOZC8YNcjdhBKaVwQWuWm2QO9' /root/.ssh/authorized_keys; then echo TEMP_KEY_PRESENT; exit 1; else echo TEMP_KEY_REVOKED; fi
systemctl is-active caddy-lamtools lamtools-relay
printf 'SITE='; readlink -f /var/www/lamtools/site
printf 'MANIFEST_VERSION='; python3 -c 'import json;print(json.load(open("/var/www/lamtools/desktop-update.json"))["version"])'
printf 'INSTALLER_SHA='; sha256sum /var/www/lamtools/Sunday_0.3.17_x64-setup.exe
for path in /var/tmp/Sunday-desktop-0.3.17-20261013.upload.exe /var/tmp/Sunday-desktop-0.3.17-20261013.parallel.exe /var/tmp/Sunday-site-mobile-0.3.17-20261013.upload.tar.gz /var/tmp/dl-0.3.17-20261013T0935 /tmp/sunday-0317-public-versioned-20261013.exe /tmp/sunday-0317-public-latest-20261013.exe; do
  if [ -e "$path" ]; then echo "STAGE_PRESENT $path"; exit 1; else echo "STAGE_ABSENT $path"; fi
done
printf 'FINAL_CONFIRM_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
