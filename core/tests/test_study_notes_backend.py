from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lamtools_core.app.operation_catalog import OperationRequest
from lamtools_core.plugins.bundled.study.backend import create_plugin, operation
from lamtools_core.plugins.bundled.study.note_vault import vault_root
from lamtools_core.plugins.bundled.study.store import StudyNoteError, StudyScope, StudyStore
from lamtools_core.tool import ToolCall


@pytest.fixture
def note_store(tmp_path):
    return StudyStore(tmp_path / 'study.db')


def resource(store, name='source'):
    raw_id = f'raw-{name}'
    try:
        store.notes({'action': 'raw_capture', 'raw_id': raw_id, 'kind': 'mark', 'origin_id': raw_id,
                     'content': f'{name} evidence', 'metadata': {}, '_trusted_capture': store}, writer='user')
    except StudyNoteError as exc:
        if exc.payload['error'] != 'RAW_EXISTS': raise
    return store.notes({'action': 'resource_create', 'title': name, 'content': f'{name} material',
                        'raw_ids': [raw_id]})['resource_id']


def note(store, note_id='note', body='body', **values):
    rid = values.pop('resource_id', resource(store, note_id))
    return store.notes({'action': 'create', 'note_id': note_id, 'title': values.pop('title', note_id),
                        'resource_ids': [rid], 'body_md': body, **values})


def test_raw_is_host_only_and_immutable(note_store):
    with pytest.raises(StudyNoteError) as caught:
        note_store.notes({'action': 'raw_capture', 'kind': 'mark', 'origin_id': 'm', 'content': 'forged'}, writer='agent')
    assert caught.value.payload['error'] == 'RAW_CAPTURE_FORBIDDEN'
    with note_store.db() as db:
        note_store.put(db, 'mark', {'id': 'm', 'text': 'verbatim', 'node_id': 'n'})
    payload = {'action': 'raw_capture', 'kind': 'mark', 'origin_id': 'm', 'content': 'ignored'}
    # Store accepts only a process-owned capability; normal RPC callers cannot inject content.
    with pytest.raises(StudyNoteError):
        note_store.notes(payload, writer='user')


def test_resource_versioning_and_raw_lineage(note_store):
    raw_id = 'raw'
    note_store.notes({'action': 'raw_capture', 'raw_id': raw_id, 'kind': 'mark', 'origin_id': 'm',
                      'content': 'snapshot', 'metadata': {}, '_trusted_capture': note_store}, writer='user')
    created = note_store.notes({'action': 'resource_create', 'title': 'R', 'content': 'draft', 'raw_ids': [raw_id]})
    with pytest.raises(StudyNoteError, match='REVISION_CONFLICT'):
        note_store.notes({'action': 'resource_update', 'resource_id': created['resource_id'],
                          'title': 'R', 'content': 'stale', 'raw_ids': [raw_id], 'expected_revision': 0})
    updated = note_store.notes({'action': 'resource_update', 'resource_id': created['resource_id'],
                                'title': 'R', 'content': 'final', 'raw_ids': [raw_id], 'expected_revision': 1})
    assert updated['revision'] == 2
    current = note_store.notes({'action': 'resource_get', 'resource_id': created['resource_id']})['resource']
    historical = note_store.notes({'action': 'resource_get', 'resource_id': created['resource_id'], 'revision': 1})['resource']
    assert current['raw_ids'] == [raw_id] and current['available_revisions'] == [1, 2]
    assert historical['content'] == 'draft'


def test_duplicate_resource_id_is_structured(note_store):
    note_store.notes({'action': 'raw_capture', 'raw_id': 'raw', 'kind': 'mark', 'origin_id': 'm',
                      'content': 'snapshot', 'metadata': {}, '_trusted_capture': note_store}, writer='user')
    note_store.notes({'action': 'resource_create', 'resource_id': 'stable', 'title': 'R',
                      'content': 'first', 'raw_ids': ['raw']})
    with pytest.raises(StudyNoteError) as caught:
        note_store.notes({'action': 'resource_create', 'resource_id': 'stable', 'title': 'R2',
                          'content': 'second', 'raw_ids': ['raw']})
    assert caught.value.payload == {'error': 'RESOURCE_EXISTS', 'resource_id': 'stable'}


