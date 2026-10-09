set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\n' 'c5d0cea2006747e004b02316461f6f95def3f7a1ca5d7670edb64835b064a1c7' '/var/tmp/Sunday-desktop-0.3.13-20261009-republish.desktop-update.json' | sha256sum -c -
printf '%s  %s\n' '81a9dc00284264fd7df43930212be1c95e33c9d052ba2e7552f40a625d6eb383' '/var/www/lamtools/Sunday-latest-x64-setup.exe' | sha256sum -c -
install -m 0644 /var/tmp/Sunday-desktop-0.3.13-20261009-republish.desktop-update.json /var/www/lamtools/desktop-update.json.tmp
printf '%s  %s\n' 'c5d0cea2006747e004b02316461f6f95def3f7a1ca5d7670edb64835b064a1c7' /var/www/lamtools/desktop-update.json.tmp | sha256sum -c -
mv /var/www/lamtools/desktop-update.json.tmp /var/www/lamtools/desktop-update.json
rm -- /var/tmp/Sunday-desktop-0.3.13-20261009-republish.desktop-update.json
printf '%s  %s\n' 'c5d0cea2006747e004b02316461f6f95def3f7a1ca5d7670edb64835b064a1c7' /var/www/lamtools/desktop-update.json | sha256sum -c -
cat /var/www/lamtools/desktop-update.json
date -u +%Y-%m-%dT%H:%M:%SZ
