set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\n' 'b7842a8357ea9f6becd4c433224d02269af21762eefeb6cd885461beb5fe32ee' '/var/tmp/Sunday-desktop-0.3.14-20261009.desktop-update.json' | sha256sum -c -
printf '%s  %s\n' 'c421d41eb452ae80c7d79a6a5fb06e4ab36c2ea1750c46774bd6c4ff4f3c1dc8' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
install -m 0644 /var/tmp/Sunday-desktop-0.3.14-20261009.desktop-update.json /var/www/lamtools/desktop-update.json.tmp
printf '%s  %s\n' 'b7842a8357ea9f6becd4c433224d02269af21762eefeb6cd885461beb5fe32ee' '/var/www/lamtools/desktop-update.json.tmp' | sha256sum -c -
mv /var/www/lamtools/desktop-update.json.tmp /var/www/lamtools/desktop-update.json
rm -- /var/tmp/Sunday-desktop-0.3.14-20261009.desktop-update.json
printf '%s  %s\n' 'b7842a8357ea9f6becd4c433224d02269af21762eefeb6cd885461beb5fe32ee' '/var/www/lamtools/desktop-update.json' | sha256sum -c -
cat /var/www/lamtools/desktop-update.json
curl -sS -D - -o /dev/null -H 'Origin: https://tauri.localhost' \
  --resolve 47.114.43.99.nip.io:443:127.0.0.1 https://47.114.43.99.nip.io/downloads/desktop-update.json \
  | grep -iE 'HTTP/|content-length' || true
date -u +%Y-%m-%dT%H:%M:%SZ
