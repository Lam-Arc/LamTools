set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\n' '8f823e3e3b58ac86c6e10ec38a39129953ff99358911511f3bd9c105b2aec6ef' '/var/tmp/Sunday-desktop-0.3.11-20261008.upload.exe' | sha256sum -c -
printf '%s  %s\n' 'c0af83099da29797ffdc3ed5f33ce0eac8b17dbe662e0c762eda5028af3d0548' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
test ! -e /var/www/lamtools/Sunday_0.3.11_x64-setup.exe
test ! -e /var/www/lamtools/Sunday-latest-x64-setup-0.3.10-before-0.3.11-20261008.exe
install -m 0755 /var/tmp/Sunday-desktop-0.3.11-20261008.upload.exe /var/www/lamtools/Sunday_0.3.11_x64-setup.exe.tmp
printf '%s  %s\n' '8f823e3e3b58ac86c6e10ec38a39129953ff99358911511f3bd9c105b2aec6ef' '/var/www/lamtools/Sunday_0.3.11_x64-setup.exe.tmp' | sha256sum -c -
ln /var/www/lamtools/Sunday-latest-x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup-0.3.10-before-0.3.11-20261008.exe
mv /var/www/lamtools/Sunday_0.3.11_x64-setup.exe.tmp /var/www/lamtools/Sunday_0.3.11_x64-setup.exe
ln /var/www/lamtools/Sunday_0.3.11_x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup.exe.new
mv -Tf /var/www/lamtools/Sunday-latest-x64-setup.exe.new /var/www/lamtools/Sunday-latest-x64-setup.exe
rm -- /var/tmp/Sunday-desktop-0.3.11-20261008.upload.exe
printf '%s  %s\n' '8f823e3e3b58ac86c6e10ec38a39129953ff99358911511f3bd9c105b2aec6ef' '/var/www/lamtools/Sunday_0.3.11_x64-setup.exe' | sha256sum -c -
printf '%s  %s\n' '8f823e3e3b58ac86c6e10ec38a39129953ff99358911511f3bd9c105b2aec6ef' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
printf '%s  %s\n' 'c0af83099da29797ffdc3ed5f33ce0eac8b17dbe662e0c762eda5028af3d0548' '/var/www/lamtools/Sunday-latest-x64-setup-0.3.10-before-0.3.11-20261008.exe' | sha256sum -c -
stat -c '%n %s' /var/www/lamtools/Sunday_0.3.11_x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup-0.3.10-before-0.3.11-20261008.exe
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
