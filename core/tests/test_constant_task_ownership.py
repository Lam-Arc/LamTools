import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lamtools_core.runtime import RuntimeTaskRegistry


# user:“调查并检修 constant 内 sunday 出现过的所有报错，整理并给出方案，然后修复，不要出错”+(后台回合登记表必须回收失败结果并保留异常链，不能留下无人接收的任务异常)。
@pytest.mark.asyncio
async def test_registered_turn_failure_is_observed_even_after_claim_release(caplog):
    registry = RuntimeTaskRegistry(background_process_registry=SimpleNamespace(cleanup_session=Mock()))
    async def fail():
        raise RuntimeError('durable terminal write failed')
    task = asyncio.create_task(fail())
    assert registry.register('thread', task, run_id='run', turn_id='turn')
    registry.release_run('thread', run_id='run')
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert task.done()
    assert not task._log_traceback
    assert any('durable terminal write failed' in r.getMessage() and r.exc_info for r in caplog.records)
