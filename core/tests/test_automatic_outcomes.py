from pathlib import Path

import pytest

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.event import RunItemEvent
from lamtools_core.tool import ToolCall
from lamtools_core.tool.memory_tools import make_memory_handler
from lamtools_core.tool.library_tools import make_library_handler


# user:“自动检验输出的 绝对地址和项目相对地址，或者无论带不带https的链接”+(只登记真实文件，链接规范化并去重)。
@pytest.mark.asyncio
async def test_final_output_collects_existing_files_links_and_turn_library_entries(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'report.md').write_text('report')
    outside = tmp_path / 'outside.txt'
    outside.write_text('outside')
    db = await open_core_app_db(tmp_path / 'core.db')
    try:
        project, _ = await db.project_store.create(root)
        filed = await db.artifact_store.register(project_id=project.id, work_root=root, path='report.md', kind='document', provenance={'thread_id': 's', 'turn_id': 't'})
        item = RunItemEvent(kind='message', thread_id='s', turn_id='t', item_id='answer', status='completed', payload={'type': 'agentMessage', 'content': f'report.md\n{outside.as_posix()}\nhttps://example.com/docs\nexample.com/docs\nmissing.txt\njavascript:alert(1)'})
        await db.artifact_store.ingest_run_item(item, project_id=project.id, work_root=root)
        artifacts = await db.artifact_store.list(project.id)
        assert len(artifacts) == 3
        assert {a.kind for a in artifacts} >= {'link'}
        assert len(item.artifacts) == 3
        assert filed.artifact_id in {a['artifact_id'] for a in item.artifacts}
        external = next(a for a in artifacts if a.name == 'outside.txt')
        assert await db.artifact_store.current_content_path(external) == outside.resolve()
        assert next(a for a in artifacts if a.kind == 'link').path == 'https://example.com/docs'
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_memory_and_explicit_library_registration_are_turn_outcomes(tmp_path, monkeypatch):
    monkeypatch.setenv('LAMTOOLS_HOME', str(tmp_path / 'home'))
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'file.txt').write_text('file')
    db = await open_core_app_db(tmp_path / 'core.db')
    try:
        project, _ = await db.project_store.create(root)
        memory = await make_memory_handler(root)(ToolCall(id='m', name='memory', arguments={'action': 'write', 'path': 'note.md', 'content': '# Remember\nUseful facts'}))
        filed = await make_library_handler(db.artifact_store, root)(ToolCall(id='l', name='library', arguments={'action': 'register', 'path': 'file.txt'}))
        assert memory.status == filed.status == 'ok'
        assert memory.artifacts and filed.artifacts
        for tool, result in [('memory', memory), ('library', filed)]:
            item = RunItemEvent(kind='tool_result', thread_id='s', turn_id='t', item_id=tool, status='completed', payload={'tool_name': tool}, artifacts=[a.to_dict() for a in result.artifacts])
            await db.artifact_store.ingest_run_item(item, project_id=project.id, work_root=root)
        final = RunItemEvent(kind='message', thread_id='s', turn_id='t', item_id='answer', status='completed', payload={'type': 'agentMessage', 'content': 'Done'})
        await db.artifact_store.ingest_run_item(final, project_id=project.id, work_root=root)
        assert len(final.artifacts) == 2
        assert {a['kind'] for a in final.artifacts} == {'memory', 'document'}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_actual_event_persistence_enriches_outcomes_before_projection(tmp_path):
    from lamtools_core.app.default_agent import _persist_run_items
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'output.txt').write_text('result')
    db = await open_core_app_db(tmp_path / 'core.db')
    try:
        project, _ = await db.project_store.create(root)
        item = RunItemEvent(kind='message', thread_id='s', turn_id='t', item_id='final', status='completed', payload={'type': 'agentMessage', 'content': 'output.txt and example.com'})
        await _persist_run_items([item], db_session_factory=db.session_factory, app_event_store=db.event_store, thread_snapshot_store=db.snapshot_store, artifact_store=db.artifact_store, work_root=root)
        assert len(item.artifacts) == 2
        assert len(await db.artifact_store.list(project.id)) == 2
        async with db.session_factory() as session:
            events = await db.event_store.list_after(session, thread_id='s', after_seq=0)
        assert len(events[0].payload['artifacts']) == 2
    finally:
        await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('live', [False, True])
async def test_real_agent_final_reply_registers_and_publishes_file_and_link(tmp_path, live):
    from lamtools_core.app.default_agent import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
    from lamtools_core.app.live_hub import CoreAppEventHub
    from lamtools_core.llm import LLMStreamEvent
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'report.md').write_text('report')
    db = await open_core_app_db(tmp_path / 'core.db')
    class Model:
        async def complete(self, request):
            raise AssertionError('Expected stream')
        async def stream(self, request):
            yield LLMStreamEvent(kind='content_delta', content='report.md and example.com')
            yield LLMStreamEvent(kind='done')
    try:
        project, _ = await db.project_store.create(root)
        operations = create_core_agent_operations(spec=CoreAgentSpec(), paths=CoreAgentPaths(data_dir=tmp_path / 'data', work_root=root), model_provider=Model(), db_session_factory=db.session_factory, app_event_store=db.event_store, thread_snapshot_store=db.snapshot_store, runtime_state_store=db.runtime_state_store, app_event_hub=CoreAppEventHub() if live else None)
        result = await operations.execute('turn.start', {'thread_id': 's', 'message': 'show outcomes'})
        assert result.status == 'ok'
        assert len(await db.artifact_store.list(project.id)) == 2
        async with db.session_factory() as session:
            events = await db.event_store.list_after(session, thread_id='s', after_seq=0)
        assert any(len(event.payload.get('artifacts', [])) == 2 for event in events)
    finally:
        await db.close()
