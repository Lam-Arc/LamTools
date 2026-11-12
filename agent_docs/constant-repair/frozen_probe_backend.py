"""Acceptance-only plugin, loaded inside the newly frozen backend."""
import json
import logging
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler


# user:“调查并检修 constant 内 sunday 出现过的所有报错，整理并给出方案，然后修复，不要出错”+(在真实冻结后端里验证修复机制，不用开发环境的导入成功冒充安装包可用)。
class Probe:
    async def start(self, context):
        import requests
        from lamtools_core.app import AppEventInput, OperationCatalog, open_core_app_db
        from lamtools_core.app.live_operations import CoreLiveContext, reconcile_terminal_turns
        from lamtools_core.app.live_hub import CoreAppEventHub
        from lamtools_core.app.queue_state import latest_active_turn_id
        from lamtools_core.event import RunItemEvent
        from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState
        import lamtools_core.logging_setup as setup
        import lamtools_core.app.event_store as events
        import lamtools_core.app.sync_store as sync
        from lamtools_core.app.live_router import _snapshot_for_notification

        report = Path(os.environ['CONSTANT_REPAIR_PROBE_REPORT'])
        with requests.Session():
            pass
        assert any(isinstance(h, RotatingFileHandler) and h.maxBytes == 16 * 1024 * 1024
                   for h in logging.getLogger().handlers)
        db = await open_core_app_db(report.parent / 'probe.db')
        try:
            store = InMemoryRuntimeStateStore()
            live = CoreLiveContext(operations=OperationCatalog(), session_factory=db.session_factory,
                                  persistence=db.persistence, runtime_state_store=store, hub=CoreAppEventHub())
            for thread in ('a', 'b'):
                turn = thread + ':turn:shared'
                async def seed(session):
                    await db.persistence.append(session, AppEventInput(thread_id=thread, turn_id=turn,
                        method='turn/accepted', payload={'status': 'running', 'run_id': 'shared'}))
                    await db.persistence.append_run_item(session, RunItemEvent(kind='status', thread_id=thread,
                        turn_id=turn, run_id='shared', item_id=turn + ':running', status='running',
                        payload={'type': 'turn', 'status': 'running'}))
                await db.persistence.write(seed)
                await store.save(RuntimeState(session_id=thread, run_id='shared', status='cancelled',
                                              metadata={'turn_id': turn}))
            assert await reconcile_terminal_turns(context=live) == 2
            assert await reconcile_terminal_turns(context=live) == 0
            for thread in ('a', 'b'):
                async with db.session_factory() as session:
                    assert latest_active_turn_id(await db.persistence.load(session, thread)) is None
            async def large(session):
                db.sync_journal.append(session, change_id='probe-large', entity_type='thread.event',
                    operation='upsert', entity_id='a', thread_id='a', revision=9,
                    entity={'event': {'payload': 'x' * 4_500_000}})
            await db.persistence.write(large)
            header = await db.sync_journal.get_change_header('probe-large')
            assert header['revision'] == 9 and len(json.dumps(header)) < 1500
            assert len((await db.sync_journal.get_change('probe-large'))['entity']['event']['payload']) == 4_500_000
        finally:
            await db.close()
        report.write_text(json.dumps({'ok': True, 'requests_version': requests.__version__,
            'checks': ['requests import/session', 'rotating log handler', 'cross-thread terminal isolation',
                       'idempotent reconciliation', 'small live change header', 'complete historical replay'],
            'origins': {m.__name__: m.__file__ for m in (setup, events, sync)}}, indent=2), encoding='utf-8')


def create_plugin(context):
    return Probe()
