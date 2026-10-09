set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\n' '1ac866a41dab56e8092219249b150388df16487ce3578ebab24f8b899213dbd8' '/var/tmp/Sunday-desktop-0.3.12-20261009.desktop-update.json' | sha256sum -c -
printf '%s  %s\n' '285e0b2f3e38b320dd342313d33f6949d48f6d975f74f447b8eaee2e0b1429d6' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
install -m 0644 /var/tmp/Sunday-desktop-0.3.12-20261009.desktop-update.json /var/www/lamtools/desktop-update.json.tmp
printf '%s  %s\n' '1ac866a41dab56e8092219249b150388df16487ce3578ebab24f8b899213dbd8' '/var/www/lamtools/desktop-update.json.tmp' | sha256sum -c -
mv /var/www/lamtools/desktop-update.json.tmp /var/www/lamtools/desktop-update.json
rm -- /var/tmp/Sunday-desktop-0.3.12-20261009.desktop-update.json
printf '%s  %s\n' '1ac866a41dab56e8092219249b150388df16487ce3578ebab24f8b899213dbd8' '/var/www/lamtools/desktop-update.json' | sha256sum -c -
cat /var/www/lamtools/desktop-update.json
curl -sS -D - -o /dev/null -H 'Origin: https://tauri.localhost' \
  --resolve 47.114.43.99.nip.io:443:127.0.0.1 https://47.114.43.99.nip.io/downloads/desktop-update.json \
  | grep -iE 'HTTP/|content-length' || true
date -u +%Y-%m-%dT%H:%M:%SZ
