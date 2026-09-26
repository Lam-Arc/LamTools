"""Audited, narrowly scoped Cloud Assistant runner for mobile release 0.1.30."""
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
TAG = "desktop-release-037"


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
    for _ in range(45):
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


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "preflight":
        command("preflight", "Read-only inspect Caddy site, APK archives, latest hash, update manifest, SSH grants and services before release 0.1.30", """set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
systemctl is-active caddy-lamtools lamtools-relay
readlink -f /var/www/lamtools
find /var/www/lamtools -maxdepth 2 -type f \( -name 'index.html' -o -name 'Sunday-mobile*.apk' \) -printf '%p %s\n' | sort
sha256sum /var/www/lamtools/Sunday-mobile-latest.apk
ls -l /var/www/lamtools/mobile-update.json 2>/dev/null || echo 'no update manifest published'
stat -c '%n %a %s' /root/.ssh/authorized_keys
wc -l /root/.ssh/authorized_keys
date -u +%Y-%m-%dT%H:%M:%SZ
""")
    elif action == "progress":
        command("transfer-progress", "Read-only sizes of release 0.1.30 staged APK and manifest", """set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
stat -c '%n %s' /var/tmp/Sunday-mobile-0.1.30-20260924.upload.apk 2>/dev/null || true
stat -c '%n %s' /var/tmp/Sunday-mobile-0.1.30-20260924.mobile-update.json 2>/dev/null || true
date -u +%Y-%m-%dT%H:%M:%SZ
""")
    else:
        raise SystemExit(f"unknown action: {action}")
