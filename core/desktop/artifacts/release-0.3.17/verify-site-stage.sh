set -eu
printf 'SITE_STAGE_VERIFY_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
stage=/var/tmp/Sunday-site-mobile-0.3.17-20261013.upload.tar.gz
printf '%s  %s\n' 'e8806876f2f7a204a51c67e12790d3e04a43c986f91b79df43d8a9e30d152be2' "$stage" | sha256sum -c -
stat -c 'bytes=%s mode=%a owner=%U:%G' "$stage"
tar -tzf "$stage" | head -12
printf '\nSYNC_SCRIPT_BEGIN\n'; sed -n '1,260p' /usr/local/bin/sync-public-site.sh; printf 'SYNC_SCRIPT_END\n'
printf 'SITE_STAGE_VERIFY_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
