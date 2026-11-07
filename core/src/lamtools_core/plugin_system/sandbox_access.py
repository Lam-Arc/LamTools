"""user:“给我把 2 阶段做完，前端除外”+(原会话政策CAS与官方Windows文件写隔离接到原Job；不把进程回收当文件隔离)。"""
from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile

from lamtools_core.async_tasks import finish_on_cancel
from .session_data import identifier
from .working_directory import directory_exists
from .process_access import ProcessAccessError


class SandboxAccessError(RuntimeError):
    def __init__(self, code, message, *, may_have_changed=False):
        self.code, self.may_have_changed = code, may_have_changed
        super().__init__(message)


_MODES = {"read-only", "workspace-write", "danger-full-access"}
_KEY = "plugin_sandbox_policy_v1"


def _mode(value):
    if type(value) is not str or value not in _MODES:
        raise SandboxAccessError("sandbox/invalid-mode", "Choose read-only, workspace-write or explicit danger-full-access")
    return value


class PluginSandboxPolicyAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._root = Path(context.work_root)
        self._fallback = Path(context.execution_root or self._root)
        self._host = context.require_service("session_data")
        self._directory_host = context.working_directory._host

    def _check_binding(self):
        # user:“复用原宿主权威”+(等待前后复核同一会话/目录宿主及启动代，读取失效时不能继续发布或派发政策写入)。
        self._scope.check_open()
        if self._context.service("session_data") is not self._host or self._context.service("working_directory") is not self._directory_host:
            raise SandboxAccessError("sandbox/host-changed", "Policy session host changed")

    async def _read(self, session_id):
        self._check_binding()
        identifier(session_id)
        _, record, revision = await self._host._read(session_id, self._root)
        self._check_binding()
        namespace = record.metadata.get(_KEY, {})
        if type(namespace) is not dict:
            raise SandboxAccessError("sandbox/invalid-policy", "Stored policy namespace is invalid")
        mode = _mode(namespace.get(self._scope.owner, "read-only"))
        return record, revision, mode

    def _result(self, record, revision, mode):
        if record is None:
            path = self._fallback
            if not directory_exists(self._root, path):
                raise SandboxAccessError("sandbox/missing-directory", "Bound execution directory is unavailable")
        else:
            # user:“复用现有宿主权威”+(使用同次原会话读取的目录/修订，避免政策和目录取自不同快照)。
            state = self._directory_host._state(self._scope, record, revision)
            if not state.exists:
                raise SandboxAccessError("sandbox/missing-directory", "Session execution directory is unavailable")
            path = Path(state.path)
        if path.drive.startswith("\\"):
            raise SandboxAccessError("sandbox/unsupported-path", "Windows confinement requires a local workspace")
        return {"mode": mode, "workspace_root": str(path), "project_root": str(self._root),
                "session_id": record.id if record is not None else None, "revision": revision,
                "additional_writable_roots": [], "consumer": "plugin-sdk-sandbox"}

    async def resolve(self, session_id=None, *, mode=None):
        self._scope.acquire()
        try:
            if session_id is None:
                return self._result(None, None, "read-only" if mode is None else _mode(mode))
            record, revision, stored = await self._read(session_id)
            return self._result(record, revision, stored if mode is None else _mode(mode))
        finally:
            self._scope.release()

    async def set(self, session_id, *, mode, expected_revision):
        self._scope.acquire()
        try:
            mode = _mode(mode)
            if type(expected_revision) is not int or not 0 <= expected_revision <= 2**63 - 1:
                raise SandboxAccessError("sandbox/invalid-revision", "Read the original session revision first")
            record, revision, _ = await self._read(session_id)
            if expected_revision != revision:
                raise SandboxAccessError("sandbox/conflict", "Session changed; read again")
            metadata = deepcopy(record.metadata)
            metadata.setdefault(_KEY, {})[self._scope.owner] = mode
            from lamtools_core.app.persistence_host import RevisionConflictError
            try:
                saved = await finish_on_cancel(self._host._store.patch(session_id, metadata=metadata, expected_revision=revision), name="plugin-sandbox-policy")
            except RevisionConflictError:
                raise SandboxAccessError("sandbox/conflict", "Session changed during policy save") from None
            if saved is None:
                raise SandboxAccessError("sandbox/conflict", "Session became unavailable")
            return self._result(saved, revision + 1, mode)
        finally:
            self._scope.release()


