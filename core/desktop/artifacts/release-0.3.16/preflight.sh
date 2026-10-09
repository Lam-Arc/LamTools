set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
readlink -f /var/www/lamtools/site
ls -1 /var/www/lamtools/site-releases/ | tail -4
echo "latest link: $(stat -c '%h %i' /var/www/lamtools/Sunday-latest-x64-setup.exe)"
sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe
cat /var/www/lamtools/desktop-update.json
ls -l /var/www/lamtools/Sunday_0.3.16_x64-setup.exe 2>/dev/null || echo "absent /var/www/lamtools/Sunday_0.3.16_x64-setup.exe"
ls -l /var/www/lamtools/Sunday-latest-x64-setup-0.3.15-before-0.3.16-20261009.exe 2>/dev/null || echo "absent /var/www/lamtools/Sunday-latest-x64-setup-0.3.15-before-0.3.16-20261009.exe"
ls -l /var/tmp/Sunday-desktop-0.3.16-20261009.upload.exe 2>/dev/null || echo "absent /var/tmp/Sunday-desktop-0.3.16-20261009.upload.exe"
ls -l /var/tmp/Sunday-site-mobile-0.3.16-20261009.upload.tar.gz 2>/dev/null || echo "absent /var/tmp/Sunday-site-mobile-0.3.16-20261009.upload.tar.gz"
ls -ld /var/www/lamtools/site-releases/0.3.16-mobile-0.1.48-20261009 2>/dev/null || echo "absent /var/www/lamtools/site-releases/0.3.16-mobile-0.1.48-20261009"
wc -l < /root/.ssh/authorized_keys
date -u +%Y-%m-%dT%H:%M:%SZ
