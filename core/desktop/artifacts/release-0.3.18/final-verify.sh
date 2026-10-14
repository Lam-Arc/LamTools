set -eu
printf 'FINAL_VERIFY_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/0.3.18-mobile-0.1.48-20261013
test "$(sha256sum /var/www/lamtools/Sunday_0.3.18_x64-setup.exe | cut -d' ' -f1)" = b8681e66243634654b98b70274aee3cee7e6fd69241ddf1f99219cec6334a5f7
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = b8681e66243634654b98b70274aee3cee7e6fd69241ddf1f99219cec6334a5f7
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup-0.3.17-before-0.3.18-20261013.exe | cut -d' ' -f1)" = d25a030599b148d52c44021a89b487f4ccf1a695d7b7d19bedd4c1a7ab3015b1
python3 - <<'PY'
import json
m=json.load(open('/var/www/lamtools/desktop-update.json'))
old=json.load(open('/var/www/lamtools/desktop-update-0.3.17-before-0.3.18-20261013.json'))
assert (m['version'],m['linux_version']) == ('0.3.18','0.3.17')
assert m['sha256']=='b8681e66243634654b98b70274aee3cee7e6fd69241ddf1f99219cec6334a5f7'
assert (old['version'],old['sha256']) == ('0.3.17','d25a030599b148d52c44021a89b487f4ccf1a695d7b7d19bedd4c1a7ab3015b1')
print('MANIFEST_CURRENT_AND_ROLLBACK_OK',m['version'],m['linux_version'],old['version'])
PY
test "$(sha256sum /usr/local/bin/sync-public-site.sh | cut -d' ' -f1)" = 94eb52fb953221223786c070fecea5ceba639ef9c5a3936665a1207ccf780030
test "$(sha256sum /usr/local/bin/sync-public-site.sh-0.3.17-before-0.3.18-20261013 | cut -d' ' -f1)" = 8537de804f89df78c134a8e3ae2aa33ab9502494ade925780a3cd5399e1ee9f3
sh -n /usr/local/bin/sync-public-site.sh
sh /usr/local/bin/sync-public-site.sh --check
curl -sS -f -m 60 https://47.114.43.99.nip.io/downloads/desktop-update.json | python3 -c 'import json,sys;m=json.load(sys.stdin);assert (m["version"],m["linux_version"]) == ("0.3.18","0.3.17");print("PUBLIC_MANIFEST_OK",m["version"],m["linux_version"],m["sha256"])'
curl -sS -I -L -m 60 -o /dev/null -w 'PUBLIC_WINDOWS_VERSIONED http=%{http_code}\n' https://47.114.43.99.nip.io/downloads/Sunday_0.3.18_x64-setup.exe
curl -sS -I -L -m 60 -o /dev/null -w 'PUBLIC_WINDOWS_LATEST http=%{http_code}\n' https://47.114.43.99.nip.io/downloads/Sunday-latest-x64-setup.exe
curl -sS -I -L -m 60 -o /dev/null -w 'GITHUB_LINUX_APPIMAGE_0317 http=%{http_code}\n' https://github.com/Lam-Arc/LamTools/releases/latest/download/Sunday_0.3.17_amd64.AppImage
curl -sS -I -L -m 60 -o /dev/null -w 'GITHUB_LINUX_DEB_0317 http=%{http_code}\n' https://github.com/Lam-Arc/LamTools/releases/latest/download/Sunday_0.3.17_amd64.deb
printf 'FINAL_VERIFY_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
