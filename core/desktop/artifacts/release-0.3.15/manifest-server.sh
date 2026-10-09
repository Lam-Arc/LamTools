set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
test -e /var/tmp/Sunday-desktop-0.3.15-20261009.upload.exe
printf '%s  %s
' '4267eac33b34698f85875f1c9e464194748d8e30ec0e381d3f10bbddac0efbed' '/var/tmp/Sunday-desktop-0.3.15-20261009.upload.exe' | sha256sum -c -
python3 - <<'INNER'
import hashlib, json, pathlib
stage = pathlib.Path('/var/tmp/Sunday-desktop-0.3.15-20261009.upload.exe')
digest = hashlib.sha256(stage.read_bytes()).hexdigest()
manifest = {
    "version": "0.3.15",
    "download_url": "https://47.114.43.99.nip.io/downloads/Sunday_0.3.15_x64-setup.exe",
    "release_url": "https://47.114.43.99.nip.io/#download",
    "release_notes": "Sunday 0.3.15",
    "published_at": __import__('time').strftime('%Y-%m-%dT%H:%M:%SZ', __import__('time').gmtime()),
    "sha256": digest,
    "size": stage.stat().st_size,
}
pathlib.Path('/var/www/lamtools/desktop-update.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + chr(10), encoding='utf-8')
print(json.dumps(manifest, ensure_ascii=False))
INNER
chmod 0644 /var/www/lamtools/desktop-update.json
sha256sum /var/www/lamtools/desktop-update.json
cat /var/www/lamtools/desktop-update.json
curl -sS -D - -o /dev/null -H 'Origin: https://tauri.localhost' --resolve 47.114.43.99.nip.io:443:127.0.0.1 https://47.114.43.99.nip.io/downloads/desktop-update.json | grep -iE 'HTTP/|content-length' || true
rm -f -- /var/tmp/Sunday-desktop-0.3.15-20261009.upload.exe
ls -1 /var/tmp/Sunday-desktop-0.3.15-*.upload.exe 2>/dev/null || echo 'no stages'
date -u +%Y-%m-%dT%H:%M:%SZ
