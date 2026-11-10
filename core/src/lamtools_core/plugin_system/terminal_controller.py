"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(会话目录下使用原受管管道进程，不冒充PTY)。"""
from pathlib import Path

from lamtools_core.async_tasks import finish_on_cancel
from .working_directory import WorkingDirectoryError


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
            return terminal
        except BaseException:
            # user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(准入后绑定失效时先等待实际终端回收再传播错误)。
            await finish_on_cancel(terminal.close(), name="session-terminal-stale-close")
            raise
