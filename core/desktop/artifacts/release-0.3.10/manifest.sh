set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\n' 'd39ebefa3a193cc1a708da454c0358e20ea0f6c8201e9b1d7cebb7b045607a2b' '/var/tmp/Sunday-desktop-0.3.10-20260930.desktop-update.json' | sha256sum -c -
printf '%s  %s\n' 'c0af83099da29797ffdc3ed5f33ce0eac8b17dbe662e0c762eda5028af3d0548' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
install -m 0644 /var/tmp/Sunday-desktop-0.3.10-20260930.desktop-update.json /var/www/lamtools/desktop-update.json.tmp
printf '%s  %s\n' 'd39ebefa3a193cc1a708da454c0358e20ea0f6c8201e9b1d7cebb7b045607a2b' '/var/www/lamtools/desktop-update.json.tmp' | sha256sum -c -
mv /var/www/lamtools/desktop-update.json.tmp /var/www/lamtools/desktop-update.json
rm -- /var/tmp/Sunday-desktop-0.3.10-20260930.desktop-update.json
printf '%s  %s\n' 'd39ebefa3a193cc1a708da454c0358e20ea0f6c8201e9b1d7cebb7b045607a2b' '/var/www/lamtools/desktop-update.json' | sha256sum -c -
cat /var/www/lamtools/desktop-update.json
curl -sS -D - -o /dev/null -H 'Origin: https://tauri.localhost' \
  --resolve 47.114.43.99.nip.io:443:127.0.0.1 https://47.114.43.99.nip.io/downloads/desktop-update.json \
  | grep -iE 'HTTP/|content-length' || true
date -u +%Y-%m-%dT%H:%M:%SZ
