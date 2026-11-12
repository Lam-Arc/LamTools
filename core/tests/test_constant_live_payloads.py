import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event

from lamtools_core.app import open_core_app_db
from lamtools_core.app.live_router import CoreLiveConnection, _snapshot_for_notification


# user:“调查并检修 constant 内 sunday 出现过的所有报错，整理并给出方案，然后修复，不要出错”+(实时版本通知只读元信息，不能再复制大段工具输出占满连接和发送队列；原始补拉内容须完整)。
@pytest.mark.asyncio
async def test_live_change_header_avoids_loading_entity_body(tmp_path):
    db = await open_core_app_db(tmp_path / 'core.db')
    statements = []
    try:
        async def seed(session):
            db.sync_journal.append(session, change_id='large-event', entity_type='thread.event',
                operation='upsert', entity_id='thread', thread_id='thread', revision=9,
                entity={'event': {'payload': 'x' * 4_500_000}})
        await db.persistence.write(seed)
        event.listen(db.engine.sync_engine, 'before_cursor_execute',
                     lambda conn, cursor, statement, params, context, many: statements.append(statement))
        header = await db.sync_journal.get_change_header('large-event')
        assert header['revision'] == 9
        assert header['thread_id'] == 'thread'
        assert len(json.dumps(header)) < 1500
        assert all('entity_json' not in s for s in statements)
        replay = await db.sync_journal.get_change('large-event')
        assert len(replay['entity']['event']['payload']) == 4_500_000
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_persisted_live_event_uses_header_lookup():
    header = {'change_id': 'e', 'thread_id': 't', 'revision': 8, 'entity_type': 'thread.event'}
    journal = SimpleNamespace(get_change_header=AsyncMock(return_value=header),
                              get_change=AsyncMock(side_effect=AssertionError('full journal read')))
    connection = CoreLiveConnection(SimpleNamespace(), context=SimpleNamespace(
        host=SimpleNamespace(sync_journal=journal)))
    connection.subscription = asyncio.Queue()
    await connection.subscription.put({'event_id': 'e', 'thread_id': 't', 'seq': 1,
        'method': 'session/updated', 'payload': {}, 'created_at': '2026-11-11T00:00:00Z'})
    task = asyncio.create_task(connection._hub_reader())
    try:
        outgoing = await asyncio.wait_for(connection._next_outbound(), 2)
        assert outgoing == {'method': 'sync/change', 'params': header}
        journal.get_change_header.assert_awaited_once_with('e')
        journal.get_change.assert_not_called()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_few_large_items_still_require_a_bounded_snapshot():
    snapshot = {'thread_id': 't', 'status': 'completed', 'turns': {}, 'items': {},
                'core': {'items': {}, 'item_order': [], 'turns': {}}}
    for i in range(8):
        iid, tid = f'i-{i}', f'turn-{i}'
        snapshot['core']['items'][iid] = {'item_id': iid, 'turn_id': tid, 'seq': i+1,
                                         'payload': {'content': 'x' * 600_000}}
        snapshot['core']['item_order'].append(iid)
        snapshot['turns'][tid] = {'turn_id': tid, 'items': [], 'seq': i+1, 'status': 'completed'}
        snapshot['core']['turns'][tid] = {'turn_id': tid, 'items': [iid], 'seq': i+1, 'status': 'completed'}
    page = _snapshot_for_notification(snapshot)
    assert len(json.dumps(page).encode()) < 4 * 1024 * 1024
    assert page.get('history_page')
    assert len(snapshot['core']['items']) == 8
