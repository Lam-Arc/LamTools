"""user:“给我把 2 阶段做完，前端除外”+(SSH复用原OpenSSH/Windows Job，固定身份和主机校验文件，不读写用户默认SSH配置)。"""
import asyncio
import ipaddress
import math
import re

from lamtools_core.async_tasks import finish_on_cancel
from .filesystem_access import PluginFilesystemAPI, FilesystemError
from .process_access import ProcessAccessError


class SSHAccessError(RuntimeError):
    def __init__(self, code, message, *, may_have_changed=False):
        self.code, self.may_have_changed = code, may_have_changed
        super().__init__(message)


def _timeout(value):
    if type(value) not in {int, float} or not math.isfinite(value) or not 0 < value <= 120:
        raise SSHAccessError("ssh/invalid-config", "Use a finite deadline within (0,120] seconds")
    return value


class PluginSSHAPI:
    def __init__(self, context, scope):
        self._scope, self._processes = scope, context.processes
        self._fs = PluginFilesystemAPI(context.work_root, scope, context.data_dir)
        self._connections = set()
        self._cleanup_registered = False

    async def _close(self):
        for connection in tuple(self._connections):
            await connection.close()

    async def connect(self, *, host, user, port=22, identity_file, known_hosts, timeout=10):
        self._scope.acquire()
        connection = None
        try:
            timeout = _timeout(timeout)
            if (type(host) is not str or not 1 <= len(host) <= 253 or type(user) is not str
                    or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}", user)
                    or type(port) is not int or not 1 <= port <= 65535):
                raise SSHAccessError("ssh/invalid-config", "Use an explicit host, user and TCP port")
            try:
                ipaddress.ip_address(host)
            except ValueError:
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,252}", host):
                    raise SSHAccessError("ssh/invalid-config", "Host cannot contain SSH options, user names or shell syntax") from None
            try:
                identity, known = self._fs.resolve(identity_file), self._fs.resolve(known_hosts)
                if any(not item.is_file() or not 0 < item.stat().st_size <= 1048576 for item in (identity, known)):
                    raise ValueError
            except (FilesystemError, ValueError, OSError):
                raise SSHAccessError("ssh/invalid-config", "Supply existing bounded project identity and known-host files") from None
            if len(self._connections) >= 8:
                raise SSHAccessError("ssh/busy", "At most eight connection configurations per view")
            try:
                executable = self._processes.resolve_executable("ssh.exe")
            except ProcessAccessError:
                raise SSHAccessError("ssh/unavailable", "Native OpenSSH client is unavailable") from None
            if not self._cleanup_registered:
                self._scope.on_dispose(self._close)
                self._cleanup_registered = True
            connection = SSHConnection(self, executable, host, user, port, identity, known)
            self._connections.add(connection)
            probe = await connection.execute("exit 0", timeout=timeout)
            if probe["exit_code"] != 0:
                raise SSHAccessError("ssh/probe-failed", "SSH endpoint did not accept a shell probe")
            return connection
        except BaseException:
            if connection is not None:
                await connection.close()
            raise
        finally:
            self._scope.release()


class SSHConnection:
    def __init__(self, api, executable, host, user, port, identity, known):
        self._api, self._scope, self._processes = api, api._scope, api._processes
        self._closed, self._running = False, set()
        self._admission = asyncio.Lock()
        # user:“不要出错”+(完全禁用默认配置/agent/交互/转发及known_hosts自动写入；每次执行都重新验证明确文件)。
        self._base = [str(executable), "-F", "NUL", "-T", "-n", "-p", str(port), "-l", user, "-i", str(identity),
            "-o", 'UserKnownHostsFile="' + known.as_posix() + '"', "-o", "GlobalKnownHostsFile=NUL",
            "-o", "StrictHostKeyChecking=yes", "-o", "UpdateHostKeys=no", "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none", "-o", "PasswordAuthentication=no",
            "-o", "KbdInteractiveAuthentication=no", "-o", "PreferredAuthentications=publickey",
            "-o", "ControlMaster=no", "-o", "ControlPath=none", "-o", "ForwardAgent=no",
            "-o", "ClearAllForwardings=yes", "-o", "ConnectionAttempts=1"]
        self._host = host
        self._identity, self._known = identity, known

    async def execute(self, command, *, timeout=30, max_output_bytes=65536):
        self._scope.acquire()
        handle = None
        try:
            if self._closed:
                raise SSHAccessError("ssh/closed", "SSH connection configuration is closed")
            timeout = _timeout(timeout)
            # user:“完成真实接口、参数/错误、作用域、取消/清理”+(编码边界也属于命令准入，不能将UnicodeEncodeError暴露给插件)。
            try:
                valid = type(command) is str and bool(command.strip()) and "\x00" not in command and len(command.encode("utf8")) <= 8192
            except UnicodeError:
                valid = False
            if not valid:
                raise SSHAccessError("ssh/invalid-command", "Use nonempty remote shell text up to 8 KiB")
            # Recheck the original path authority before each independent SSH connection.
            self._api._fs.resolve(self._identity)
            self._api._fs.resolve(self._known)
            argv = self._base + ["-o", "ConnectTimeout=" + str(max(1, math.ceil(timeout))), "--", self._host, command]
            # user:“不要出错”+(关闭必须等待已准入但尚未拿到句柄的原进程启动，不能遗漏稍后出现的进程)。
            async with self._admission:
                if self._closed:
                    raise SSHAccessError("ssh/closed", "SSH connection configuration is closed")
                handle = await self._processes.spawn(argv, timeout=timeout, max_output_bytes=max_output_bytes)
                self._running.add(handle)
            result = await handle.wait()
            output = handle.read_output()
            if result.status == "timed_out":
                raise SSHAccessError("ssh/timeout", "SSH command exceeded its deadline; remote effects may already exist", may_have_changed=True)
            if result.exit_code == 255:
                raise SSHAccessError("ssh/transport-failed", "SSH transport/authentication/host verification failed, or remote command exited255", may_have_changed=True)
            return {"exit_code": result.exit_code, "status": result.status, "quiescent": result.quiescent,
                    "stdout": output.stdout, "stderr": output.stderr,
                    "stdout_lost": output.stdout_lost, "stderr_lost": output.stderr_lost,
                    "transport": "openssh", "remote_cleanup_guaranteed": False}
        finally:
            try:
                if handle is not None:
                    await handle.shutdown()
                    self._running.discard(handle)
            finally:
                self._scope.release()

    async def close(self):
        self._closed = True
        async def settle():
            async with self._admission:
                running = tuple(self._running)
            for handle in running:
                await handle.shutdown()
            self._api._connections.discard(self)
        await finish_on_cancel(settle(), name="plugin-ssh-close")
