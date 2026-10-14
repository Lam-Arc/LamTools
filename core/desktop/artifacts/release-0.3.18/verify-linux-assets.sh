set -eu
printf 'GITHUB_LINUX_VERIFY_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
api=/tmp/sunday-0318-github-latest.json
curl --http1.1 -fsSL --retry 2 --retry-all-errors -m 90 https://api.github.com/repos/Lam-Arc/LamTools/releases/latest -o "$api"
python3 - "$api" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]))
print('LATEST_RELEASE',r['tag_name'])
assert r['tag_name']=='v0.3.17'
assets={a['name']:a for a in r['assets']}
for name in ('Sunday_0.3.17_amd64.AppImage','Sunday_0.3.17_amd64.deb'):
    a=assets[name]
    print('LINUX_ASSET',name,a['size'],a['browser_download_url'])
    assert a['size']>0
PY
for name in Sunday_0.3.17_amd64.AppImage Sunday_0.3.17_amd64.deb; do
  curl --http1.1 -sS -I -L --retry 2 --retry-all-errors -m 90 -o /dev/null -w "$name http=%{http_code} size=%{size_download}\n" "https://github.com/Lam-Arc/LamTools/releases/latest/download/$name"
done
printf 'GITHUB_LINUX_VERIFY_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
