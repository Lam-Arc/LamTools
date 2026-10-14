#!/bin/bash
set -euo pipefail
VERSION=0.3.17
EXPECTED_SIZE=58717198
TAG="v${VERSION}"
NAME="Sunday_${VERSION}_x64-setup.exe"
STAGE=/var/tmp/Sunday-desktop-0.3.17-20261013.upload.exe
VERSIONED=/var/www/lamtools/Sunday_0.3.17_x64-setup.exe
ARCHIVE=/var/www/lamtools/Sunday-latest-x64-setup-0.3.16-before-0.3.17-20261013.exe
LATEST=/var/www/lamtools/Sunday-latest-x64-setup.exe
MANIFEST=/var/www/lamtools/desktop-update.json
OLD_SHA=16bc6aaeb34d77002c9db8880b9b60d2ccd918af03e00d2e7342794e6e964c9a
OLD_MANIFEST_SHA=a311014f29570b9263a7dd6e5e31965bda92b7cbe54c68dfc00a783337e4fb15
META=/tmp/sunday-release-v0.3.17.json
ASSET_META=/tmp/sunday-release-v0.3.17-asset.txt

date -u +PREFLIGHT_UTC_BEGIN=%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test ! -e "$STAGE"
test ! -e "$VERSIONED"
test ! -e "$ARCHIVE"
printf '%s  %s\n' "$OLD_SHA" "$LATEST" | sha256sum -c -
printf '%s  %s\n' "$OLD_MANIFEST_SHA" "$MANIFEST" | sha256sum -c -
curl -fsSL -m 90 -o "$META" "https://api.github.com/repos/Lam-Arc/LamTools/releases/tags/${TAG}"
python3 - "$META" "$TAG" "$NAME" "$EXPECTED_SIZE" > "$ASSET_META" <<'PY'
import json, sys
path, tag, name, expected_size = sys.argv[1:]
release = json.load(open(path, encoding="utf-8"))
assert release.get("tag_name") == tag, release.get("tag_name")
assert release.get("draft") is False, "release is still a draft"
assert release.get("prerelease") is False, "release is marked prerelease"
assets = [asset for asset in release.get("assets", []) if asset.get("name") == name]
assert len(assets) == 1, [asset.get("name") for asset in release.get("assets", [])]
asset = assets[0]
assert int(asset.get("size", -1)) == int(expected_size), asset.get("size")
digest = (asset.get("digest") or "").removeprefix("sha256:")
print(asset["name"], asset["size"], digest, asset["browser_download_url"])
PY
read -r asset_name expected_size expected_digest download_url < "$ASSET_META"
echo "GITHUB_ASSET $asset_name size=$expected_size sha256=${expected_digest:-not-provided}"
test "$asset_name" = "$NAME"
test "$expected_size" = "$EXPECTED_SIZE"
curl -fLsS --retry 4 --retry-delay 3 --retry-all-errors -m 1800 -o "$STAGE" "$download_url"
actual_size=$(stat -c '%s' "$STAGE")
actual_digest=$(sha256sum "$STAGE" | cut -d' ' -f1)
echo "STAGED $STAGE bytes=$actual_size sha256=$actual_digest"
test "$actual_size" = "$EXPECTED_SIZE"
if [ -n "$expected_digest" ]; then test "$actual_digest" = "$expected_digest"; fi
rm -f -- "$META" "$ASSET_META"
echo FETCH_OK
date -u +FETCH_UTC_END=%Y-%m-%dT%H:%M:%SZ