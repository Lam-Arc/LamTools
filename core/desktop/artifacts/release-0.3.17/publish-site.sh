set -eu
printf 'SITE_PUBLISH_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
stage=/var/tmp/Sunday-site-mobile-0.3.17-20261013.upload.tar.gz
release=/var/www/lamtools/site-releases/0.3.17-mobile-0.1.48-20261013
previous=/var/www/lamtools/site-releases/0.3.16-mobile-0.1.48-20261009
link=/var/www/lamtools/site
next_link=/var/www/lamtools/site.new0317
manifest=/var/www/lamtools/desktop-update.json
expected_sha=e8806876f2f7a204a51c67e12790d3e04a43c986f91b79df43d8a9e30d152be2
test "$(readlink -f "$link")" = "$previous"
test "$(python3 -c 'import json;print(json.load(open("'"$manifest"'"))["version"])')" = 0.3.17
test -f "$stage"
printf '%s  %s\n' "$expected_sha" "$stage" | sha256sum -c -
test ! -e "$release"
test ! -e "$next_link"
mkdir -m 0755 "$release"
tar -xzf "$stage" -C "$release" --no-same-owner
find "$release" -type d -exec chmod 755 {} +
find "$release" -type f -exec chmod 644 {} +
test -f "$release/index.html"
grep -R -q '0.3.17' "$release/assets"
ln -s "$release" "$next_link"
mv -Tf "$next_link" "$link"
test "$(readlink -f "$link")" = "$release"
asset=$(grep -o 'assets/main-[A-Za-z0-9._-]*\.js' "$release/index.html" | head -1 | sed 's|assets/||')
test -n "$asset"
curl -sS -m 60 "https://47.114.43.99.nip.io/assets/$asset" | grep -o '0.3.17' | head -1
systemctl is-active caddy-lamtools lamtools-relay
printf 'SITE_PUBLISH_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