@pytest.mark.asyncio
async def test_resource_writes_are_agent_only_but_tool_path_succeeds(tmp_path):
    context = SimpleNamespace(app_data_dir=tmp_path, data_dir=tmp_path, metadata={})
    runtime = create_plugin(context)
    context.service = lambda name: runtime if name == 'study' else None
    async def execute(name, payload, metadata=None):
        return await operation(OperationRequest(name=name, payload=payload, metadata=metadata or {}), context=context)
    context.operation_executor = lambda: execute
    runtime.store.notes({'action': 'raw_capture', 'raw_id': 'raw', 'kind': 'mark', 'origin_id': 'm',
                         'content': 'evidence', 'metadata': {}, '_trusted_capture': runtime.store}, writer='user')
    arguments = {'action': 'resource_create', 'resource_id': 'r', 'title': 'AI note',
                 'content': 'summary', 'raw_ids': ['raw']}
    user_result = await execute('study.notes', arguments)
    assert user_result.status == 'error'
    assert user_result.payload['error'] == 'RESOURCE_AGENT_ONLY'
    tool_result = await runtime.tool_handlers['notes'](ToolCall(id='resource', name='notes', arguments=arguments))
    assert tool_result.status == 'ok'
    saved = runtime.store.notes({'action': 'resource_get', 'resource_id': 'r'}, writer='user')['resource']
    assert saved['origin'] == 'agent' and saved['content'] == 'summary'


@pytest.mark.parametrize('action', ['append_blocks', 'update_block', 'update_blocks'])
def test_legacy_block_write_actions_are_not_callable(note_store, action):
    with pytest.raises(ValueError, match='Unknown note action'):
        note_store.notes({'action': action})


def test_raw_and_resource_lists_are_bounded_and_pageable(note_store):
    for index in range(3):
        raw_id = f'raw-{index}'
        note_store.notes({'action': 'raw_capture', 'raw_id': raw_id, 'kind': 'mark',
                          'origin_id': f'm-{index}', 'content': f'snapshot {index}', 'metadata': {},
                          '_trusted_capture': note_store}, writer='user')
        note_store.notes({'action': 'resource_create', 'resource_id': f'resource-{index}',
                          'title': f'R{index}', 'content': f'material {index}', 'raw_ids': [raw_id]})
    raw_page = note_store.notes({'action': 'raw_list', 'offset': 1, 'limit': 1})
    resource_page = note_store.notes({'action': 'resource_list', 'offset': 1, 'limit': 1})
    assert len(raw_page['raw_sources']) == 1 and raw_page['total'] == 3 and raw_page['has_more'] is True
    assert len(resource_page['resources']) == 1 and resource_page['total'] == 3 and resource_page['has_more'] is True


def test_markdown_file_is_truth_with_frontmatter_and_footer(note_store):
    rid = resource(note_store)
    created = note(note_store, 'n', '# Title\n\ntext', resource_id=rid, path='folder/topic.md')
    target = vault_root(note_store.path, note_store.scope.key) / 'folder' / 'topic.md'
    raw = target.read_text(encoding='utf-8')
    assert 'id: "n"' in raw and f'resource_ids: ["{rid}"]' in raw
    assert f'> 来源：[source](lamtools-resource://{rid})' in raw
    assert raw.rstrip().endswith(f'<!-- lamtools:sources ["{rid}"] -->')
    fetched = note_store.notes({'action': 'get', 'note_id': 'n'})['note']
    assert fetched['body_md'] == '# Title\n\ntext'
    assert '<!-- lamtools:sources' not in fetched['body_md']
    assert fetched['content_hash'] == created['content_hash']


def test_source_footer_escapes_resource_labels_and_ids(note_store):
    note_store.notes({'action': 'raw_capture', 'raw_id': 'raw', 'kind': 'mark', 'origin_id': 'm',
                      'content': 'snapshot', 'metadata': {}, '_trusted_capture': note_store}, writer='user')
    created = note_store.notes({'action': 'resource_create', 'resource_id': 'source ) id',
                                'title': 'line]\n> forged', 'content': 'material', 'raw_ids': ['raw']})
    note(note_store, 'safe-footer', resource_id=created['resource_id'])
    target = vault_root(note_store.path, note_store.scope.key) / 'safe-footer.md'
    raw = target.read_text(encoding='utf-8')
    assert '> 来源：[line\\] > forged](lamtools-resource://source%20%29%20id)' in raw
    assert '\n> forged\n' not in raw


