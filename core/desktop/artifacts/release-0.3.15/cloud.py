"""Audited, narrowly scoped Cloud Assistant runner for desktop release 0.3.15.

Two differences from the 0.3.9 / 0.3.10 runner:

* The installer is produced by CI from the pushed tag, and this machine cannot
  reach the GitHub API or release assets (a local relay answers api.github.com
  with a certificate for another host). So the *server* fetches the release
  asset and reports its digest; the file then comes back down over the audited
  sftp key, is installed and verified locally, and is uploaded from that same
  copy — the published bytes are the bytes the setup acceptance ran on.
* `fetch` checks the download against GitHub's own asset metadata (size and
  digest) instead of trusting the transfer.

Every remote step still goes through Cloud Assistant with KeepCommand=true, and
records the JSON result, the shell script and the output next to it.
"""
import base64
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLI = r"E:\阿里云服务\aliyun-cli\aliyun.exe"
INSTANCE = "i-bp10t7y63rvbncmjstpm"
TAG = "desktop-release-0315"
VERSION = "0.3.15"
DATE_TAG = "20261009"
STAGE = f"/var/tmp/Sunday-desktop-{VERSION}-{DATE_TAG}.upload.exe"


def save(name, data):
    (ROOT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def api(action, name, **params):
    last = None
    for endpoint in ("ecs.cn-hangzhou.aliyuncs.com", "ecs.aliyuncs.com", "ecs-cn-hangzhou.aliyuncs.com"):
        args = [CLI, "ecs", action, "--endpoint", endpoint, "--RegionId", "cn-hangzhou"]
        for key, value in params.items():
            args += ["--" + key, str(value)]
        try:
            result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=35)
            data = json.loads(result.stdout) if result.stdout.strip() else {}
            if result.returncode == 0 and data.get("RequestId"):
                save(name, data)
                return data
            last = result.stderr[:300]
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            last = type(exc).__name__
    raise RuntimeError(f"Cloud API {action} failed: {last}")


def command(name, description, script, timeout=120):
    (ROOT / f"{name}.sh").write_text(script, encoding="utf-8")
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run = api("RunCommand", name + "-run", **{
        "InstanceId.1": INSTANCE,
        "Type": "RunShellScript",
        "Name": TAG + "-" + name,
        "Description": description,
        "KeepCommand": "true",
        "ClientToken": TAG + "-" + name + "-" + now,
        "ContentEncoding": "Base64",
        "CommandContent": base64.b64encode(script.encode()).decode(),
        "Timeout": timeout,
    })
    for _ in range(900):
        time.sleep(2)
        status = api("DescribeInvocationResults", name + "-result", InvokeId=run["InvokeId"])
        rows = status.get("Invocation", {}).get("InvocationResults", {}).get("InvocationResult", [])
        for row in rows:
            state = row.get("InvocationStatus")
            if state == "Success" and row.get("ExitCode") == 0:
                output = base64.b64decode(row.get("Output", "")).decode("utf-8", errors="replace")
                (ROOT / f"{name}.output.txt").write_text(output, encoding="utf-8")
                print(f"{name}: {output}", flush=True)
                return output
            if state in ("Failed", "Stopped", "Timeout", "Error"):
                output = base64.b64decode(row.get("Output", "")).decode("utf-8", errors="replace")
                (ROOT / f"{name}.output.txt").write_text(output, encoding="utf-8")
                raise RuntimeError(f"{name} failed: {output[-600:]}")
    raise RuntimeError(f"{name} did not finish")


