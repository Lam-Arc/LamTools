"""Publish the refreshed website (Sunday 0.3.8 + mobile 0.1.45 labels).

Same audited shape as the installer deploy: authorize -> upload -> publish ->
revoke. This is a desktop-led site release: the desktop label moves to 0.3.8
while the mobile label stays 0.1.45, and the previous site release is preserved.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import cloud  # noqa: E402

DESKTOP_VERSION = "0.3.8"
MOBILE_VERSION = "0.1.45"
DATE_TAG = "20260928"
SITE_NAME = f"{DESKTOP_VERSION}-mobile-{MOBILE_VERSION}-{DATE_TAG}"
TARBALL = ROOT / f"site-{DESKTOP_VERSION}.tar.gz"
TARBALL_SHA = "62a13514bcae1ce5528450428d9ca3ddfb90c12d4ab5d0b0b19f6b4289ae9276"
CURRENT_SITE = "0.3.7-mobile-0.1.45-20260928"
LATEST_INSTALLER_SHA = "c76b67615955c870a8cdaab61fecf4e1c08e4d29b04bb1a123dd74b45b8c5e6e"
LATEST_APK_SHA = "fcf64cb9cd695d24b82c43e7fc64aae6afbbbc0b59dce4d9eae2cd598a2f571f"
# Pre-existing grants are left exactly as they were found: the instance carries
# one Aliyun key pair (comment skp-bp19aylqsh2502ocgm9c) that this flow did not
# add and must not remove. Both the authorize step and the revoke step work from
# this baseline.
BASELINE_KEY_LINES = 1
STAGED = f"/var/tmp/Sunday-site-{DESKTOP_VERSION}-{DATE_TAG}.upload.tar.gz"
# One-shot suffix for the atomic symlink swap (e.g. 0380145).
SYMLINK_SUFFIX = DESKTOP_VERSION.replace(".", "") + MOBILE_VERSION.replace(".", "")
RELEASE_DIR = f"/var/www/lamtools/site-releases/{SITE_NAME}"
KEY_DIR = ROOT / "site-key"
PRIVATE_KEY = KEY_DIR / "upload_ed25519"
PUB_KEY = KEY_DIR / "upload_ed25519.pub"


def require(values):
    for name, value in values.items():
        if not value:
            raise SystemExit(f"{name} must be set before running this step")


def step_authorize():
    require({"TARBALL_SHA": TARBALL_SHA, "LATEST_APK_SHA": LATEST_APK_SHA, "LATEST_INSTALLER_SHA": LATEST_INSTALLER_SHA})
    KEY_DIR.mkdir(exist_ok=True)
    if not PRIVATE_KEY.exists():
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C",
                        f"sunday-desktop-{DESKTOP_VERSION}-site-upload", "-f", str(PRIVATE_KEY)], check=True)
    key = PUB_KEY.read_text(encoding="utf-8").strip()
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq {BASELINE_KEY_LINES}
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/{CURRENT_SITE}
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = {LATEST_INSTALLER_SHA}
test "$(sha256sum /var/www/lamtools/Sunday-mobile-latest.apk | cut -d' ' -f1)" = {LATEST_APK_SHA}
test ! -e {RELEASE_DIR}
test ! -e {STAGED}
printf '%s\\n' 'restrict,command="internal-sftp" {key}' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("site-authorize", f"Append one restricted forced-internal-sftp key for the {DESKTOP_VERSION} site transfer", script)


def step_upload():
    require({"TARBALL_SHA": TARBALL_SHA})
    target = f"root@47.114.43.99:{STAGED}"
    result = subprocess.run(
        ["scp", "-C", "-i", str(PRIVATE_KEY), "-o", "StrictHostKeyChecking=no",
         "-o", "UserKnownHostsFile=/dev/null", "-o", "IdentitiesOnly=yes", str(TARBALL), target],
        capture_output=True, text=True, timeout=1800)
    (ROOT / "site-local-transfer.json").write_text(
        f'{{"tarball": "{TARBALL.name}", "bytes": {TARBALL.stat().st_size}, "sha256": "{TARBALL_SHA}", '
        f'"staged": "{STAGED}", "returncode": {result.returncode}}}\n', encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"scp failed:\n{result.stderr[-2000:]}")
    print(f"uploaded {TARBALL.stat().st_size} bytes to {STAGED}", flush=True)


def step_publish():
    require({"TARBALL_SHA": TARBALL_SHA})
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\\n' '{TARBALL_SHA}' '{STAGED}' | sha256sum -c -
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/{CURRENT_SITE}
test ! -e {RELEASE_DIR}
mkdir -m 0755 {RELEASE_DIR}
tar -xzf {STAGED} -C {RELEASE_DIR} --no-same-owner
find {RELEASE_DIR} -type d -exec chmod 755 {{}} +
find {RELEASE_DIR} -type f -exec chmod 644 {{}} +
test -f {RELEASE_DIR}/index.html
grep -R -q '{DESKTOP_VERSION}' {RELEASE_DIR}/assets
grep -R -q '{MOBILE_VERSION}' {RELEASE_DIR}/assets
ln -s {RELEASE_DIR} /var/www/lamtools/site.new{SYMLINK_SUFFIX}
mv -Tf /var/www/lamtools/site.new{SYMLINK_SUFFIX} /var/www/lamtools/site
rm -- {STAGED}
readlink -f /var/www/lamtools/site
ls -1 /var/www/lamtools/site-releases/ | tail -4
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("site-publish", f"Extract the {SITE_NAME} site release and atomically repoint the site symlink", script)


def step_cleanup():
    key_line = PUB_KEY.read_text(encoding="utf-8").strip().split()[1]
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
grep -vF '{key_line}' /root/.ssh/authorized_keys > /root/.ssh/authorized_keys.tmp{DESKTOP_VERSION.replace('.', '')} || true
mv /root/.ssh/authorized_keys.tmp{DESKTOP_VERSION.replace('.', '')} /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
ls -1 /var/tmp/Sunday-site-{DESKTOP_VERSION}-*.upload.tar.gz 2>/dev/null || echo 'no stages'
readlink -f /var/www/lamtools/site
sha256sum /var/www/lamtools/Sunday-mobile-latest.apk /var/www/lamtools/mobile-update.json
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("site-cleanup", f"Revoke the exact site transfer key and verify the published {SITE_NAME} site", script)


if __name__ == "__main__":
    {"authorize": step_authorize, "upload": step_upload,
     "publish": step_publish, "cleanup": step_cleanup}[sys.argv[1]]()
