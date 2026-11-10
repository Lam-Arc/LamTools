"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(只控制当前插件拥有且会话可见的真实作业)。"""
import asyncio
import base64
import copy
import math
from pathlib import Path

from .jobs_access import JobAccessError


class PluginJobController:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._root = Path(context.work_root).resolve()
        self._host = context.require_service("working_directory")
        self._jobs = context.jobs

    def _check(self):
        self._scope.check_open()
        if (self._context._registration_scope is not self._scope
                or Path(self._context.work_root).resolve() != self._root
                or self._context.service("working_directory") is not self._host
                or self._context.jobs is not self._jobs):
            raise JobAccessError("job/host-changed", "Original job or session binding changed")

    async def _admit(self, session_id):
        self._check()
        state = await self._host.for_scope(self._scope).get(session_id)
        # user:“复用原宿主权威”+(先检查会话可见性和原项目归属，再按现有插件作业的会话标签过滤)。
        self._check()
        if Path(state.project_root).resolve() != self._root:
            raise JobAccessError("job/not-found", "Session is unavailable in this project")

    def _visible(self, session_id, job_id):
        job = self._jobs.get(job_id)
        if job.session_id is not None and job.session_id != session_id:
            raise JobAccessError("job/not-found", "Job is unavailable in this session")
        return job

    async def list(self, session_id):
        await self._admit(session_id)
        result = tuple(job for job in self._jobs.list() if job.session_id is None or job.session_id == session_id)
        self._check()
        return result

    async def watch_list(self, session_id, *, interval=0.1):
        if type(interval) not in {int, float} or not math.isfinite(interval) or not 0.01 <= interval <= 2:
            raise ValueError("Polling interval must be between 0.01 and 2 seconds")
        previous = None
        while True:
            # user:“复用原宿主权威”+(每次轮询重新校验会话，并仅发布现有插件作业的变化快照)。
            current = await self.list(session_id)
            if current != previous:
                previous = copy.deepcopy(current)
                yield {"kind": "jobs", "jobs": current}
            await asyncio.sleep(interval)

    async def read(self, session_id, job_id, *, stdout_after=0, stderr_after=0):
        await self._admit(session_id)
        self._visible(session_id, job_id)
        result = self._jobs.read(job_id, stdout_after=stdout_after, stderr_after=stderr_after)
        self._check()
        return result

    async def kill(self, session_id, job_id):
        await self._admit(session_id)
        self._visible(session_id, job_id)
        result = await self._jobs.kill(job_id)
        self._check()
        return result

    async def follow(self, session_id, job_id, *, stdout_after=0, stderr_after=0, interval=0.1):
        if type(interval) not in {int, float} or not math.isfinite(interval) or not 0.01 <= interval <= 2:
            raise ValueError("Polling interval must be between 0.01 and 2 seconds")
        await self._admit(session_id)
        job = self._visible(session_id, job_id)
        self._jobs.read(job_id, stdout_after=stdout_after, stderr_after=stderr_after)
        self._check()
        yield {"kind": "opened", "job": job}
        while True:
            # user:“复用原宿主权威”+(每次读取重新检查会话可见性与原作业标签，使用已有非消耗双路字节偏移)。
            output = await self.read(session_id, job_id, stdout_after=stdout_after, stderr_after=stderr_after)
            stdout_after, stderr_after = output.stdout_offset, output.stderr_offset
            if output.stdout or output.stderr or output.stdout_lost or output.stderr_lost:
                yield {"kind": "output", "stdout_base64": base64.b64encode(output.stdout).decode("ascii"),
                       "stderr_base64": base64.b64encode(output.stderr).decode("ascii"),
                       "stdout_offset": stdout_after, "stderr_offset": stderr_after,
                       "stdout_lost": output.stdout_lost, "stderr_lost": output.stderr_lost}
                continue
            if output.complete:
                self._check()
                yield {"kind": "status", "job": self._visible(session_id, job_id)}
                return
            await asyncio.sleep(interval)
