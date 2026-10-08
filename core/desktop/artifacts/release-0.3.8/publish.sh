set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\n' 'c76b67615955c870a8cdaab61fecf4e1c08e4d29b04bb1a123dd74b45b8c5e6e' '/var/tmp/Sunday-desktop-0.3.8-20260928.upload.exe' | sha256sum -c -
printf '%s  %s\n' '93338593d1cc06456fecc4bdff5d05fccbe7e5ca09a76c48c1b355e286eda2d1' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
test ! -e /var/www/lamtools/Sunday_0.3.8_x64-setup.exe
test ! -e /var/www/lamtools/Sunday-latest-x64-setup-0.3.7-before-0.3.8-20260928.exe
install -m 0755 /var/tmp/Sunday-desktop-0.3.8-20260928.upload.exe /var/www/lamtools/Sunday_0.3.8_x64-setup.exe.tmp
printf '%s  %s\n' 'c76b67615955c870a8cdaab61fecf4e1c08e4d29b04bb1a123dd74b45b8c5e6e' '/var/www/lamtools/Sunday_0.3.8_x64-setup.exe.tmp' | sha256sum -c -
ln /var/www/lamtools/Sunday-latest-x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup-0.3.7-before-0.3.8-20260928.exe
mv /var/www/lamtools/Sunday_0.3.8_x64-setup.exe.tmp /var/www/lamtools/Sunday_0.3.8_x64-setup.exe
ln /var/www/lamtools/Sunday_0.3.8_x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup.exe.new
mv -Tf /var/www/lamtools/Sunday-latest-x64-setup.exe.new /var/www/lamtools/Sunday-latest-x64-setup.exe
rm -- /var/tmp/Sunday-desktop-0.3.8-20260928.upload.exe
printf '%s  %s\n' 'c76b67615955c870a8cdaab61fecf4e1c08e4d29b04bb1a123dd74b45b8c5e6e' '/var/www/lamtools/Sunday_0.3.8_x64-setup.exe' | sha256sum -c -
printf '%s  %s\n' 'c76b67615955c870a8cdaab61fecf4e1c08e4d29b04bb1a123dd74b45b8c5e6e' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
printf '%s  %s\n' '93338593d1cc06456fecc4bdff5d05fccbe7e5ca09a76c48c1b355e286eda2d1' '/var/www/lamtools/Sunday-latest-x64-setup-0.3.7-before-0.3.8-20260928.exe' | sha256sum -c -
stat -c '%n %s' /var/www/lamtools/Sunday_0.3.8_x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup-0.3.7-before-0.3.8-20260928.exe
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