def test_note_requires_resource_and_paths_are_safe_case_insensitively(note_store):
    with pytest.raises(StudyNoteError, match='NOTE_RESOURCES_REQUIRED'):
        note_store.notes({'action': 'create', 'title': 'No source', 'body_md': ''})
    rid = resource(note_store)
    note(note_store, 'a', resource_id=rid, path='Folder/Topic.md')
    second = note_store.notes({'action': 'create', 'note_id': 'b', 'title': 'Other', 'resource_ids': [rid],
                               'path': 'folder/topic.md', 'body_md': ''})
    assert second['path'].casefold() != 'folder/topic.md'
    with pytest.raises(ValueError, match='INVALID_NOTE_PATH'):
        note_store.notes({'action': 'create', 'title': 'Escape', 'resource_ids': [rid], 'path': '../escape.md'})


def test_note_cas_external_change_and_lock_are_zero_write(note_store):
    rid = resource(note_store)
    created = note(note_store, 'locked', 'alpha beta gamma', resource_id=rid)
    lock = note_store.notes({'action': 'lock_range', 'note_id': 'locked', 'start': 6, 'end': 10}, writer='user')
    with pytest.raises(StudyNoteError) as caught:
        note_store.notes({'action': 'update', 'note_id': 'locked', 'body_md': 'alpha XXXX gamma',
                          'resource_ids': [rid], 'expected_revision': 1,
                          'expected_content_hash': created['content_hash']}, writer='agent')
    assert caught.value.payload['error'] == 'NOTE_REGION_LOCKED'
    assert caught.value.payload['overlaps'][0]['lock_id'] == lock['lock_id']
    unchanged = note_store.notes({'action': 'get', 'note_id': 'locked'})['note']
    assert unchanged['revision'] == 1 and unchanged['body_md'] == 'alpha beta gamma'
    path = vault_root(note_store.path, note_store.scope.key) / unchanged['path']
    path.write_text(path.read_text(encoding='utf-8').replace('alpha', 'external'), encoding='utf-8')
    with pytest.raises(StudyNoteError, match='NOTE_EXTERNAL_CHANGE'):
        note_store.notes({'action': 'update', 'note_id': 'locked', 'body_md': 'new', 'resource_ids': [rid],
                          'expected_revision': 1, 'expected_content_hash': unchanged['content_hash']})
    external = note_store.notes({'action': 'get', 'note_id': 'locked'}, writer='user')['note']
    adopted = note_store.notes({'action': 'update', 'note_id': 'locked',
                                'body_md': external['body_md'] + ' user edit', 'resource_ids': [rid],
                                'expected_revision': 1, 'expected_content_hash': external['content_hash']},
                               writer='user')
    assert adopted['revision'] == 2
    assert note_store.notes({'action': 'get', 'note_id': 'locked'})['note']['body_md'].endswith('user edit')


def test_agent_can_edit_outside_lock_and_user_edit_reanchors(note_store):
    rid = resource(note_store)
    created = note(note_store, 'n', 'locked tail', resource_id=rid)
    note_store.notes({'action': 'lock_range', 'note_id': 'n', 'start': 0, 'end': 6}, writer='user')
    changed = note_store.notes({'action': 'update', 'note_id': 'n', 'body_md': 'locked changed-tail',
                                'resource_ids': [rid], 'expected_revision': 1,
                                'expected_content_hash': created['content_hash']}, writer='agent')
    edited = note_store.notes({'action': 'update', 'note_id': 'n', 'body_md': 'prefix locked changed-tail',
                               'resource_ids': [rid], 'expected_revision': 2,
                               'expected_content_hash': changed['content_hash']}, writer='user')
    lock = note_store.notes({'action': 'get', 'note_id': 'n'})['note']['locks'][0]
    assert edited['revision'] == 3 and lock['quote'] == 'locked' and lock['start_offset'] == 7


def test_locks_use_utf16_and_deleted_lock_becomes_conservative(note_store):
    rid = resource(note_store)
    created = note(note_store, 'emoji', '😀locked tail', resource_id=rid)
    # Browser selection offsets count the astral emoji as two UTF-16 units.
    saved = note_store.notes({'action': 'lock_range', 'note_id': 'emoji', 'start': 2, 'end': 8,
                              'unit': 'utf16_code_unit'}, writer='user')
    assert saved['quote'] == 'locked'
    removed = note_store.notes({'action': 'update', 'note_id': 'emoji', 'body_md': '😀 tail',
                                'resource_ids': [rid], 'expected_revision': 1,
                                'expected_content_hash': created['content_hash']}, writer='user')
    assert note_store.notes({'action': 'get', 'note_id': 'emoji'})['note']['locks'][0]['state'] == 'orphaned'
    with pytest.raises(StudyNoteError, match='NOTE_REGION_LOCKED'):
        note_store.notes({'action': 'update', 'note_id': 'emoji', 'body_md': '😀 changed',
                          'resource_ids': [rid], 'expected_revision': 2,
                          'expected_content_hash': removed['content_hash']}, writer='agent')


