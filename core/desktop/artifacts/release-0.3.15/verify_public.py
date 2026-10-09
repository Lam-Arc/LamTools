"""Public verification for desktop release 0.3.15.

Four assertions, all against the public origin (not the server's own view):
the versioned installer and `latest` both answer with the published size, a full
public GET of the versioned installer hashes to the local build, the published
`desktop-update.json` describes that same installer, and the site bundle carries
the 0.3.15 label.
"""
import hashlib
import json
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
VERSION = CFG["version"]
EXPECTED_BYTES = CFG["installer_size"]
EXPECTED_SHA = CFG["installer_sha256"]
MANIFEST_SHA = CFG["manifest_sha256"]
BASE = "https://47.114.43.99.nip.io"
CTX = ssl.create_default_context()

results = []


def head(url):
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request, timeout=60, context=CTX) as response:
        return response.status, dict(response.headers)


for url in (f"{BASE}/downloads/Sunday_{VERSION}_x64-setup.exe",
            f"{BASE}/downloads/Sunday-latest-x64-setup.exe"):
    status, headers = head(url)
    length = int(headers.get("Content-Length", 0))
    results.append({"url": url, "status": status, "content_length": length,
                    "length_ok": length == EXPECTED_BYTES})
    print(f"HEAD {status} {length} {url}", flush=True)

url = f"{BASE}/downloads/Sunday_{VERSION}_x64-setup.exe"
digest = hashlib.sha256()
total = 0
try:
    with urllib.request.urlopen(url, timeout=900, context=CTX) as response:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
    matches = total == EXPECTED_BYTES and digest.hexdigest() == EXPECTED_SHA
    print(f"GET {total} bytes sha256={digest.hexdigest()} matches={matches}", flush=True)
    results.append({"url": url, "get_bytes": total, "get_sha256": digest.hexdigest(),
                    "complete": True, "matches_local": matches})
except (urllib.error.URLError, TimeoutError, OSError) as exc:
    print(f"GET incomplete after {total} bytes: {type(exc).__name__}", flush=True)
    results.append({"url": url, "get_bytes": total, "complete": False,
                    "error": type(exc).__name__})

manifest_url = f"{BASE}/downloads/desktop-update.json"
try:
    with urllib.request.urlopen(manifest_url, timeout=60, context=CTX) as response:
        raw = response.read()
        status = response.status
        content_type = response.headers.get("Content-Type", "")
    body = json.loads(raw.decode("utf-8"))
    manifest = {
        "url": manifest_url,
        "status": status,
        "content_type": content_type,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "body": body,
        "version_matches": body.get("version") == VERSION,
        "sha_matches": body.get("sha256") == EXPECTED_SHA,
        "size_matches": body.get("size") == EXPECTED_BYTES,
        "published_sha_matches": hashlib.sha256(raw).hexdigest() == MANIFEST_SHA,
    }
    print(f"GET {status} manifest={json.dumps(body, ensure_ascii=False)} "
          f"version_ok={manifest['version_matches']} sha_ok={manifest['sha_matches']} "
          f"size_ok={manifest['size_matches']} published_sha_ok={manifest['published_sha_matches']}",
          flush=True)
    download = str(body.get("download_url") or "")
    if download:
        download_status, download_headers = head(download)
        manifest["download_url_status"] = download_status
        manifest["download_url_length"] = int(download_headers.get("Content-Length", 0))
        manifest["download_url_ok"] = (download_status == 200
                                      and manifest["download_url_length"] == EXPECTED_BYTES)
        print(f"HEAD {download_status} {manifest['download_url_length']} {download}", flush=True)
    else:
        manifest["download_url_ok"] = False
    results.append(manifest)
except Exception as exc:  # noqa: BLE001
    print(f"GET manifest failed: {type(exc).__name__}: {exc}", flush=True)
    results.append({"url": manifest_url, "error": type(exc).__name__, "message": str(exc)})

try:
    with urllib.request.urlopen(f"{BASE}/", timeout=60, context=CTX) as response:
        body = response.read().decode("utf-8", errors="replace")
    assets = []
    for line in body.splitlines():
        if "/assets/" in line:
            assets.extend(part.split('"')[0] for part in line.split("/assets/")[1:])
    site = {"url": f"{BASE}/", "status": 200, "site_len": len(body)}
    for name in sorted(set(assets)):
        try:
            with urllib.request.urlopen(f"{BASE}/assets/{name}", timeout=60, context=CTX) as response:
                bundle = response.read().decode("utf-8", errors="replace")
            if VERSION in bundle:
                site["version_label_bundle"] = name
                break
        except Exception:  # noqa: BLE001
            continue
    results.append(site)
    print(f"GET site ok len={len(body)} label_bundle={site.get('version_label_bundle')}", flush=True)
except Exception as exc:  # noqa: BLE001
    results.append({"url": f"{BASE}/", "error": type(exc).__name__})

json.dump({"checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "version": VERSION, "expected_bytes": EXPECTED_BYTES, "expected_sha256": EXPECTED_SHA,
           "results": results},
          (ROOT / "public-verification.json").open("w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
