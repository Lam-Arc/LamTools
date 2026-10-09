set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\n' 'f84b53ebf330dd5e37b354288597279d7deaf439c182777127373b096be49b35' '/var/tmp/Sunday-site-mobile-0.3.15-20261009.upload.tar.gz' | sha256sum -c -
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/0.3.14-mobile-0.1.48-20261009
test ! -e /var/www/lamtools/site-releases/0.3.15-mobile-0.1.48-20261009
mkdir -m 0755 /var/www/lamtools/site-releases/0.3.15-mobile-0.1.48-20261009
tar -xzf /var/tmp/Sunday-site-mobile-0.3.15-20261009.upload.tar.gz -C /var/www/lamtools/site-releases/0.3.15-mobile-0.1.48-20261009 --no-same-owner
find /var/www/lamtools/site-releases/0.3.15-mobile-0.1.48-20261009 -type d -exec chmod 755 {} +
find /var/www/lamtools/site-releases/0.3.15-mobile-0.1.48-20261009 -type f -exec chmod 644 {} +
test -f /var/www/lamtools/site-releases/0.3.15-mobile-0.1.48-20261009/index.html
grep -R -q '0.3.15' /var/www/lamtools/site-releases/0.3.15-mobile-0.1.48-20261009/assets
ln -s /var/www/lamtools/site-releases/0.3.15-mobile-0.1.48-20261009 /var/www/lamtools/site.new0315
mv -Tf /var/www/lamtools/site.new0315 /var/www/lamtools/site
rm -- /var/tmp/Sunday-site-mobile-0.3.15-20261009.upload.tar.gz
readlink -f /var/www/lamtools/site
ls -1 /var/www/lamtools/site-releases/ | tail -4
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
