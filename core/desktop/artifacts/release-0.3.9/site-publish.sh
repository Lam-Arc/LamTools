set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\n' '2a6858480bdae5c2e9ef340d4451bbb15583e088e95c823e307ce2c43ea13590' '/var/tmp/Sunday-site-0.3.9-20260929.upload.tar.gz' | sha256sum -c -
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/0.3.8-mobile-0.1.45-20260928
test ! -e /var/www/lamtools/site-releases/0.3.9-mobile-0.1.46-20260929
mkdir -m 0755 /var/www/lamtools/site-releases/0.3.9-mobile-0.1.46-20260929
tar -xzf /var/tmp/Sunday-site-0.3.9-20260929.upload.tar.gz -C /var/www/lamtools/site-releases/0.3.9-mobile-0.1.46-20260929 --no-same-owner
find /var/www/lamtools/site-releases/0.3.9-mobile-0.1.46-20260929 -type d -exec chmod 755 {} +
find /var/www/lamtools/site-releases/0.3.9-mobile-0.1.46-20260929 -type f -exec chmod 644 {} +
test -f /var/www/lamtools/site-releases/0.3.9-mobile-0.1.46-20260929/index.html
grep -R -q '0.3.9' /var/www/lamtools/site-releases/0.3.9-mobile-0.1.46-20260929/assets
grep -R -q '0.1.46' /var/www/lamtools/site-releases/0.3.9-mobile-0.1.46-20260929/assets
ln -s /var/www/lamtools/site-releases/0.3.9-mobile-0.1.46-20260929 /var/www/lamtools/site.new0390146
mv -Tf /var/www/lamtools/site.new0390146 /var/www/lamtools/site
rm -- /var/tmp/Sunday-site-0.3.9-20260929.upload.tar.gz
readlink -f /var/www/lamtools/site
ls -1 /var/www/lamtools/site-releases/ | tail -4
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
