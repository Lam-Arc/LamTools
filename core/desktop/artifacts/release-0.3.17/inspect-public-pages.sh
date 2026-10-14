set -eu
printf 'PAGE_INSPECT_UTC='; date -u +%Y-%m-%dT%H:%M:%SZ
for spec in 'https://47.114.43.99.nip.io/|/tmp/0317-origin-index.html' 'https://ainarit.com/sunday.html|/tmp/0317-ainarit-sunday.html' 'https://ainarit.com/preview/|/tmp/0317-ainarit-preview.html'; do
  url=${spec%%|*}; file=${spec#*|}
  curl -fLsS -m 60 -o "$file" "$url"
  echo "PAGE $url bytes=$(stat -c '%s' "$file")"
  grep -oE '(/?assets/|/preview/assets/)[A-Za-z0-9._-]+\.(js|css)' "$file" | head -4 || true
  grep -oE 'SUNDAY( MOBILE)? [0-9.]+' "$file" | head -3 || true
done
for file in /tmp/0317-origin-index.html /tmp/0317-ainarit-sunday.html /tmp/0317-ainarit-preview.html; do rm -f "$file"; done
