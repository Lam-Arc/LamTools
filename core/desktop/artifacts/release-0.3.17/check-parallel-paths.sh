set -eu
for path in /var/tmp/Sunday-desktop-0.3.17-20261013.parallel.exe /var/tmp/dl-0.3.17-20261013T0935; do
  if [ -e "$path" ]; then echo "EXISTS $path"; else echo "ABSENT $path"; fi
done
printf 'PATH_CHECK_UTC='; date -u +%Y-%m-%dT%H:%M:%SZ
