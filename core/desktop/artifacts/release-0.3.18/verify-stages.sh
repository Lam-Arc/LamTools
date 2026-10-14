set -eu
printf 'STAGE_VERIFY_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 2
grep -Fq 'sunday-desktop-0.3.18-site-upload-20261013' /root/.ssh/authorized_keys
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/0.3.17-mobile-0.1.48-20261013
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = d25a030599b148d52c44021a89b487f4ccf1a695d7b7d19bedd4c1a7ab3015b1
test "$(python3 -c 'import json;print(json.load(open("/var/www/lamtools/desktop-update.json"))["version"])')" = 0.3.17
test "$(sha256sum /usr/local/bin/sync-public-site.sh | cut -d' ' -f1)" = 8537de804f89df78c134a8e3ae2aa33ab9502494ade925780a3cd5399e1ee9f3
installer=/var/tmp/Sunday-desktop-0.3.18-20261013.upload.exe
manifest=/var/tmp/Sunday-desktop-0.3.18-20261013.desktop-update.json
site=/var/tmp/Sunday-site-mobile-0.3.18-20261013.upload.tar.gz
test "$(stat -c '%s' "$installer")" = 95007704
printf '%s  %s\n' b8681e66243634654b98b70274aee3cee7e6fd69241ddf1f99219cec6334a5f7 "$installer" | sha256sum -c -
test "$(stat -c '%s' "$manifest")" = 388
printf '%s  %s\n' df7aa434ab46fe030aea8d8194eb9fd0f2592a27f059b5cce796fe850e0e0789 "$manifest" | sha256sum -c -
python3 - "$manifest" <<'PY'
import json, sys
m=json.load(open(sys.argv[1]))
assert m['version']=='0.3.18'
assert m['linux_version']=='0.3.17'
assert m['download_url'].endswith('/Sunday_0.3.18_x64-setup.exe')
print('MANIFEST_OK', m['version'], m['linux_version'], m['sha256'], m['size'])
PY
test "$(stat -c '%s' "$site")" = 4826049
printf '%s  %s\n' 7937108279626799e883bb0a87567984fe56f5271c83113ebbc98f4b7874615a "$site" | sha256sum -c -
tar -tzf "$site" | grep -Fxq './index.html'
tar -tzf "$site" | grep -Fxq './preview.html'
test ! -e /var/www/lamtools/Sunday_0.3.18_x64-setup.exe
test ! -e /var/www/lamtools/site-releases/0.3.18-mobile-0.1.48-20261013
test ! -e /usr/local/bin/sync-public-site.sh-0.3.17-before-0.3.18-20261013
printf 'STAGED_SITE_SHA='; sha256sum "$site"
printf 'STAGE_VERIFY_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
