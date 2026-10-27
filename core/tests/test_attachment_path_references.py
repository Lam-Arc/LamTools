from pathlib import Path

import pytest

from lamtools_core.attachment import AttachmentRecord, AttachmentService, AttachmentSession, build_capability_aware_attachment_input
from lamtools_core.app.queue_state import build_queue_guidance_plan, build_queue_update_plan


class Repository:
    def __init__(self, root):
        self.root, self.records = root, {}

    async def session(self, session_id):
        return AttachmentSession(session_id, self.root)

    async def create(self, record):
        self.records[record.id] = record
        return record

    async def get(self, attachment_id):
        return self.records.get(attachment_id)

    async def list(self, session_id):
        return [r for r in self.records.values() if r.session_id == session_id]


# user:“先给我方案再动”+(先验证文件引用、去重及排队编辑的验收行为)。
@pytest.mark.asyncio
async def test_existing_file_is_referenced_and_inline_bytes_are_never_sent(tmp_path):
    source = tmp_path / '原文件 with spaces.png'
    source.write_bytes(b'original bytes')
    service = AttachmentService(Repository(tmp_path / 'artifact'))
    result = await service.reference('s', str(source))
    assert result['path'] == str(source.resolve())
    record = await service.get(result['id'])
    text, blocks, deferred = build_capability_aware_attachment_input([record], [record.id], 'multimodal')
    assert str(source.resolve().as_posix()) in text
    assert blocks == [] and deferred == []
    assert 'base64' not in text
    assert not (tmp_path / 'artifact').exists()


@pytest.mark.asyncio
async def test_identical_temporary_files_share_bytes_across_names_and_sessions(tmp_path):
    service = AttachmentService(Repository(tmp_path / 'artifact'))
    a = await service.create('s1', 'one.txt', b'identical')
    b = await service.create('s2', 'other.txt', b'identical')
    c = await service.create('s2', 'one.txt', b'different')
    assert a['path'] == b['path'] != c['path']
    assert a['metadata']['sha256'] == b['metadata']['sha256']
    assert a['id'] != b['id']
    assert len([p for p in (tmp_path / 'artifact').rglob('*') if p.is_file()]) == 2


@pytest.mark.asyncio
async def test_dedup_rechecks_bytes_instead_of_reusing_a_damaged_file(tmp_path):
    service = AttachmentService(Repository(tmp_path / 'artifact'))
    first = await service.create('s', 'first.txt', b'original')
    Path(first['path']).write_bytes(b'corrupted')
    second = await service.create('s', 'second.txt', b'original')
    assert first['path'] == second['path']
    assert Path(second['path']).read_bytes() == b'original'


@pytest.mark.asyncio
async def test_attachment_only_input_reaches_model_as_path_without_contents(tmp_path):
    from lamtools_core.app.default_agent import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
    from lamtools_core.llm import LLMStreamEvent
    service = AttachmentService(Repository(tmp_path / 'artifact'))
    record = await service.create('s', 'note.txt', b'content must stay on disk')
    requests = []
    class Model:
        async def complete(self, request):
            raise AssertionError("Expected streaming")
        async def stream(self, request):
            requests.append(request)
            yield LLMStreamEvent(kind='content_delta', content='Received')
            yield LLMStreamEvent(kind='done')
    catalog = create_core_agent_operations(spec=CoreAgentSpec(), paths=CoreAgentPaths(data_dir=tmp_path / 'data', work_root=tmp_path), model_provider=Model(), attachment_service=service)
    result = await catalog.execute('turn.start', {'thread_id': 's', 'message': '', 'attachment_ids': [record['id']]})
    assert result.status == 'ok'
    user = next(m for m in requests[0].messages if m.role == 'user')
    text = str(user.content)
    assert Path(record['path']).as_posix() in text
    assert 'content must stay on disk' not in text and 'base64' not in text


@pytest.mark.asyncio
async def test_preview_distinguishes_missing_from_invalid_image(tmp_path):
    service = AttachmentService(Repository(tmp_path / 'artifact'))
    result = await service.create('s', 'bad.png', b'not a png', 'image/png')
    assert (await service.preview(result['id']))['error_code'] == 'image_decode_failed'
    Path(result['path']).unlink()
    assert (await service.preview(result['id']))['error_code'] == 'file_missing'


