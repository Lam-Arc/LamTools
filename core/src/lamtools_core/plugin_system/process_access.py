"""user:“宿主能力补齐和接口完善与文档更新”+(先公开可验证的程序解析和环境构造，不将查找成功误称为进程已启动)。"""
from __future__ import annotations

import os
import math
import asyncio
import re
import stat
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


class ProcessAccessError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


_SENSITIVE = re.compile(r"KEY|PASSWORD|SECRET|TOKEN", re.IGNORECASE)
_PREFIXES = ("DSH_", "SUNDAY_", "LAMTOOLS_")
_MAX_ENV_BYTES = 1_048_576


def _environment(overrides):
    try:
        if overrides is None:
            overrides = {}
        if type(overrides) is not dict or len(overrides) > 256:
            raise ValueError
        def key_of(key):
            if type(key) is not str or not key or "=" in key or "\x00" in key:
                raise ValueError
            return key.upper() if os.name == "nt" else key
        result = {key_of(k): v for k, v in os.environ.items()
                  if not _SENSITIVE.search(k) and not k.upper().startswith(_PREFIXES)}
        for key, value in overrides.items():
            key = key_of(key)
            if key.upper() == "DSH_SUBPROCESS_CONTROL":
                raise ValueError
            if value is None:
                result.pop(key, None)
            elif type(value) is str and "\x00" not in value:
                result[key] = value
            else:
                raise ValueError
        total = 0
        for key, value in result.items():
            total += len(key.encode("utf-8")) + len(value.encode("utf-8")) + 2
            if total > _MAX_ENV_BYTES:
                raise ValueError
        return MappingProxyType(result)
    except (ValueError, TypeError, UnicodeError):
        raise ProcessAccessError("process/invalid-environment", "Environment requires at most 256 UTF-8 string overrides or None tombstones, no NUL or reserved control marker; combined limit is 1 MiB") from None


