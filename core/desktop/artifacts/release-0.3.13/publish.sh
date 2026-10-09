set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\n' '69e63994851bb0152838b3d37f4612c9a061157f10594c6a60527a782eb52409' '/var/tmp/Sunday-desktop-0.3.13-20261009.upload.exe' | sha256sum -c -
printf '%s  %s\n' '285e0b2f3e38b320dd342313d33f6949d48f6d975f74f447b8eaee2e0b1429d6' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
test ! -e /var/www/lamtools/Sunday_0.3.13_x64-setup.exe
test ! -e /var/www/lamtools/Sunday-latest-x64-setup-0.3.12-before-0.3.13-20261009.exe
install -m 0755 /var/tmp/Sunday-desktop-0.3.13-20261009.upload.exe /var/www/lamtools/Sunday_0.3.13_x64-setup.exe.tmp
printf '%s  %s\n' '69e63994851bb0152838b3d37f4612c9a061157f10594c6a60527a782eb52409' '/var/www/lamtools/Sunday_0.3.13_x64-setup.exe.tmp' | sha256sum -c -
ln /var/www/lamtools/Sunday-latest-x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup-0.3.12-before-0.3.13-20261009.exe
mv /var/www/lamtools/Sunday_0.3.13_x64-setup.exe.tmp /var/www/lamtools/Sunday_0.3.13_x64-setup.exe
ln /var/www/lamtools/Sunday_0.3.13_x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup.exe.new
mv -Tf /var/www/lamtools/Sunday-latest-x64-setup.exe.new /var/www/lamtools/Sunday-latest-x64-setup.exe
rm -- /var/tmp/Sunday-desktop-0.3.13-20261009.upload.exe
printf '%s  %s\n' '69e63994851bb0152838b3d37f4612c9a061157f10594c6a60527a782eb52409' '/var/www/lamtools/Sunday_0.3.13_x64-setup.exe' | sha256sum -c -
printf '%s  %s\n' '69e63994851bb0152838b3d37f4612c9a061157f10594c6a60527a782eb52409' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
printf '%s  %s\n' '285e0b2f3e38b320dd342313d33f6949d48f6d975f74f447b8eaee2e0b1429d6' '/var/www/lamtools/Sunday-latest-x64-setup-0.3.12-before-0.3.13-20261009.exe' | sha256sum -c -
stat -c '%n %s' /var/www/lamtools/Sunday_0.3.13_x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup-0.3.12-before-0.3.13-20261009.exe
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
