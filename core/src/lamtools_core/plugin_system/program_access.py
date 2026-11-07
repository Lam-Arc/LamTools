"""user:“给我把 2 阶段做完，前端除外”+(程序和动态定义复用受管进程/作业，明示无沙箱和DSH SDK回调)。"""
import base64
import hashlib
import json
import sys
import uuid
from pathlib import Path

from lamtools_core.async_tasks import finish_on_cancel


def _source(value):
    if type(value) is not str or len(value.encode("utf8")) > 8192 or not value.strip():
        raise ValueError("Use nonempty Python source, at most 8 KiB")
    compile(value, "<sunday-plugin-program>", "exec")
    return value


class PluginProgramAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope

    async def run(self, source, *, input=None, timeout=30):
        self._scope.acquire()
        try:
            source = _source(source)
            encoded = json.dumps(input, ensure_ascii=False, allow_nan=False).encode("utf8")
            if len(encoded) > 8192:
                raise ValueError("Program input exceeds 8 KiB JSON")
            marker = "SUNDAY_PROGRAM_" + uuid.uuid4().hex + ":"
            argv = [sys.executable, "-X", "utf8", str(Path(__file__).with_name("program_worker.py")),
                    base64.b64encode(source.encode("utf8")).decode("ascii"), base64.b64encode(encoded).decode("ascii"), marker]
            outcome, output = await self._context.processes.run(argv, timeout=timeout, max_output_bytes=65536)
            stdout, stderr = output.stdout.decode("utf8", errors="replace"), output.stderr.decode("utf8", errors="replace")
            result = {"status": outcome.status, "exit_code": outcome.exit_code, "quiescent": outcome.quiescent,
                      "confined": False, "stdout": stdout, "stderr": stderr,
                      "stdout_lost": output.stdout_lost, "stderr_lost": output.stderr_lost}
            if outcome.status == "exited":
                before, separator, after = stdout.rpartition(marker)
                try:
                    payload = json.loads(after.strip()) if separator else None
                    if type(payload) is not dict or payload.get("status") not in {"completed", "failed"} or outcome.exit_code != 0:
                        raise ValueError
                    result.update(payload)
                    result["stdout"] = before.removesuffix("\n")
                except (ValueError, TypeError):
                    result.update(status="failed", error={"type": "ProtocolError", "message": "Worker exited without a complete result receipt"})
            return result
        finally:
            self._scope.release()


class PluginDynamicRunnerAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._definitions, self._runs = {}, {}
        self._stopping = set()

    def define(self, source):
        self._scope.check_open()
        source = _source(source)
        key = hashlib.sha256(source.encode("utf8")).hexdigest()
        if key not in self._definitions and len(self._definitions) >= 32:
            raise ValueError("At most 32 dynamic program definitions per view")
        self._definitions[key] = source
        return {"id": key, "language": "python", "persistent": False, "host_callbacks": False, "confined": False}

    def run(self, definition_id, *, input=None, timeout=30):
        self._scope.check_open()
        if definition_id in self._stopping:
            raise RuntimeError("Dynamic definition is stopping; no new runs are admitted")
        source = self._definitions.get(definition_id)
        if source is None:
            raise LookupError("Dynamic definition is unavailable in this plugin view")
        async def execute(_job):
            result = await self._context.ptc_runtime.run(source, input=input, timeout=timeout)
            # Jobs retain 64 KiB JSON; return values/errors and bounded log tails fit that contract.
            for stream in ("stdout", "stderr"):
                result[stream] = result[stream].encode("utf8")[-4000:].decode("utf8", errors="replace")
            return result
        job = self._context.jobs.start("dynamic", definition_id[:12], execute)
        self._runs.setdefault(definition_id, set()).add(job.id)
        return job

    async def stop(self, definition_id):
        # user:“审查当前代码，然后继续”+(关闭准入后固定任务集合，取消调用者也须完成原集合的停止/等待)。
        self._scope.acquire()
        admitted = False
        try:
            if definition_id not in self._definitions:
                raise LookupError("Dynamic definition is unavailable")
            if definition_id in self._stopping:
                raise RuntimeError("Dynamic definition is already stopping")
            self._stopping.add(definition_id)
            admitted = True
            jobs = self._context.jobs
            runs = tuple(self._runs.get(definition_id, ()))
            async def stop_all():
                # user:“完成真实接口、参数/错误、作用域、取消/清理”+(单项失败不跳过其余作业；仅保留失败所有权供重试，全部尝试后报告真实错误)。
                failures, remaining = [], set()
                for job_id in runs:
                    try:
                        await jobs.kill(job_id)
                    except Exception as error:
                        if getattr(error, "code", None) != "job/not-found":
                            failures.append(error)
                            remaining.add(job_id)
                if failures:
                    self._runs[definition_id] = remaining
                    raise ExceptionGroup("Dynamic program job cleanup failed", failures)
                self._runs.pop(definition_id, None)
            await finish_on_cancel(stop_all(), name="plugin-dynamic-stop")
        finally:
            if admitted:
                self._stopping.discard(definition_id)
            self._scope.release()

    async def undefine(self, definition_id):
        await self.stop(definition_id)
        self._definitions.pop(definition_id)
