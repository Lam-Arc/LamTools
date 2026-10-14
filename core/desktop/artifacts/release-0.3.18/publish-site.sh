set -eu
printf 'SITE_PUBLISH_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
stage=/var/tmp/Sunday-site-mobile-0.3.18-20261013.upload.tar.gz
release=/var/www/lamtools/site-releases/0.3.18-mobile-0.1.48-20261013
previous=/var/www/lamtools/site-releases/0.3.17-mobile-0.1.48-20261013
link=/var/www/lamtools/site
next_link=/var/www/lamtools/site.new0318
manifest=/var/www/lamtools/desktop-update.json
expected_sha=7937108279626799e883bb0a87567984fe56f5271c83113ebbc98f4b7874615a
expected_helper=94eb52fb953221223786c070fecea5ceba639ef9c5a3936665a1207ccf780030
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 2
test "$(readlink -f "$link")" = "$previous"
python3 - "$manifest" <<'PY'
import json,sys
m=json.load(open(sys.argv[1]))
assert m['version']=='0.3.18' and m['linux_version']=='0.3.17'
assert m['sha256']=='b8681e66243634654b98b70274aee3cee7e6fd69241ddf1f99219cec6334a5f7'
print('MANIFEST_FOR_SITE_OK',m['version'],m['linux_version'])
PY
test "$(sha256sum /usr/local/bin/sync-public-site.sh | cut -d' ' -f1)" = "$expected_helper"
test -s "$stage"
printf '%s  %s\n' "$expected_sha" "$stage" | sha256sum -c -
test ! -e "$release"
test ! -e "$next_link"
mkdir -m 0755 "$release"
tar -xzf "$stage" -C "$release" --no-same-owner
find "$release" -type d -exec chmod 755 {} +
find "$release" -type f -exec chmod 644 {} +
test -f "$release/index.html"
test -f "$release/preview.html"
grep -R -q '0.3.17' "$release/assets"
grep -R -q '0.3.18' "$release/assets"
ln -s "$release" "$next_link"
mv -Tf "$next_link" "$link"
test "$(readlink -f "$link")" = "$release"
asset=$(grep -o 'assets/main-[A-Za-z0-9._-]*\.js' "$release/index.html" | head -1 | sed 's|assets/||')
test -n "$asset"
served=/tmp/sunday-0.3.18-main.js
curl -sS -f -m 60 "https://47.114.43.99.nip.io/assets/$asset" -o "$served"
grep -q '0.3.17' "$served"
grep -q '0.3.18' "$served"
printf 'PUBLIC_MAIN_ASSET=%s\n' "$asset"
printf 'SITE_POINTER='; readlink -f "$link"
systemctl is-active caddy-lamtools lamtools-relay
printf 'SITE_PUBLISH_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
