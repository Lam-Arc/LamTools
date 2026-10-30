"""user:“给我把 2 阶段做完，前端除外”+(授权仅凭真实凭据提交成功，撤回/取消排空提供方，不能把问答当授权)。"""
import asyncio

import pytest

from lamtools_core.plugin_system import PluginContext
from lamtools_core.plugin_system.secrets import PluginSecretStore


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
