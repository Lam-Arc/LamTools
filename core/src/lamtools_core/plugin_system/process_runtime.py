"""External-process plugin backend (JSON-RPC over stdio).

The host already knows how to supervise a plugin backend, but only in-process
Python backends were supported.  A Node/Python/other process can now be a
backend by declaring a ``runtime`` block in ``plugin.json``:

```json
"runtime": {
  "kind": "process",
  "command": ["node", "dist/server.js"],
  "cwd": ".",
  "env": {"NODE_ENV": "production"},
  "startupTimeoutMs": 15000,
  "requestTimeoutMs": 60000
}
```

The process speaks newline-delimited JSON-RPC 2.0:

* ``initialize`` -> ``{name, version, tools?, operations?}``
* ``tools/call`` ``{name, arguments, call_id}`` -> ``{status, content, error, artifacts, metadata}``
* ``operations/call`` ``{name, payload, metadata}`` -> ``{status, payload}``
* ``health`` -> ``{ok: true}``
* ``shutdown`` -> ``{}``

The plugin still declares its tools/operations in ``tools.jsonc`` /
``operations.jsonc``; the process implements the handlers.  The host keeps its
normal lifecycle, readiness, stop and generation rules.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import shlex
import sys
import time
from pathlib import Path
from typing import Any

from lamtools_core.tool import ToolArtifact, ToolResult

PROTOCOL_VERSION = 1
# user:“该修修 如果是架构问题就重构”+(协议按消息限制为 8 MiB，不能受默认 64 KiB 行缓冲限制)。
MAX_MESSAGE_BYTES = 8 * 1024 * 1024


class ProcessBackendError(RuntimeError):
    pass


class ProcessBackend:
    def __init__(self, plugin: Any, spec: dict[str, Any], context: Any) -> None:
        self.plugin = plugin
        self.spec = dict(spec or {})
        self.context = context
        self.logger = logging.getLogger(f"plugin.process.{getattr(plugin, 'name', 'plugin')}")
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stop_task: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._next_id = 0
        self._lock = asyncio.Lock()
        self._ready = False
        self._last_error = ""
        self._initialized: dict[str, Any] = {}
        self._tool_names = self._declared_tool_names()

    # ── Host lifecycle ─────────────────────────────────────────────────────
    async def start(self, context: Any | None = None) -> None:
        if self._process is not None:
            return
        self._last_error = ""
        command = self._command()
        cwd = self._cwd()
        env = {**os.environ, **{str(key): str(value) for key, value in (self.spec.get("env") or {}).items()}}
        startup_timeout = float(int(self.spec.get("startupTimeoutMs") or 15000)) / 1000.0
        try:
            self._process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(cwd),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as exc:
            self._last_error = f"process start failed: {exc}"
            raise ProcessBackendError(self._last_error) from exc
        self._reader_task = asyncio.create_task(self._read_stdout(), name=f"plugin-process:{self.plugin.name}:stdout")
        self._stderr_task = asyncio.create_task(self._read_stderr(), name=f"plugin-process:{self.plugin.name}:stderr")
        try:
            initialized = await asyncio.wait_for(
                self.call(
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "plugin": self.plugin.name,
                        "host": {"name": "lamtools", "python": sys.version.split()[0]},
                        "context": {
                            "workRoot": str(getattr(context, "work_root", "") or ""),
                            "dataDir": str(getattr(context, "data_dir", "") or ""),
                        },
                    },
                    timeout=startup_timeout,
                ),
                timeout=startup_timeout,
            )
        except Exception as exc:
            self._last_error = f"process initialize failed: {exc}"
            await self.stop()
            raise ProcessBackendError(self._last_error) from exc
        self._initialized = initialized if isinstance(initialized, dict) else {}
        declared = self._initialized.get("tools")
        if isinstance(declared, list):
            names = [
                str(item.get("name") or "")
                for item in declared
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ]
            if names:
                self._tool_names = names
        self._ready = True

    async def stop(self) -> None:
        # user:“修完打包发布新版本”+(取消调用方不能取消资源回收；退出确认前始终持有进程和清理任务)。
        if self._stop_task is None or self._stop_task.done():
            self._stop_task = asyncio.create_task(self._stop_process(), name=f"plugin-process:{self.plugin.name}:stop")
        await asyncio.shield(self._stop_task)

    async def _stop_process(self) -> None:
        self._ready = False
        process = self._process
        if process is not None and process.returncode is None:
            try:
                await asyncio.wait_for(self.call("shutdown", {}, timeout=2.0), timeout=2.0)
            except Exception:
                pass
        if process is not None:
            try:
                if process.returncode is None:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=3.0)
            except Exception:
                try:
                    process.kill()
                    await asyncio.wait_for(process.wait(), timeout=3.0)
                except Exception as exc:
                    raise ProcessBackendError(f"plugin process did not stop: {exc}") from exc
            if process.returncode is None:
                raise ProcessBackendError("plugin process did not stop")
            # user:“该修修 如果是架构问题就重构”+(进程结束时关闭写管道，避免通信失败后遗留句柄)。
            if process.stdin is not None:
                process.stdin.close()
                try:
                    await process.stdin.wait_closed()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
        for task in (self._reader_task, self._stderr_task):
            if task is not None:
                task.cancel()
        tasks = [task for task in (self._reader_task, self._stderr_task) if task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._reader_task = None
        self._stderr_task = None
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(ProcessBackendError("plugin process stopped"))
        self._pending.clear()
        self._process = None

    def health_check(self) -> dict[str, Any]:
        process = self._process
        ready = bool(self._ready and process is not None and process.returncode is None)
        return {
            "ready": ready,
            **({"error": self._last_error} if self._last_error and not ready else {}),
            "pid": process.pid if process is not None else None,
            "protocol": "jsonrpc-stdio",
        }

    # ── Tool/operation proxies ─────────────────────────────────────────────
    @property
    def tool_handlers(self) -> dict[str, Any]:
        handlers: dict[str, Any] = {}
        for name in self._tool_names:
            async def handler(call: Any, _name: str = name) -> ToolResult:
                return await self.call_tool(_name, call)
            handlers[name] = handler
        return handlers

    @property
    def tool_specs(self) -> list[Any]:
        return []

    @property
    def lifecycle_processes(self) -> tuple[Any, ...]:
        return (self._process,) if self._process is not None else ()

    @property
    def lifecycle_tasks(self) -> tuple[Any, ...]:
        # user:“修完打包发布新版本”+(只上报仍在回收的任务，已完成清理不能使重新启用的插件被判为失效)。
        return (self._stop_task,) if self._stop_task is not None and not self._stop_task.done() else ()

    @property
    def services(self) -> dict[str, Any]:
        return {}

    async def call_tool(self, name: str, call: Any) -> ToolResult:
        call_id = str(getattr(call, "id", "") or "")
        arguments = getattr(call, "arguments", None)
        try:
            result = await self.call(
                "tools/call",
                {
                    "name": name,
                    "callId": call_id,
                    "arguments": arguments if isinstance(arguments, dict) else {},
                },
                timeout=self._request_timeout(),
            )
        except Exception as exc:
            return ToolResult(
                call_id=call_id,
                name=name,
                status="failed",
                error=f"process tool failed: {exc}",
            )
        if not isinstance(result, dict):
            return ToolResult(call_id=call_id, name=name, status="failed", error="process returned a non-object tool result")
        artifacts: list[ToolArtifact] = []
        raw_artifacts = result.get("artifacts")
        if isinstance(raw_artifacts, list):
            for item in raw_artifacts:
                if not isinstance(item, dict):
                    continue
                artifacts.append(
                    ToolArtifact(
                        kind=str(item.get("kind") or "file"),
                        uri=str(item.get("uri") or ""),
                        content=item.get("content"),
                        metadata=dict(item.get("metadata") or {}),
                        artifact_id=str(item.get("artifact_id") or ""),
                    )
                )
        return ToolResult(
            call_id=call_id,
            name=name,
            status=str(result.get("status") or "ok"),
            content=str(result.get("content") or ""),
            error=str(result.get("error") or ""),
            error_code=str(result.get("error_code") or result.get("errorCode") or ""),
            artifacts=artifacts,
            metadata=dict(result.get("metadata") or {}),
        )

    async def call_operation(self, name: str, payload: dict[str, Any], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        result = await self.call(
            "operations/call",
            {"name": name, "payload": payload or {}, "metadata": metadata or {}},
            timeout=self._request_timeout(),
        )
        return result if isinstance(result, dict) else {"status": "error", "payload": {"error": "process returned a non-object result"}}

    # ── JSON-RPC ───────────────────────────────────────────────────────────
    async def call(self, method: str, params: dict[str, Any], *, timeout: float | None = None) -> Any:
        process = self._process
        if process is None or process.stdin is None:
            raise ProcessBackendError("plugin process is not running")
        if self._last_error and not self._ready:
            raise ProcessBackendError(self._last_error)
        async with self._lock:
            self._next_id += 1
            request_id = self._next_id
            future: asyncio.Future = asyncio.get_running_loop().create_future()
            self._pending[request_id] = future
            payload = json.dumps(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
                ensure_ascii=False,
            )
            try:
                process.stdin.write((payload + "\n").encode("utf-8"))
                await process.stdin.drain()
            except Exception as exc:
                self._pending.pop(request_id, None)
                raise ProcessBackendError(f"process write failed: {exc}") from exc
        wait = timeout if timeout is not None else self._request_timeout()
        try:
            return await asyncio.wait_for(future, timeout=wait)
        finally:
            self._pending.pop(request_id, None)

    async def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            async for line in self._message_lines(process.stdout):
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    message = json.loads(text)
                except json.JSONDecodeError:
                    self.logger.warning("plugin process wrote non-JSON stdout: %s", text[:200])
                    continue
                if not isinstance(message, dict):
                    continue
                request_id = message.get("id")
                if request_id is not None:
                    if not isinstance(request_id, int) or isinstance(request_id, bool):
                        continue
                    future = self._pending.pop(request_id, None)
                    if future is not None and not future.done():
                        if "error" in message:
                            error = message.get("error") or {}
                            detail = str(error.get("message") or error.get("code") or "process error") if isinstance(error, dict) else str(error)
                            future.set_exception(ProcessBackendError(detail))
                        else:
                            future.set_result(message.get("result"))
                    continue
                self.logger.debug("plugin process notification: %s", message.get("method"))
        except (ProcessBackendError, OSError) as exc:
            self._last_error = str(exc)
        finally:
            # user:“该修修 如果是架构问题就重构”+(传输故障一次通知全部等待者，后续调用立即收到同一原因)。
            self._ready = False
            self._last_error = self._last_error or "plugin process exited"
            for future in list(self._pending.values()):
                if not future.done():
                    future.set_exception(ProcessBackendError(self._last_error))
            self._pending.clear()
        # A failed protocol still needs its pipe drained until stop() terminates
        # the child; otherwise a full pipe can prevent process.wait() finishing.
        if process.returncode is None:
            try:
                while await process.stdout.read(65536):
                    pass
            except OSError:
                pass

    @staticmethod
    async def _message_lines(stream):
        # user:“该修修 如果是架构问题就重构”+(增量分帧同时约束完整消息与未结束消息的内存占用)。
        buffer = bytearray()
        while True:
            chunk = await stream.read(65536)
            if not chunk:
                if buffer:
                    yield bytes(buffer)
                return
            buffer.extend(chunk)
            start = 0
            while (end := buffer.find(b"\n", start)) >= 0:
                if end - start > MAX_MESSAGE_BYTES:
                    raise ProcessBackendError(f"plugin response exceeds {MAX_MESSAGE_BYTES} byte message limit")
                yield bytes(buffer[start:end])
                start = end + 1
            if start:
                del buffer[:start]
            if len(buffer) > MAX_MESSAGE_BYTES:
                raise ProcessBackendError(f"plugin response exceeds {MAX_MESSAGE_BYTES} byte message limit")

    async def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while True:
            try:
                # user:“修完打包发布新版本”+(日志分块排空，单条超长日志不能堵住子进程的业务通信)。
                line = await process.stderr.read(4096)
            except (ValueError, OSError):
                break
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                self.logger.info("[%s] %s", self.plugin.name, text[:2000])

    # ── Helpers ────────────────────────────────────────────────────────────
    def _command(self) -> list[str]:
        command = self.spec.get("command")
        if isinstance(command, str):
            return shlex.split(command, posix=os.name != "nt")
        if isinstance(command, list) and command:
            return [str(item) for item in command]
        raise ProcessBackendError("runtime.command must be a string or a non-empty array")

    def _cwd(self) -> Path:
        cwd = str(self.spec.get("cwd") or "").strip()
        if not cwd:
            return Path(self.plugin.root)
        path = Path(cwd)
        return path if path.is_absolute() else (Path(self.plugin.root) / path).resolve()

    def _request_timeout(self) -> float:
        return max(1.0, float(int(self.spec.get("requestTimeoutMs") or 60000)) / 1000.0)

    def _declared_tool_names(self) -> list[str]:
        try:
            from .capabilities import read_capabilities

            return [spec.name for spec in read_capabilities(self.plugin).tools]
        except Exception:
            return []


def process_runtime_spec(manifest: Any) -> dict[str, Any] | None:
    raw = getattr(manifest, "raw", None)
    if not isinstance(raw, dict):
        return None
    runtime = raw.get("runtime")
    if isinstance(runtime, dict) and str(runtime.get("kind") or "").lower() == "process":
        return dict(runtime)
    return None


__all__ = ["ProcessBackend", "ProcessBackendError", "process_runtime_spec"]
