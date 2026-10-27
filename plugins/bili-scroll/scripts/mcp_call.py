#!/usr/bin/env python3
"""scripts/mcp_call.py —— 调一次 bilibili MCP 工具的 stdio 客户端。

原版用 lib/mcp.mjs 在自己的进程里起这份 Python MCP（`command`/`args`/`env` 都来自设置）。
宿主通过 mcp action=run 执行；此脚本仅用于人工诊断**同一个**服务器：
它读 `mcp/mcp.json`（和宿主读的是同一份声明），按里面的 command/args/env 起子进程，
走 `initialize` → `notifications/initialized` → `tools/call`。

用法：
    python scripts/mcp_call.py bili_search '{"keyword":"DeepSeek Harness","num":3}'
    python scripts/mcp_call.py --list                 # 只列工具名（相当于 tools/list）
    python scripts/mcp_call.py bili_reply --json '{"bvid":"BV...","text":"..."}' --timeout 60

只依赖标准库：MCP 的 stdio 协议就是"一行一个 JSON-RPC"。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP_JSON = ROOT / "mcp" / "mcp.json"
SERVER = "bilibili"


def load_jsonc(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except Exception:
        pass
    clean = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    clean = re.sub(r"(^|\s)//[^\n]*", r"\1", clean)
    clean = re.sub(r",(\s*[}\]])", r"\1", clean)
    return json.loads(clean)


def server_config() -> dict:
    # user:“都试一试”+(独立诊断工具也使用当前环境与通用模板)。
    sys.path.insert(0, str(ROOT))
    import common
    data = load_jsonc(MCP_JSON)
    servers = data.get("mcpServers") or {}
    cfg = servers.get(SERVER)
    if not isinstance(cfg, dict):
        raise SystemExit(f"mcp/mcp.json 里没有 {SERVER} 服务器声明")
    python = common.venv_python()
    if python is None:
        raise SystemExit("先安装主依赖，或配置有效的 pythonPath")
    replacements = {"{{PLUGIN_DIR}}": str(ROOT), "{{PLUGIN_DATA_DIR}}": str(common.DATA),
                    "{{PLUGIN_PYTHON}}": str(python), "{{PLUGIN_PYTHON:./data/duty/.venv}}": str(python)}
    def expand(value):
        for key, replacement in replacements.items():
            value = str(value).replace(key, replacement)
        return value
    cfg["command"] = expand(cfg.get("command") or "")
    cfg["args"] = [expand(item) for item in cfg.get("args", [])]
    cfg["env"] = {key: expand(value) for key, value in cfg.get("env", {}).items()}
    command = cfg["command"]
    if not Path(command).exists():
        raise SystemExit(f"mcp.json 里配置的解释器不存在：{command}（重跑一次「装主依赖」）")
    return cfg


class Client:
    def __init__(self, cfg: dict, timeout: float = 120.0):
        self.cfg = cfg
        self.timeout = timeout
        self.proc: subprocess.Popen | None = None
        self.next_id = 1
        self.pending: dict[int, dict] = {}
        self.lock = threading.Lock()
        self.buffer = ""
        self.stderr = ""

    def start(self) -> None:
        env = dict(os.environ)
        env.update({str(k): str(v) for k, v in (self.cfg.get("env") or {}).items()})
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        creation = 0
        if os.name == "nt":
            creation = 0x08000000  # CREATE_NO_WINDOW
        self.proc = subprocess.Popen(
            [self.cfg["command"], *[str(a) for a in (self.cfg.get("args") or [])]],
            cwd=str(ROOT / "data" / "duty"),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creation,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "bili-scroll-bridge", "version": "2.2.1"},
            },
        )
        self.notify("notifications/initialized", {})

    def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if "id" in msg and msg["id"] in self.pending:
                slot = self.pending.pop(msg["id"])
                slot["result"] = msg
                slot["done"].set()

    def _read_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        for line in self.proc.stderr:
            self.stderr = (self.stderr + line)[-4000:]

    def _send(self, payload: dict) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict, timeout: float | None = None) -> dict:
        with self.lock:
            rid = self.next_id
            self.next_id += 1
            slot = {"done": threading.Event(), "result": None}
            self.pending[rid] = slot
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        if not slot["done"].wait(timeout or self.timeout):
            raise SystemExit(f"MCP {method} 超时（{timeout or self.timeout}s）{self._tail()}")
        msg = slot["result"] or {}
        if "error" in msg:
            err = msg["error"]
            message = err.get("message") if isinstance(err, dict) else str(err)
            raise SystemExit(f"MCP {method} 报错：{message}")
        return msg.get("result") or {}

    def _tail(self) -> str:
        tail = self.stderr.strip()[-400:]
        return f"：{tail}" if tail else ""

    def stop(self) -> None:
        try:
            if self.proc:
                self.proc.kill()
        except Exception:
            pass


def render(result: dict) -> str:
    blocks = result.get("content") or []
    parts: list[str] = []
    for block in blocks:
        kind = block.get("type")
        if kind == "text" and block.get("text"):
            parts.append(str(block["text"]))
        elif kind == "image":
            parts.append(f"[图片 {block.get('mimeType') or block.get('mime_type') or 'image'}，{len(block.get('data') or '')} 字节 base64]")
    text = "\n".join(parts).strip()
    if result.get("isError"):
        return "工具报错：" + (text or "（没有说明）")
    return text or "（空）"


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    if argv[0] == "--list":
        cfg = server_config()
        client = Client(cfg, 120)
        client.start()
        try:
            tools = client.request("tools/list", {}).get("tools") or []
            print("\n".join(f"{t.get('name')}  —  {(t.get('description') or '').splitlines()[0][:80]}" for t in tools))
        finally:
            client.stop()
        return 0

    tool = argv[0]
    args: dict = {}
    timeout = 180.0
    rest = argv[1:]
    i = 0
    while i < len(rest):
        item = rest[i]
        if item in ("--json", "--arguments"):
            raw = rest[i + 1] if i + 1 < len(rest) else "{}"
            i += 2
        elif item == "--timeout":
            timeout = float(rest[i + 1])
            i += 2
            continue
        elif item == "--list":
            return main(["--list"])
        else:
            raw = item
            i += 1
        try:
            parsed = json.loads(raw or "{}")
        except Exception as exc:
            raise SystemExit(f"参数不是合法 JSON：{exc}")
        if isinstance(parsed, dict):
            args.update(parsed)

    cfg = server_config()
    client = Client(cfg, timeout)
    client.start()
    try:
        result = client.request("tools/call", {"name": tool, "arguments": args}, timeout)
        print(render(result))
    finally:
        client.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
