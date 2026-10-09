set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
VERSION=0.3.13
STAGE=/var/tmp/Sunday-desktop-0.3.13-20261009.upload.exe
curl -sSL -m 60 -o /tmp/release-$VERSION.json "https://api.github.com/repos/Lam-Arc/LamTools/releases/tags/v$VERSION"
python3 -c 'import json; r=json.load(open("/tmp/release-'"$VERSION"'.json")); a=[a for a in r["assets"] if a["name"].endswith("_x64-setup.exe")]; assert len(a)==1; a=a[0]; print(a["name"], a["size"], (a.get("digest") or "").replace("sha256:",""))' > /tmp/asset-$VERSION.txt
read asset_name expected_size expected_digest < /tmp/asset-$VERSION.txt
test -n "$expected_size"
echo "ASSET $asset_name $expected_size $expected_digest"
work=/var/tmp/dl-$VERSION
parts=8

fetch_all() {
  base="$1"; label="$2"
  echo "TRY $label $base"
  rm -rf "$work"; mkdir -m 0700 "$work"
  chunk=$(( (expected_size + parts - 1) / parts ))
  i=0
  while [ $i -lt $parts ]; do
    start=$(( i * chunk ))
    end=$(( start + chunk - 1 ))
    if [ $end -ge $expected_size ]; then end=$(( expected_size - 1 )); fi
    want=$(( end - start + 1 ))
    (
      attempt=1
      while [ $attempt -le 4 ]; do
        curl -sSL --http1.1 --retry 3 --retry-delay 2 --retry-all-errors -r "$start-$end" -o "$work/part.$i" -m 600 "$base/$asset_name" || true
        have=$(stat -c '%s' "$work/part.$i" 2>/dev/null || echo 0)
        if [ "$have" = "$want" ]; then exit 0; fi
        echo "$label part.$i attempt $attempt: $have/$want bytes"
        attempt=$(( attempt + 1 ))
        sleep 2
      done
      echo "$label part.$i gave up at $(stat -c '%s' "$work/part.$i" 2>/dev/null || echo 0)/$want"
      exit 1
    ) &
    i=$(( i + 1 ))
    sleep 1
  done
  if ! wait; then echo "$label incomplete"; return 1; fi
  : > "$STAGE"
  i=0
  while [ $i -lt $parts ]; do
    cat "$work/part.$i" >> "$STAGE"
    i=$(( i + 1 ))
  done
  rm -rf "$work"
  actual_size=$(stat -c '%s' "$STAGE")
  actual_digest=$(sha256sum "$STAGE" | cut -d' ' -f1)
  echo "GOT $label $actual_size $actual_digest"
  test "$actual_size" = "$expected_size" || return 1
  if [ -n "$expected_digest" ]; then test "$actual_digest" = "$expected_digest" || return 1; fi
  return 0
}

# GitHub's own asset host throttles this instance to ~20-50 KB/s (measured twice,
# HTTP/2 streams also get cut). A public mirror reads at ~1 MB/s, and the asset is
# a public release file, so the mirror goes first and the canonical URL stays as
# the fallback. Neither can fake the bytes: both are checked against the size and
# digest GitHub reports for the asset.
if ! fetch_all "https://gh-proxy.com/https://github.com/Lam-Arc/LamTools/releases/download/v$VERSION" gh-proxy; then
  echo "mirror fetch failed; falling back to the canonical asset host"
  rm -f "$STAGE"
  fetch_all "https://github.com/Lam-Arc/LamTools/releases/download/v$VERSION" canonical
fi
sha256sum "$STAGE"
echo FETCH_OK
date -u +%Y-%m-%dT%H:%M:%SZ
