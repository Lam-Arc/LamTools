set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\n' 'ca07adf50f3f8c20accfbe74d34a820152b4b4a436ea7507a521004d69af371f' '/var/tmp/Sunday-site-mobile-0.3.16-20261009.upload.tar.gz' | sha256sum -c -
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/0.3.15-mobile-0.1.48-20261009
test ! -e /var/www/lamtools/site-releases/0.3.16-mobile-0.1.48-20261009
mkdir -m 0755 /var/www/lamtools/site-releases/0.3.16-mobile-0.1.48-20261009
tar -xzf /var/tmp/Sunday-site-mobile-0.3.16-20261009.upload.tar.gz -C /var/www/lamtools/site-releases/0.3.16-mobile-0.1.48-20261009 --no-same-owner
find /var/www/lamtools/site-releases/0.3.16-mobile-0.1.48-20261009 -type d -exec chmod 755 {} +
find /var/www/lamtools/site-releases/0.3.16-mobile-0.1.48-20261009 -type f -exec chmod 644 {} +
test -f /var/www/lamtools/site-releases/0.3.16-mobile-0.1.48-20261009/index.html
grep -R -q '0.3.16' /var/www/lamtools/site-releases/0.3.16-mobile-0.1.48-20261009/assets
ln -s /var/www/lamtools/site-releases/0.3.16-mobile-0.1.48-20261009 /var/www/lamtools/site.new0316
mv -Tf /var/www/lamtools/site.new0316 /var/www/lamtools/site
rm -- /var/tmp/Sunday-site-mobile-0.3.16-20261009.upload.tar.gz
readlink -f /var/www/lamtools/site
curl -sS -m 60 "https://47.114.43.99.nip.io/assets/$(grep -o 'assets/main-[A-Za-z0-9._-]*\.js' /var/www/lamtools/site-releases/0.3.16-mobile-0.1.48-20261009/index.html | head -1 | sed 's|assets/||')" | grep -o '0.3.16' | head -1
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
