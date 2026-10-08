"""Republish only the desktop 0.3.8 update manifest.

Why this exists: the first `deploy.py manifest` run failed before doing anything —
`check_manifest()` reads the upload copy from this directory, and the manifest had
been generated next to the installer (`release/desktop/desktop-update.json`) instead.
The installer publish had already succeeded, so at that moment the site served the
0.3.8 installer while `/var/www/lamtools/desktop-update.json` still described 0.3.7.
This script closes exactly that gap:

1. authorize — asserts the one-line baseline, that the *new* installer is the one
   served as latest (the precondition `deploy.py authorize` cannot express, because
   it runs before the publish), and that the stale 0.3.7 manifest is still there;
2. upload the manifest (already checked against the repository copy by `deploy.py`
   in the first run — `check_manifest()` is repeated here through the same file);
3. publish it with digest verification on both sides;
4. revoke the key and verify the published state.

Usage: py -3.14 manifest_republish.py authorize|upload|publish|cleanup
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import cloud  # noqa: E402
import deploy  # noqa: E402  (same constants and transfer helper)

CFG = deploy.CFG
VERSION = deploy.VERSION
DIGEST = deploy.DIGEST
LATEST = deploy.LATEST
MANIFEST = deploy.MANIFEST
MANIFEST_STAGED = deploy.MANIFEST_STAGED
MANIFEST_REMOTE = deploy.MANIFEST_REMOTE
PUB_KEY = deploy.PUB_KEY
BASELINE = CFG["authorized_keys_lines"]
STALE_SHA = "0beae41aad6dc93bab932f90c7109aba93e8c7bd23cfa083652be782f687c725"


def step_authorize():
    key = PUB_KEY.read_text(encoding="utf-8").strip()
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq {BASELINE}
test "$(sha256sum {LATEST} | cut -d' ' -f1)" = {DIGEST}
test "$(sha256sum {MANIFEST_REMOTE} | cut -d' ' -f1)" = {STALE_SHA}
test ! -e {MANIFEST_STAGED}
printf '%s\\n' 'restrict,command="internal-sftp" {key}' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("manifest-authorize", f"Append one restricted sftp key to republish the {VERSION} desktop manifest", script)


def step_upload():
    deploy.check_manifest()
    result = deploy.transfer(MANIFEST, f"root@47.114.43.99:{MANIFEST_STAGED}")
    digest = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    (ROOT / "manifest-transfer.json").write_text(json.dumps({
        "manifest": str(MANIFEST), "bytes": MANIFEST.stat().st_size,
        "sha256": digest, "staged": MANIFEST_STAGED, "returncode": result.returncode,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"manifest scp failed:\n{result.stderr[-2000:]}")
    print(f"uploaded {MANIFEST.stat().st_size} bytes to {MANIFEST_STAGED}", flush=True)


def step_publish():
    digest = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
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
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("manifest", f"Publish the desktop {VERSION} update manifest", script)
    CFG["manifest_sha256"] = digest
    CFG["manifest_bytes"] = MANIFEST.stat().st_size
    (ROOT / "release.json").write_text(json.dumps(CFG, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def step_cleanup():
    key_line = PUB_KEY.read_text(encoding="utf-8").strip().split()[1]
    digest = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
grep -vF '{key_line}' /root/.ssh/authorized_keys > /root/.ssh/authorized_keys.tmp038 || true
mv /root/.ssh/authorized_keys.tmp038 /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
ls -1 /var/tmp/Sunday-desktop-{VERSION}-*.desktop-update.json 2>/dev/null || echo 'no manifest stages'
sha256sum {LATEST} {MANIFEST_REMOTE}
printf '%s  %s\\n' '{digest}' '{MANIFEST_REMOTE}' | sha256sum -c -
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("manifest-cleanup", f"Revoke the manifest republish key and verify the published {VERSION} manifest", script)


if __name__ == "__main__":
    {"authorize": step_authorize, "upload": step_upload,
     "publish": step_publish, "cleanup": step_cleanup}[sys.argv[1]]()
