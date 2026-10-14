"""Run named Cloud Assistant steps and save complete per-step evidence."""
import base64
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLI = r"E:\阿里云服务\aliyun-cli\aliyun.exe"  # Resolved by Get-Command aliyun.exe
INSTANCE = "i-bp10t7y63rvbncmjstpm"
REGION = "cn-hangzhou"
ENDPOINTS = ("ecs.cn-hangzhou.aliyuncs.com", "ecs.aliyuncs.com", "ecs-cn-hangzhou.aliyuncs.com")

def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def cli_api(action, step, suffix, prefix, **params):
    last = None
    for endpoint in ENDPOINTS:
        args = [CLI, "ecs", action, "--endpoint", endpoint, "--RegionId", REGION]
        for key, value in params.items():
            args.extend(["--" + key, str(value)])
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=90)
        try:
            payload = json.loads(result.stdout) if result.stdout.strip() else {}
        except json.JSONDecodeError:
            payload = {}
        if result.returncode == 0 and payload.get("RequestId"):
            save(ROOT / f"{prefix}.{suffix}.json", payload)
            return payload
        last = {"exitCode": result.returncode, "stderr": result.stderr[-1000:]}
    save(ROOT / f"{prefix}.{suffix}-error.json", last or {})
    raise RuntimeError(f"Cloud API {action} failed: {last}")

def run(step, script_file, description, timeout=600):
    script_path = (ROOT / script_file).resolve()
    if script_path.parent != ROOT or not script_path.is_file():
        raise SystemExit("The command file must be a file in this release directory.")
    script = script_path.read_text(encoding="utf-8")
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    prefix = f"{step}-{stamp}"
    name = f"sunday-desktop-0317-{step}-{stamp}"
    client_token = name
    started = utc_now()
    request = {
        "purpose": step,
        "commandName": name,
        "description": description,
        "instanceId": INSTANCE,
        "region": REGION,
        "keepCommand": True,
        "contentEncoding": "Base64",
        "commandFile": script_path.name,
        "commandSha256": hashlib.sha256(script.encode("utf-8")).hexdigest(),
        "timeoutSeconds": timeout,
        "startedAtUtc": started,
        "clientToken": client_token,
    }
    save(ROOT / f"{prefix}.request.json", request)
    run_result = cli_api("RunCommand", step, "run-api-response", prefix,
        **{
            "InstanceId.1": INSTANCE,
            "Type": "RunShellScript",
            "Name": name,
            "Description": description,
            "KeepCommand": "true",
            "ClientToken": client_token,
            "ContentEncoding": "Base64",
            "CommandContent": base64.b64encode(script.encode("utf-8")).decode("ascii"),
            "Timeout": timeout,
        })
    invoke_id = run_result["InvokeId"]
    deadline = time.monotonic() + timeout + 300
    while time.monotonic() < deadline:
        status = cli_api("DescribeInvocationResults", step, "result-api-response", prefix, InvokeId=invoke_id)
        rows = status.get("Invocation", {}).get("InvocationResults", {}).get("InvocationResult", [])
        for row in rows:
            state = row.get("InvocationStatus")
            output = base64.b64decode(row.get("Output", "")).decode("utf-8", errors="replace")
            (ROOT / f"{prefix}.output.txt").write_text(output, encoding="utf-8")
            record = {
                **request,
                "completedAtUtc": utc_now(),
                "commandId": run_result.get("CommandId"),
                "invokeId": invoke_id,
                "runCommandRequestId": run_result.get("RequestId"),
                "resultRequestId": status.get("RequestId"),
                "invocationStatus": state,
                "exitCode": row.get("ExitCode"),
                "outputFile": f"{prefix}.output.txt",
                "runApiResponseFile": f"{prefix}.run-api-response.json",
                "resultApiResponseFile": f"{prefix}.result-api-response.json",
                "commandFile": script_path.name,
            }
            save(ROOT / f"{prefix}.record.json", record)
            if state == "Success" and row.get("ExitCode") == 0:
                print(output, end="")
                print(json.dumps(record, ensure_ascii=False, indent=2))
                return record
            if state in ("Failed", "Stopped", "Timeout", "Error"):
                raise RuntimeError(f"Cloud step {step} ended {state}, exit={row.get('ExitCode')}: {output[-2000:]}")
        time.sleep(2)
    raise TimeoutError(f"Cloud step {step} timed out; invocation {invoke_id}")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        raise SystemExit("usage: py -3.14 cloud_action.py STEP SCRIPT_FILE DESCRIPTION [TIMEOUT_SECONDS]")
    run(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 600)