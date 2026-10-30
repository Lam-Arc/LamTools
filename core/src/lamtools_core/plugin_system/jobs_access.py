"""user:“继续，把 2 阶段都做完”+(插件后台任务有有界记录、输出和显式归属，停用取消并等待实际回调退出)。"""
from __future__ import annotations

import asyncio
import inspect
import json
import math
import re
import uuid
from dataclasses import dataclass

from .durable_access import _json


class JobAccessError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class JobView:
    id: str
    kind: str
    label: str
    session_id: str | None
    status: str
    progress: str
    result: object
    error_code: str | None


@dataclass(frozen=True)
class JobOutput:
    stdout: bytes
    stderr: bytes
    stdout_offset: int
    stderr_offset: int
    stdout_lost: bool
    stderr_lost: bool
    complete: bool


class PluginJob:
    def __init__(self, api, kind, label, run, session_id, limit):
        self._api, self._limit = api, limit
        self.id, self.kind, self.label, self.session_id = f"{kind}-{uuid.uuid4().hex[:16]}", kind, label, session_id
        self._status, self._progress, self._result, self._error = "running", "", None, None
        self._buffers, self._totals = [b"", b""], [0, 0]
        self._stopping, self._done = False, asyncio.Event()
        self._task = asyncio.create_task(self._run(run), name="plugin-job:" + self.id)
        self._task.add_done_callback(self._settled)

    def _settled(self, task):
        if task.cancelled():
            self._status = "killed"
        elif task.exception() is not None:
            self._status, self._error = "failed", "job/execution-failed"
        self._done.set()

    async def _run(self, run):
        try:
            value = run(self)
            if not inspect.isawaitable(value):
                raise ValueError("Job callback must be async")
            value = await value
            # Copy finite JSON before publication; never retain arbitrary caller objects.
            encoded = json.dumps(_json(value, maximum=65536), ensure_ascii=False, allow_nan=False).encode("utf-8")
            if len(encoded) > 65536:
                raise ValueError("Job result exceeds 64 KiB")
            self._result = json.loads(encoded)
            self._status = "killed" if self._stopping else "completed"
            if self._stopping:
                self._result = None
        except asyncio.CancelledError:
            self._status = "killed"
        except Exception:
            self._status, self._error = "failed", "job/execution-failed"

    def _check_producer(self):
        self._api._scope.check_open()
        if self._task.done() or self._stopping:
            raise JobAccessError("job/closed", "Job output is closed")
        if asyncio.current_task() is not self._task:
            raise JobAccessError("job/invalid-producer", "Only this job callback may publish output")

    def emit(self, stream, value):
        self._check_producer()
        if stream not in {"stdout", "stderr"} or type(value) not in {str, bytes}:
            raise JobAccessError("job/invalid-output", "Output must be stdout/stderr and text or bytes")
        try:
            data = value.encode("utf-8") if type(value) is str else value
        except UnicodeError:
            raise JobAccessError("job/invalid-output", "Text must be valid UTF-8") from None
        if len(data) > 65536:
            raise JobAccessError("job/invalid-output", "Each output chunk is limited to 64 KiB")
        index = 0 if stream == "stdout" else 1
        self._totals[index] += len(data)
        self._buffers[index] = (self._buffers[index] + data)[-self._limit:]

    def progress(self, text):
        self._check_producer()
        if type(text) is not str or len(text) > 1024 or "\x00" in text:
            raise JobAccessError("job/invalid-progress", "Progress is text of at most 1024 characters")
        self._progress = text

    def view(self):
        return JobView(self.id, self.kind, self.label, self.session_id, self._status, self._progress,
                       _json(self._result), self._error)

    def stop(self):
        if not self._task.done() and not self._stopping:
            self._stopping, self._status = True, "stopping"
            self._task.cancel()


class PluginJobsAPI:
    def __init__(self, scope):
        self._scope, self._records = scope, {}
        scope.on_dispose(self._close)

    async def _close(self):
        records = tuple(self._records.values())
        for record in records:
            record.stop()
        for record in records:
            await self._join(record)
        self._records.clear()

    async def _join(self, record):
        caller = asyncio.current_task()
        cancelling = caller.cancelling()
        while not record._done.is_set():
            try:
                await asyncio.shield(record._done.wait())
            except asyncio.CancelledError:
                continue
        if caller.cancelling() > cancelling:
            raise asyncio.CancelledError

    def _record(self, job_id):
        self._scope.check_open()
        if type(job_id) is not str or job_id not in self._records:
            raise JobAccessError("job/not-found", "Job is not owned by this plugin view")
        return self._records[job_id]

    def start(self, kind, label, run, *, session_id=None, max_output_bytes=65536):
        self._scope.check_open()
        if (type(kind) is not str or not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", kind)
                or type(label) is not str or not label.strip() or len(label) > 256 or "\x00" in label or not callable(run)):
            raise JobAccessError("job/invalid-spec", "Use a bounded kind/label and async callback")
        if session_id is not None and (type(session_id) is not str or not session_id or len(session_id) > 256 or "\x00" in session_id):
            raise JobAccessError("job/invalid-spec", "Use a bounded session label or None")
        if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= 65536:
            raise JobAccessError("job/invalid-limit", "Output tails are limited to 1–65536 bytes per stream")
        if len(self._records) >= 128 or sum(not r._task.done() for r in self._records.values()) >= 8:
            raise JobAccessError("job/limit", "At most 8 running and 128 retained jobs per view")
        job = PluginJob(self, kind, label, run, session_id, max_output_bytes)
        self._records[job.id] = job
        return job

    def get(self, job_id):
        return self._record(job_id).view()

    def list(self, *, session_id=None):
        self._scope.check_open()
        return tuple(r.view() for r in self._records.values() if session_id is None or r.session_id == session_id)

    def read(self, job_id, *, stdout_after=0, stderr_after=0):
        record = self._record(job_id)
        offsets = (stdout_after, stderr_after)
        chunks, lost = [], []
        for index, offset in enumerate(offsets):
            if type(offset) is not int or not 0 <= offset <= record._totals[index]:
                raise JobAccessError("job/invalid-cursor", "Use observed byte offsets")
            start = record._totals[index] - len(record._buffers[index])
            chunks.append(record._buffers[index][max(start, offset) - start:])
            lost.append(offset < start)
        return JobOutput(*chunks, *record._totals, *lost, record._done.is_set())

    async def wait(self, job_id, *, timeout):
        record = self._record(job_id)
        if asyncio.current_task() is record._task:
            raise JobAccessError("job/self-wait", "A job cannot wait for itself")
        if type(timeout) not in {int,float} or not math.isfinite(timeout) or not 0 <= timeout <= 60:
            raise JobAccessError("job/invalid-timeout", "Wait timeout must be within [0,60] seconds")
        try:
            if timeout > 0 and not record._done.is_set():
                await asyncio.wait_for(record._done.wait(), timeout)
        except TimeoutError:
            pass
        return record.view()

    async def kill(self, job_id):
        record = self._record(job_id)
        if asyncio.current_task() is record._task:
            raise JobAccessError("job/self-stop", "A job cannot join itself")
        record.stop()
        await self._join(record)
        return record.view()

    def remove(self, job_id):
        record = self._record(job_id)
        if not record._done.is_set():
            raise JobAccessError("job/running", "Wait for job completion before removal")
        del self._records[job_id]
