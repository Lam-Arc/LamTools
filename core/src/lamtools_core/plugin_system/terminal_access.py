"""user:“给我把 2 阶段做完，前端除外”+(管道交互终端复用现有进程所有权，明确pty=false，不接收外部PID)。"""


class PluginTerminal:
    pty = False

    def __init__(self, process):
        self._process = process

    @property
    def pid(self):
        return self._process.pid

    async def send(self, data, *, timeout=5):
        return await self._process.write_stdin(data, timeout=timeout)

    def read(self, *, stdout_after=0, stderr_after=0):
        return self._process.read_output(stdout_after=stdout_after, stderr_after=stderr_after)

    async def wait(self):
        return await self._process.wait()

    async def close(self):
        return await self._process.terminate()


class PluginTerminalsAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope

    async def open(self, argv, *, timeout, cwd=None, env=None, max_output_bytes=65536):
        self._scope.check_open()
        return PluginTerminal(await self._context.processes.spawn(argv, timeout=timeout, cwd=cwd, env=env,
                                                                 max_output_bytes=max_output_bytes, stdin_enabled=True))
