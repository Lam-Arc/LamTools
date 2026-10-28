#!/bin/sh
# Keep the public domain in step with the published update channel.
#
# The registered domain carries its own copies of the product pages: the
# Sunday page holds the download labels, and /preview/ embeds the product UI.
# The site publish step only repoints /var/www/lamtools/site, so without this
# step those copies silently keep the version they were built with. The
# versions are read back from the manifests the release just published, so a
# desktop-only or mobile-only release updates exactly the label it changed.
#
# Runs on the server (Cloud Assistant or ssh). `--check` only reads.
#
#   sync-public-site.sh [--check]
#
# Exit codes: 0 in step (or repaired), 1 out of step under --check.

set -eu

CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

PUBLIC_ROOT=/var/www/ainarit
PREVIEW=/var/www/ainarit-preview
SITE=/var/www/lamtools/site
BACKUPS=/var/backups/ainarit
ORIGIN=https://ainarit.com
NEEDLE='SUNDAY [0-9.]* \|SUNDAY MOBILE [0-9.]* \|Sunday_[0-9.]*_amd64'

die() { echo "sync-public-site: $1" >&2; exit 1; }

versions() {
    python3 - <<'PY'
import json
import pathlib

def read(path):
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))

desktop = read('/var/www/lamtools/desktop-update.json')
mobile = read('/var/www/lamtools/mobile-update.json')
print(desktop['version'], mobile['version'], desktop.get('linux_version', desktop['version']))
PY
}

# The stamped page is the source of truth for what visitors read, so compare it
# against the manifests rather than trusting that the last run succeeded.
page_is_current() {
    wanted_desktop=$1
    wanted_mobile=$2
    wanted_linux=$3
    grep -q "SUNDAY $wanted_desktop " "$PUBLIC_ROOT/sunday.html" &&
        grep -q "SUNDAY MOBILE $wanted_mobile " "$PUBLIC_ROOT/sunday.html" &&
        grep -q "Sunday_${wanted_linux}_amd64" "$PUBLIC_ROOT/sunday.html"
}

preview_is_current() {
    [ -f "$PREVIEW/index.html" ] || return 1
    # user:“测试，提交打包发布”+(版本元数据与实际资源都必须对应本次发布)。
    grep -q "name=\"sunday-version\" content=\"$wanted_desktop\"" "$PREVIEW/index.html" || return 1
    # The embedded UI must be the bundle the site release is serving.
    entry=$(sed -n 's|.*/preview/\(assets/preview-[A-Za-z0-9._-]*\.js\).*|\1|p' "$PREVIEW/index.html" | head -1)
    [ -n "$entry" ] || return 1
    [ -f "$PREVIEW/$entry" ] || return 1
    cmp -s "$PREVIEW/$entry" "$SITE/$entry"
}

stamp_page() {
    python3 - <<'PY'
import json
import pathlib
import re

desktop = json.loads(pathlib.Path('/var/www/lamtools/desktop-update.json').read_text(encoding='utf-8'))
mobile = json.loads(pathlib.Path('/var/www/lamtools/mobile-update.json').read_text(encoding='utf-8'))
dv, mv = desktop['version'], mobile['version']
lv = desktop.get('linux_version', dv)

changed = []
for path in sorted(pathlib.Path('/var/www/ainarit').rglob('*')):
    if not path.is_file() or path.suffix.lower() not in {'.html', '.js', '.css', '.json', '.svg'}:
        continue
    text = path.read_text(encoding='utf-8')
    before = text
    text = re.sub(r'SUNDAY (\d+\.\d+\.\d+)(?=\s+.\s+X64)', 'SUNDAY ' + dv, text)
    text = re.sub(r'SUNDAY MOBILE (\d+\.\d+\.\d+)(?=\s+.\s+APK)', 'SUNDAY MOBILE ' + mv, text)
    text = re.sub(r'Sunday_\d+\.\d+\.\d+_amd64', 'Sunday_' + lv + '_amd64', text)
    if text != before:
        path.write_text(text, encoding='utf-8')
        changed.append(path.name)
print('page stamped for desktop {} / mobile {} / Linux {}: {}'.format(dv, mv, lv, ', '.join(changed) or 'already current'))
PY
}

