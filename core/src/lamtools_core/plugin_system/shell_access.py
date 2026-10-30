"""user:“继续，把 2 阶段都做完”+(桌面 PowerShell 和环境贡献共用现有受管进程，公开近似差异，不创建第二套执行权威)。"""
from __future__ import annotations

import asyncio
import inspect
import math
import re
from dataclasses import dataclass, field
from types import MappingProxyType


class ShellAccessError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ShellEnvironmentContext:
    work_root: str
    session_id: str | None


@dataclass(frozen=True)
class ShellEnvironmentDeclaration:
    owner: str
    name: str
    variables: tuple[tuple[str, str], ...]


@dataclass(eq=False)
class _Contribution:
    scope: object
    declaration: ShellEnvironmentDeclaration
    resolve: object
    live: bool = True


class ShellEnvironmentHost:
    def __init__(self):
        self.entries = []


_RESERVED = {"SUNDAY_HOME", "SUNDAY_SHELL", "SUNDAY_SESSION_ID", "SUNDAY_PROFILE", "SUNDAY_PROFILE_DIR"}


class PluginShellEnvironmentAPI:
    def __init__(self, context, scope):
        self._scope = scope
        self._root, self._home = str(context.execution_root if context.execution_root is not None else context.work_root), context.data_dir
        host = context.service("shell_environment")
        if host is None:
            host = ShellEnvironmentHost()
            context.set_service("shell_environment", host)
        self._host = host

    def register(self, name, variables, resolve):
        self._scope.check_open()
        if (type(name) is not str or not re.fullmatch(r"[a-z][a-z0-9-]{0,127}", name)
                or type(variables) is not dict or not 1 <= len(variables) <= 64 or not callable(resolve)):
            raise ShellAccessError("shell/invalid-declaration", "Use a bounded name, 1–64 declared variables and a callable")
        for key, description in variables.items():
            if (type(key) is not str or len(key) > 128 or not re.fullmatch(r"SUNDAY_[A-Z][A-Z0-9_]*", key)
                    or key in _RESERVED or type(description) is not str or not description.strip()
                    or len(description) > 1024):
                raise ShellAccessError("shell/invalid-declaration", "Declare described non-reserved SUNDAY_* keys")
        if len(self._host.entries) >= 64:
            raise ShellAccessError("shell/limit", "At most 64 environment contributors")
        for entry in self._host.entries:
            if entry.live and entry.scope.accepting and (entry.declaration.name == name
                    or set(dict(entry.declaration.variables)) & variables.keys()):
                raise ShellAccessError("shell/conflict", "Environment name or variable is already owned")
        entry = _Contribution(self._scope, ShellEnvironmentDeclaration(self._scope.owner, name, tuple(sorted(variables.items()))), resolve)
        self._host.entries.append(entry)
        def remove():
            entry.live = False
            if entry in self._host.entries:
                self._host.entries.remove(entry)
        self._scope.on_dispose(remove)
        return remove

    def _entries(self):
        return sorted((e for e in self._host.entries if e.live and e.scope.accepting and e.scope.published),
                      key=lambda e: e.declaration.name)

    def list(self):
        self._scope.check_open()
        return tuple(e.declaration for e in self._entries())

    async def collect(self, *, session_id=None):
        self._scope.acquire()
        try:
            if session_id is not None and (type(session_id) is not str or not session_id or len(session_id) > 256 or "\x00" in session_id):
                raise ShellAccessError("shell/invalid-session", "Use a bounded session identifier or None")
            if self._home is None:
                raise ShellAccessError("shell/unavailable", "Shell environment requires the host data directory")
            result = {"SUNDAY_HOME": str(self._home), "SUNDAY_SHELL": "1"}
            if session_id is not None:
                result["SUNDAY_SESSION_ID"] = session_id
            execution = ShellEnvironmentContext(self._root, session_id)
            try:
                async with asyncio.timeout(5):
                    for entry in self._entries():
                        entry.scope.acquire()
                        try:
                            values = entry.resolve(execution)
                            if inspect.isawaitable(values):
                                values = await values
                            self._scope.check_open()
                            entry.scope.check_open()
                            if not entry.live:
                                raise ShellAccessError("shell/contributor-revoked", "Environment contributor was removed")
                            declared = dict(entry.declaration.variables)
                            if type(values) is not dict or len(values) > len(declared):
                                raise ShellAccessError("shell/invalid-contribution", "Environment resolver must return declared strings")
                            for key, value in values.items():
                                if key not in declared or type(value) is not str or "\x00" in value or len(value.encode("utf-8")) > 65536:
                                    raise ShellAccessError("shell/invalid-contribution", "Environment resolver returned invalid values")
                            result.update(values)
                            if sum(len(k.encode("utf-8")) + len(v.encode("utf-8")) for k,v in result.items()) > 65536:
                                raise ShellAccessError("shell/limit", "Managed shell environment exceeds 64 KiB")
                        finally:
                            entry.scope.release()
            except ShellAccessError:
                raise
            except Exception:
                raise ShellAccessError("shell/contribution-failed", "Environment collection failed or exceeded its deadline") from None
            return MappingProxyType(dict(sorted(result.items())))
        finally:
            self._scope.release()


