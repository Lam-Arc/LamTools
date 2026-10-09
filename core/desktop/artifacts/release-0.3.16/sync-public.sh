set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
if [ -x /usr/local/bin/sync-public-site.sh ]; then
  sh /usr/local/bin/sync-public-site.sh
else
  echo "sync-public-site.sh is not installed on the server" >&2
  exit 1
fi
sh /usr/local/bin/sync-public-site.sh --check
echo SYNC_OK
date -u +%Y-%m-%dT%H:%M:%SZ