def test_tree_graph_and_backlinks_contain_notes_only(note_store):
    rid = resource(note_store)
    with note_store.db() as db:
        note_store.put(db, 'node', {'id': 'concept', 'name': 'Concept'})
    note(note_store, 'root', '[[child]] and [[node:concept]]', resource_id=rid, title='Root', path='root.md')
    note(note_store, 'child', 'child', resource_id=rid, parent_id='root', title='Child', path='folder/topic.md')
    tree = note_store.notes({'action': 'tree'})['tree']
    assert tree[0]['kind'] == 'folder'
    assert tree[0]['id'] == 'folder:folder' and tree[0]['path'] == 'folder'
    child_file = tree[0]['children'][0]
    assert child_file['kind'] == 'note' and child_file['note_id'] == child_file['id'] == 'child'
    assert child_file['path'] == 'folder/topic.md' and 'children' not in child_file
    root_file = tree[1]
    assert root_file['kind'] == 'note' and root_file['note_id'] == 'root'
    # Semantic parentage is graph data, not physical tree nesting.
    assert child_file['parent_id'] == 'root'
    graph = note_store.notes({'action': 'graph'})
    assert {node['id'] for node in graph['nodes']} == {'root', 'child'}
    assert {edge['kind'] for edge in graph['edges']} == {'wikilink', 'parent'}
    root_links = note_store.notes({'action': 'get', 'note_id': 'root'})['note']['links']
    assert any(link.get('kind') == 'node' and link.get('id') == 'concept' for link in root_links)
    assert note_store.notes({'action': 'backlinks', 'note_id': 'child'})['backlinks'][0]['note_id'] == 'root'


def test_legacy_migration_is_idempotent_lossless_and_scoped(tmp_path):
    base = StudyStore(tmp_path / 'study.db')
    with base.db() as db:
        db.execute('INSERT INTO study_notes(scope_key,id,title,revision,source_json,deleted_at,path,parent_id,content_hash) VALUES(?,?,?,?,?,NULL,?,?,?)',
                   (base.scope.key, 'legacy', 'Legacy', 1, '{}', '', '', ''))
        db.execute('INSERT INTO study_note_blocks VALUES(?,?,?,?,?,?,?,?,?)',
                   (base.scope.key, 'legacy', 'u', 0, 'user', 'exact user text', 1, 1, '{}'))
        db.execute('INSERT INTO study_note_blocks VALUES(?,?,?,?,?,?,?,?,?)',
                   (base.scope.key, 'legacy', 'a', 1, 'ai', 'exact agent text', 0, 1, '{}'))
        db.execute('INSERT INTO study_notes(scope_key,id,title,revision,source_json,deleted_at,path,parent_id,content_hash) VALUES(?,?,?,?,?,NULL,?,?,?)',
                   (base.scope.key, 'empty', 'Empty legacy', 1, '{}', '', '', ''))
    first = base.notes({'action': 'get', 'note_id': 'legacy'})['note']
    second = base.notes({'action': 'get', 'note_id': 'legacy'})['note']
    assert first['body_md'] == second['body_md'] == 'exact user text\n\nexact agent text'
    assert len(first['resource_ids']) == 2 and first['locks'][0]['quote'] == 'exact user text'
    empty = base.notes({'action': 'get', 'note_id': 'empty'})['note']
    assert len(empty['resource_ids']) == 1
    all_resource_ids = [*first['resource_ids'], *empty['resource_ids']]
    for resource_id in all_resource_ids:
        migrated = base.notes({'action': 'resource_get', 'resource_id': resource_id})['resource']
        assert len(migrated['raw_ids']) == 1
        raw = base.notes({'action': 'raw_get', 'raw_id': migrated['raw_ids'][0]})['raw']
        assert raw['origin_id']
    other = base.scoped(StudyScope('other', 'env', 'lib'))
    assert other.notes({'action': 'list'})['total'] == 0