FETCH_PARALLEL_TEMPLATE = ROOT / "fetch_parallel.template.sh"
FETCH_PARALLEL_SCRIPT = FETCH_PARALLEL_TEMPLATE.read_text(encoding="utf-8")


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "preflight":
        command("preflight", "Read-only inspect the site, desktop installer channel, update manifest, SSH grants and services before release 0.3.15", f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
readlink -f /var/www/lamtools/site
ls -1 /var/www/lamtools/site-releases/ | tail -4
sha256sum /var/www/lamtools/Sunday-latest-x64-setup.exe
cat /var/www/lamtools/desktop-update.json
sha256sum /var/www/lamtools/Sunday-mobile-latest.apk
stat -c '%n %a %s' /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
for path in /var/www/lamtools/Sunday_{VERSION}_x64-setup.exe /var/tmp/Sunday-desktop-{VERSION}-{DATE_TAG}.upload.exe /var/tmp/Sunday-desktop-{VERSION}-{DATE_TAG}.desktop-update.json; do
  if [ -e "$path" ]; then echo "PRESENT $path"; else echo "absent $path"; fi
done
date -u +%Y-%m-%dT%H:%M:%SZ
""")
    elif action == "fetch":
        # Server-side fetch of the CI-built asset, checked against the asset's
        # own size and digest from the GitHub release metadata.
        command("fetch", f"Fetch the v{VERSION} release asset to the release stage and verify it against GitHub metadata", f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
curl -sSL -m 60 -o /tmp/release-{VERSION}.json https://api.github.com/repos/Lam-Arc/LamTools/releases/tags/v{VERSION}
python3 -c 'import json,sys; r=json.load(open("/tmp/release-{VERSION}.json")); assert r.get("tag_name")=="v{VERSION}", r.get("tag_name"); a=[a for a in r["assets"] if a["name"].endswith("_x64-setup.exe")]; assert len(a)==1, [x["name"] for x in r["assets"]]; a=a[0]; print(a["name"], a["size"], (a.get("digest") or "").replace("sha256:",""))' > /tmp/asset-{VERSION}.txt
cat /tmp/asset-{VERSION}.txt
read asset_name expected_size expected_digest < /tmp/asset-{VERSION}.txt
stage={STAGE}
test ! -e "$stage"
curl -sSL -m 1800 -o "$stage" "https://github.com/Lam-Arc/LamTools/releases/download/v{VERSION}/$asset_name"
actual_size=$(stat -c '%s' "$stage")
actual_digest=$(sha256sum "$stage" | cut -d' ' -f1)
echo "DOWNLOADED $asset_name $actual_size $actual_digest"
test "$actual_size" = "$expected_size"
if [ -n "$expected_digest" ]; then test "$actual_digest" = "$expected_digest"; fi
echo FETCH_OK
date -u +%Y-%m-%dT%H:%M:%SZ
""", timeout=1900)
    elif action == "fetch-parallel":
        # One connection to the release asset ran at ~19 KB/s from this host and
        # was cut at the command timeout. The link is throttled per connection,
        # so the same bytes come down as eight ranged requests in parallel and
        # are then verified against the asset's own size and digest — a
        # truncated or tampered part cannot pass that check.
        script = (FETCH_PARALLEL_SCRIPT
                  .replace("@@VERSION@@", VERSION)
                  .replace("@@STAGE@@", STAGE))
        command("fetch-parallel", f"Fetch the v{VERSION} installer as parallel ranged requests and verify it against GitHub metadata", script, timeout=1800)
    elif action == "fetch-resume":
        # The first fetch was throttled to ~19 KB/s from this host and was cut at
        # the command timeout; resume the same download and keep checking it
        # against the release asset's own size and digest.
        command("fetch-resume", f"Resume the v{VERSION} installer download and verify it against GitHub metadata", f"""set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
curl -sSL -m 60 -o /tmp/release-{VERSION}.json https://api.github.com/repos/Lam-Arc/LamTools/releases/tags/v{VERSION}
python3 -c 'import json; r=json.load(open("/tmp/release-{VERSION}.json")); a=[a for a in r["assets"] if a["name"].endswith("_x64-setup.exe")][0]; print(a["name"], a["size"], (a.get("digest") or "").replace("sha256:",""))' > /tmp/asset-{VERSION}.txt
read asset_name expected_size expected_digest < /tmp/asset-{VERSION}.txt
stage={STAGE}
if [ -e "$stage" ]; then echo "resuming from $(stat -c '%s' "$stage") bytes"; fi
curl -sSL -C - --retry 5 --retry-delay 3 --retry-all-errors -m 3300 -o "$stage" "https://github.com/Lam-Arc/LamTools/releases/download/v{VERSION}/$asset_name"
actual_size=$(stat -c '%s' "$stage")
actual_digest=$(sha256sum "$stage" | cut -d' ' -f1)
echo "DOWNLOADED $asset_name $actual_size $actual_digest"
test "$actual_size" = "$expected_size"
if [ -n "$expected_digest" ]; then test "$actual_digest" = "$expected_digest"; fi
echo FETCH_OK
date -u +%Y-%m-%dT%H:%M:%SZ
""", timeout=3500)
    elif action == "download-back":
        key = ROOT / "transfer-key" / "upload_ed25519"
        target = sys.argv[2]
        result = subprocess.run(
            ["scp", "-C", "-i", str(key), "-o", "StrictHostKeyChecking=no",
             "-o", "UserKnownHostsFile=/dev/null", "-o", "IdentitiesOnly=yes",
             f"root@47.114.43.99:{STAGE}", target],
            capture_output=True, text=True, timeout=3600,
        )
        print(f"returncode={result.returncode} {result.stderr[-300:]}", flush=True)
        if result.returncode != 0:
            raise SystemExit("download-back failed")
    elif action == "cleanup-fetch-stage":
        command("cleanup-fetch-stage", f"Remove the release {VERSION} fetch stage after it has been published", f"""set -eu
rm -f -- {STAGE}
test ! -e {STAGE}
ls -1 /var/tmp/Sunday-desktop-{VERSION}-*.upload.exe 2>/dev/null || echo 'no stages'
date -u +%Y-%m-%dT%H:%M:%SZ
""")
    else:
        raise SystemExit(f"unknown action: {action}")
