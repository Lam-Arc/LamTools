"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(会话目录下使用原受管管道进程，不冒充PTY)。"""
import asyncio
import base64
import binascii
import math
import secrets
from pathlib import Path

from lamtools_core.async_tasks import finish_on_cancel
from .working_directory import WorkingDirectoryError


class TerminalPipeError(RuntimeError):
    def __init__(self, code, message, *, may_have_changed=False):
        self.code, self.may_have_changed = code, may_have_changed
        super().__init__(message)


class PluginTerminalController:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._root = Path(context.work_root).resolve()
        self._host = context.require_service("working_directory")
        self._processes = context.processes

    def _check(self):
        self._scope.check_open()
        if (self._context._registration_scope is not self._scope
                or Path(self._context.work_root).resolve() != self._root
                or self._context.service("working_directory") is not self._host
                or self._context.processes is not self._processes):
            raise WorkingDirectoryError("working-directory/host-changed", "Terminal binding changed")

    async def _admit(self, session_id):
        self._check()
        state = await self._host.for_scope(self._scope).get(session_id)
        # user:“复用原宿主权威”+(工作目录和可见性均从原会话宿主取得，不接受客户端授权根)。
        self._check()
        if Path(state.project_root).resolve() != self._root:
            raise WorkingDirectoryError("working-directory/not-found", "Session is unavailable in this project")
        return state

    async def environment(self, session_id):
        state = await self._admit(session_id)
        return {"session_id": session_id, "cwd": state.path, "cwd_exists": state.exists, "pty": False}

    def _pipes(self, *, create=False):
        pipes = getattr(self._scope, "_session_terminal_pipes", None)
        if pipes is None and create:
            pipes = {}
            async def dispose_pipes():
                for key, (_, terminal) in tuple(pipes.items()):
                    await terminal.close()
                    pipes.pop(key, None)
            self._scope.on_dispose(dispose_pipes)
            self._scope._session_terminal_pipes = pipes
        return pipes

    def _pipe(self, session_id, terminal_id):
        self._check()
        pipes = self._pipes()
        row = pipes.get(terminal_id) if pipes is not None and type(terminal_id) is str else None
        if row is None or row[0] != session_id:
            raise TerminalPipeError("terminal/not-found", "Terminal is unavailable in this session")
        return row[1]

    async def create_pipe(self, session_id, argv, *, timeout, env=None, max_output_bytes=65536):
        self._check()
        if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= 262144:
            raise TerminalPipeError("terminal/invalid-limit", "Output limit must be 1–262144 bytes per stream")
        existing = self._pipes()
        if existing is not None and len(existing) >= 32:
            raise TerminalPipeError("terminal/limit", "At most 32 retained terminals")
        terminal = await self.open(session_id, argv, timeout=timeout, env=env, max_output_bytes=max_output_bytes)
        try:
            self._check()
            pipes = self._pipes(create=True)
            if len(pipes) >= 32:
                raise TerminalPipeError("terminal/limit", "At most 32 retained terminals")
            terminal_id = secrets.token_urlsafe(24)
            pipes[terminal_id] = (session_id, terminal)
            return {"id": terminal_id, "pty": False}
        except BaseException:
            await finish_on_cancel(terminal.close(), name="terminal-pipe-unpublished-close")
            raise

    async def read_pipe(self, session_id, terminal_id, *, stdout_after=0, stderr_after=0):
        await self._admit(session_id)
        output = self._pipe(session_id, terminal_id).read(stdout_after=stdout_after, stderr_after=stderr_after)
        self._check()
        return {"stdout_base64": base64.b64encode(output.stdout).decode("ascii"),
                "stderr_base64": base64.b64encode(output.stderr).decode("ascii"),
                "stdout_after": output.stdout_after, "stderr_after": output.stderr_after,
                "stdout_lost": output.stdout_lost, "stderr_lost": output.stderr_lost, "complete": output.complete}

    async def follow_pipe(self, session_id, terminal_id, *, stdout_after=0, stderr_after=0, interval=0.1):
        if type(interval) not in {int, float} or not math.isfinite(interval) or not 0.01 <= interval <= 2:
            raise TerminalPipeError("terminal/invalid-interval", "Polling interval must be 0.01–2 seconds")
        await self.read_pipe(session_id, terminal_id, stdout_after=stdout_after, stderr_after=stderr_after)
        # user:“继续”+(输出流复用原受管管道，不因观察者关闭而停止进程)。
        yield {"kind": "opened", "id": terminal_id, "pty": False}
        output = await self.read_pipe(session_id, terminal_id, stdout_after=stdout_after, stderr_after=stderr_after)
        while True:
            stdout_after, stderr_after = output["stdout_after"], output["stderr_after"]
            if output["stdout_base64"] or output["stderr_base64"] or output["stdout_lost"] or output["stderr_lost"]:
                yield {"kind": "output", **output}
            elif output["complete"]:
                yield {"kind": "end", "stdout_after": stdout_after, "stderr_after": stderr_after}
                return
            else:
                await asyncio.sleep(interval)
            output = await self.read_pipe(session_id, terminal_id, stdout_after=stdout_after, stderr_after=stderr_after)

    async def send_pipe(self, session_id, terminal_id, data, *, timeout=5):
        if type(data) is not str or len(data) > 21848:
            raise TerminalPipeError("terminal/invalid-input", "Use bounded base64 input")
        try:
            payload = base64.b64decode(data, validate=True)
            if len(payload) > 16384:
                raise ValueError("input too large")
        except (ValueError, binascii.Error, UnicodeError):
            raise TerminalPipeError("terminal/invalid-input", "Use bounded base64 input") from None
        await self._admit(session_id)
        terminal = self._pipe(session_id, terminal_id)
        try:
            written = await terminal.send(payload, timeout=timeout)
            # user:“第二阶段结束后 就继续开展第三阶段”+(输入后复核原会话和句柄，失败不假定输入未送达)。
            await self._admit(session_id)
            if self._pipe(session_id, terminal_id) is not terminal:
                raise TerminalPipeError("terminal/host-changed", "Terminal binding changed")
            return {"written": written}
        except asyncio.CancelledError:
            raise
        except Exception:
            raise TerminalPipeError("terminal/write-uncertain", "Input may have been delivered", may_have_changed=True) from None

    async def close_pipe(self, session_id, terminal_id):
        terminal = self._pipe(session_id, terminal_id)
        try:
            # user:“复用原宿主权威”+(只关闭当前插件拥有的句柄，允许原会话失效后清理)。
            await finish_on_cancel(terminal.close(), name="terminal-pipe-close")
        finally:
            pipes = self._pipes()
            if pipes is not None and terminal._process._cleaned:
                pipes.pop(terminal_id, None)

    def _watch_session(self, session_id, terminal):
        watchers = getattr(self._scope, "_session_terminal_watchers", None)
        if watchers is None:
            watchers = set()

            async def dispose_watchers():
                tasks = tuple(watchers)
                for task in tasks:
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

            self._scope.on_dispose(dispose_watchers)
            self._scope._session_terminal_watchers = watchers

        async def watch():
            try:
                while True:
                    try:
                        await asyncio.wait_for(asyncio.shield(terminal._process._task), timeout=0.2)
                        return
                    except TimeoutError:
                        # user:“第二阶段结束后 就继续开展第三阶段”+(终端存活时轮询原会话准入，失效则回收原受管进程)。
                        await self._admit(session_id)
            except Exception:
                pass
            finally:
                if not terminal._process._task.done() or not terminal._process._cleaned:
                    await finish_on_cancel(terminal.close(), name="session-terminal-lifetime-close")

        task = asyncio.create_task(watch(), name="session-terminal-lifetime")
        watchers.add(task)
        def finished(done):
            watchers.discard(done)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)

    async def open(self, session_id, argv, *, timeout, env=None, max_output_bytes=65536):
        state = await self._admit(session_id)
        if not state.exists:
            raise WorkingDirectoryError("working-directory/missing", "Session execution directory is unavailable")
        terminal = await self._context.terminals.open(argv, timeout=timeout, cwd=state.path, env=env,
                                                       max_output_bytes=max_output_bytes)
        try:
            self._check()
            # user:“复用原宿主权威”+(进程已启动后重新核对会话可见性与执行目录，失效则回收实际进程)。
            current = await self._admit(session_id)
            if not current.exists or Path(current.path).resolve() != Path(state.path).resolve():
                raise WorkingDirectoryError("working-directory/changed", "Session execution directory changed during terminal start")
            self._check()
            self._watch_session(session_id, terminal)
            return terminal
        except BaseException:
            # user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(准入后绑定失效时先等待实际终端回收再传播错误)。
            await finish_on_cancel(terminal.close(), name="session-terminal-stale-close")
            raise
