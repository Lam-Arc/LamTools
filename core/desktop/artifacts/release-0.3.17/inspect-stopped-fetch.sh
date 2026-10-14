set -eu
printf 'CHECK_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
stage=/var/tmp/Sunday-desktop-0.3.17-20261013.upload.exe
if [ -f "$stage" ]; then stat -c 'STAGE_BEFORE size=%s mtime=%y' "$stage"; else echo STAGE_BEFORE missing; fi
pgrep -a -f '[c]url.*Sunday_0\.3\.17_x64-setup\.exe' || true
sleep 15
if [ -f "$stage" ]; then stat -c 'STAGE_AFTER size=%s mtime=%y' "$stage"; else echo STAGE_AFTER missing; fi
pgrep -a -f '[c]url.*Sunday_0\.3\.17_x64-setup\.exe' || true
printf 'CHECK_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
