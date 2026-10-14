set -eu
printf 'PUBLIC_VERIFY_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
expected_sha=d25a030599b148d52c44021a89b487f4ccf1a695d7b7d19bedd4c1a7ab3015b1
expected_size=58717198
ver=/tmp/sunday-0317-public-versioned-20261013.exe
latest=/tmp/sunday-0317-public-latest-20261013.exe
test ! -e "$ver"; test ! -e "$latest"
curl -fLsS -m 300 -o "$ver" https://47.114.43.99.nip.io/downloads/Sunday_0.3.17_x64-setup.exe
curl -fLsS -m 300 -o "$latest" https://47.114.43.99.nip.io/downloads/Sunday-latest-x64-setup.exe
for file in "$ver" "$latest"; do
  test "$(stat -c '%s' "$file")" = "$expected_size"
  test "$(sha256sum "$file" | cut -d' ' -f1)" = "$expected_sha"
  sha256sum "$file"
done
rm -- "$ver" "$latest"
manifest=$(curl -fLsS -m 60 https://47.114.43.99.nip.io/downloads/desktop-update.json)
printf '%s\n' "$manifest"
printf '%s' "$manifest" | python3 -c 'import json,sys;m=json.load(sys.stdin);assert m["version"]=="0.3.17" and m["size"]==58717198 and m["sha256"]=="d25a030599b148d52c44021a89b487f4ccf1a695d7b7d19bedd4c1a7ab3015b1";print("MANIFEST_OK")'
home=$(curl -fLsS -m 60 https://47.114.43.99.nip.io/)
printf '%s' "$home" | grep -q '0.3.17'
echo official_home_version=0.3.17
page=$(curl -fLsS -m 60 https://ainarit.com/sunday.html)
printf '%s' "$page" | grep -q 'SUNDAY 0.3.17 '
printf '%s' "$page" | grep -q 'SUNDAY MOBILE 0.1.48 '
printf '%s' "$page" | grep -q 'Sunday_0.3.17_amd64'
echo ainarit_page_versions=0.3.17,0.1.48
preview=$(curl -fLsS -m 60 https://ainarit.com/preview/)
entry=$(printf '%s' "$preview" | sed -n 's|.*\(/preview/assets/preview-[A-Za-z0-9._-]*\.js\).*|\1|p' | head -1)
test -n "$entry"
preview_js=$(curl -fLsS -m 60 "https://ainarit.com$entry")
printf '%s' "$preview_js" | grep -q '0.3.17'
echo "preview_resource=$entry carries 0.3.17"
systemctl is-active caddy-lamtools lamtools-relay
printf 'PUBLIC_VERIFY_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
