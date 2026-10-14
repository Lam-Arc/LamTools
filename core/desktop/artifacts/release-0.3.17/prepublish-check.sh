set -eu
printf 'PREPUBLISH_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
printf 'SITE='; readlink -f /var/www/lamtools/site
printf 'RELEASE_DIRS\n'; ls -1 /var/www/lamtools/site-releases | tail -8
printf 'CURRENT_MANIFEST='; cat /var/www/lamtools/desktop-update.json
printf 'LATEST_SHA='; sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe
for path in /var/www/lamtools/Sunday_0.3.17_x64-setup.exe /var/www/lamtools/Sunday-latest-x64-setup-0.3.16-before-0.3.17-20261013.exe /var/tmp/Sunday-desktop-0.3.17-20261013.parallel.exe; do
  if [ -e "$path" ]; then ls -l "$path"; else echo "ABSENT $path"; fi
done
printf 'AUTHORIZED_KEYS_LINES='; wc -l < /root/.ssh/authorized_keys
curl -sSL -m 60 -o /tmp/release-v0.3.17-prepublish.json https://api.github.com/repos/Lam-Arc/LamTools/releases/tags/v0.3.17
python3 - <<'PY'
import json
r=json.load(open('/tmp/release-v0.3.17-prepublish.json'))
assets=[a for a in r['assets'] if a['name']=='Sunday_0.3.17_x64-setup.exe']
assert len(assets)==1
print('GITHUB_ASSET',assets[0]['name'],assets[0]['size'],assets[0].get('digest'))
PY
printf 'STAGE='; stat -c '%s bytes' /var/tmp/Sunday-desktop-0.3.17-20261013.parallel.exe; sha256sum /var/tmp/Sunday-desktop-0.3.17-20261013.parallel.exe
printf 'PREPUBLISH_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
