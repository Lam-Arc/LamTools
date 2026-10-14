set -eu
printf 'STOP_UTC='; date -u +%Y-%m-%dT%H:%M:%SZ
stage=/var/tmp/Sunday-desktop-0.3.17-20261013.upload.exe
expected='https://github.com/Lam-Arc/LamTools/releases/download/v0.3.17/Sunday_0.3.17_x64-setup.exe'
found=0
for proc in /proc/[0-9]*; do
  [ -r "$proc/cmdline" ] || continue
  cmd=$(tr '\000' ' ' < "$proc/cmdline")
  case "$cmd" in
    *"curl "*"-o $stage"*"$expected"*)
      pid=${proc##*/}
      printf 'MATCH pid=%s cmd=%s\n' "$pid" "$cmd"
      kill -TERM "$pid"
      found=$((found+1))
      ;;
  esac
done
sleep 3
printf 'MATCHES_STOPPED=%s\n' "$found"
pgrep -a -f '[c]url.*Sunday_0\.3\.17_x64-setup\.exe' || true
stat -c 'STAGE_AFTER_STOP size=%s mtime=%y' "$stage"
printf 'STOP_UTC_END='; date -u +%Y-%m-%dT%H:%M:%SZ
