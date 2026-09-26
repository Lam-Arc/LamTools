"""Publish the desktop 0.3.7 installer and update manifest to the official site.

Same audited shape as the mobile releases: one restricted sftp key, upload,
verify-then-swap, revoke. The manifest is the release pointer the app reads, and
it carries the installer's digest — the desktop downloads and verifies against
it before running anything, so the two must be published together.

Usage::

    py -3.14 deploy.py authorize|upload|publish|manifest|cleanup
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import cloud  # noqa: E402

CFG = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
VERSION = CFG["version"]
INSTALLER = Path(CFG["installer_path"])
NAME = INSTALLER.name
DIGEST = CFG["installer_sha256"]
STAGED = f"/var/tmp/Sunday-desktop-{VERSION}-{CFG['date_tag']}.upload.exe"
VERSIONED = f"/var/www/lamtools/{NAME}"
LATEST = "/var/www/lamtools/Sunday-latest-x64-setup.exe"
ARCHIVE = (
    f"/var/www/lamtools/Sunday-latest-x64-setup-{CFG['old_version']}"
    f"-before-{VERSION}-{CFG['date_tag']}.exe"
)
MANIFEST = ROOT / "desktop-update.json"
MANIFEST_STAGED = f"/var/tmp/Sunday-desktop-{VERSION}-{CFG['date_tag']}.desktop-update.json"
MANIFEST_REMOTE = "/var/www/lamtools/desktop-update.json"
MANIFEST_REPO = ROOT.parent.parent / "update-manifest.json"
KEY_DIR = ROOT / "transfer-key"
PRIVATE_KEY = KEY_DIR / "upload_ed25519"
PUB_KEY = KEY_DIR / "upload_ed25519.pub"
# The owner's Aliyun key pair is pre-existing; this flow restores this baseline.
BASELINE_KEY_LINES = CFG["authorized_keys_lines"]


def run_cloud(action):
    result = subprocess.run(
        [sys.executable, str(ROOT / "cloud.py"), action],
        capture_output=True, text=True, encoding="utf-8", timeout=900,
    )
    print(result.stdout, flush=True)
    if result.returncode != 0:
        raise SystemExit(f"cloud {action} failed:\n{result.stderr[-2000:]}")


def check_manifest():
    """The published manifest must describe this installer and match the repo copy."""
    published = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if published.get("version") != VERSION:
        raise SystemExit(f"manifest says {published.get('version')}, expected {VERSION}")
    if published.get("sha256") != DIGEST:
        raise SystemExit("manifest digest does not match the installer being published")
    if published.get("size") != INSTALLER.stat().st_size:
        raise SystemExit("manifest size does not match the installer being published")
    repository = json.loads(MANIFEST_REPO.read_text(encoding="utf-8"))
    if repository != published:
        raise SystemExit(
            "core/desktop/update-manifest.json disagrees with the manifest being published:\n"
            f"  repo:      {json.dumps(repository, ensure_ascii=False, sort_keys=True)}\n"
            f"  published: {json.dumps(published, ensure_ascii=False, sort_keys=True)}"
        )
    return MANIFEST


def transfer(local, target):
    return subprocess.run(
        ["scp", "-C", "-i", str(PRIVATE_KEY), "-o", "StrictHostKeyChecking=no",
         "-o", "UserKnownHostsFile=/dev/null", "-o", "IdentitiesOnly=yes", str(local), target],
        capture_output=True, text=True, timeout=3600,
    )


def step_authorize():
    KEY_DIR.mkdir(exist_ok=True)
    if not PRIVATE_KEY.exists():
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "sunday-desktop-037-upload",
             "-f", str(PRIVATE_KEY)],
            check=True, capture_output=True,
        )
    key = PUB_KEY.read_text(encoding="utf-8").strip()
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq {BASELINE_KEY_LINES}
test "$(sha256sum {LATEST} | cut -d' ' -f1)" = {CFG['old_latest_sha256']}
test ! -e {VERSIONED}
test ! -e {ARCHIVE}
test ! -e {STAGED}
test ! -e {MANIFEST_STAGED}
printf '%s\\n' 'restrict,command="internal-sftp" {key}' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
ls -l {MANIFEST_REMOTE}
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("authorize", f"Append one restricted forced-internal-sftp key for desktop {VERSION}", script)


def step_upload():
    target = f"root@47.114.43.99:{STAGED}"
    result = transfer(INSTALLER, target)
    (ROOT / "local-transfer.json").write_text(json.dumps({
        "installer": str(INSTALLER), "bytes": INSTALLER.stat().st_size, "sha256": DIGEST,
        "target": target, "staged": STAGED, "returncode": result.returncode,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"scp failed:\n{result.stderr[-2000:]}")
    print(f"uploaded {INSTALLER.stat().st_size} bytes to {STAGED}", flush=True)


def step_publish():
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\\n' '{DIGEST}' '{STAGED}' | sha256sum -c -
printf '%s  %s\\n' '{CFG['old_latest_sha256']}' '{LATEST}' | sha256sum -c -
test ! -e {VERSIONED}
test ! -e {ARCHIVE}
install -m 0755 {STAGED} {VERSIONED}.tmp
printf '%s  %s\\n' '{DIGEST}' '{VERSIONED}.tmp' | sha256sum -c -
ln {LATEST} {ARCHIVE}
mv {VERSIONED}.tmp {VERSIONED}
ln {VERSIONED} {LATEST}.new
mv -Tf {LATEST}.new {LATEST}
rm -- {STAGED}
printf '%s  %s\\n' '{DIGEST}' '{VERSIONED}' | sha256sum -c -
printf '%s  %s\\n' '{DIGEST}' '{LATEST}' | sha256sum -c -
printf '%s  %s\\n' '{CFG['old_latest_sha256']}' '{ARCHIVE}' | sha256sum -c -
stat -c '%n %s' {VERSIONED} {LATEST} {ARCHIVE}
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("publish", f"Publish desktop {VERSION}: versioned installer, latest pointer, previous archived", script)


def step_manifest():
    manifest = check_manifest()
    result = transfer(manifest, f"root@47.114.43.99:{MANIFEST_STAGED}")
    (ROOT / "manifest-transfer.json").write_text(json.dumps({
        "manifest": str(manifest), "bytes": manifest.stat().st_size,
        "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "staged": MANIFEST_STAGED, "returncode": result.returncode,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"manifest scp failed:\n{result.stderr[-2000:]}")
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\\n' '{digest}' '{MANIFEST_STAGED}' | sha256sum -c -
printf '%s  %s\\n' '{DIGEST}' '{LATEST}' | sha256sum -c -
install -m 0644 {MANIFEST_STAGED} {MANIFEST_REMOTE}.tmp
printf '%s  %s\\n' '{digest}' '{MANIFEST_REMOTE}.tmp' | sha256sum -c -
mv {MANIFEST_REMOTE}.tmp {MANIFEST_REMOTE}
rm -- {MANIFEST_STAGED}
printf '%s  %s\\n' '{digest}' '{MANIFEST_REMOTE}' | sha256sum -c -
cat {MANIFEST_REMOTE}
curl -sS -D - -o /dev/null -H 'Origin: https://tauri.localhost' \\
  --resolve 47.114.43.99.nip.io:443:127.0.0.1 https://47.114.43.99.nip.io/downloads/desktop-update.json \\
  | grep -iE 'HTTP/|content-length' || true
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("manifest", f"Publish the desktop {VERSION} update manifest", script)


def step_cleanup():
    key_line = PUB_KEY.read_text(encoding="utf-8").strip().split()[1]
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
grep -vF '{key_line}' /root/.ssh/authorized_keys > /root/.ssh/authorized_keys.tmp037 || true
mv /root/.ssh/authorized_keys.tmp037 /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
grep -cF '{key_line}' /root/.ssh/authorized_keys || true
wc -l /root/.ssh/authorized_keys
ls -1 /var/tmp/Sunday-desktop-{VERSION}-*.upload.exe 2>/dev/null || echo 'no stages'
sha256sum {VERSIONED} {LATEST} {ARCHIVE} {MANIFEST_REMOTE}
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("cleanup", f"Revoke the desktop {VERSION} transfer key and verify published state", script)


if __name__ == "__main__":
    {"authorize": step_authorize, "upload": step_upload, "publish": step_publish,
     "manifest": step_manifest, "cleanup": step_cleanup}[sys.argv[1]]()
