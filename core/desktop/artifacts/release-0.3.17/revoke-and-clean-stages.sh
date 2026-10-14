set -eu
printf 'CLEANUP_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
keyblob=AAAAC3NzaC1lZDI1NTE5AAAAID45J4CxMJeeFTFb+FabOZC8YNcjdhBKaVwQWuWm2QO9
authorized=/root/.ssh/authorized_keys
tmpkeys=/root/.ssh/authorized_keys.tmp0317
test "$(grep -Fc "$keyblob" "$authorized")" -eq 1
test "$(wc -l < "$authorized")" -eq 2
test ! -e "$tmpkeys"
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/0.3.17-mobile-0.1.48-20261013
test "$(python3 -c 'import json;print(json.load(open("/var/www/lamtools/desktop-update.json"))["version"])')" = 0.3.17
partial=/var/tmp/Sunday-desktop-0.3.17-20261013.upload.exe
site_stage=/var/tmp/Sunday-site-mobile-0.3.17-20261013.upload.tar.gz
ranges=/var/tmp/dl-0.3.17-20261013T0935
test "$(stat -c '%s' "$partial")" = 6496256
printf '%s  %s\n' e8806876f2f7a204a51c67e12790d3e04a43c986f91b79df43d8a9e30d152be2 "$site_stage" | sha256sum -c -
test "$(find "$ranges" -maxdepth 1 -type f | wc -l)" -eq 8
test "$(find "$ranges" -maxdepth 1 -type f ! -name 'part.[0-7]' | wc -l)" -eq 0
grep -Fv "$keyblob" "$authorized" > "$tmpkeys"
test "$(wc -l < "$tmpkeys")" -eq 1
! grep -Fq "$keyblob" "$tmpkeys"
mv -- "$tmpkeys" "$authorized"
chmod 600 "$authorized"
rm -f -- "$partial" "$site_stage"
rm -rf -- "$ranges"
test "$(wc -l < "$authorized")" -eq 1
! grep -Fq "$keyblob" "$authorized"
for path in "$partial" "$site_stage" "$ranges"; do test ! -e "$path"; done
printf 'AUTHORIZED_KEYS_LINES='; wc -l < "$authorized"
printf 'SITE='; readlink -f /var/www/lamtools/site
systemctl is-active caddy-lamtools lamtools-relay
printf 'CLEANUP_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
