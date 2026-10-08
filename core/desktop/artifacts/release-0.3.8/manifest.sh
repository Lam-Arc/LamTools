set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\n' 'cdaa2daace3a2e192f7651bb07bfd4d976f1a1592e2be3c51831b963e16345da' '/var/tmp/Sunday-desktop-0.3.8-20260928.desktop-update.json' | sha256sum -c -
printf '%s  %s\n' 'c76b67615955c870a8cdaab61fecf4e1c08e4d29b04bb1a123dd74b45b8c5e6e' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
install -m 0644 /var/tmp/Sunday-desktop-0.3.8-20260928.desktop-update.json /var/www/lamtools/desktop-update.json.tmp
printf '%s  %s\n' 'cdaa2daace3a2e192f7651bb07bfd4d976f1a1592e2be3c51831b963e16345da' '/var/www/lamtools/desktop-update.json.tmp' | sha256sum -c -
mv /var/www/lamtools/desktop-update.json.tmp /var/www/lamtools/desktop-update.json
rm -- /var/tmp/Sunday-desktop-0.3.8-20260928.desktop-update.json
printf '%s  %s\n' 'cdaa2daace3a2e192f7651bb07bfd4d976f1a1592e2be3c51831b963e16345da' '/var/www/lamtools/desktop-update.json' | sha256sum -c -
cat /var/www/lamtools/desktop-update.json
date -u +%Y-%m-%dT%H:%M:%SZ
