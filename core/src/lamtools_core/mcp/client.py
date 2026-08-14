from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from typing import Any

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

    async def start(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            return
        env = os.environ.copy()
        env.update(self.config.env)
        self._proc = await asyncio.create_subprocess_exec(
            self.config.command,
            *self.config.args,
            **subprocess_start_kwargs(env=env),
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        await self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "LamToolsCore", "version": "0.1.0"},
            },
        )
        await self.notify("notifications/initialized", {})

    async def close(self) -> None:
        proc = self._proc
        self._proc = None
        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            self._stderr_task = None
        if proc is not None and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

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
                )
            )
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.request("tools/call", {"name": name, "arguments": arguments})

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._proc is None or self._proc.returncode is not None:
            await self.start()
        if self._proc is None or self._proc.stdin is None:
            raise MCPError(f"MCP server {self.config.name} is not running")
        request_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        await self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        try:
            message = await asyncio.wait_for(future, timeout=self.config.timeout_seconds)
        finally:
            self._pending.pop(request_id, None)
        if "error" in message:
            raise MCPError(f"{self.config.name}.{method} failed: {message['error']}")
        result = message.get("result", {})
        return result if isinstance(result, dict) else {"result": result}

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
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
                    for future in self._pending.values():
                        if not future.done():
                            future.set_exception(MCPError("Connection closed"))
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
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(MCPError(str(exc)))

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
            line = await reader.readline()
            if not line:
                return None
            if len(line) > MAX_MESSAGE_BYTES:
                logger.warning("Dropping oversized MCP line (%d bytes)", len(line))
                return None
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

