#!/bin/sh
# Read-only preflight for desktop 0.3.17. Do not print authorized_keys contents.
set -u
VERSION=0.3.17
OLD_VERSION=0.3.16
DATE_TAG=20261013
MOBILE_VERSION=0.1.48
INSTALLER="Sunday_${VERSION}_x64-setup.exe"
VERSIONED="/var/www/lamtools/${INSTALLER}"
LATEST=/var/www/lamtools/Sunday-latest-x64-setup.exe
ARCHIVE="/var/www/lamtools/Sunday-latest-x64-setup-${OLD_VERSION}-before-${VERSION}-${DATE_TAG}.exe"
MANIFEST=/var/www/lamtools/desktop-update.json
STAGE="/var/tmp/Sunday-desktop-${VERSION}-${DATE_TAG}.upload.exe"
MANIFEST_STAGE="/var/tmp/Sunday-desktop-${VERSION}-${DATE_TAG}.desktop-update.json"
SITE="/var/www/lamtools/site"
SITE_CURRENT="/var/www/lamtools/site-releases/${OLD_VERSION}-mobile-${MOBILE_VERSION}-20261009"
SITE_TARGET="/var/www/lamtools/site-releases/${VERSION}-mobile-${MOBILE_VERSION}-${DATE_TAG}"
SITE_STAGE="/var/tmp/Sunday-site-mobile-${VERSION}-${DATE_TAG}.upload.tar.gz"

printf 'PREFLIGHT_UTC_BEGIN='
date -u +%Y-%m-%dT%H:%M:%SZ
printf '\nSERVICES\n'
for service in caddy-lamtools lamtools-relay; do
  printf '%s=' "$service"
  systemctl is-active "$service" 2>&1 || true
done
printf '\nCURRENT_SITE\n'
readlink -f "$SITE" 2>&1 || true
printf '\nLATEST_SITE_RELEASES\n'
if [ -d /var/www/lamtools/site-releases ]; then
  ls -1 /var/www/lamtools/site-releases | sort -V | tail -6
else
  echo 'MISSING /var/www/lamtools/site-releases'
fi
printf '\nLATEST_INSTALLER_HASH\n'
if [ -f "$LATEST" ]; then sha256sum "$LATEST"; else echo "MISSING $LATEST"; fi
printf '\nCURRENT_MANIFEST\n'
if [ -f "$MANIFEST" ]; then
  cat "$MANIFEST"
  printf '\nMANIFEST_FILE_HASH\n'
  sha256sum "$MANIFEST"
else
  echo "MISSING $MANIFEST"
fi
printf '\nTARGET_AND_STAGING_PATHS\n'
for path in "$VERSIONED" "$ARCHIVE" "$STAGE" "$MANIFEST_STAGE" "$SITE_TARGET" "$SITE_STAGE"; do
  if [ -e "$path" ]; then
    stat -c 'PRESENT %n mode=%a bytes=%s' "$path"
  else
    printf 'ABSENT %s\n' "$path"
  fi
done
printf '\nCURRENT_SITE_EXPECTED\n'
if [ "$(readlink -f "$SITE" 2>/dev/null || true)" = "$SITE_CURRENT" ]; then
  printf 'MATCH %s\n' "$SITE_CURRENT"
else
  printf 'MISMATCH expected=%s actual=%s\n' "$SITE_CURRENT" "$(readlink -f "$SITE" 2>/dev/null || echo MISSING)"
fi
printf '\nSSH_AUTHORIZED_KEYS_METADATA_ONLY\n'
if [ -f /root/.ssh/authorized_keys ]; then
  stat -c 'mode=%a bytes=%s' /root/.ssh/authorized_keys
  printf 'lines='
  wc -l < /root/.ssh/authorized_keys
else
  echo 'MISSING /root/.ssh/authorized_keys'
fi
printf '\nPREFLIGHT_UTC_END='
date -u +%Y-%m-%dT%H:%M:%SZ