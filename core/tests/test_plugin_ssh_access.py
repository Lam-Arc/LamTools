"""user:“给我把 2 阶段做完，前端除外”+(用真实本地SSH服务验证原OpenSSH身份/主机校验、命令与取消)。"""
import asyncio
import subprocess
from contextlib import asynccontextmanager

import asyncssh
import pytest

from .test_plugin_working_directory import env


@asynccontextmanager
async def server(root):
    host = asyncssh.generate_private_key("ssh-ed25519")
    # user:“不要修改用户密钥”+(只在测试临时目录生成独立身份，使用原OpenSSH生成正确的Windows私钥权限)。
    await asyncio.to_thread(subprocess.run, ["ssh-keygen.exe", "-q", "-t", "ed25519", "-N", "", "-f", str(root / "identity")],
                            capture_output=True, check=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    key = asyncssh.import_private_key((root / "identity").read_bytes())
    public = key.convert_to_public()
    entered = asyncio.Event()
    class Server(asyncssh.SSHServer):
        def begin_auth(self, username):
            return True
        def public_key_auth_supported(self):
            return True
        def validate_public_key(self, username, offered):
            return username == "test" and offered == public
    async def execute(process):
        if process.command == "wait-for-close":
            entered.set()
            await process.wait_closed()
            return
        proc = await asyncio.to_thread(subprocess.run, process.command, shell=True, capture_output=True,
                                       timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        process.stdout.write(proc.stdout.decode())
        process.stderr.write(proc.stderr.decode())
        process.exit(proc.returncode)
    listener = await asyncssh.create_server(Server, "127.0.0.1", 0, server_host_keys=[host], process_factory=execute,
                                           rdns_lookup=False, config=None, gss_host=None, gss_auth=False, gss_kex=False)
    port = listener.get_port()
    (root / "known_hosts").write_bytes(f"[127.0.0.1]:{port} ".encode()+host.export_public_key())
    try:
        yield port, entered
    finally:
        listener.close()
        await listener.wait_closed()


async def connect(ctx, port):
    return await ctx.ssh.connect(host="127.0.0.1", port=port, user="test", identity_file="identity", known_hosts="known_hosts", timeout=10)


@pytest.mark.asyncio
async def test_real_ssh_authenticates_pinned_host_and_runs_remote_shell(env):
    ctx, _, _, root = env
    async with server(root) as (port, _):
        connection = await connect(ctx, port)
        result = await connection.execute("echo sunday-ssh-executed", timeout=10)
        assert result["exit_code"] == 0 and result["quiescent"]
        assert b"sunday-ssh-executed" in result["stdout"]
        await connection.close()
        from lamtools_core.plugin_system.ssh_access import SSHAccessError
        with pytest.raises(SSHAccessError) as error:
            await connection.execute("echo later", timeout=10)
        assert error.value.code == "ssh/closed"


@pytest.mark.asyncio
async def test_invalid_unicode_command_is_rejected_before_spawn_and_connection_remains_usable(env,monkeypatch):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(无效Unicode须在传输前拒绝，不泄漏编码错误且不破坏已打开配置)。
    from lamtools_core.plugin_system.ssh_access import SSHAccessError
    ctx, _, _, root = env
    async with server(root) as (port, _):
        connection = await connect(ctx, port)
        original = connection._processes.spawn
        calls = []
        async def observed(*args, **kwargs):
            calls.append(args)
            return await original(*args, **kwargs)
        monkeypatch.setattr(connection._processes,"spawn",observed)
        with pytest.raises(SSHAccessError) as error:
            await connection.execute("echo \ud800")
        assert error.value.code == "ssh/invalid-command" and not calls
        assert not connection._running
        result = await connection.execute("echo valid-after-rejection",timeout=10)
        assert result["exit_code"] == 0 and b"valid-after-rejection" in result["stdout"]
        await connection.close()


@pytest.mark.asyncio
async def test_host_key_mismatch_fails_without_touching_user_ssh_files(env):
    from lamtools_core.plugin_system.ssh_access import SSHAccessError
    ctx, _, _, root = env
    async with server(root) as (port, _):
        wrong = asyncssh.generate_private_key("ssh-ed25519")
        original_identity = (root / "identity").read_bytes()
        (root / "known_hosts").write_bytes(f"[127.0.0.1]:{port} ".encode()+wrong.export_public_key())
        before = (root / "known_hosts").read_bytes()
        with pytest.raises(SSHAccessError) as error:
            await connect(ctx, port)
        assert error.value.code == "ssh/transport-failed"
        assert (root / "known_hosts").read_bytes() == before
        assert (root / "identity").read_bytes() == original_identity


@pytest.mark.asyncio
async def test_cancel_owned_ssh_process_and_connection_close_joins(env):
    ctx, _, _, root = env
    async with server(root) as (port, entered):
        connection = await connect(ctx, port)
        task = asyncio.create_task(connection.execute("wait-for-close", timeout=30))
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not connection._running
        await connection.close()


@pytest.mark.asyncio
async def test_invalid_host_paths_and_revoked_scope_do_not_start_transport(env):
    from lamtools_core.plugin_system.ssh_access import SSHAccessError
    from lamtools_core.plugin_system.services import ServiceError
    ctx, _, _, _ = env
    api = ctx.ssh
    for host in ["-oProxyCommand=bad", "host with spaces", "user@host"]:
        with pytest.raises(SSHAccessError):
            await api.connect(host=host, port=22, user="test", identity_file="../key", known_hosts="hosts")
    await ctx._registration_scope.dispose()
    with pytest.raises(ServiceError):
        await api.connect(host="127.0.0.1", port=22, user="test", identity_file="identity", known_hosts="known_hosts")


@pytest.mark.asyncio
async def test_close_waits_for_admitted_spawn_before_returning(env, monkeypatch):
    ctx, _, _, root = env
    async with server(root) as (port, _):
        connection = await connect(ctx, port)
        entered, release = asyncio.Event(), asyncio.Event()
        original = connection._processes.spawn
        async def delayed(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)
        monkeypatch.setattr(connection._processes, "spawn", delayed)
        execute = asyncio.create_task(connection.execute("echo admitted", timeout=10))
        await asyncio.wait_for(entered.wait(), 3)
        close = asyncio.create_task(connection.close())
        done, _ = await asyncio.wait({close}, timeout=0.05)
        release.set()
        results = await asyncio.gather(execute, close, return_exceptions=True)
        assert not done, "close returned before the admitted process spawn could settle"
        assert not connection._running and results[1] is None
