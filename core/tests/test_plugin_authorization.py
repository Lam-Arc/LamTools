"""user:“给我把 2 阶段做完，前端除外”+(授权仅凭真实凭据提交成功，撤回/取消排空提供方，不能把问答当授权)。"""
import asyncio

import pytest

from lamtools_core.plugin_system import PluginContext
from lamtools_core.plugin_system.secrets import PluginSecretStore


@pytest.mark.asyncio
async def test_cancelled_controller_does_not_disable_next_attempt(views):
    # user:“复用原宿主权威”+(仅关闭已取消的尝试，同一受管流下一次正常提交仍可成功)。
    from lamtools_core.plugin_system.authorization_access import AuthorizationError
    provider, requester = views
    entered = asyncio.Event()
    attempts = []
    async def run(control):
        attempts.append(control)
        if len(attempts) == 1:
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                control.commit("late")
        else:
            control.commit("fresh")
    provider.authorization.register_flow("retry",label="Retry",methods=["key"],credential="RETRY_KEY",run=run)
    provider._registration_scope.publish(set())
    task = asyncio.create_task(requester.authorization.begin("retry",method="key",timeout=3))
    try:
        await asyncio.wait_for(entered.wait(),3)
        provider.authorization.cancel("retry")
        with pytest.raises(AuthorizationError):
            await task
        result = await requester.authorization.begin("retry",method="key",timeout=3)
        assert result["status"] == "authorized"
        assert provider.credentials.resolve("RETRY_KEY").value == "fresh"
        with pytest.raises(AuthorizationError) as error:
            attempts[0].commit("stale")
        assert error.value.code == "authorization/closed"
        assert provider.credentials.resolve("RETRY_KEY").value == "fresh"
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        await requester._registration_scope.dispose()
        await provider._registration_scope.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation",["commit","prompt","notify"])
@pytest.mark.parametrize("withdrawal",["flow","requester","cancel","timeout","caller"])
async def test_withdrawn_flow_cannot_commit_when_provider_catches_cancellation(views,operation,withdrawal):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(单独撤回授权流后，提供方即使处理取消也不能再提交凭据)。
    from lamtools_core.plugin_system.authorization_access import AuthorizationError
    provider, requester = views
    entered = asyncio.Event()
    interactions = []
    async def run(control):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if operation == "commit":
                control.commit("late-secret")
            else:
                await getattr(control,operation)({"message":"late-interaction"})
    withdraw = provider.authorization.register_flow("retire",label="Retire",methods=["key"],credential="RETIRED_KEY",run=run)
    provider._registration_scope.publish(set())
    task = asyncio.create_task(requester.authorization.begin("retire",method="key",timeout=0.1 if withdrawal == "timeout" else 3,
        prompt=lambda value: interactions.append(value),notify=lambda value: interactions.append(value)))
    try:
        await asyncio.wait_for(entered.wait(),3)
        if withdrawal in {"flow","cancel"}:
            if withdrawal == "flow":
                withdraw()
            else:
                provider.authorization.cancel("retire")
            with pytest.raises(AuthorizationError) as error:
                await task
            assert error.value.code == "authorization/closed"
        elif withdrawal == "requester":
            await asyncio.wait_for(requester._registration_scope.dispose(),3)
            assert (await task)["status"] == "cancelled"
        elif withdrawal == "timeout":
            with pytest.raises(AuthorizationError) as error:
                await task
            assert error.value.code == "authorization/timeout"
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert provider.credentials.resolve("RETIRED_KEY") is None
        assert not interactions
        assert provider._registration_scope.accepting
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        await requester._registration_scope.dispose()
        await provider._registration_scope.dispose()


@pytest.fixture
def views(tmp_path):
    provider = PluginContext(tmp_path, _secret_store=PluginSecretStore(tmp_path / "secrets"))
    provider._begin_registration_scope("provider", 1)
    requester = provider.for_work_root(tmp_path)
    requester._registration_scope = None
    requester._begin_registration_scope("requester", 1)
    return provider, requester


@pytest.mark.asyncio
async def test_authorized_requires_real_provider_owned_credential_commit(views):
    from lamtools_core.plugin_system.authorization_access import AuthorizationError
    provider, requester = views
    async def run(control):
        control.commit("actual-secret")
    provider.authorization.register_flow("connect", label="Connect", methods=["key"], credential="API_KEY", run=run)
    provider._registration_scope.publish(set())
    assert requester.authorization.list()[0]["key"] == "connect"
    result = await requester.authorization.begin("connect", method="key", timeout=3)
    assert result["status"] == "authorized" and "actual-secret" not in str(result)
    assert provider.credentials.resolve("API_KEY").value == "actual-secret"
    assert requester.credentials.resolve("API_KEY") is None
    async def no_commit(control):
        return "authorized"
    provider.authorization.register_flow("false", label="False", methods=["key"], credential="OTHER", run=no_commit)
    with pytest.raises(AuthorizationError) as error:
        await requester.authorization.begin("false", method="key", timeout=3)
    assert error.value.code == "authorization/not-committed"
    await provider._registration_scope.dispose()
    await requester._registration_scope.dispose()


@pytest.mark.asyncio
async def test_withdrawal_cancels_provider_and_joins_before_unload(views):
    provider, requester = views
    entered, finished = asyncio.Event(), asyncio.Event()
    async def run(control):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()
    provider.authorization.register_flow("connect", label="Connect", methods=["key"], credential="API_KEY", run=run)
    provider._registration_scope.publish(set())
    task = asyncio.create_task(requester.authorization.begin("connect", method="key", timeout=3))
    await asyncio.wait_for(entered.wait(), 3)
    await asyncio.wait_for(provider._registration_scope.dispose(), 3)
    assert (await task)["status"] == "cancelled" and finished.is_set()
    assert requester.authorization.list() == []
    await requester._registration_scope.dispose()


@pytest.mark.asyncio
async def test_concurrent_attempt_and_caller_cancellation_are_owned(views):
    from lamtools_core.plugin_system.authorization_access import AuthorizationError
    provider, requester = views
    entered, finished = asyncio.Event(), asyncio.Event()
    async def run(control):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()
    provider.authorization.register_flow("connect", label="Connect", methods=["key"], credential="API_KEY", run=run)
    provider._registration_scope.publish(set())
    task = asyncio.create_task(requester.authorization.begin("connect", method="key", timeout=3))
    await asyncio.wait_for(entered.wait(), 3)
    with pytest.raises(AuthorizationError) as error:
        await requester.authorization.begin("connect", method="key", timeout=3)
    assert error.value.code == "authorization/busy"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()
    await provider._registration_scope.dispose()
    await requester._registration_scope.dispose()


@pytest.mark.asyncio
async def test_requester_unload_cancels_attempt_without_waiting_for_deadline(views):
    # user:“审查当前代码，然后继续”+(停用发起方也必须取消授权，不能等到300秒期限)。
    provider, requester = views
    entered, finished = asyncio.Event(), asyncio.Event()
    async def run(control):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()
    provider.authorization.register_flow("connect", label="Connect", methods=["key"], credential="API_KEY", run=run)
    provider._registration_scope.publish(set())
    task = asyncio.create_task(requester.authorization.begin("connect", method="key", timeout=300))
    await asyncio.wait_for(entered.wait(), 3)
    try:
        await asyncio.wait_for(requester._registration_scope.dispose(), 1)
        assert (await task)["status"] == "cancelled" and finished.is_set()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await provider._registration_scope.dispose()
        await requester._registration_scope.dispose()
