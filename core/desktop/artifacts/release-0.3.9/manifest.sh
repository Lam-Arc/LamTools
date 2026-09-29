set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\n' '7d86aae2e13b56a442efd256eab9ffc9008c1966083a8306680c29e6081d9b23' '/var/tmp/Sunday-desktop-0.3.9-20260929.desktop-update.json' | sha256sum -c -
printf '%s  %s\n' '7b4860b9424c09bd34d310e77e7dd449ab16c2eb5bc8788bc7e3ac6a4fd9bca9' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
install -m 0644 /var/tmp/Sunday-desktop-0.3.9-20260929.desktop-update.json /var/www/lamtools/desktop-update.json.tmp
printf '%s  %s\n' '7d86aae2e13b56a442efd256eab9ffc9008c1966083a8306680c29e6081d9b23' '/var/www/lamtools/desktop-update.json.tmp' | sha256sum -c -
mv /var/www/lamtools/desktop-update.json.tmp /var/www/lamtools/desktop-update.json
rm -- /var/tmp/Sunday-desktop-0.3.9-20260929.desktop-update.json
printf '%s  %s\n' '7d86aae2e13b56a442efd256eab9ffc9008c1966083a8306680c29e6081d9b23' '/var/www/lamtools/desktop-update.json' | sha256sum -c -
cat /var/www/lamtools/desktop-update.json
curl -sS -D - -o /dev/null -H 'Origin: https://tauri.localhost' \
  --resolve 47.114.43.99.nip.io:443:127.0.0.1 https://47.114.43.99.nip.io/downloads/desktop-update.json \
  | grep -iE 'HTTP/|content-length' || true
date -u +%Y-%m-%dT%H:%M:%SZ
