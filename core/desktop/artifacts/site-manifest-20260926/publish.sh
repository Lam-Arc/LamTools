set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\n' 'e06c9001cbaedb57744320af7948b0090e4e798685b533899fec458f2a9df98b' '/var/tmp/Sunday-desktop-update-20260926.json' | sha256sum -c -
install -m 0644 /var/tmp/Sunday-desktop-update-20260926.json.tmp-guard /dev/null 2>/dev/null || true
install -m 0644 /var/tmp/Sunday-desktop-update-20260926.json /var/www/lamtools/desktop-update.json.tmp
printf '%s  %s\n' 'e06c9001cbaedb57744320af7948b0090e4e798685b533899fec458f2a9df98b' '/var/www/lamtools/desktop-update.json.tmp' | sha256sum -c -
mv /var/www/lamtools/desktop-update.json.tmp /var/www/lamtools/desktop-update.json
printf '%s  %s\n' 'e06c9001cbaedb57744320af7948b0090e4e798685b533899fec458f2a9df98b' '/var/www/lamtools/desktop-update.json' | sha256sum -c -
rm -- /var/tmp/Sunday-desktop-update-20260926.json
echo '--- served with the WebView origin ---'
curl -sS -D - -o /dev/null -H 'Origin: https://tauri.localhost' \
  --resolve 47.114.43.99.nip.io:443:127.0.0.1 https://47.114.43.99.nip.io/downloads/desktop-update.json \
  | grep -iE 'HTTP/|content-type|content-length' || true
cat /var/www/lamtools/desktop-update.json
stat -c '%n %s %y' /var/www/lamtools/desktop-update.json
date -u +%Y-%m-%dT%H:%M:%SZ
