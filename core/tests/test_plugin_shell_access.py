"""user:“继续，把 2 阶段都做完”+(shell 与环境贡献必须真实执行、随启动代撤回，不伪装为沙箱或持久终端)。"""
import asyncio
import os

import pytest

from lamtools_core.plugin_system import PluginContext
from lamtools_core.plugin_system.services import ServiceError


def context(tmp_path, services=None, owner="caller"):
    ctx = PluginContext(tmp_path, data_dir=tmp_path / "data", services=services if services is not None else {})
    ctx._begin_registration_scope(owner, 1)
    return ctx


@pytest.mark.asyncio
async def test_environment_contributors_publish_collect_and_revoke(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    seen = []
    def resolve(execution):
        seen.append(execution.session_id)
        return {"SUNDAY_REGION": "east"}
    remove = ctx.shell_env.register("region", {"SUNDAY_REGION": "Deployment region"}, resolve)
    assert ctx.shell_env.list() == ()  # start is not ready
    ctx._registration_scope.publish(set())
    assert ctx.shell_env.list()[0].variables == (("SUNDAY_REGION", "Deployment region"),)
    assert seen == []
    monkeypatch.setenv("SUNDAY_REGION", "untrusted")
    values = await ctx.shell_env.collect(session_id="session")
    assert values["SUNDAY_REGION"] == "east"
    assert values["SUNDAY_SESSION_ID"] == "session"
    assert values["SUNDAY_HOME"] == str(tmp_path / "data")
    with pytest.raises(TypeError):
        values["SUNDAY_REGION"] = "changed"
    assert os.environ["SUNDAY_REGION"] == "untrusted"
    remove()
    assert "SUNDAY_REGION" not in await ctx.shell_env.collect()
    api = ctx.shell_env
    await ctx._registration_scope.dispose()
    with pytest.raises(ServiceError):
        await api.collect()


@pytest.mark.asyncio
async def test_environment_conflicts_reserved_keys_and_invalid_runtime_values(tmp_path):
    ctx = context(tmp_path)
    try:
        from lamtools_core.plugin_system.shell_access import ShellAccessError
        with pytest.raises(ShellAccessError):
            ctx.shell_env.register("bad", {"SUNDAY_HOME": "home"}, lambda _: {})
        ctx.shell_env.register("region", {"SUNDAY_REGION": "region"}, lambda _: {"SUNDAY_OTHER": "x"})
        with pytest.raises(ShellAccessError):
            ctx.shell_env.register("other", {"SUNDAY_REGION": "duplicate"}, lambda _: {})
        ctx._registration_scope.publish(set())
        with pytest.raises(ShellAccessError) as error:
            await ctx.shell_env.collect()
        assert error.value.code == "shell/invalid-contribution"
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_shell_real_powershell_cwd_environment_exit_and_owned_output(tmp_path):
    ctx = context(tmp_path)
    ctx.shell_env.register("region", {"SUNDAY_REGION": "region"}, lambda _: {"SUNDAY_REGION": "east"})
    ctx._registration_scope.publish(set())
    try:
        shell = ctx.shell
        spec = shell.resolve('[Console]::Out.Write($env:SUNDAY_REGION + "|" + (Get-Location).Path); exit 7', timeout=10)
        handle = await shell.execute(spec)
        result = await handle.result()
        assert result.outcome.exit_code == 7
        assert result.outcome.quiescent
        assert result.output.stdout.decode("utf-8") == "east|" + str(tmp_path)
        assert handle.read_output().stdout == result.output.stdout
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_shell_timeout_and_dispose_reclaim_background_execution(tmp_path):
    ctx = context(tmp_path)
    try:
        shell = ctx.shell
        timed = await shell.execute(shell.resolve("Start-Sleep -Seconds 20", timeout=0.2))
        assert (await timed.result()).outcome.status == "timed_out"
        running = await shell.execute(shell.resolve("Start-Sleep -Seconds 20", timeout=30))
        await ctx._registration_scope.dispose()
        assert not running._handle._process.poll() is None
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_environment_collection_cancellation_drains_provider_lease(tmp_path):
    ctx = context(tmp_path)
    entered = asyncio.Event()
    finished = asyncio.Event()
    async def resolve(execution):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()
    ctx.shell_env.register("region", {"SUNDAY_REGION": "region"}, resolve)
    ctx._registration_scope.publish(set())
    task = asyncio.create_task(ctx.shell_env.collect())
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()
    await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_spec_owner_tampering_and_reserved_environment_rejected(tmp_path):
    from dataclasses import replace
    from lamtools_core.plugin_system.shell_access import ShellAccessError
    ctx = context(tmp_path)
    other = context(tmp_path, owner="other")
    try:
        spec = ctx.shell.resolve("exit 0", timeout=10)
        with pytest.raises(ShellAccessError):
            await other.shell.execute(spec)
        with pytest.raises(ShellAccessError):
            await ctx.shell.execute(replace(spec, timeout=float("nan")))
        with pytest.raises(ShellAccessError):
            ctx.shell.resolve("exit 0", timeout=10, env={"SUNDAY_HOME": "forged"})
    finally:
        await ctx._registration_scope.dispose()
        await other._registration_scope.dispose()


@pytest.mark.asyncio
async def test_contributors_are_shared_and_revocation_during_collection_discards_value(tmp_path):
    services = {}
    caller = context(tmp_path, services)
    provider = context(tmp_path, services, "provider")
    started, release = asyncio.Event(), asyncio.Event()
    async def resolve(execution):
        started.set()
        await release.wait()
        return {"SUNDAY_REGION": "late"}
    remove = provider.shell_env.register("region", {"SUNDAY_REGION": "region"}, resolve)
    provider._registration_scope.publish(set())
    task = asyncio.create_task(caller.shell_env.collect())
    await asyncio.wait_for(started.wait(), 3)
    remove()
    release.set()
    try:
        from lamtools_core.plugin_system.shell_access import ShellAccessError
        with pytest.raises(ShellAccessError) as error:
            await task
        assert error.value.code == "shell/contributor-revoked"
        assert caller.shell_env.list() == ()
    finally:
        await caller._registration_scope.dispose()
        await provider._registration_scope.dispose()


@pytest.mark.asyncio
async def test_shell_capture_reports_truncated_tail_and_explicit_kill(tmp_path):
    ctx = context(tmp_path)
    try:
        handle = await ctx.shell.execute(ctx.shell.resolve('[Console]::Out.Write("x" * 4096)', timeout=10, max_output_bytes=32))
        result = await handle.result()
        assert result.output.stdout == b"x" * 32
        assert result.output.stdout_lost
        handle = await ctx.shell.execute(ctx.shell.resolve("Start-Sleep -Seconds 20", timeout=30))
        assert (await handle.kill()).quiescent
        assert (await handle.result()).outcome.status == "stopped"
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_cancelled_shell_observer_keeps_owned_execution_until_explicit_kill(tmp_path):
    ctx = context(tmp_path)
    try:
        handle = await ctx.shell.execute(ctx.shell.resolve("Start-Sleep -Seconds 20", timeout=30))
        waiter = asyncio.create_task(handle.result())
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert handle._handle._process.poll() is None
        assert (await handle.kill()).quiescent
    finally:
        await ctx._registration_scope.dispose()

