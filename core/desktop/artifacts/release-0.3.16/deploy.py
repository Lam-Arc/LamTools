"""Publish desktop 0.3.16 to the official channel and keep the public domain in step.

Fast path, and the one that keeps the strongest guarantee available: the
installer is fetched on the server from the release GitHub built for tag
v0.3.16 and checked against GitHub's own asset size and digest, so no copy of it
travels through this machine. Acceptance then downloads the *published* file
over HTTPS and hashes it against the published manifest, which tests the public
URL end to end instead of a local copy of it.

One restricted sftp key, used only for the website bundle; authorize, upload,
verify-then-swap, revoke, exactly as the previous rounds.

Usage::

    py -3.14 deploy.py preflight|fetch|publish|site-authorize|site-upload|site-publish|sync-public|site-cleanup|verify
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import cloud  # noqa: E402

VERSION = "0.3.16"
OLD_VERSION = "0.3.15"
DATE_TAG = "20261009"
MOBILE_VERSION = "0.1.48"
TAG = "v" + VERSION

INSTALLER_NAME = f"Sunday_{VERSION}_x64-setup.exe"
STAGE = f"/var/tmp/Sunday-desktop-{VERSION}-{DATE_TAG}.upload.exe"
VERSIONED = f"/var/www/lamtools/{INSTALLER_NAME}"
LATEST = "/var/www/lamtools/Sunday-latest-x64-setup.exe"
ARCHIVE = (
    f"/var/www/lamtools/Sunday-latest-x64-setup-{OLD_VERSION}"
    f"-before-{VERSION}-{DATE_TAG}.exe"
)
MANIFEST_REMOTE = "/var/www/lamtools/desktop-update.json"
MANIFEST_REPO = ROOT.parent.parent / "update-manifest.json"
LATEST_BEFORE_SHA = "4267eac33b34698f85875f1c9e464194748d8e30ec0e381d3f10bbddac0efbed"

SITE_NAME = f"{VERSION}-mobile-{MOBILE_VERSION}-{DATE_TAG}"
CURRENT_SITE = f"{OLD_VERSION}-mobile-{MOBILE_VERSION}-{DATE_TAG}"
TARBALL = ROOT / f"site-{VERSION}.tar.gz"
TARBALL_SHA = "ca07adf50f3f8c20accfbe74d34a820152b4b4a436ea7507a521004d69af371f"
RELEASE_DIR = f"/var/www/lamtools/site-releases/{SITE_NAME}"
SITE_STAGED = f"/var/tmp/Sunday-site-mobile-{VERSION}-{DATE_TAG}.upload.tar.gz"
KEY_DIR = ROOT / "site-key"
PRIVATE_KEY = KEY_DIR / "upload_ed25519"
PUB_KEY = KEY_DIR / "upload_ed25519.pub"
# Pre-existing grant on the instance; this flow adds one line and removes it again.
BASELINE_KEY_LINES = 1

PUBLIC_ORIGIN = "https://47.114.43.99.nip.io"

ACTIONS = {}


def action(fn):
    ACTIONS[fn.__name__.replace("_", "-")] = fn
    return fn


@action
def preflight():
    cloud.command("preflight", f"Read-only inspect the channel, site and grants before release {VERSION}", f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
readlink -f /var/www/lamtools/site
ls -1 /var/www/lamtools/site-releases/ | tail -4
echo "latest link: $(stat -c '%h %i' {LATEST})"
sha256sum {LATEST}
cat {MANIFEST_REMOTE}
ls -l /var/www/lamtools/{INSTALLER_NAME} 2>/dev/null || echo "absent {VERSIONED}"
ls -l {ARCHIVE} 2>/dev/null || echo "absent {ARCHIVE}"
ls -l {STAGE} 2>/dev/null || echo "absent {STAGE}"
ls -l {SITE_STAGED} 2>/dev/null || echo "absent {SITE_STAGED}"
ls -ld {RELEASE_DIR} 2>/dev/null || echo "absent {RELEASE_DIR}"
wc -l < /root/.ssh/authorized_keys
date -u +%Y-%m-%dT%H:%M:%SZ
""", timeout=180)


@action
def publish():
    """Move the verified stage into the channel, archive what it replaces, write the pointer."""
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
test -e {STAGE}
test ! -e {VERSIONED}
test ! -e {ARCHIVE}
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/{CURRENT_SITE}
test "$(sha256sum {LATEST} | cut -d' ' -f1)" = {LATEST_BEFORE_SHA}

