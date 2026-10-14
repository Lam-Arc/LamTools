set -eu
printf 'SYNC_STAGE_VERIFY_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 2
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/0.3.17-mobile-0.1.48-20261013
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = b8681e66243634654b98b70274aee3cee7e6fd69241ddf1f99219cec6334a5f7
python3 - <<'PY'
import json
m=json.load(open('/var/www/lamtools/desktop-update.json'))
assert m['version']=='0.3.18' and m['linux_version']=='0.3.17'
assert m['sha256']=='b8681e66243634654b98b70274aee3cee7e6fd69241ddf1f99219cec6334a5f7'
print('PUBLISHED_MANIFEST_OK',m['version'],m['linux_version'])
PY
old=/usr/local/bin/sync-public-site.sh
backup=/usr/local/bin/sync-public-site.sh-0.3.17-before-0.3.18-20261013
stage=/var/tmp/sync-public-site-0.3.18-20261013.upload.sh
test "$(sha256sum "$old" | cut -d' ' -f1)" = 8537de804f89df78c134a8e3ae2aa33ab9502494ade925780a3cd5399e1ee9f3
test ! -e "$backup"
test -s "$stage"
test "$(stat -c '%s' "$stage")" = 6302
printf '%s  %s\n' 94eb52fb953221223786c070fecea5ceba639ef9c5a3936665a1207ccf780030 "$stage" | sha256sum -c -
grep -q 'linux_version' "$stage"
sh -n "$stage"
test ! -e /var/www/lamtools/site-releases/0.3.18-mobile-0.1.48-20261013
printf 'SYNC_STAGE_VERIFY_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
