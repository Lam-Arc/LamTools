"""Publish ``downloads/desktop-update.json`` — the desktop update manifest.

The desktop checker reads the official site first and falls back to GitHub
Releases. The manifest was never uploaded, so `/downloads/desktop-update.json`
answered 404 and every install silently used GitHub — workable here, poor
exactly where the site exists for: regions where GitHub is slow or blocked.

Same audited shape as a mobile release: authorize one restricted key, upload,
publish, revoke.

Usage::

    py -3.14 deploy.py authorize|upload|publish|cleanup
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import cloud  # noqa: E402

MANIFEST = ROOT / "desktop-update.json"
STAGED = "/var/tmp/Sunday-desktop-update-20260926.json"
REMOTE = "/var/www/lamtools/desktop-update.json"
KEY_DIR = ROOT / "transfer-key"
PRIVATE_KEY = KEY_DIR / "upload_ed25519"
PUB_KEY = KEY_DIR / "upload_ed25519.pub"
# The owner's Aliyun key pair is pre-existing; this flow restores this baseline.
BASELINE_KEY_LINES = 1

DIGEST = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
BYTES = MANIFEST.stat().st_size


def run_cloud(action):
    result = subprocess.run(
        [sys.executable, str(ROOT / "cloud.py"), action],
        capture_output=True, text=True, encoding="utf-8", timeout=900,
    )
    print(result.stdout, flush=True)
    if result.returncode != 0:
        raise SystemExit(f"cloud {action} failed:\n{result.stderr[-2000:]}")


def step_authorize():
    KEY_DIR.mkdir(exist_ok=True)
    if not PRIVATE_KEY.exists():
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "sunday-desktop-manifest-20260926",
             "-f", str(PRIVATE_KEY)],
            check=True, capture_output=True,
        )
    key = PUB_KEY.read_text(encoding="utf-8").strip()
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq {BASELINE_KEY_LINES}
test ! -e {STAGED}
ls -l {REMOTE} 2>/dev/null || echo 'no manifest published yet'
printf '%s\\n' 'restrict,command="internal-sftp" {key}' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("authorize", "Append one restricted forced-internal-sftp key for the desktop update manifest", script)


def step_upload():
    target = f"root@47.114.43.99:{STAGED}"
    result = subprocess.run(
        ["scp", "-C", "-i", str(PRIVATE_KEY), "-o", "StrictHostKeyChecking=no",
         "-o", "UserKnownHostsFile=/dev/null", "-o", "IdentitiesOnly=yes", str(MANIFEST), target],
        capture_output=True, text=True, timeout=600,
    )
    (ROOT / "local-transfer.json").write_text(json.dumps({
        "manifest": str(MANIFEST), "bytes": BYTES, "sha256": DIGEST,
        "target": target, "staged": STAGED, "returncode": result.returncode,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"scp failed:\n{result.stderr[-2000:]}")
    print(f"uploaded {BYTES} bytes to {STAGED}", flush=True)


def step_publish():
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\\n' '{DIGEST}' '{STAGED}' | sha256sum -c -
install -m 0644 {STAGED}.tmp-guard /dev/null 2>/dev/null || true
install -m 0644 {STAGED} {REMOTE}.tmp
printf '%s  %s\\n' '{DIGEST}' '{REMOTE}.tmp' | sha256sum -c -
mv {REMOTE}.tmp {REMOTE}
printf '%s  %s\\n' '{DIGEST}' '{REMOTE}' | sha256sum -c -
rm -- {STAGED}
echo '--- served with the WebView origin ---'
curl -sS -D - -o /dev/null -H 'Origin: https://tauri.localhost' \\
  --resolve 47.114.43.99.nip.io:443:127.0.0.1 https://47.114.43.99.nip.io/downloads/desktop-update.json \\
  | grep -iE 'HTTP/|content-type|content-length' || true
cat {REMOTE}
stat -c '%n %s %y' {REMOTE}
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("publish", "Publish the desktop update manifest beside the installers", script)


def step_cleanup():
    key_line = PUB_KEY.read_text(encoding="utf-8").strip().split()[1]
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
grep -vF '{key_line}' /root/.ssh/authorized_keys > /root/.ssh/authorized_keys.tmp-manifest || true
mv /root/.ssh/authorized_keys.tmp-manifest /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
grep -cF '{key_line}' /root/.ssh/authorized_keys || true
wc -l /root/.ssh/authorized_keys
ls -1 /var/tmp/Sunday-desktop-update-*.json 2>/dev/null || echo 'no stages'
sha256sum {REMOTE}
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("cleanup", "Revoke the manifest key and verify the published state", script)


if __name__ == "__main__":
    {"authorize": step_authorize, "upload": step_upload,
     "publish": step_publish, "cleanup": step_cleanup}[sys.argv[1]]()
