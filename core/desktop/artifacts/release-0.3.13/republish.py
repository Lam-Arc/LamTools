"""Same-version republish of the 0.3.13 installer (no version bump, by request).

The 0.3.13 release record in this folder covers the CI build of tag v0.3.13.
This script publishes a *second* build of the same version — the in-app guidance
fix — for the site channel only. It mirrors the audited shape of `deploy.py`
(restricted sftp key, upload, verify-then-swap, revoke) with the two preconditions
a same-version republish needs:

* what is on the channel now must be the first 0.3.13 build, so an interleaved
  publish from anywhere else fails here instead of being silently replaced;
* the versioned file already exists, so the previous bytes are archived before
  the swap instead of the step refusing to run.

The GitHub Release for v0.3.13 keeps the first build: its assets cannot be
replaced without repository credentials this machine does not have, and the tag
that produced them is immutable. That divergence is recorded in REPUBLISH.md.

Usage::

    py -3.14 republish.py preflight|authorize|upload|publish|manifest|cleanup
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import cloud  # noqa: E402

VERSION = "0.3.13"
DATE_TAG = "20261009"
#: The build this republish supersedes (CI build of tag v0.3.13).
BUILD1_SHA = "69e63994851bb0152838b3d37f4612c9a061157f10594c6a60527a782eb52409"
BUILD1_SIZE = 58191548
#: The manifest the channel serves before this republish.
BUILD1_MANIFEST_SHA = "0016a410549484de8b8e22777891e977a98b49645f778e94f8c0a40befa197ce"

INSTALLER = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("E:/LamTools/release/desktop/Sunday_0.3.13_x64-setup.exe")
STAGE = f"/var/tmp/Sunday-desktop-{VERSION}-{DATE_TAG}-republish.upload.exe"
VERSIONED = f"/var/www/lamtools/Sunday_{VERSION}_x64-setup.exe"
LATEST = "/var/www/lamtools/Sunday-latest-x64-setup.exe"
ARCHIVE = f"/var/www/lamtools/Sunday-latest-x64-setup-{VERSION}-build1-before-republish-{DATE_TAG}.exe"
MANIFEST_SRC = Path("E:/LamTools/release/desktop/desktop-update.json")
MANIFEST_STAGED = f"/var/tmp/Sunday-desktop-{VERSION}-{DATE_TAG}-republish.desktop-update.json"
MANIFEST_REMOTE = "/var/www/lamtools/desktop-update.json"
KEY_DIR = ROOT / "transfer-key"
PRIVATE_KEY = KEY_DIR / "upload_ed25519"
PUB_KEY = KEY_DIR / "upload_ed25519.pub"
BASELINE_KEY_LINES = 1


def digest_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def transfer(local: Path, target: str):
    return subprocess.run(
        ["scp", "-C", "-i", str(PRIVATE_KEY), "-o", "StrictHostKeyChecking=no",
         "-o", "UserKnownHostsFile=/dev/null", "-o", "IdentitiesOnly=yes", str(local), target],
        capture_output=True, text=True, timeout=3600,
    )


def step_preflight():
    cloud.command("republish-preflight", f"Read-only: state of the {VERSION} channel before the same-version republish", f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
printf '%s  %s\\n' '{BUILD1_SHA}' '{LATEST}' | sha256sum -c -
printf '%s  %s\\n' '{BUILD1_SHA}' '{VERSIONED}' | sha256sum -c -
printf '%s  %s\\n' '{BUILD1_MANIFEST_SHA}' '{MANIFEST_REMOTE}' | sha256sum -c -
cat {MANIFEST_REMOTE}
wc -l /root/.ssh/authorized_keys
for path in {ARCHIVE} {STAGE} {MANIFEST_STAGED}; do
  if [ -e "$path" ]; then echo "PRESENT $path"; else echo "absent $path"; fi
done
date -u +%Y-%m-%dT%H:%M:%SZ
""")


def step_authorize():
    KEY_DIR.mkdir(exist_ok=True)
    if not PRIVATE_KEY.exists():
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", f"sunday-desktop-{VERSION}-republish",
                        "-f", str(PRIVATE_KEY)], check=True, capture_output=True)
    key = PUB_KEY.read_text(encoding="utf-8").strip()
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq {BASELINE_KEY_LINES}
printf '%s  %s\\n' '{BUILD1_SHA}' '{LATEST}' | sha256sum -c -
printf '%s  %s\\n' '{BUILD1_SHA}' '{VERSIONED}' | sha256sum -c -
test ! -e {ARCHIVE}
test ! -e {STAGE}
test ! -e {MANIFEST_STAGED}
printf '%s\\n' 'restrict,command="internal-sftp" {key}' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("republish-authorize", f"Append one restricted forced-internal-sftp key for the {VERSION} republish", script)