def test_queue_edit_and_guide_preserve_attachment_references():
    items = [{'type': 'text', 'text': 'before'}, {'type': 'attachment', 'attachment_id': 'a', 'path': 'C:/test/a.png'}]
    snapshot = {'core': {'status': 'running'}, 'turns': {'t': {'status': 'running'}}, 'queue': [{'queue_item_id': 'q', 'status': 'queued', 'input': items, 'runtime_input': items}]}
    guide = build_queue_guidance_plan(snapshot, thread_id='s', turn_id='t', queue_item_id='q', client_message_id='g', replacement_text='after')
    assert guide.applied and guide.runtime_input_items[-1] == items[-1]
    updated = build_queue_update_plan(snapshot, queue_item_id='q', input_items=[{'type': 'text', 'text': 'after'}])
    assert updated.payload['runtime_input'][-1] == items[-1]


@pytest.mark.asyncio
async def test_live_queue_dispatch_and_both_guidance_routes_receive_paths(tmp_path):
    import asyncio
    from lamtools_core.app.core_db import open_core_app_db
    from lamtools_core.app.live_operations import CoreLiveContext
    from lamtools_core.app.live_hub import CoreAppEventHub
    from lamtools_core.app import OperationCatalog
    from lamtools_core.attachment import CoreAttachmentStore
    from lamtools_core.app import OperationResult
    from lamtools_core.app.live_operations import handle_queue_create_operation, handle_queue_guidance_operation, handle_turn_steer_operation, _dispatch_next_queue_item
    handle = await open_core_app_db(tmp_path / "live.db")
    engine = handle.engine
    context = CoreLiveContext(session_factory=handle.session_factory, event_store=handle.event_store, snapshot_store=handle.snapshot_store, operations=OperationCatalog(), hub=CoreAppEventHub())
    started, release = asyncio.Event(), asyncio.Event()
    received = []
    async def run(request):
        received.append(request.payload)
        started.set()
        await release.wait()
        return OperationResult(name='turn.start')
    context.operations.register('turn.start', run)
    task = None
    try:
        store = CoreAttachmentStore(context.session_factory, tmp_path / 'data')
        attachment = await store.create('s', 'photo.png', b'image evidence', 'image/png')
        item = {'type': 'attachment', 'attachment_id': attachment['id']}
        queued = await handle_queue_create_operation(request_id=1, params={'thread_id': 's', 'input': [item], 'work_root': str(tmp_path)}, context=context)
        assert 'result' in queued.response
        await _dispatch_next_queue_item(context=context, thread_id='s', work_root=str(tmp_path), completed_turn_id='')
        await asyncio.wait_for(started.wait(), 3)
        assert received[0]['attachment_ids'] == [attachment['id']]
        turn_id = context.host.runtime_task_registry.active_run_id('s')
        task = context.host.runtime_task_registry.task('s', run_id=turn_id)
        direct = await handle_turn_steer_operation(request_id=2, params={'thread_id': 's', 'turn_id': turn_id, 'client_message_id': 'direct-image', 'input': [item]}, context=context)
        assert direct.response['result']['applied'] is True
        queued = await handle_queue_create_operation(request_id=3, params={'thread_id': 's', 'input': [{'type': 'text', 'text': 'inspect'}, item]}, context=context)
        queue_id = queued.response['result']['queue_item']['queue_item_id']
        guided = await handle_queue_guidance_operation(request_id=4, params={'thread_id': 's', 'turn_id': turn_id, 'queue_item_id': queue_id, 'text': 'edited', 'client_message_id': 'queued-image'}, context=context)
        assert guided.response['result']['applied'] is True
        offers = context.host.runtime_task_registry.offer_guidance('s', run_id=turn_id)
        assert len(offers) == 2
        assert all(Path(attachment['path']).as_posix() in offer['content'] for offer in offers)
        assert all('base64' not in offer['content'] for offer in offers)
    finally:
        release.set()
        if task:
            await asyncio.wait_for(task, 3)
        context.host.runtime_task_registry.clear()
        await engine.dispose()


def test_reference_http_registers_original_and_library_index(tmp_path):
    from fastapi.testclient import TestClient
    from lamtools_core.app.http_agent_app import create_core_agent_http_app
    root = tmp_path / 'project'
    source = tmp_path / 'existing.txt'
    source.write_text('existing file')
    app = create_core_agent_http_app(core_db=tmp_path / 'core.db', data_dir=tmp_path / 'data', work_root=root)
    with TestClient(app) as client:
        response = client.post('/api/core/sessions/s/attachments/reference', json={'path': str(source.resolve())})
        assert response.status_code == 200, response.text
        record = response.json()
        assert record['path'] == str(source.resolve())
        assert record['artifact_id']
        preview = client.get(f"/api/core/attachments/{record['id']}/preview").json()
        assert preview['text'] == 'existing file'
        assert preview['error_code'] == ''
        assert client.get(f"/api/core/attachments/{record['id']}/download").content == b'existing file'