@dataclass(frozen=True)
class ShellExecutionSpec:
    command: str
    timeout: float
    cwd: str
    env: tuple[tuple[str, str | None], ...]
    max_output_bytes: int
    session_id: str | None
    _scope: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class ShellExecutionResult:
    outcome: object
    output: object


class ShellExecution:
    def __init__(self, handle):
        self._handle = handle

    async def result(self):
        outcome = await self._handle.wait()
        return ShellExecutionResult(outcome, self._handle.read_output())

    def read_output(self, *, stdout_after=0, stderr_after=0):
        return self._handle.read_output(stdout_after=stdout_after, stderr_after=stderr_after)

    async def kill(self):
        return await self._handle.terminate()


class PluginShellAPI:
    def __init__(self, context, scope):
        self._scope, self._root = scope, str(context.execution_root if context.execution_root is not None else context.work_root)
        self._processes, self._environment = context.processes, context.shell_env

    def resolve(self, command, *, timeout, cwd=None, env=None, max_output_bytes=65536, session_id=None):
        self._scope.check_open()
        try:
            valid_command = type(command) is str and bool(command.strip()) and "\x00" not in command and len(command.encode("utf-8")) <= 16384
        except UnicodeError:
            valid_command = False
        if not valid_command:
            raise ShellAccessError("shell/invalid-command", "Use a nonempty UTF-8 command of at most 16 KiB")
        if type(timeout) not in {int,float} or not math.isfinite(timeout) or not 0 < timeout <= 3600:
            raise ShellAccessError("shell/invalid-timeout", "Explicit timeout must be within (0,3600] seconds")
        if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= 1048576:
            raise ShellAccessError("shell/invalid-limit", "Output bound must be 1–1048576 bytes per stream")
        if env is None:
            env = {}
        if type(env) is not dict or any(type(k) is not str or k.upper().startswith(("SUNDAY_", "DSH_", "LAMTOOLS_")) for k in env):
            raise ShellAccessError("shell/invalid-environment", "Ordinary overrides cannot supply host-owned variables")
        self._processes.environment(env)  # Validate without mutating the parent environment.
        if session_id is not None and (type(session_id) is not str or not session_id or len(session_id) > 256 or "\x00" in session_id):
            raise ShellAccessError("shell/invalid-session", "Use a bounded session identifier or None")
        from pathlib import Path
        try:
            directory = (Path(self._root) / (cwd if cwd is not None else ".")).resolve()
            if not directory.is_dir():
                raise ValueError
        except (ValueError, TypeError, OSError, RuntimeError):
            raise ShellAccessError("shell/invalid-cwd", "Shell working directory must exist") from None
        return ShellExecutionSpec(command, float(timeout), str(directory), tuple(sorted(env.items())), max_output_bytes, session_id, self._scope)

    async def execute(self, spec):
        self._scope.acquire()
        try:
            if type(spec) is not ShellExecutionSpec or spec._scope is not self._scope:
                raise ShellAccessError("shell/invalid-spec", "Resolve a spec in this plugin startup scope")
            spec = self.resolve(spec.command, timeout=spec.timeout, cwd=spec.cwd, env=dict(spec.env),
                                max_output_bytes=spec.max_output_bytes, session_id=spec.session_id)
            start = asyncio.get_running_loop().time()
            try:
                async with asyncio.timeout(spec.timeout):
                    managed = await self._environment.collect(session_id=spec.session_id)
            except TimeoutError:
                raise ShellAccessError("shell/preparation-timeout", "Shell preparation exceeded its deadline") from None
            remaining = spec.timeout - (asyncio.get_running_loop().time() - start)
            if remaining <= 0:
                raise ShellAccessError("shell/preparation-timeout", "Shell preparation exceeded its deadline")
            # Explicit PowerShell selection; never trust COMSPEC or evaluate shell discovery output.
            from .process_access import ProcessAccessError
            try:
                program = self._processes.resolve_executable("pwsh.exe")
            except ProcessAccessError as error:
                if error.code != "process/not-found":
                    raise
                program = self._processes.resolve_executable("powershell.exe")
            env = dict(spec.env)
            env.update(managed)
            handle = await self._processes.spawn([str(program), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", spec.command],
                       timeout=remaining, cwd=spec.cwd, env=env, max_output_bytes=spec.max_output_bytes)
            return ShellExecution(handle)
        finally:
            self._scope.release()
