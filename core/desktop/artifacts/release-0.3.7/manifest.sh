set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\n' '0beae41aad6dc93bab932f90c7109aba93e8c7bd23cfa083652be782f687c725' '/var/tmp/Sunday-desktop-0.3.7-20260926.desktop-update.json' | sha256sum -c -
printf '%s  %s\n' '93338593d1cc06456fecc4bdff5d05fccbe7e5ca09a76c48c1b355e286eda2d1' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
install -m 0644 /var/tmp/Sunday-desktop-0.3.7-20260926.desktop-update.json /var/www/lamtools/desktop-update.json.tmp
printf '%s  %s\n' '0beae41aad6dc93bab932f90c7109aba93e8c7bd23cfa083652be782f687c725' '/var/www/lamtools/desktop-update.json.tmp' | sha256sum -c -
mv /var/www/lamtools/desktop-update.json.tmp /var/www/lamtools/desktop-update.json
rm -- /var/tmp/Sunday-desktop-0.3.7-20260926.desktop-update.json
printf '%s  %s\n' '0beae41aad6dc93bab932f90c7109aba93e8c7bd23cfa083652be782f687c725' '/var/www/lamtools/desktop-update.json' | sha256sum -c -
cat /var/www/lamtools/desktop-update.json
curl -sS -D - -o /dev/null -H 'Origin: https://tauri.localhost' \
  --resolve 47.114.43.99.nip.io:443:127.0.0.1 https://47.114.43.99.nip.io/downloads/desktop-update.json \
  | grep -iE 'HTTP/|content-length' || true
date -u +%Y-%m-%dT%H:%M:%SZ
