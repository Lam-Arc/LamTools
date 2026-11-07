#!/usr/bin/env bash
# Installs the built APK and reports what actually happened on the device.
#
# This is the acceptance step the emulator can answer: does the app install, does it
# unpack the runtime, does the guest core come up, and does the UI reach it. Anything it
# cannot answer (a real arm64 phone, background/foreground recovery) is reported as
# unverified rather than assumed.
set -uo pipefail
ADB="adb -s ${DEVICE:-emulator-5554}"
APK="${1:?usage: verify-apk.sh path/to.apk}"
PKG=com.lamtools.sunday.core

say() { printf '\n\033[1;34m[verify]\033[0m %s\n' "$*"; }

say "installing $APK ($(du -h "$APK" | cut -f1))"
$ADB install -r -g "$APK" 2>&1 | tail -3 || exit 1

say "clearing logcat"
$ADB logcat -c

say "launching"
$ADB shell am start -n "$PKG/.MainActivity" 2>&1 | tail -2

say "waiting for the runtime to unpack and the guest to start (up to 240s)"
for i in $(seq 1 48); do
  sleep 5
  if $ADB logcat -d -s sunday:* RustStdoutStderr:* AndroidRuntime:E 2>/dev/null | grep -q "Uvicorn running"; then
    say "guest core is listening after $((i * 5))s"
    break
  fi
  if $ADB logcat -d 2>/dev/null | grep -q "core did not become ready"; then
    say "guest failed to become ready"
    break
  fi
done

say "logcat (sunday + runtime)"
$ADB logcat -d -s sunday:* RustStdoutStderr:* AndroidRuntime:E 2>/dev/null | tail -40

say "installed files"
$ADB shell "run-as $PKG ls -la files/runtime 2>/dev/null | head -10; du -sh files/runtime 2>/dev/null"

say "process"
$ADB shell "ps -A | grep -e sunday -e proot -e python3 | head -6"

say "screenshot"
$ADB exec-out screencap -p > "apk-screen.png" 2>/dev/null && echo "wrote apk-screen.png"
