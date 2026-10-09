set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\n' '4267eac33b34698f85875f1c9e464194748d8e30ec0e381d3f10bbddac0efbed' '/var/tmp/Sunday-desktop-0.3.15-20261009.upload.exe' | sha256sum -c -
printf '%s  %s\n' 'c421d41eb452ae80c7d79a6a5fb06e4ab36c2ea1750c46774bd6c4ff4f3c1dc8' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
test ! -e /var/www/lamtools/Sunday_0.3.15_x64-setup.exe
test ! -e /var/www/lamtools/Sunday-latest-x64-setup-0.3.14-before-0.3.15-20261009.exe
install -m 0755 /var/tmp/Sunday-desktop-0.3.15-20261009.upload.exe /var/www/lamtools/Sunday_0.3.15_x64-setup.exe.tmp
printf '%s  %s\n' '4267eac33b34698f85875f1c9e464194748d8e30ec0e381d3f10bbddac0efbed' '/var/www/lamtools/Sunday_0.3.15_x64-setup.exe.tmp' | sha256sum -c -
ln /var/www/lamtools/Sunday-latest-x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup-0.3.14-before-0.3.15-20261009.exe
mv /var/www/lamtools/Sunday_0.3.15_x64-setup.exe.tmp /var/www/lamtools/Sunday_0.3.15_x64-setup.exe
ln /var/www/lamtools/Sunday_0.3.15_x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup.exe.new
mv -Tf /var/www/lamtools/Sunday-latest-x64-setup.exe.new /var/www/lamtools/Sunday-latest-x64-setup.exe
rm -- /var/tmp/Sunday-desktop-0.3.15-20261009.upload.exe
printf '%s  %s\n' '4267eac33b34698f85875f1c9e464194748d8e30ec0e381d3f10bbddac0efbed' '/var/www/lamtools/Sunday_0.3.15_x64-setup.exe' | sha256sum -c -
printf '%s  %s\n' '4267eac33b34698f85875f1c9e464194748d8e30ec0e381d3f10bbddac0efbed' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
printf '%s  %s\n' 'c421d41eb452ae80c7d79a6a5fb06e4ab36c2ea1750c46774bd6c4ff4f3c1dc8' '/var/www/lamtools/Sunday-latest-x64-setup-0.3.14-before-0.3.15-20261009.exe' | sha256sum -c -
stat -c '%n %s' /var/www/lamtools/Sunday_0.3.15_x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup-0.3.14-before-0.3.15-20261009.exe
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