class PluginSandboxAPI:
    def __init__(self, context, scope):
        self._scope, self._processes = scope, context.processes
        self._policy = context.sandbox_policy

    def _runtime(self):
        module = Path(__file__).resolve()
        for root in (module.parents[1] / "resources/windows-sandbox", module.parents[3] / "runtime/windows-sandbox"):
            package = root / "node_modules/@deepseek-ai/dsh-sandbox-windows-acl"
            try:
                metadata = json.loads((package / "package.json").read_text(encoding="utf8"))
                runner = package / "lib/runner.js"
                if metadata.get("version") == "0.2.2-alpha.2" and runner.is_file():
                    return self._processes.resolve_executable("node.exe"), runner
            except (OSError, ValueError, ProcessAccessError):
                continue
        raise SandboxAccessError("sandbox/unavailable", "Installed pinned Windows ACL runtime and Node22+ are required; refusing unconfined fallback")

    async def run(self, argv, *, session_id=None, mode=None, timeout=30, max_output_bytes=65536):
        self._scope.acquire()
        try:
            try:
                valid = (type(argv) is list and 1 <= len(argv) <= 256
                         and all(type(arg) is str and "\x00" not in arg for arg in argv)
                         and sum(len(arg.encode("utf8")) for arg in argv) <= 32768)
            except UnicodeError:
                valid = False
            if not valid or type(timeout) not in {int,float} or not math.isfinite(timeout) or not 0 < timeout <= 120:
                raise SandboxAccessError("sandbox/invalid-request", "Use bounded argv and a deadline within (0,120]")
            if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= 1048576:
                raise SandboxAccessError("sandbox/invalid-request", "Output limit must be1–1048576 bytes")
            policy = await self._policy.resolve(session_id, mode=mode)
            argv = [str(self._processes.resolve_executable(argv[0])), *argv[1:]]
            confined = policy["mode"] != "danger-full-access"
            node, runner = self._runtime() if confined else (None, None)
            # user:“不能用空壳、未安装提供方或静态扫描冒充兼容”+(实际调用已安装的官方限制令牌runner，不可用时绝不执行原argv)。
            with tempfile.TemporaryDirectory(prefix="sunday-sandbox-") as directory:
                if confined and Path(directory).is_relative_to(Path(policy["workspace_root"])):
                    raise SandboxAccessError("sandbox/unsupported-path", "Private temp root must be outside the workspace")
                command = ([str(node), str(runner), "--workspace", policy["workspace_root"], "--temp", directory,
                            "--mode", policy["mode"], "--", *argv] if confined else argv)
                outcome, output = await self._processes.run(command, cwd=policy["workspace_root"], timeout=timeout,
                    max_output_bytes=max_output_bytes, env={"NODE_OPTIONS":None,"NODE_PATH":None})
                if confined and outcome.exit_code == 127 and b"windows-acl-run:" in output.stderr.lower():
                    raise SandboxAccessError("sandbox/runner-failed", "Windows confinement runner failed; no unconfined retry was attempted", may_have_changed=True)
                response = {"status":outcome.status,"exit_code":outcome.exit_code,"quiescent":outcome.quiescent,
                    "stdout":output.stdout,"stderr":output.stderr,"stdout_lost":output.stdout_lost,"stderr_lost":output.stderr_lost,
                    "confined":confined,"enforcement":"partial" if confined else "none", "policy":policy,
                    "scratch_directory":directory, "backend":"dsh-windows-acl@0.2.2-alpha.2" if confined else None}
            return response
        except OSError:
            raise SandboxAccessError("sandbox/io-failed", "Sandbox scratch I/O or cleanup failed", may_have_changed=True) from None
        finally:
            self._scope.release()
