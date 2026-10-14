set -eu
printf 'PUBLISH_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
stage=/var/tmp/Sunday-desktop-0.3.17-20261013.parallel.exe
target=/var/www/lamtools/Sunday_0.3.17_x64-setup.exe
latest=/var/www/lamtools/Sunday-latest-x64-setup.exe
latest_backup=/var/www/lamtools/Sunday-latest-x64-setup-0.3.16-before-0.3.17-20261013.exe
manifest=/var/www/lamtools/desktop-update.json
manifest_backup=/var/www/lamtools/desktop-update-0.3.16-before-0.3.17-20261013.json
expected_old_sha=16bc6aaeb34d77002c9db8880b9b60d2ccd918af03e00d2e7342794e6e964c9a
expected_size=58717198
expected_sha=d25a030599b148d52c44021a89b487f4ccf1a695d7b7d19bedd4c1a7ab3015b1
test -s "$stage"
test ! -e "$target"
test ! -e "$latest_backup"
test ! -e "$manifest_backup"
test "$(sha256sum "$latest" | cut -d' ' -f1)" = "$expected_old_sha"
test "$(python3 -c 'import json;print(json.load(open("'"$manifest"'"))["version"])')" = 0.3.16
curl -sSL -m 60 -o /tmp/release-v0.3.17-publish.json https://api.github.com/repos/Lam-Arc/LamTools/releases/tags/v0.3.17
python3 - <<'PY'
import json
r=json.load(open('/tmp/release-v0.3.17-publish.json'))
a=[x for x in r['assets'] if x['name']=='Sunday_0.3.17_x64-setup.exe']
assert len(a)==1 and a[0]['size']==58717198 and a[0].get('digest')=='sha256:d25a030599b148d52c44021a89b487f4ccf1a695d7b7d19bedd4c1a7ab3015b1'
print('GITHUB_METADATA_OK')
PY
test "$(stat -c '%s' "$stage")" = "$expected_size"
test "$(sha256sum "$stage" | cut -d' ' -f1)" = "$expected_sha"
cp -a -- "$latest" "$latest_backup"
cp -a -- "$manifest" "$manifest_backup"
mv -- "$stage" "$target"
ln -f -- "$target" "$latest"
chmod 0644 "$target"
published_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
tmp_manifest=/var/www/lamtools/desktop-update.json.new0317
printf '%s\n' \
  '{' \
  '  "version": "0.3.17",' \
  '  "download_url": "https://47.114.43.99.nip.io/downloads/Sunday_0.3.17_x64-setup.exe",' \
  '  "release_url": "https://47.114.43.99.nip.io/#download",' \
  '  "release_notes": "Sunday 0.3.17",' \
  "  \"published_at\": \"$published_at\"," \
  '  "sha256": "'"$expected_sha"'",' \
  '  "size": '"$expected_size" \
  '}' > "$tmp_manifest"
chmod 0644 "$tmp_manifest"
mv -f -- "$tmp_manifest" "$manifest"
python3 -c 'import json;print(json.dumps(json.load(open("'"$manifest"'")),ensure_ascii=False,sort_keys=True))'
curl -sS -m 60 https://47.114.43.99.nip.io/downloads/desktop-update.json
curl -sS -m 120 -o /dev/null -w 'installer http=%{http_code} bytes=%{size_download}\n' https://47.114.43.99.nip.io/downloads/Sunday_0.3.17_x64-setup.exe
curl -sS -m 60 -o /dev/null -w 'latest http=%{http_code} bytes=%{size_download}\n' https://47.114.43.99.nip.io/downloads/Sunday-latest-x64-setup.exe
sha256sum "$target" "$latest" "$latest_backup"
ls -l "$manifest" "$manifest_backup"
printf 'PUBLISH_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
