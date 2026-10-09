"""Publish the refreshed website (Sunday 0.3.14 label) alongside release 0.3.14.

Same audited shape as the APK deploy: authorize -> upload -> publish -> revoke.
The phone label stays 0.1.48; the previous site release is preserved.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import cloud  # noqa: E402

SITE_VERSION = "0.3.14"
DATE_TAG = "20261009"
SITE_NAME = f"{SITE_VERSION}-mobile-0.1.48-{DATE_TAG}"
TARBALL = ROOT / f"site-{SITE_VERSION}.tar.gz"
TARBALL_SHA = "35a1c41bc897b0cbf3f2c8abd7879529856af96940358915ce27ffd1a5d6aa6c"
CURRENT_SITE = "0.3.13-mobile-0.1.48-20261009"
LATEST_APK_SHA = "fc18f4c0676822d52884b490a2beb196ea3fb978dc4640e4e8acfc8904f5684a"
# The installer channel must be the 0.3.13 this round published (the installer goes out
# first), so an interleaved publish from another session fails here instead of downgrading
# the site with a stale bundle.
LATEST_INSTALLER_SHA = "c421d41eb452ae80c7d79a6a5fb06e4ab36c2ea1750c46774bd6c4ff4f3c1dc8"  # 0.3.14, published in this round
# Pre-existing grants are left exactly as they were found: the 0.1.23 flow ended
# with zero lines, but by 20:31 on 2026-09-24 the instance carried one Aliyun key
# pair (comment skp-bp19aylqsh2502ocgm9c) that this flow did not add and must not
# remove. Both the authorize step and the revoke step work from this baseline.
BASELINE_KEY_LINES = 1
STAGED = f"/var/tmp/Sunday-site-mobile-{SITE_VERSION}-{DATE_TAG}.upload.tar.gz"
RELEASE_DIR = f"/var/www/lamtools/site-releases/{SITE_NAME}"
KEY_DIR = ROOT / "site-key"
PRIVATE_KEY = KEY_DIR / "upload_ed25519"
PUB_KEY = KEY_DIR / "upload_ed25519.pub"


def require(values):
    for name, value in values.items():
        if not value:
            raise SystemExit(f"{name} must be set before running this step")


def step_authorize():
    require({"TARBALL_SHA": TARBALL_SHA, "LATEST_APK_SHA": LATEST_APK_SHA})
    KEY_DIR.mkdir(exist_ok=True)
    if not PRIVATE_KEY.exists():
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C",
                        f"sunday-mobile-{SITE_VERSION}-site-upload", "-f", str(PRIVATE_KEY)], check=True)
    key = PUB_KEY.read_text(encoding="utf-8").strip()
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq {BASELINE_KEY_LINES}
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/{CURRENT_SITE}
test "$(sha256sum /var/www/lamtools/Sunday-mobile-latest.apk | cut -d' ' -f1)" = {LATEST_APK_SHA}
test "$(sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe | cut -d' ' -f1)" = {LATEST_INSTALLER_SHA}
test ! -e {RELEASE_DIR}
test ! -e {STAGED}
printf '%s\\n' 'restrict,command="internal-sftp" {key}' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("site-authorize", f"Append one restricted forced-internal-sftp key for the {SITE_VERSION} site transfer", script)


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
grep -R -q '{SITE_VERSION}' {RELEASE_DIR}/assets
ln -s {RELEASE_DIR} /var/www/lamtools/site.new{SITE_VERSION.replace('.', '')}
mv -Tf /var/www/lamtools/site.new{SITE_VERSION.replace('.', '')} /var/www/lamtools/site
rm -- {STAGED}
readlink -f /var/www/lamtools/site
ls -1 /var/www/lamtools/site-releases/ | tail -4
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("site-publish", f"Extract the {SITE_VERSION} site release and atomically repoint the site symlink", script)


def step_cleanup():
    key_line = PUB_KEY.read_text(encoding="utf-8").strip().split()[1]
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
grep -vF '{key_line}' /root/.ssh/authorized_keys > /root/.ssh/authorized_keys.tmp{SITE_VERSION.replace('.', '')} || true
mv /root/.ssh/authorized_keys.tmp{SITE_VERSION.replace('.', '')} /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
ls -1 /var/tmp/Sunday-site-mobile-{SITE_VERSION}-*.upload.tar.gz 2>/dev/null || echo 'no stages'
readlink -f /var/www/lamtools/site
sha256sum /var/www/lamtools/Sunday-mobile-latest.apk /var/www/lamtools/mobile-update.json
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("site-cleanup", f"Revoke the exact site transfer key and verify the published {SITE_VERSION} site", script)


if __name__ == "__main__":
    {"authorize": step_authorize, "upload": step_upload,
     "publish": step_publish, "cleanup": step_cleanup}[sys.argv[1]]()
