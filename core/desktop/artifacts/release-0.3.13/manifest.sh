set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\n' '0016a410549484de8b8e22777891e977a98b49645f778e94f8c0a40befa197ce' '/var/tmp/Sunday-desktop-0.3.13-20261009.desktop-update.json' | sha256sum -c -
printf '%s  %s\n' '69e63994851bb0152838b3d37f4612c9a061157f10594c6a60527a782eb52409' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
install -m 0644 /var/tmp/Sunday-desktop-0.3.13-20261009.desktop-update.json /var/www/lamtools/desktop-update.json.tmp
printf '%s  %s\n' '0016a410549484de8b8e22777891e977a98b49645f778e94f8c0a40befa197ce' '/var/www/lamtools/desktop-update.json.tmp' | sha256sum -c -
mv /var/www/lamtools/desktop-update.json.tmp /var/www/lamtools/desktop-update.json
rm -- /var/tmp/Sunday-desktop-0.3.13-20261009.desktop-update.json
printf '%s  %s\n' '0016a410549484de8b8e22777891e977a98b49645f778e94f8c0a40befa197ce' '/var/www/lamtools/desktop-update.json' | sha256sum -c -
cat /var/www/lamtools/desktop-update.json
curl -sS -D - -o /dev/null -H 'Origin: https://tauri.localhost' \
  --resolve 47.114.43.99.nip.io:443:127.0.0.1 https://47.114.43.99.nip.io/downloads/desktop-update.json \
  | grep -iE 'HTTP/|content-length' || true
date -u +%Y-%m-%dT%H:%M:%SZ
