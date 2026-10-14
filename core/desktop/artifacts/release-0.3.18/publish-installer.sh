set -eu
printf 'PUBLISH_INSTALLER_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
stage=/var/tmp/Sunday-desktop-0.3.18-20261013.upload.exe
manifest_stage=/var/tmp/Sunday-desktop-0.3.18-20261013.desktop-update.json
target=/var/www/lamtools/Sunday_0.3.18_x64-setup.exe
latest=/var/www/lamtools/Sunday-latest-x64-setup.exe
latest_backup=/var/www/lamtools/Sunday-latest-x64-setup-0.3.17-before-0.3.18-20261013.exe
manifest=/var/www/lamtools/desktop-update.json
manifest_backup=/var/www/lamtools/desktop-update-0.3.17-before-0.3.18-20261013.json
expected_old_sha=d25a030599b148d52c44021a89b487f4ccf1a695d7b7d19bedd4c1a7ab3015b1
expected_size=95007704
expected_sha=b8681e66243634654b98b70274aee3cee7e6fd69241ddf1f99219cec6334a5f7
expected_manifest_sha=df7aa434ab46fe030aea8d8194eb9fd0f2592a27f059b5cce796fe850e0e0789
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 2
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/0.3.17-mobile-0.1.48-20261013
test "$(sha256sum /usr/local/bin/sync-public-site.sh | cut -d' ' -f1)" = 8537de804f89df78c134a8e3ae2aa33ab9502494ade925780a3cd5399e1ee9f3
test -s "$stage"
test -s "$manifest_stage"
test ! -e "$target"
test ! -e "$latest_backup"
test ! -e "$manifest_backup"
test "$(sha256sum "$latest" | cut -d' ' -f1)" = "$expected_old_sha"
python3 - "$manifest" <<'PY'
import json,sys
m=json.load(open(sys.argv[1]))
assert m['version']=='0.3.17'
assert m['sha256']=='d25a030599b148d52c44021a89b487f4ccf1a695d7b7d19bedd4c1a7ab3015b1'
assert m['size']==58717198
print('CURRENT_MANIFEST_OK',m['version'],m['sha256'])
PY
test "$(stat -c '%s' "$stage")" = "$expected_size"
test "$(sha256sum "$stage" | cut -d' ' -f1)" = "$expected_sha"
test "$(sha256sum "$manifest_stage" | cut -d' ' -f1)" = "$expected_manifest_sha"
python3 - "$manifest_stage" <<'PY'
import json,sys
m=json.load(open(sys.argv[1]))
assert m['version']=='0.3.18' and m['linux_version']=='0.3.17'
assert m['sha256']=='b8681e66243634654b98b70274aee3cee7e6fd69241ddf1f99219cec6334a5f7'
assert m['size']==95007704
print('STAGED_MANIFEST_OK')
PY
cp -a -- "$latest" "$latest_backup"
cp -a -- "$manifest" "$manifest_backup"
mv -- "$stage" "$target"
ln -f -- "$target" "$latest"
chmod 0644 "$target"
mv -- "$manifest_stage" "$manifest"
chmod 0644 "$manifest"
test "$(sha256sum "$target" | cut -d' ' -f1)" = "$expected_sha"
test "$(sha256sum "$latest" | cut -d' ' -f1)" = "$expected_sha"
test "$(sha256sum "$latest_backup" | cut -d' ' -f1)" = "$expected_old_sha"

# Verify the saved rollback manifest still names the previous official release.
python3 - "$manifest" "$manifest_backup" <<'PY'
import json,sys
new=json.load(open(sys.argv[1])); old=json.load(open(sys.argv[2]))
assert new['version']=='0.3.18' and new['linux_version']=='0.3.17'
assert new['sha256']=='b8681e66243634654b98b70274aee3cee7e6fd69241ddf1f99219cec6334a5f7'
assert old['version']=='0.3.17'
print('MANIFEST_CURRENT_OK',new['version'],new['linux_version'])
print('MANIFEST_ROLLBACK_OK',old['version'],old['sha256'])
PY
printf 'PUBLISHED_INSTALLER_SHA='; sha256sum "$target" "$latest" "$latest_backup"
printf 'PUBLISHED_MANIFEST='; cat "$manifest"
printf 'PUBLIC_VERSIONED='; curl -sS -m 120 -o /dev/null -w 'http=%{http_code} bytes=%{size_download}\n' https://47.114.43.99.nip.io/downloads/Sunday_0.3.18_x64-setup.exe
printf 'PUBLIC_LATEST='; curl -sS -m 120 -o /dev/null -w 'http=%{http_code} bytes=%{size_download}\n' https://47.114.43.99.nip.io/downloads/Sunday-latest-x64-setup.exe
printf 'PUBLISH_INSTALLER_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
