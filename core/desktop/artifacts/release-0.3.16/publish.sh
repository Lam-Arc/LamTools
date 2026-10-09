set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
test -e /var/tmp/Sunday-desktop-0.3.16-20261009.upload.exe
test ! -e /var/www/lamtools/Sunday_0.3.16_x64-setup.exe
test ! -e /var/www/lamtools/Sunday-latest-x64-setup-0.3.15-before-0.3.16-20261009.exe
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/0.3.15-mobile-0.1.48-20261009
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = 4267eac33b34698f85875f1c9e464194748d8e30ec0e381d3f10bbddac0efbed

# Re-check the bytes against the release's own metadata at publish time, not
# only at fetch time: a stage left behind by an aborted run must not ship.
curl -sSL -m 60 -o /tmp/release-v0.3.16.json https://api.github.com/repos/Lam-Arc/LamTools/releases/tags/v0.3.16
python3 -c 'import json; r=json.load(open("/tmp/release-v0.3.16.json")); a=[a for a in r["assets"] if a["name"]=="Sunday_0.3.16_x64-setup.exe"]; assert len(a)==1; print(a[0]["size"], (a[0].get("digest") or "").replace("sha256:",""))' > /tmp/asset-v0.3.16.txt
read expected_size expected_digest < /tmp/asset-v0.3.16.txt
actual_size=$(stat -c '%s' /var/tmp/Sunday-desktop-0.3.16-20261009.upload.exe)
actual_digest=$(sha256sum /var/tmp/Sunday-desktop-0.3.16-20261009.upload.exe | cut -d' ' -f1)
test "$actual_size" = "$expected_size"
test "$actual_digest" = "$expected_digest"

# The previous latest is kept as its own inode so the versioned file it shares
# with stays downloadable after the link moves.
cp -al -- /var/www/lamtools/Sunday-latest-x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup-0.3.15-before-0.3.16-20261009.exe
mv -- /var/tmp/Sunday-desktop-0.3.16-20261009.upload.exe /var/www/lamtools/Sunday_0.3.16_x64-setup.exe
ln -f -- /var/www/lamtools/Sunday_0.3.16_x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup.exe
chmod 0644 /var/www/lamtools/Sunday_0.3.16_x64-setup.exe

published_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
printf '%s\n' \
  '{' \
  '  "version": "0.3.16",' \
  '  "download_url": "https://47.114.43.99.nip.io/downloads/Sunday_0.3.16_x64-setup.exe",' \
  '  "release_url": "https://47.114.43.99.nip.io/#download",' \
  '  "release_notes": "Sunday 0.3.16",' \
  "  \"published_at\": \"$published_at\"," \
  '  "sha256": "'"$actual_digest"'",' \
  '  "size": '"$actual_size" \
  '}' > /var/www/lamtools/desktop-update.json
chmod 0644 /var/www/lamtools/desktop-update.json
python3 -c 'import json;print(json.dumps(json.load(open("/var/www/lamtools/desktop-update.json")),ensure_ascii=False,sort_keys=True))'

echo "--- read back over the public origin ---"
curl -sS -m 60 "https://47.114.43.99.nip.io/downloads/desktop-update.json"
echo
curl -sS -m 120 -o /dev/null -w 'installer http=%{http_code} bytes=%{size_download}\n' "https://47.114.43.99.nip.io/downloads/Sunday_0.3.16_x64-setup.exe"
curl -sS -m 60 -o /dev/null -w 'latest    http=%{http_code} bytes=%{size_download}\n' "https://47.114.43.99.nip.io/downloads/Sunday-latest-x64-setup.exe"
ls -l /var/www/lamtools/Sunday_0.3.16_x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup-0.3.15-before-0.3.16-20261009.exe
date -u +%Y-%m-%dT%H:%M:%SZ
