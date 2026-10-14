set -eu
printf 'VERIFY_UTC_BEGIN='; date -u +%Y-%m-%dT%H:%M:%SZ
stage=/var/tmp/dl-0.3.17-20261013/Sunday_0.3.17_x64-setup.exe
if [ -f "$stage" ]; then stat -c 'NEW_STAGE size=%s mtime=%y' "$stage"; else echo NEW_STAGE absent; fi
pgrep -a -f '[c]url.*Sunday_0\.3\.17_x64-setup\.exe' || true
sleep 15
if [ -f "$stage" ]; then stat -c 'NEW_STAGE_AFTER size=%s mtime=%y' "$stage"; else echo NEW_STAGE_AFTER absent; fi
pgrep -a -f '[c]url.*Sunday_0\.3\.17_x64-setup\.exe' || true
printf 'VERIFY_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
