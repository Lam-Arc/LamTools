set -eu
printf 'CLEANUP_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
site=/var/www/lamtools/site
manifest=/var/www/lamtools/desktop-update.json
latest=/var/www/lamtools/Sunday-latest-x64-setup.exe
helper=/usr/local/bin/sync-public-site.sh
backup=/root/.ssh/authorized_keys
keyblob=AAAAC3NzaC1lZDI1NTE5AAAAIF9b1TSzWo+mNUI8AGQmdv/uDt6SgifW+npKG/YFSaro
test "$(readlink -f "$site")" = /var/www/lamtools/site-releases/0.3.18-mobile-0.1.48-20261013
test "$(sha256sum "$latest" | cut -d' ' -f1)" = b8681e66243634654b98b70274aee3cee7e6fd69241ddf1f99219cec6334a5f7
test "$(sha256sum "$helper" | cut -d' ' -f1)" = 94eb52fb953221223786c070fecea5ceba639ef9c5a3936665a1207ccf780030
python3 - <<'PY'
import json
m=json.load(open('/var/www/lamtools/desktop-update.json'))
assert (m['version'],m['linux_version']) == ('0.3.18','0.3.17')
print('CURRENT_CHANNEL_OK',m['version'],m['linux_version'])
PY
sh "$helper" --check
keycount=$(grep -Fc "$keyblob" "$backup")
test "$keycount" -eq 1
test "$(wc -l < "$backup")" -eq 2
tmpkeys=/root/.ssh/authorized_keys.tmp0318
test ! -e "$tmpkeys"
grep -Fv "$keyblob" "$backup" > "$tmpkeys"
test "$(wc -l < "$tmpkeys")" -eq 1
! grep -Fq "$keyblob" "$tmpkeys"
mv -- "$tmpkeys" "$backup"
chmod 600 "$backup"
test "$(wc -l < "$backup")" -eq 1
! grep -Fq "$keyblob" "$backup"
rm -f -- \
  /var/tmp/Sunday-site-mobile-0.3.18-20261013.upload.tar.gz \
  /var/tmp/sync-public-site-0.3.18-20261013.upload.sh \
  /tmp/sunday-0.3.18-main.js \
  /tmp/sunday-0318-github-latest.json
for path in \
  /var/tmp/Sunday-desktop-0.3.18-20261013.upload.exe \
  /var/tmp/Sunday-desktop-0.3.18-20261013.desktop-update.json \
  /var/tmp/Sunday-site-mobile-0.3.18-20261013.upload.tar.gz \
  /var/tmp/sync-public-site-0.3.18-20261013.upload.sh \
  /tmp/sunday-0.3.18-main.js \
  /tmp/sunday-0318-github-latest.json; do test ! -e "$path"; done
printf 'AUTHORIZED_KEYS_LINES='; wc -l < "$backup"
printf 'SITE_POINTER='; readlink -f "$site"
printf 'LATEST_SHA='; sha256sum "$latest"
printf 'SYNC_HELPER_SHA='; sha256sum "$helper"
systemctl is-active caddy-lamtools lamtools-relay
sh "$helper" --check
printf 'CLEANUP_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