# Re-check the bytes against the release's own metadata at publish time, not
# only at fetch time: a stage left behind by an aborted run must not ship.
curl -sSL -m 60 -o /tmp/release-{TAG}.json https://api.github.com/repos/Lam-Arc/LamTools/releases/tags/{TAG}
python3 -c 'import json; r=json.load(open("/tmp/release-{TAG}.json")); a=[a for a in r["assets"] if a["name"]=="{INSTALLER_NAME}"]; assert len(a)==1; print(a[0]["size"], (a[0].get("digest") or "").replace("sha256:",""))' > /tmp/asset-{TAG}.txt
read expected_size expected_digest < /tmp/asset-{TAG}.txt
actual_size=$(stat -c '%s' {STAGE})
actual_digest=$(sha256sum {STAGE} | cut -d' ' -f1)
test "$actual_size" = "$expected_size"
test "$actual_digest" = "$expected_digest"

# The previous latest is kept as its own inode so the versioned file it shares
# with stays downloadable after the link moves.
cp -al -- {LATEST} {ARCHIVE}
mv -- {STAGE} {VERSIONED}
ln -f -- {VERSIONED} {LATEST}
chmod 0644 {VERSIONED}

published_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
printf '%s\\n' \\
  '{{' \\
  '  "version": "{VERSION}",' \\
  '  "download_url": "{PUBLIC_ORIGIN}/downloads/{INSTALLER_NAME}",' \\
  '  "release_url": "{PUBLIC_ORIGIN}/#download",' \\
  '  "release_notes": "Sunday {VERSION}",' \\
  "  \\"published_at\\": \\"$published_at\\"," \\
  '  "sha256": "'"$actual_digest"'",' \\
  '  "size": '"$actual_size" \\
  '}}' > {MANIFEST_REMOTE}
chmod 0644 {MANIFEST_REMOTE}
python3 -c 'import json;print(json.dumps(json.load(open("{MANIFEST_REMOTE}")),ensure_ascii=False,sort_keys=True))'

echo "--- read back over the public origin ---"
curl -sS -m 60 "{PUBLIC_ORIGIN}/downloads/desktop-update.json"
echo
curl -sS -m 120 -o /dev/null -w 'installer http=%{{http_code}} bytes=%{{size_download}}\\n' "{PUBLIC_ORIGIN}/downloads/{INSTALLER_NAME}"
curl -sS -m 60 -o /dev/null -w 'latest    http=%{{http_code}} bytes=%{{size_download}}\\n' "{PUBLIC_ORIGIN}/downloads/Sunday-latest-x64-setup.exe"
ls -l {VERSIONED} {LATEST} {ARCHIVE}
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("publish", f"Publish the v{VERSION} installer and write the update manifest", script, timeout=600)


@action
def site_authorize():
    KEY_DIR.mkdir(exist_ok=True)
    if not PRIVATE_KEY.exists():
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C",
                        f"sunday-{VERSION}-site-upload", "-f", str(PRIVATE_KEY)], check=True,
                       capture_output=True)
    key = PUB_KEY.read_text(encoding="utf-8").strip()
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
test "$(wc -l < /root/.ssh/authorized_keys)" -eq {BASELINE_KEY_LINES}
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/{CURRENT_SITE}
test "$(sha256sum {LATEST} | cut -d' ' -f1)" = "$(python3 -c 'import json;print(json.load(open("{MANIFEST_REMOTE}"))["sha256"])')"
test ! -e {RELEASE_DIR}
test ! -e {SITE_STAGED}
printf '%s\\n' 'restrict,command="internal-sftp" {key}' >> /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("site-authorize", f"Append one restricted forced-internal-sftp key for the {VERSION} site transfer", script)


@action
def site_upload():
    result = subprocess.run(
        ["scp", "-C", "-i", str(PRIVATE_KEY), "-o", "StrictHostKeyChecking=no",
         "-o", "UserKnownHostsFile=/dev/null", "-o", "IdentitiesOnly=yes",
         str(TARBALL), f"root@47.114.43.99:{SITE_STAGED}"],
        capture_output=True, text=True, timeout=1800,
    )
    (ROOT / "site-local-transfer.json").write_text(
        f'{{"tarball": "{TARBALL.name}", "bytes": {TARBALL.stat().st_size}, '
        f'"sha256": "{TARBALL_SHA}", "staged": "{SITE_STAGED}", "returncode": {result.returncode}}}\n',
        encoding="utf-8")
    print(f"returncode={result.returncode} {result.stderr[-300:]}", flush=True)
    if result.returncode != 0:
        raise SystemExit("site upload failed")