def test_legacy_migration_preserves_unindexed_markdown(tmp_path):
    store = StudyStore(tmp_path / 'study.db')
    with store.db() as db:
        db.execute('INSERT INTO study_notes(scope_key,id,title,revision,source_json,deleted_at,path,parent_id,content_hash) '
                   "VALUES(?,?,?,?,?,NULL,?,?,?)",
                   (store.scope.key, 'legacy', 'Legacy', 1, '{}', '', '', ''))
        db.execute('INSERT INTO study_note_blocks VALUES(?,?,?,?,?,?,?,?,?)',
                   (store.scope.key, 'legacy', 'block', 0, 'user', 'migrated text', 0, 1, '{}'))
    root = vault_root(store.path, store.scope.key)
    root.mkdir(parents=True)
    occupied = root / 'Legacy.md'
    occupied.write_text('keep this file', encoding='utf-8')

    migrated = store.notes({'action': 'get', 'note_id': 'legacy'})['note']

    assert occupied.read_text(encoding='utf-8') == 'keep this file'
    assert migrated['path'] != 'Legacy.md'
    assert migrated['body_md'] == 'migrated text'


def test_note_vault_root_symlink_cannot_redirect_writes(tmp_path):
    store = StudyStore(tmp_path / 'study.db')
    resource_id = resource(store, 'symlink')
    root = vault_root(store.path, store.scope.key)
    root.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        root.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f'directory symlinks unavailable: {exc}')

    with pytest.raises(ValueError, match='INVALID_NOTE_PATH'):
        store.notes({'action': 'create', 'note_id': 'escape', 'title': 'Escape',
                     'resource_ids': [resource_id], 'body_md': 'secret'})
    assert list(outside.iterdir()) == []


@pytest.mark.asyncio
async def test_structured_tool_failure_and_success_only_broadcast(tmp_path):
    events = []
    class EventBus:
        async def broadcast(self, event): events.append(event)
    context = SimpleNamespace(app_data_dir=tmp_path, data_dir=tmp_path, metadata={}, event_bus=EventBus())
    runtime = create_plugin(context)
    context.service = lambda name: runtime if name == 'study' else None
    async def execute(name, payload, metadata=None):
        return await operation(OperationRequest(name=name, payload=payload, metadata=metadata or {}), context=context)
    context.operation_executor = lambda: execute
    runtime.store.notes({'action': 'raw_capture', 'raw_id': 'raw', 'kind': 'mark', 'origin_id': 'm',
                         'content': 'source', 'metadata': {}, '_trusted_capture': runtime.store}, writer='user')
    rid = runtime.store.notes({'action': 'resource_create', 'title': 'R', 'content': 'source', 'raw_ids': ['raw']})['resource_id']
    created = runtime.store.notes({'action': 'create', 'note_id': 'n', 'title': 'N', 'resource_ids': [rid], 'body_md': 'locked'})
    runtime.store.notes({'action': 'lock_range', 'note_id': 'n', 'start': 0, 'end': 6}, writer='user')
    reply = await runtime.tool_handlers['notes'](ToolCall(id='edit', name='notes', arguments={
        'action': 'update', 'note_id': 'n', 'body_md': 'changed', 'resource_ids': [rid],
        'expected_revision': 1, 'expected_content_hash': created['content_hash']}))
    assert reply.status == 'failed'
    failure = json.loads(reply.content)
    assert failure['error'] == 'NOTE_REGION_LOCKED' and failure['reason']
    assert failure['overlaps'][0]['lock_id'] and failure['overlaps'][0]['quote'] == 'locked'
    assert failure['overlaps'][0]['overlap_start'] == 0
    assert events == []
    assert (await execute('study.notes', {'action': 'list'})).status == 'ok'
    assert events == []


@pytest.mark.asyncio
async def test_raw_list_host_syncs_real_study_session_messages(tmp_path):
    message = SimpleNamespace(id='m1', content='verbatim conversation', role='user')
    session = SimpleNamespace(id='study:notes', title='Notes', metadata={'owner_plugin': 'study', 'study_scope': 'notes'})
    class Sessions:
        async def list(self): return [session]
        async def list_messages(self, session_id): return [message] if session_id == 'study:notes' else []
    sessions = Sessions()
    context = SimpleNamespace(app_data_dir=tmp_path, data_dir=tmp_path, metadata={})
    runtime = create_plugin(context)
    context.service = lambda name: runtime if name == 'study' else sessions if name == 'session_store' else None
    result = await operation(OperationRequest(name='study.notes', payload={'action': 'raw_list'}, metadata={}), context=context)
    assert result.status == 'ok'
    captured = result.payload['raw_sources']
    assert [(item['kind'], item['origin_id'], item['content']) for item in captured] == [
        ('session_message', 'm1', 'verbatim conversation')]
