"""Audited, narrowly scoped Cloud Assistant runner for the API gateway rollout.

Read-only inspection and (later) explicitly scoped mutations against the
LamTools Aliyun instance. Every Cloud Assistant call is tagged and retained.
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
TAG = "api-gateway-0926"


def save(name, data):
    (ROOT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def api(action, name, **params):
    last = None
    for endpoint in ("ecs.cn-hangzhou.aliyuncs.com", "ecs.aliyuncs.com", "ecs-cn-hangzhou.aliyuncs.com"):
        args = [CLI, "ecs", action, "--endpoint", endpoint, "--RegionId", "cn-hangzhou"]
        for key, value in params.items():
            args += ["--" + key, str(value)]
        try:
            result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=40)
            data = json.loads(result.stdout) if result.stdout.strip() else {}
            if result.returncode == 0 and data.get("RequestId"):
                save(name, data)
                return data
            last = (result.stderr or result.stdout)[:300]
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            last = type(exc).__name__
    raise RuntimeError(f"Cloud API {action} failed: {last}")


def command(name, description, script, timeout=180, expect_success=True):
    """Run a shell script on the instance and return (stdout, InvokeId)."""
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
    invoke_id = run["InvokeId"]
    print(f"[{name}] RequestId={run.get('RequestId')} InvokeId={invoke_id}", flush=True)
    for _ in range(max(30, timeout // 2)):
        time.sleep(2)
        status = api("DescribeInvocationResults", name + "-result", InvokeId=invoke_id)
        rows = status.get("Invocation", {}).get("InvocationResults", {}).get("InvocationResult", [])
        for row in rows:
            state = row.get("InvocationStatus")
            output = base64.b64decode(row.get("Output", "")).decode("utf-8", errors="replace")
            if state == "Success" and row.get("ExitCode") == 0:
                (ROOT / f"{name}.output.txt").write_text(output, encoding="utf-8")
                print(output, flush=True)
                return output
            if state in ("Failed", "Stopped", "Timeout", "Error"):
                (ROOT / f"{name}.output.txt").write_text(output, encoding="utf-8")
                if expect_success:
                    raise RuntimeError(f"{name} failed ({state}): {output[-800:]}")
                print(f"[{name}] {state} exit={row.get('ExitCode')}\n{output}", flush=True)
                return output
    raise RuntimeError(f"{name} did not finish")


def inspect_sg():
    sg = api("DescribeSecurityGroupAttribute", "sg-attribute", SecurityGroupId="sg-bp10t7y63rvbncml4leb")
    rules = sg.get("Permissions", {}).get("Permission", [])
    for rule in rules:
        print(
            f"{rule.get('Direction')} {rule.get('IpProtocol')} "
            f"{rule.get('PortRange')} {rule.get('SourceCidrIp') or rule.get('DestCidrIp')} "
            f"policy={rule.get('Policy')} desc={rule.get('Description')}",
            flush=True,
        )


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "sg":
        inspect_sg()
    else:
        raise SystemExit(f"unknown action: {action}")
