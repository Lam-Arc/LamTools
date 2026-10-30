"""user:“给我把 2 阶段做完，前端除外”+(程序和动态定义复用受管进程/作业，明示无沙箱和DSH SDK回调)。"""
import base64
import hashlib
import json
import sys
import uuid
from pathlib import Path


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
        self._scope.check_open()
        if definition_id not in self._definitions:
            raise LookupError("Dynamic definition is unavailable")
        for job_id in self._runs.get(definition_id, ()):
            try:
                await self._context.jobs.kill(job_id)
            except Exception as error:
                if getattr(error, "code", None) != "job/not-found":
                    raise
        self._runs.pop(definition_id, None)

    async def undefine(self, definition_id):
        await self.stop(definition_id)
        self._definitions.pop(definition_id)
