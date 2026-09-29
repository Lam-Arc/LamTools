set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\n' '7b4860b9424c09bd34d310e77e7dd449ab16c2eb5bc8788bc7e3ac6a4fd9bca9' '/var/tmp/Sunday-desktop-0.3.9-20260929.upload.exe' | sha256sum -c -
printf '%s  %s\n' 'c76b67615955c870a8cdaab61fecf4e1c08e4d29b04bb1a123dd74b45b8c5e6e' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
test ! -e /var/www/lamtools/Sunday_0.3.9_x64-setup.exe
test ! -e /var/www/lamtools/Sunday-latest-x64-setup-0.3.8-before-0.3.9-20260929.exe
install -m 0755 /var/tmp/Sunday-desktop-0.3.9-20260929.upload.exe /var/www/lamtools/Sunday_0.3.9_x64-setup.exe.tmp
printf '%s  %s\n' '7b4860b9424c09bd34d310e77e7dd449ab16c2eb5bc8788bc7e3ac6a4fd9bca9' '/var/www/lamtools/Sunday_0.3.9_x64-setup.exe.tmp' | sha256sum -c -
ln /var/www/lamtools/Sunday-latest-x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup-0.3.8-before-0.3.9-20260929.exe
mv /var/www/lamtools/Sunday_0.3.9_x64-setup.exe.tmp /var/www/lamtools/Sunday_0.3.9_x64-setup.exe
ln /var/www/lamtools/Sunday_0.3.9_x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup.exe.new
mv -Tf /var/www/lamtools/Sunday-latest-x64-setup.exe.new /var/www/lamtools/Sunday-latest-x64-setup.exe
rm -- /var/tmp/Sunday-desktop-0.3.9-20260929.upload.exe
printf '%s  %s\n' '7b4860b9424c09bd34d310e77e7dd449ab16c2eb5bc8788bc7e3ac6a4fd9bca9' '/var/www/lamtools/Sunday_0.3.9_x64-setup.exe' | sha256sum -c -
printf '%s  %s\n' '7b4860b9424c09bd34d310e77e7dd449ab16c2eb5bc8788bc7e3ac6a4fd9bca9' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
printf '%s  %s\n' 'c76b67615955c870a8cdaab61fecf4e1c08e4d29b04bb1a123dd74b45b8c5e6e' '/var/www/lamtools/Sunday-latest-x64-setup-0.3.8-before-0.3.9-20260929.exe' | sha256sum -c -
stat -c '%n %s' /var/www/lamtools/Sunday_0.3.9_x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup-0.3.8-before-0.3.9-20260929.exe
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