def step_upload():
    digest = digest_of(INSTALLER)
    target = f"root@47.114.43.99:{STAGE}"
    result = transfer(INSTALLER, target)
    (ROOT / "republish-local-transfer.json").write_text(json.dumps({
        "installer": str(INSTALLER), "bytes": INSTALLER.stat().st_size, "sha256": digest,
        "build": "second build of 0.3.13 (local package.ps1, guidance fix, version unchanged)",
        "target": target, "staged": STAGE, "returncode": result.returncode,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"scp failed:\n{result.stderr[-2000:]}")
    print(f"uploaded {INSTALLER.stat().st_size} bytes to {STAGE}", flush=True)


def step_publish():
    digest = digest_of(INSTALLER)
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\\n' '{digest}' '{STAGE}' | sha256sum -c -
printf '%s  %s\\n' '{BUILD1_SHA}' '{VERSIONED}' | sha256sum -c -
printf '%s  %s\\n' '{BUILD1_SHA}' '{LATEST}' | sha256sum -c -
test ! -e {ARCHIVE}
ln {VERSIONED} {ARCHIVE}
printf '%s  %s\\n' '{BUILD1_SHA}' '{ARCHIVE}' | sha256sum -c -
install -m 0755 {STAGE} {VERSIONED}.tmp
printf '%s  %s\\n' '{digest}' '{VERSIONED}.tmp' | sha256sum -c -
mv {VERSIONED}.tmp {VERSIONED}
ln {VERSIONED} {LATEST}.new
mv -Tf {LATEST}.new {LATEST}
rm -- {STAGE}
printf '%s  %s\\n' '{digest}' '{VERSIONED}' | sha256sum -c -
printf '%s  %s\\n' '{digest}' '{LATEST}' | sha256sum -c -
printf '%s  %s\\n' '{BUILD1_SHA}' '{ARCHIVE}' | sha256sum -c -
stat -c '%n %s' {VERSIONED} {LATEST} {ARCHIVE}
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("republish-publish", f"Publish the second {VERSION} build: archive the first build, swap versioned and latest", script)


def step_manifest():
    body = MANIFEST_SRC.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    manifest = json.loads(body.decode("utf-8"))
    if manifest.get("version") != VERSION or manifest.get("sha256") != digest_of(INSTALLER):
        raise SystemExit("desktop-update.json does not describe this build")
    result = transfer(MANIFEST_SRC, f"root@47.114.43.99:{MANIFEST_STAGED}")
    (ROOT / "republish-manifest-transfer.json").write_text(json.dumps({
        "manifest": str(MANIFEST_SRC), "bytes": len(body), "sha256": digest,
        "staged": MANIFEST_STAGED, "returncode": result.returncode,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"manifest scp failed:\n{result.stderr[-2000:]}")
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\\n' '{digest}' '{MANIFEST_STAGED}' | sha256sum -c -
printf '%s  %s\\n' '{digest_of(INSTALLER)}' '{LATEST}' | sha256sum -c -
install -m 0644 {MANIFEST_STAGED} {MANIFEST_REMOTE}.tmp
printf '%s  %s\\n' '{digest}' {MANIFEST_REMOTE}.tmp | sha256sum -c -
mv {MANIFEST_REMOTE}.tmp {MANIFEST_REMOTE}
rm -- {MANIFEST_STAGED}
printf '%s  %s\\n' '{digest}' {MANIFEST_REMOTE} | sha256sum -c -
cat {MANIFEST_REMOTE}
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("republish-manifest", f"Publish the {VERSION} manifest for the second build", script)


def step_cleanup():
    key_line = PUB_KEY.read_text(encoding="utf-8").strip().split()[1]
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
grep -vF '{key_line}' /root/.ssh/authorized_keys > /root/.ssh/authorized_keys.tmp-rp || true
mv /root/.ssh/authorized_keys.tmp-rp /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
grep -cF '{key_line}' /root/.ssh/authorized_keys || true
wc -l /root/.ssh/authorized_keys
ls -1 /var/tmp/Sunday-desktop-{VERSION}-*republish* 2>/dev/null || echo 'no republish stages'
sha256sum {VERSIONED} {LATEST} {ARCHIVE} {MANIFEST_REMOTE}
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("republish-cleanup", f"Revoke the republish transfer key and verify the published {VERSION} state", script)


if __name__ == "__main__":
    action = sys.argv[1]
    {"preflight": step_preflight, "authorize": step_authorize, "upload": step_upload,
     "publish": step_publish, "manifest": step_manifest, "cleanup": step_cleanup}[action]()
