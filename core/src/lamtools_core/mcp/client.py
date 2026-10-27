from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
from typing import Any

from lamtools_core.config.network import subprocess_env

from .schemas import MCPServerConfig, MCPTool

logger = logging.getLogger(__name__)

# Upper bound for a single MCP message body — a malicious/broken server must
# not be able to exhaust process memory via a huge Content-Length or line.
MAX_MESSAGE_BYTES = 32 * 1024 * 1024


def subprocess_start_kwargs(*, env: dict[str, str]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "stdin": asyncio.subprocess.PIPE,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
        "env": env,
        # user:“该修就修，该测就测”+(JSON 行的读取限制与声明的消息上限一致，大字幕不能被默认 64 KiB 截断)。
        "limit": MAX_MESSAGE_BYTES + 1,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return kwargs


class MCPError(RuntimeError):
    pass


class MCPClient:
    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._proc: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._initialized = False
        self._reader_error: MCPError | None = None

    async def start(self) -> None:
        # user:“该修就修，该测就测”+(并发请求共享一个完成握手的连接；读循环故障后下次调用重建，不重放原请求)。
        async with self._lifecycle_lock:
            if (self._proc is not None and self._proc.returncode is None and self._initialized
                    and self._reader_error is None and self._reader_task is not None and not self._reader_task.done()):
                return
            await self._close_unlocked()
            env = subprocess_env()
            env.update(self.config.env)
            self._reader_error = None
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    self.config.command, *self.config.args, **subprocess_start_kwargs(env=env),
                )
                self._reader_task = asyncio.create_task(self._read_loop())
                self._stderr_task = asyncio.create_task(self._drain_stderr())
                await self._request("initialize", {
                    "protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "LamToolsCore", "version": "0.1.0"},
                })
                await self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
                self._initialized = True
            except BaseException:
                await self._close_unlocked()
                raise

    async def close(self) -> None:
        async with self._lifecycle_lock:
            await self._close_unlocked()

    async def _close_unlocked(self) -> None:
        proc = self._proc
        self._proc = None
        self._initialized = False
        for future in self._pending.values():
            if not future.done():
                future.set_exception(MCPError("MCP 连接已关闭，操作结果可能未知"))
        self._pending.clear()
        tasks = [task for task in (self._reader_task, self._stderr_task) if task is not None]
        self._reader_task = self._stderr_task = None
        for task in tasks:
            task.cancel()
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def list_tools(self) -> list[MCPTool]:
        data = await self.request("tools/list", {})
        raw_tools = data.get("tools", [])
        tools: list[MCPTool] = []
        if not isinstance(raw_tools, list):
            return tools
        for raw in raw_tools:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name", "")).strip()
            if not name:
                continue
            schema = raw.get("inputSchema", {})
            tools.append(
                MCPTool(
                    server=self.config.name,
                    name=name,
                    function_name=encode_mcp_tool_name(self.config.name, name),
                    description=str(raw.get("description", "")),
                    input_schema=schema if isinstance(schema, dict) else {},
                    permission=self.config.permission,
                    level=self.config.level_for_tool(name),
                    action_levels=(self.config.tool_levels[name].get("actions", {})
                                   if isinstance(self.config.tool_levels.get(name), dict) else {}),
                )
            )
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.request("tools/call", {"name": name, "arguments": arguments})

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        await self.start()
        return await self._request(method, params)

    async def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._proc is None or self._proc.stdin is None:
            raise MCPError(f"MCP server {self.config.name} is not running")
        if self._reader_error is not None:
            raise self._reader_error
        request_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        try:
            await self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
            message = await asyncio.wait_for(future, timeout=self.config.timeout_seconds)
        except asyncio.TimeoutError as exc:
            # user:“假如说原本可以拿到回执，那么它也要能够拿到回执”+(超时不代表写入失败，不自动重放)。
            raise MCPError(f"MCP {self.config.name}.{method} 超时（{self.config.timeout_seconds} 秒）；操作可能已执行，请先核对结果") from exc
        finally:
            self._pending.pop(request_id, None)
        if "error" in message:
            raise MCPError(f"{self.config.name}.{method} failed: {message['error']}")
        result = message.get("result", {})
        return result if isinstance(result, dict) else {"result": result}

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self.start()
        await self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def _send(self, payload: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise MCPError(f"MCP server {self.config.name} is not running")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if self.config.transport == "json_lines":
            framed = body + b"\n"
        else:
            framed = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
        async with self._write_lock:
            self._proc.stdin.write(framed)
            await self._proc.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        try:
            while True:
                message = await read_message(self._proc.stdout, transport=self.config.transport)
                if message is None:
                    self._reader_error = MCPError("MCP 连接已关闭，操作结果可能未知")
                    for future in self._pending.values():
                        if not future.done():
                            future.set_exception(self._reader_error)
                    self._pending.clear()
                    break
                response_id = message.get("id")
                if isinstance(response_id, int) and response_id in self._pending:
                    future = self._pending[response_id]
                    if not future.done():
                        future.set_result(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._reader_error = exc if isinstance(exc, MCPError) else MCPError(str(exc) or type(exc).__name__)
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(self._reader_error)

    async def _drain_stderr(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        try:
            while True:
                chunk = await self._proc.stderr.readline()
                if not chunk:
                    break
        except asyncio.CancelledError:
            raise


async def read_message(reader: asyncio.StreamReader, *, transport: str = "headers") -> dict[str, Any] | None:
    if transport == "json_lines":
        while True:
            try:
                line = await reader.readline()
            except ValueError as exc:
                raise MCPError(f"MCP 消息超过大小上限（{MAX_MESSAGE_BYTES} 字节）") from exc
            if not line:
                return None
            if len(line.rstrip(b'\r\n')) > MAX_MESSAGE_BYTES:
                raise MCPError(f"MCP 消息超过大小上限（{MAX_MESSAGE_BYTES} 字节）")
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSON line from MCP server: %s", text[:200])
                continue

    headers: dict[str, str] = {}
    while True:
        line = await reader.readline()
        if not line:
            return None
        text = line.decode("ascii", errors="replace").strip()
        if text == "":
            break
        if ":" in text:
            key, value = text.split(":", 1)
            headers[key.lower()] = value.strip()
    try:
        length = int(headers.get("content-length", "0"))
    except ValueError:
        logger.warning("Skipping message with invalid Content-Length: %s", headers.get("content-length"))
        return None
    if length <= 0:
        return None
    # A malicious/broken server advertising a huge body must not exhaust
    # process memory (audit 11) — cap single-message size.
    if length > MAX_MESSAGE_BYTES:
        logger.warning("Dropping MCP message with oversized Content-Length: %d", length)
        return None
    body = await reader.readexactly(length)
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        logger.warning("Skipping malformed JSON body from MCP server")
        return None


def encode_mcp_tool_name(server: str, tool: str) -> str:
    return f"mcp__{safe_name(server)}__{safe_name(tool)}"


def safe_name(value: str) -> str:
    chars = [ch if ch.isalnum() or ch == "_" else "_" for ch in value]
    result = "".join(chars).strip("_")
    return result or "tool"

