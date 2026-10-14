set -eu
printf 'VERIFY_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
stage=/var/tmp/Sunday-desktop-0.3.17-20261013.upload.exe
stat -c 'PARTIAL_BEFORE size=%s mtime=%y' "$stage"
pgrep -a -f '[c]url.*Sunday_0\.3\.17_x64-setup\.exe' || true
sleep 15
stat -c 'PARTIAL_AFTER size=%s mtime=%y' "$stage"
pgrep -a -f '[c]url.*Sunday_0\.3\.17_x64-setup\.exe' || true
printf 'VERIFY_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
