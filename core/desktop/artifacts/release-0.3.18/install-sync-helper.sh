set -eu
printf 'INSTALL_SYNC_HELPER_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
old=/usr/local/bin/sync-public-site.sh
backup=/usr/local/bin/sync-public-site.sh-0.3.17-before-0.3.18-20261013
stage=/var/tmp/sync-public-site-0.3.18-20261013.upload.sh
next=/usr/local/bin/sync-public-site.sh.new0318
expected_old=8537de804f89df78c134a8e3ae2aa33ab9502494ade925780a3cd5399e1ee9f3
expected_new=94eb52fb953221223786c070fecea5ceba639ef9c5a3936665a1207ccf780030
test "$(sha256sum "$old" | cut -d' ' -f1)" = "$expected_old"
test ! -e "$backup"
test ! -e "$next"
test "$(sha256sum "$stage" | cut -d' ' -f1)" = "$expected_new"
test "$(python3 -c 'import json; m=json.load(open("/var/www/lamtools/desktop-update.json")); print(m["version"],m["linux_version"])')" = '0.3.18 0.3.17'
cp -a -- "$old" "$backup"
install -m 0755 -- "$stage" "$next"
test "$(sha256sum "$backup" | cut -d' ' -f1)" = "$expected_old"
test "$(sha256sum "$next" | cut -d' ' -f1)" = "$expected_new"
mv -- "$next" "$old"
test -x "$old"
test "$(sha256sum "$old" | cut -d' ' -f1)" = "$expected_new"
grep -q 'linux_version' "$old"
sh -n "$old"
printf 'SYNC_HELPER_CURRENT_SHA='; sha256sum "$old"
printf 'SYNC_HELPER_ROLLBACK_SHA='; sha256sum "$backup"
printf 'INSTALL_SYNC_HELPER_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
