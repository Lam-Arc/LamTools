#!/bin/bash
set -u
date -u +INSPECT_UTC_BEGIN=%Y-%m-%dT%H:%M:%SZ
stage=/var/tmp/Sunday-desktop-0.3.17-20261013.upload.exe
if [ -e "$stage" ]; then stat -c 'STAGE_PRESENT path=%n bytes=%s mode=%a mtime=%y' "$stage"; sha256sum "$stage"; else echo "STAGE_ABSENT $stage"; fi
printf 'CURL_PIDS='
ps -eo pid,ppid,stat,etime,comm | awk '$5 == "curl" { printf "%s(pid=%s,ppid=%s,state=%s,elapsed=%s) ", $5, $1, $2, $3, $4 } END { print "" }'
date -u +INSPECT_UTC_END=%Y-%m-%dT%H:%M:%SZ