set -eu
printf 'FINAL_CONFIRM_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq 1
! grep -Fq 'sunday-desktop-0.3.18-site-upload-20261013' /root/.ssh/authorized_keys
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/0.3.18-mobile-0.1.48-20261013
test "$(sha256sum /var/www/lamtools/Sunday_0.3.18_x64-setup.exe | cut -d' ' -f1)" = b8681e66243634654b98b70274aee3cee7e6fd69241ddf1f99219cec6334a5f7
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = b8681e66243634654b98b70274aee3cee7e6fd69241ddf1f99219cec6334a5f7
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup-0.3.17-before-0.3.18-20261013.exe | cut -d' ' -f1)" = d25a030599b148d52c44021a89b487f4ccf1a695d7b7d19bedd4c1a7ab3015b1
python3 - <<'PY'
import json
m=json.load(open('/var/www/lamtools/desktop-update.json'))
old=json.load(open('/var/www/lamtools/desktop-update-0.3.17-before-0.3.18-20261013.json'))
assert (m['version'],m['linux_version'])==('0.3.18','0.3.17')
assert (old['version'],old['sha256'])==('0.3.17','d25a030599b148d52c44021a89b487f4ccf1a695d7b7d19bedd4c1a7ab3015b1')
print('CHANNEL_AND_MANIFEST_ROLLBACK_OK',m['version'],m['linux_version'],old['version'])
PY
test "$(sha256sum /usr/local/bin/sync-public-site.sh | cut -d' ' -f1)" = 94eb52fb953221223786c070fecea5ceba639ef9c5a3936665a1207ccf780030
test "$(sha256sum /usr/local/bin/sync-public-site.sh-0.3.17-before-0.3.18-20261013 | cut -d' ' -f1)" = 8537de804f89df78c134a8e3ae2aa33ab9502494ade925780a3cd5399e1ee9f3
for path in /var/tmp/Sunday-desktop-0.3.18-20261013.upload.exe /var/tmp/Sunday-desktop-0.3.18-20261013.desktop-update.json /var/tmp/Sunday-site-mobile-0.3.18-20261013.upload.tar.gz /var/tmp/sync-public-site-0.3.18-20261013.upload.sh /tmp/sunday-0.3.18-main.js /tmp/sunday-0318-github-latest.json; do test ! -e "$path"; done
sh -n /usr/local/bin/sync-public-site.sh
sh /usr/local/bin/sync-public-site.sh --check
printf 'FINAL_LATEST_SHA='; sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe
printf 'FINAL_SITE_POINTER='; readlink -f /var/www/lamtools/site
printf 'AUTHORIZED_KEYS_LINES='; wc -l < /root/.ssh/authorized_keys
systemctl is-active caddy-lamtools lamtools-relay
printf 'FINAL_CONFIRM_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