class PluginProcessAPI:
    def __init__(self, scope, work_root=None):
        self._scope = scope
        self._root = Path(work_root).resolve() if work_root is not None else Path.cwd().resolve()
        self._handles = set()
        self._cleanup_registered = False

    async def _dispose(self):
        handles = tuple(self._handles)
        for handle in handles:
            handle._stop.set()
        for handle in handles:
            await handle.shutdown()
            self._handles.discard(handle)

    async def spawn(self, argv: list[str], *, timeout: float, cwd=None, env=None, max_output_bytes: int = 65536, stdin_enabled=False):
        # user:“继续，把 2 阶段都做完”+(进程启动固定工作目录，注册所有权后再异步分配；停用回收原生 Job，不接收任意外部 PID)。
        self._scope.acquire()
        try:
            if type(stdin_enabled) is not bool:
                raise ProcessAccessError("process/invalid-input", "stdin_enabled must be a boolean")
            try:
                encoded_size = sum(len(arg.encode("utf-8")) for arg in argv) if type(argv) is list and all(type(arg) is str for arg in argv) else 0
            except UnicodeError:
                raise ProcessAccessError("process/invalid-command", "Arguments must be valid UTF-8 strings") from None
            if (type(argv) is not list or not argv or len(argv) > 256
                    or any(type(arg) is not str or "\x00" in arg for arg in argv)
                    or encoded_size > 32768):
                raise ProcessAccessError("process/invalid-command", "Use an argv list of at most 256 strings and 32 KiB")
            if type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= 3600:
                raise ProcessAccessError("process/invalid-timeout", "Execution timeout must be finite and within (0, 3600] seconds")
            if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= 1048576:
                raise ProcessAccessError("process/invalid-limit", "Output limit must be 1–1048576 bytes per stream")
            if os.name != "nt":
                raise ProcessAccessError("process/platform-unavailable", "Managed native process owner is currently Windows desktop only")
            if len(self._handles) >= 8:
                raise ProcessAccessError("process/busy", "At most 8 active processes per view")
            executable = self.resolve_executable(argv[0], env=env)
            if executable.suffix.lower() not in {".exe", ".com"}:
                raise ProcessAccessError("process/invalid-command", "Spawn accepts native programs; invoke a chosen shell explicitly for scripts")
            try:
                directory = (self._root / Path(cwd)).resolve() if cwd is not None else self._root
            except (ValueError, TypeError, OSError, RuntimeError):
                raise ProcessAccessError("process/invalid-cwd", "Working directory could not be resolved") from None
            if not directory.is_dir():
                raise ProcessAccessError("process/invalid-cwd", "Working directory must exist")
            if not self._cleanup_registered:
                self._scope.on_dispose(self._dispose)
                self._cleanup_registered = True
            from .owned_processes import OwnedProcess
            handle = OwnedProcess(self._scope, [str(executable), *argv[1:]], directory, dict(self.environment(env)), timeout, max_output_bytes, stdin_enabled=stdin_enabled)
            self._handles.add(handle)
            handle._task.add_done_callback(lambda task: self._handles.discard(handle) if handle._cleaned else None)
            await handle.ready()
            try:
                self._scope.check_open()
            except Exception:
                await handle.shutdown()
                raise
            return handle
        finally:
            self._scope.release()

    async def run(self, argv: list[str], **kwargs):
        handle = await self.spawn(argv, **kwargs)
        try:
            result = await handle.wait()
            return result, handle.read_output()
        except asyncio.CancelledError:
            await handle.shutdown()
            raise

    def environment(self, overrides: dict[str, str | None] | None = None) -> Mapping[str, str]:
        self._scope.check_open()
        return _environment(overrides)

    def resolve_executable(self, command: str | Path, *, env: dict[str, str | None] | None = None) -> Path:
        self._scope.check_open()
        try:
            name = os.fspath(command)
            if not isinstance(name, str) or not name or name != name.strip() or "\x00" in name:
                raise ValueError
            path = Path(name)
            if not path.is_absolute() and any(character in name for character in ("/", "\\", ":")):
                raise ValueError
        except (TypeError, ValueError):
            raise ProcessAccessError("process/invalid-command", "Use an absolute program path or a bare PATH name; relative program paths are unsupported") from None
        environment = self.environment(env)
        extensions = [""]
        if os.name == "nt":
            extensions = environment.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").upper().split(";")
            if not 1 <= len(extensions) <= 32 or any(not re.fullmatch(r"\.[A-Z0-9]+", ext) for ext in extensions):
                raise ProcessAccessError("process/invalid-environment", "PATHEXT requires semicolon-separated dot extensions")
        folders = environment.get("PATH", "").split(os.pathsep)
        if not path.is_absolute() and len(folders) > 256:
            raise ProcessAccessError("process/invalid-environment", "Executable lookup accepts at most 256 PATH entries")
        def existing(candidate):
            if os.name == "nt" and candidate.suffix.upper() not in extensions:
                return None
            try:
                canonical = candidate.resolve(strict=True)
                info = canonical.stat()
                if stat.S_ISREG(info.st_mode) and (os.name == "nt" or os.access(canonical, os.X_OK)):
                    return canonical
            except (FileNotFoundError, NotADirectoryError):
                return None
            return None
        try:
            if path.is_absolute():
                found = existing(path)
                if found is not None:
                    return found
            else:
                # user:“写好清单，逐项打勾完成，不要出错”+(显式只搜索 PATH 的绝对目录，避免 Windows 隐式当前目录搜索和相对目录猜测)。
                suffixes = [""] if os.name != "nt" or path.suffix.upper() in extensions else extensions
                for folder in folders:
                    directory = Path(folder)
                    if not directory.is_absolute():
                        continue
                    for suffix in suffixes:
                        found = existing(directory / (name + suffix))
                        if found is not None:
                            return found
        except (OSError, RuntimeError, ValueError):
            raise ProcessAccessError("process/lookup-failed", "Executable lookup failed; no process was started") from None
        raise ProcessAccessError("process/not-found", "No matching executable file was found; no process was started")


__all__ = ["ProcessAccessError", "PluginProcessAPI"]
