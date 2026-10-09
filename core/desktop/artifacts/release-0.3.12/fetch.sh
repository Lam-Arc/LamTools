set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
curl -sSL -m 60 -o /tmp/release-0.3.11.json https://api.github.com/repos/Lam-Arc/LamTools/releases/tags/v0.3.11
python3 -c 'import json,sys; r=json.load(open("/tmp/release-0.3.11.json")); assert r.get("tag_name")=="v0.3.11", r.get("tag_name"); a=[a for a in r["assets"] if a["name"].endswith("_x64-setup.exe")]; assert len(a)==1, [x["name"] for x in r["assets"]]; a=a[0]; print(a["name"], a["size"], (a.get("digest") or "").replace("sha256:",""))' > /tmp/asset-0.3.11.txt
cat /tmp/asset-0.3.11.txt
read asset_name expected_size expected_digest < /tmp/asset-0.3.11.txt
stage=/var/tmp/Sunday-desktop-0.3.11-20261008.upload.exe
test ! -e "$stage"
curl -sSL -m 1800 -o "$stage" "https://github.com/Lam-Arc/LamTools/releases/download/v0.3.11/$asset_name"
actual_size=$(stat -c '%s' "$stage")
actual_digest=$(sha256sum "$stage" | cut -d' ' -f1)
echo "DOWNLOADED $asset_name $actual_size $actual_digest"
test "$actual_size" = "$expected_size"
if [ -n "$expected_digest" ]; then test "$actual_digest" = "$expected_digest"; fi
echo FETCH_OK
date -u +%Y-%m-%dT%H:%M:%SZ
