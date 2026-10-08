set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\n' '62a13514bcae1ce5528450428d9ca3ddfb90c12d4ab5d0b0b19f6b4289ae9276' '/var/tmp/Sunday-site-0.3.8-20260928.upload.tar.gz' | sha256sum -c -
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/0.3.7-mobile-0.1.45-20260928
test ! -e /var/www/lamtools/site-releases/0.3.8-mobile-0.1.45-20260928
mkdir -m 0755 /var/www/lamtools/site-releases/0.3.8-mobile-0.1.45-20260928
tar -xzf /var/tmp/Sunday-site-0.3.8-20260928.upload.tar.gz -C /var/www/lamtools/site-releases/0.3.8-mobile-0.1.45-20260928 --no-same-owner
find /var/www/lamtools/site-releases/0.3.8-mobile-0.1.45-20260928 -type d -exec chmod 755 {} +
find /var/www/lamtools/site-releases/0.3.8-mobile-0.1.45-20260928 -type f -exec chmod 644 {} +
test -f /var/www/lamtools/site-releases/0.3.8-mobile-0.1.45-20260928/index.html
grep -R -q '0.3.8' /var/www/lamtools/site-releases/0.3.8-mobile-0.1.45-20260928/assets
grep -R -q '0.1.45' /var/www/lamtools/site-releases/0.3.8-mobile-0.1.45-20260928/assets
ln -s /var/www/lamtools/site-releases/0.3.8-mobile-0.1.45-20260928 /var/www/lamtools/site.new0380145
mv -Tf /var/www/lamtools/site.new0380145 /var/www/lamtools/site
rm -- /var/tmp/Sunday-site-0.3.8-20260928.upload.tar.gz
readlink -f /var/www/lamtools/site
ls -1 /var/www/lamtools/site-releases/ | tail -4
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
