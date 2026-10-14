"""Audited Cloud Assistant client for the Sunday 0.3.17 publication.

Only the read-only preflight is enabled in this preparation step.
"""
import base64
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLI = r"E:\阿里云服务\aliyun-cli\aliyun.exe"  # Source from Get-Command aliyun.exe
INSTANCE = "i-bp10t7y63rvbncmjstpm"
REGION = "cn-hangzhou"
TAG = "sunday-desktop-0317-preflight"


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def save(name, value):
    (ROOT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def api(action, name, **params):
    last = None
    for endpoint in (
        "ecs.cn-hangzhou.aliyuncs.com",
        "ecs.aliyuncs.com",
        "ecs-cn-hangzhou.aliyuncs.com",
    ):
        args = [CLI, "ecs", action, "--endpoint", endpoint, "--RegionId", REGION]
        for key, value in params.items():
            args += ["--" + key, str(value)]
        result = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8", timeout=60
        )
        try:
            data = json.loads(result.stdout) if result.stdout.strip() else {}
        except json.JSONDecodeError:
            data = {}
        if result.returncode == 0 and data.get("RequestId"):
            save(name + ".json", data)
            return data
        last = {"exitCode": result.returncode, "stderr": result.stderr[-500:]}
    raise RuntimeError(f"Cloud API {action} failed: {last}")


def preflight():
    started = utc_now()
    script_path = ROOT / "preflight.sh"
    script = script_path.read_text(encoding="utf-8")
    name = TAG + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    description = (
        "Read-only inspect official site health, active site release, installer channel, "
        "0.3.17 publication targets and SSH grant baseline before Sunday desktop 0.3.17 publish"
    )
    run = api("RunCommand", "preflight-run", **{
        "InstanceId.1": INSTANCE,
        "Type": "RunShellScript",
        "Name": name,
        "Description": description,
        "KeepCommand": "true",
        "ClientToken": name,
        "ContentEncoding": "Base64",
        "CommandContent": base64.b64encode(script.encode("utf-8")).decode("ascii"),
        "Timeout": 180,
    })
    save("preflight-request.json", {
        "name": name,
        "description": description,
        "instanceId": INSTANCE,
        "region": REGION,
        "keepCommand": True,
        "contentEncoding": "Base64",
        "commandFile": str(script_path.name),
        "startedAtUtc": started,
    })
    for _ in range(90):
        time.sleep(2)
        status = api(
            "DescribeInvocationResults", "preflight-result",
            InvokeId=run["InvokeId"],
        )
        rows = (
            status.get("Invocation", {})
            .get("InvocationResults", {})
            .get("InvocationResult", [])
        )
        for row in rows:
            state = row.get("InvocationStatus")
            output = base64.b64decode(row.get("Output", "")).decode(
                "utf-8", errors="replace"
            )
            (ROOT / "preflight.output.txt").write_text(output, encoding="utf-8")
            record = {
                "purpose": "read-only website publication preflight",
                "startedAtUtc": started,
                "completedAtUtc": utc_now(),
                "commandName": name,
                "commandDescription": description,
                "keepCommand": True,
                "commandId": run.get("CommandId"),
                "invokeId": run.get("InvokeId"),
                "runCommandRequestId": run.get("RequestId"),
                "resultRequestId": status.get("RequestId"),
                "invocationStatus": state,
                "exitCode": row.get("ExitCode"),
                "outputFile": "preflight.output.txt",
            }
            save("preflight-record.json", record)
            if state == "Success" and row.get("ExitCode") == 0:
                print(output, end="")
                print(json.dumps(record, ensure_ascii=False, indent=2))
                return
            if state in ("Failed", "Stopped", "Timeout", "Error"):
                raise RuntimeError(f"preflight ended {state}: {output[-1200:]}")
    raise TimeoutError("Cloud Assistant preflight timed out after 180 seconds")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] != "preflight":
        raise SystemExit("Only the read-only action is enabled: preflight")
    preflight()