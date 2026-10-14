"""No I/O or background work at import/factory time; the host owns startup."""

import asyncio


class Runtime:
    def __init__(self):
        self.ticks = 0
        self._task = None

    @property
    def lifecycle_tasks(self):
        return [self._task] if self._task is not None else []

    async def start(self):
        async def heartbeat():
            while True:
                await asyncio.sleep(1)
                self.ticks += 1
        self._task = asyncio.create_task(heartbeat(), name="lifecycle-demo:heartbeat")

    def health_check(self):
        return self._task is not None and not self._task.done()

    async def stop(self):
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None


def create_plugin(context):
    return Runtime()
