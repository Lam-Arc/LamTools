"""Cross-thread execution IDs must not alias terminal events."""
import pytest

from lamtools_core.app import AppEventInput, OperationCatalog, open_core_app_db
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.live_operations import CoreLiveContext, reconcile_terminal_turns
from lamtools_core.app.queue_state import latest_active_turn_id
from lamtools_core.event import RunItemEvent
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState


# user:“调查并检修 constant 内 sunday 出现过的所有报错，整理并给出方案，然后修复，不要出错”+(相同执行编号的不同会话必须各自结束，重复巡检不得反复写入)。
@pytest.mark.asyncio
async def test_shared_execution_id_reconciles_both_threads_once(tmp_path):
    db = await open_core_app_db(tmp_path / 'core.db')
    store = InMemoryRuntimeStateStore()
    context = CoreLiveContext(operations=OperationCatalog(), session_factory=db.session_factory,
                              persistence=db.persistence, runtime_state_store=store, hub=CoreAppEventHub())
    try:
        for thread in ('schedule-a', 'schedule-b'):
            turn = thread + ':turn:shared-occurrence'
            async def seed(session):
                await db.persistence.append(session, AppEventInput(
                    thread_id=thread, turn_id=turn, method='turn/accepted',
                    payload={'status': 'running', 'run_id': 'shared-occurrence'}))
                await db.persistence.append_run_item(session, RunItemEvent(
                    thread_id=thread, turn_id=turn, run_id='shared-occurrence',
                    kind='status', item_id=turn + ':running', status='running',
                    payload={'type': 'turn', 'status': 'running'}))
            await db.persistence.write(seed)
            await store.save(RuntimeState(session_id=thread, run_id='shared-occurrence',
                status='cancelled', metadata={'turn_id': turn}))
        assert await reconcile_terminal_turns(context=context) == 2
        for thread in ('schedule-a', 'schedule-b'):
            async with db.session_factory() as session:
                snapshot = await db.persistence.load(session, thread)
            assert latest_active_turn_id(snapshot) is None, thread
            assert snapshot['core']['turns'][thread + ':turn:shared-occurrence']['status'] == 'cancelled'
        assert await reconcile_terminal_turns(context=context) == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_event_collision_never_returns_another_threads_event(tmp_path):
    db = await open_core_app_db(tmp_path / 'core.db')
    try:
        async def write(session):
            first = await db.event_store.append(session, AppEventInput(
                thread_id='a', event_id='shared-event', method='session/updated'))
            again = await db.event_store.append(session, AppEventInput(
                thread_id='a', event_id='shared-event', method='session/updated'))
            assert again == first
        await db.persistence.write(write)
        async def collide(session):
            return await db.event_store.append(session, AppEventInput(
                thread_id='b', event_id='shared-event', method='session/updated'))
        with pytest.raises(ValueError, match='another thread'):
            await db.persistence.write(collide)
    finally:
        await db.close()