# /preview/ serves the product UI out of a directory of its own, so it needs the
# released bundle with preview.html promoted to the index and the asset prefix
# rewritten for the subpath Caddy strips.
sync_preview() {
    staging="$PREVIEW.staging.$$"
    rm -rf "$staging"
    mkdir -p "$staging"
    cp -aL "$SITE"/. "$staging"/
    rm -f "$staging/index.html"
    cp "$staging/preview.html" "$staging/index.html"
    sed -i 's|="/assets/|="/preview/assets/|g' "$staging/index.html"

    for ref in $(sed -n 's|.*\(/preview/assets/[A-Za-z0-9._-]*\).*|\1|p' "$staging/index.html" | sort -u); do
        [ -e "$staging/${ref#/preview/}" ] || die "the released bundle is missing $ref"
    done

    rm -rf "$PREVIEW.replaced.$$"
    mv "$PREVIEW" "$PREVIEW.replaced.$$"
    mv "$staging" "$PREVIEW"
    rm -rf "$PREVIEW.replaced.$$"
}

backup() {
    mkdir -p "$BACKUPS"
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    tar -czf "$BACKUPS/sunday-before-$stamp.tar.gz" -C "$PUBLIC_ROOT" sunday.html
    tar -czf "$BACKUPS/ainarit-preview-before-$stamp.tar.gz" -C /var/www ainarit-preview
    echo "backups: $BACKUPS/sunday-before-$stamp.tar.gz $BACKUPS/ainarit-preview-before-$stamp.tar.gz"
}

verify_live() {
    wanted_desktop=$1
    wanted_mobile=$2
    wanted_linux=$3
    page=$(curl -sS -m 30 "$ORIGIN/sunday.html")
    echo "$page" | grep -q "SUNDAY $wanted_desktop " || die "$ORIGIN still does not read desktop $wanted_desktop"
    echo "$page" | grep -q "SUNDAY MOBILE $wanted_mobile " || die "$ORIGIN still does not read mobile $wanted_mobile"
    echo "$page" | grep -q "Sunday_${wanted_linux}_amd64" || die "$ORIGIN still links the old Linux build"

    preview=$(curl -fsS -m 30 "$ORIGIN/preview/")
    echo "$preview" | grep -q "name=\"sunday-version\" content=\"$wanted_desktop\"" || die "$ORIGIN/preview/ has the wrong build version"
    entry=$(echo "$preview" |
        sed -n 's|.*\(/preview/assets/preview-[A-Za-z0-9._-]*\.js\).*|\1|p' | head -1)
    [ -n "$entry" ] || die "$ORIGIN/preview/ serves no product bundle"
    # user:“测试，提交打包发布”+(入口分包不一定含版本文本，改为校验公开资源与已发布文件的完整摘要)。
    served_sha=$(curl -fsS -m 60 "$ORIGIN$entry" | sha256sum | awk '{print $1}')
    expected_sha=$(sha256sum "$SITE/${entry#/preview/}" | awk '{print $1}')
    [ "$served_sha" = "$expected_sha" ] || die "$ORIGIN$entry differs from the published bundle"
    echo "live: $ORIGIN/sunday.html reads $wanted_desktop / $wanted_mobile; /preview/ serves $entry"
}

set -- $(versions)
wanted_desktop=$1
wanted_mobile=$2
wanted_linux=$3
echo "published channel: desktop $wanted_desktop, mobile $wanted_mobile, Linux $wanted_linux"

[ -d "$SITE" ] || die "$SITE is absent; publish the site release first"

if page_is_current "$wanted_desktop" "$wanted_mobile" "$wanted_linux" && preview_is_current; then
    echo "public site already in step"
    [ "$CHECK" -eq 1 ] && exit 0
    verify_live "$wanted_desktop" "$wanted_mobile" "$wanted_linux"
    exit 0
fi

if [ "$CHECK" -eq 1 ]; then
    page_is_current "$wanted_desktop" "$wanted_mobile" "$wanted_linux" || echo "out of step: $PUBLIC_ROOT/sunday.html"
    preview_is_current || echo "out of step: $PREVIEW"
    exit 1
fi

backup
stamp_page
sync_preview
systemctl is-active caddy-lamtools lamtools-relay
verify_live "$wanted_desktop" "$wanted_mobile" "$wanted_linux"
