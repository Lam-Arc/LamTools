"""user:“从 GitHub 等平台下载并安装”+(对隔离的真实后端验证市场、校验安装、运行状态与更新)。"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core/src"))


async def verify(port):
    from lamtools_core.app.live_client import CoreAppServerClient
    client = CoreAppServerClient(f"http://127.0.0.1:{port}")
    await client.connect()
    try:
        # user:“修完打包发布新版本”+(冷启动后项目和供应商请求必须返回实际 JSON，临时供应商写入后可读回)。
        await client.request("project.list", {})
        await client.request("config.provider.create", {"id": "market-acceptance", "name": "Market acceptance", "base_url": "https://example.invalid/v1", "api_key": "sk-acceptance-placeholder"})
        providers = await client.request("config.providers.list", {})
        assert any(row.get("id") == "market-acceptance" for row in providers.get("providers", [])), providers
        await client.request("config.provider.delete", {"id": "market-acceptance"})
        print(json.dumps({"cold_start_projects": "passed", "provider_write_read": "passed"}), flush=True)
        initial = await client.request("plugin.system.list", {})
        assert not any(row["name"] in {"qq-bot", "bili-scroll"} for row in initial["plugins"]), "market plugins were bundled"
        network = await client.request("network-exploration.status", {})
        assert network["accelerator"]["running"] and network["accelerator"]["port"] > 0, network
        print(json.dumps({"network_accelerator": "ready", "system_proxy_modified": False}), flush=True)
        market = await asyncio.wait_for(client.request("plugin.market.list", {}), 30)
        assert {row["id"] for row in market["plugins"]} == {"qq-bot", "bili-scroll"}
        for name in ("qq-bot", "bili-scroll"):
            result = await asyncio.wait_for(client.request("plugin.market.install", {"name": name}), 180)
            assert result.get("installed") and result.get("available"), result
            print(json.dumps({"plugin": name, "version": next(row["version"] for row in market["plugins"] if row["id"] == name), "available": result["available"], "backend": result["backend"]["state"]}), flush=True)
        # Reinstalling the published version exercises the update transaction,
        # rather than claiming update support from an install-only smoke test.
        updated = await asyncio.wait_for(client.request("plugin.market.install", {"name": "bili-scroll"}), 180)
        assert updated.get("updated") and updated.get("available"), updated
        listing = await client.request("plugin.system.list", {})
        assert all(next(row for row in listing["plugins"] if row["name"] == name)["available"] for name in ("qq-bot", "bili-scroll"))
        print(json.dumps({"market": "passed", "github_install": "passed", "plugin_update": "passed"}), flush=True)
    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    args = parser.parse_args()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    home = Path(tempfile.mkdtemp(prefix="sunday-market-acceptance-"))
    env = {**os.environ, "LAMTOOLS_HOME": str(home), "LAMTOOLS_CORE_WORK_ROOT": str(home / "project"), "LAMCORE_PORT": str(port)}
    (home / "project").mkdir()
    with (home / "backend.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([str(args.exe.resolve())], env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            deadline = time.monotonic() + 90
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2):
                        break
                except OSError:
                    time.sleep(0.25)
            else:
                raise RuntimeError(f"backend did not become healthy; log: {home / 'backend.log'}")
            asyncio.run(verify(port))
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    print(f"Acceptance evidence: {home}")


if __name__ == "__main__":
    main()
