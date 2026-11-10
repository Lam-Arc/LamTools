"""user:“完成真实接口、参数/错误、作用域、取消/清理”+(市场条目读取在撤回或取消时不发布旧结果并等待读取结算)。"""
import asyncio
import threading
import pytest
from .test_plugin_market_readonly_remote import market_env

@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['cancel', 'scope', 'catalog'])
async def test_entry_waits_for_native_read_and_rejects_changed_scope(market_env, monkeypatch, reason):
    from lamtools_core.plugin_system import market
    from lamtools_core.app.operation_catalog import OperationCatalog
    ctx, _, _, data = market_env
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    def gated():
        entered.set()
        release.wait()
        try: return market.validate_catalog(data)
        finally: done.set()
    monkeypatch.setattr(market, 'load_catalog', gated)
    task = asyncio.create_task(ctx.plugin_market.entry('qq-bot'))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        if reason == 'cancel':
            task.cancel()
            await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        elif reason == 'scope':
            ctx._registration_scope.revoke()
        else:
            ctx.operation_catalog = OperationCatalog()
        release.set()
        with pytest.raises(asyncio.CancelledError if reason == 'cancel' else RuntimeError):
            await task
        assert done.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
