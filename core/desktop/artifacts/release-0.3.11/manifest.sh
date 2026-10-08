set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\n' 'b14e8d2bb87052f670f7789167e08dabb204686eb5e506b77ee0a5b5684d07f5' '/var/tmp/Sunday-desktop-0.3.11-20261008.desktop-update.json' | sha256sum -c -
printf '%s  %s\n' '8f823e3e3b58ac86c6e10ec38a39129953ff99358911511f3bd9c105b2aec6ef' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
install -m 0644 /var/tmp/Sunday-desktop-0.3.11-20261008.desktop-update.json /var/www/lamtools/desktop-update.json.tmp
printf '%s  %s\n' 'b14e8d2bb87052f670f7789167e08dabb204686eb5e506b77ee0a5b5684d07f5' '/var/www/lamtools/desktop-update.json.tmp' | sha256sum -c -
mv /var/www/lamtools/desktop-update.json.tmp /var/www/lamtools/desktop-update.json
rm -- /var/tmp/Sunday-desktop-0.3.11-20261008.desktop-update.json
printf '%s  %s\n' 'b14e8d2bb87052f670f7789167e08dabb204686eb5e506b77ee0a5b5684d07f5' '/var/www/lamtools/desktop-update.json' | sha256sum -c -
cat /var/www/lamtools/desktop-update.json
curl -sS -D - -o /dev/null -H 'Origin: https://tauri.localhost' \
  --resolve 47.114.43.99.nip.io:443:127.0.0.1 https://47.114.43.99.nip.io/downloads/desktop-update.json \
  | grep -iE 'HTTP/|content-length' || true
date -u +%Y-%m-%dT%H:%M:%SZ