@action
def site_publish():
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
printf '%s  %s\\n' '{TARBALL_SHA}' '{SITE_STAGED}' | sha256sum -c -
test "$(readlink -f /var/www/lamtools/site)" = /var/www/lamtools/site-releases/{CURRENT_SITE}
test ! -e {RELEASE_DIR}
mkdir -m 0755 {RELEASE_DIR}
tar -xzf {SITE_STAGED} -C {RELEASE_DIR} --no-same-owner
find {RELEASE_DIR} -type d -exec chmod 755 {{}} +
find {RELEASE_DIR} -type f -exec chmod 644 {{}} +
test -f {RELEASE_DIR}/index.html
grep -R -q '{VERSION}' {RELEASE_DIR}/assets
ln -s {RELEASE_DIR} /var/www/lamtools/site.new{VERSION.replace('.', '')}
mv -Tf /var/www/lamtools/site.new{VERSION.replace('.', '')} /var/www/lamtools/site
rm -- {SITE_STAGED}
readlink -f /var/www/lamtools/site
curl -sS -m 60 "{PUBLIC_ORIGIN}/assets/$(grep -o 'assets/main-[A-Za-z0-9._-]*\\.js' {RELEASE_DIR}/index.html | head -1 | sed 's|assets/||')" | grep -o '{VERSION}' | head -1
systemctl is-active caddy-lamtools lamtools-relay
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("site-publish", f"Extract the {VERSION} site release and atomically repoint the site symlink", script, timeout=600)


@action
def sync_public():
    """Stamp ainarit.com from the manifests just published and refresh its embedded preview."""
    cloud.command("sync-public", f"Bring the public domain in step with the {VERSION} channel", f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
if [ -x /usr/local/bin/sync-public-site.sh ]; then
  sh /usr/local/bin/sync-public-site.sh
else
  echo "sync-public-site.sh is not installed on the server" >&2
  exit 1
fi
sh /usr/local/bin/sync-public-site.sh --check
echo SYNC_OK
date -u +%Y-%m-%dT%H:%M:%SZ
""", timeout=600)


@action
def site_cleanup():
    key_line = PUB_KEY.read_text(encoding="utf-8").strip().split()[1]
    script = f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
grep -vF '{key_line}' /root/.ssh/authorized_keys > /root/.ssh/authorized_keys.tmp{VERSION.replace('.', '')} || true
mv /root/.ssh/authorized_keys.tmp{VERSION.replace('.', '')} /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
wc -l < /root/.ssh/authorized_keys
ls -1 /var/tmp/Sunday-site-mobile-{VERSION}-*.upload.tar.gz 2>/dev/null || echo 'no site stages'
ls -1 /var/tmp/Sunday-desktop-{VERSION}-*.upload.exe 2>/dev/null || echo 'no installer stages'
readlink -f /var/www/lamtools/site
date -u +%Y-%m-%dT%H:%M:%SZ
"""
    cloud.command("site-cleanup", f"Revoke the exact {VERSION} site transfer key and confirm no stages remain", script)


@action
def verify():
    """Read the published channel back and assert it agrees with the repository manifest."""
    import json
    import urllib.request

    def get(url):
        with urllib.request.urlopen(url, timeout=180) as response:
            return response.status, response.read()

    status, body = get(f"{PUBLIC_ORIGIN}/downloads/desktop-update.json")
    published = json.loads(body)
    print("published:", json.dumps(published, ensure_ascii=False, sort_keys=True), flush=True)
    repo = json.loads(Path(MANIFEST_REPO).read_text(encoding="utf-8"))
    if published != repo:
        raise SystemExit(
            "the published manifest disagrees with core/desktop/update-manifest.json:\n"
            f"  published: {json.dumps(published, ensure_ascii=False, sort_keys=True)}\n"
            f"  repo:      {json.dumps(repo, ensure_ascii=False, sort_keys=True)}"
        )
    if published["version"] != VERSION:
        raise SystemExit(f"published version is {published['version']}, expected {VERSION}")

    # The published file must be the digest the manifest promises, or every
    # client turns around and discards it.
    import hashlib

    for label, url in (
        ("installer", published["download_url"]),
        ("latest", f"{PUBLIC_ORIGIN}/downloads/Sunday-latest-x64-setup.exe"),
    ):
        status, body = get(url)
        if status != 200:
            raise SystemExit(f"{label} answered {status}")
        digest = hashlib.sha256(body).hexdigest()
        if digest != published["sha256"] or len(body) != published["size"]:
            raise SystemExit(
                f"{label} is {len(body)} bytes / {digest}, manifest says "
                f"{published['size']} / {published['sha256']}"
            )
        print(f"{label} ok: {len(body)} bytes, digest matches the manifest", flush=True)


if __name__ == "__main__":
    name = sys.argv[1]
    if name not in ACTIONS:
        raise SystemExit(f"unknown action: {name} (have {sorted(ACTIONS)})")
    ACTIONS[name]()
