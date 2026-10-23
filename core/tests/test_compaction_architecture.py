"""user:“审查压缩相关的改动，尤其是是否存在架构缺陷”+(用隔离数据验证压缩边界，不触碰真实会话)。"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_kernel import _make_kernel, MockRuntimeKit, MockKitStep
from lamtools_core.kernel import LoopPolicy
from lamtools_core.runtime import RuntimeState, InMemoryRuntimeStateStore
from lamtools_core.llm import ChatMessage, LLMRequest
from lamtools_core.context_compaction import ContextCompactionController, CompactionExecution, ContextCompactionResult
from lamtools_core.context_compaction import ContextCompactionError
from lamtools_core.context_compaction_budget import TokenBudget, TokenMeasurement, LOCAL_ESTIMATE_SCALE


def setup_case(usage=9000):
    store = InMemoryRuntimeStateStore()
    kernel = _make_kernel(MockRuntimeKit(steps=[MockKitStep(decision='done')]), state_store=store,
                          policy=LoopPolicy(context_window_tokens=10000))
    state = RuntimeState(session_id='review', run_id='run-1', metadata={
        'runtime_context_metrics': {'model_id': 'mock-model', 'context_usage_prompt_tokens': usage}})
    return kernel, state, store


def execution(request, history):
    summary = ChatMessage(role='system', content='summary', metadata={'key': 'context_compaction_summary'})
    result = ContextCompactionResult(status='compacted', trigger='auto', summary='summary', summary_message=summary,
        prefix_messages=[request.messages[0]], compacted_messages=history[:-1], retained_messages=history[-1:],
        replacement_messages=[request.messages[0], summary, *history[-1:]], before_tokens=9000, after_tokens=1000, limit_tokens=6000)
    return CompactionExecution(result=result, measurement=TokenMeasurement(tokens=9000, exact=True), execution_model='mock-model')


@pytest.mark.asyncio
async def test_latest_real_usage_has_priority_despite_larger_local_estimate():
    kernel, state, _ = setup_case(usage=1000)
    request = LLMRequest(model='mock-model', messages=[ChatMessage(role='user', content='x' * 50000)])
    assert kernel._estimate_request_tokens(request, fast=False) * LOCAL_ESTIMATE_SCALE > 10000
    compact = AsyncMock(return_value=CompactionExecution(result=None, measurement=TokenMeasurement(tokens=9000, exact=True)))
    with patch.object(ContextCompactionController, 'compact', compact):
        await kernel._compact_request_if_needed(state, request)
    # user:“慢一拍的话是可接受的，因为提前留了 20% 的阈值给他，主要是要保证优先使用真实 usage”+(接受一拍延迟，不用较大估算值覆盖真实读数)。
    assert compact.await_count == 0
    assert state.metadata['runtime_context_metrics']['estimated_prompt_tokens'] == 1000
    assert state.metadata['runtime_context_metrics']['context_measurement_source'] == 'usage'


@pytest.mark.asyncio
async def test_same_run_can_compact_again_after_context_grows():
    kernel, state, _ = setup_case()
    state.metadata['_context_compaction_run_id'] = state.run_id
    request = LLMRequest(model='mock-model', messages=[ChatMessage(role='user', content='x' * 50000)])
    compact = AsyncMock(return_value=CompactionExecution(result=None, measurement=TokenMeasurement(tokens=9000, exact=True)))
    with patch.object(ContextCompactionController, 'compact', compact):
        await kernel._compact_request_if_needed(state, request)
    assert compact.await_count == 1, 'run-id fence permanently suppresses a second required compaction'


def test_missing_usage_invalidates_previous_measurement():
    kernel, state, _ = setup_case()
    kernel._record_context_usage(state, LLMRequest(messages=[], model='mock-model'), SimpleNamespace(usage=None))
    assert not state.metadata['runtime_context_metrics'].get('context_usage_prompt_tokens'), 'missing usage silently reuses an older request forever'


@pytest.mark.asyncio
async def test_fitting_uses_the_same_calibrated_estimate_as_trigger():
    controller = ContextCompactionController(llm_client=None, estimate_request_tokens=lambda messages, fast: 100)
    captured = []
    async def pipeline(request):
        captured.append(request)
        return ContextCompactionResult(status='not_needed', trigger='auto')
    with patch('lamtools_core.context_compaction.controller.compact_context', pipeline):
        await controller.compact([ChatMessage(role='user', content='text')],
            budget=TokenBudget(context_window=10000, trigger_tokens=8000, target_tokens=6000),
            timeout=None, current_model='mock-model', force=True)
    measured = controller.measure(captured[0].messages, trigger_tokens=8000).tokens
    fitted = captured[0].estimate_exact_tokens(captured[0].messages)
    assert fitted == measured, f'trigger={measured}, fitter={fitted}; target uses incompatible token units'


@pytest.mark.asyncio
async def test_checkpoints_after_compaction_still_persist_completed_work():
    kernel, state, store = setup_case()
    history = [ChatMessage(role='user', content='old', metadata={'history_seq': 1}),
               ChatMessage(role='assistant', content='retained', metadata={'history_seq': 2})]
    await store.append_history(state.session_id, [m.to_dict() for m in history])
    kernel._live_history = history
    kernel._persisted_len = len(history)
    request = LLMRequest(model='mock-model', messages=[ChatMessage(role='system', content='prefix'), *history])
    outcome = execution(request, history)
    with patch.object(ContextCompactionController, 'compact', AsyncMock(return_value=outcome)):
        await kernel._compact_request_if_needed(state, request, history=history)
    history.append(ChatMessage(role='assistant', content='COMPLETED_WORK_AFTER_COMPACTION'))
    await kernel._save_checkpoint(state)
    recovered = await store.get_history(state.session_id)
    assert any(m.get('content') == 'COMPLETED_WORK_AFTER_COMPACTION' for m in recovered), 'crash after successful checkpoint loses work completed since compaction'


@pytest.mark.asyncio
async def test_post_compaction_rebuilt_prefix_cannot_bypass_final_budget_check():
    kernel, state, _ = setup_case()
    history = [ChatMessage(role='user', content='old', metadata={'history_seq': 1}),
               ChatMessage(role='assistant', content='retained', metadata={'history_seq': 2})]
    request = LLMRequest(model='mock-model', messages=[ChatMessage(role='system', content='prefix'), *history])
    outcome = execution(request, history)
    def rebuild(s):
        from lamtools_core.kernel.loop import MOVABLE_CONTEXT_METADATA_KEY
        s.metadata[MOVABLE_CONTEXT_METADATA_KEY] = {'system_prompt': '中' * 20000}
    kernel.kit.rebuild_movable_system_context = rebuild
    with patch.object(ContextCompactionController, 'compact', AsyncMock(return_value=outcome)):
        with pytest.raises(ContextCompactionError):
            await kernel._compact_request_if_needed(state, request, history=history)
    assert 'context_compaction' not in state.metadata
    assert history[0].content == 'old'


@pytest.mark.asyncio
async def test_manual_compaction_invalidates_old_provider_usage():
    from lamtools_core.app.command_execution import _persist_manual_compaction_metadata
    _, state, store = setup_case()
    history = [ChatMessage(role='user', content='old', metadata={'history_seq': 1}),
               ChatMessage(role='assistant', content='retained', metadata={'history_seq': 2})]
    request = LLMRequest(model='mock-model', messages=[ChatMessage(role='system', content='prefix'), *history])
    outcome = execution(request, history)
    await _persist_manual_compaction_metadata(store, state, result=outcome.result, execution=outcome,
        source_messages=request.messages, budget=TokenBudget(context_window=10000, trigger_tokens=8000, target_tokens=6000),
        retained_steps=0, before_messages=3, total_context_window_tokens=10000, reserved_output_tokens=0)
    assert not state.metadata['runtime_context_metrics'].get('context_usage_prompt_tokens'), 'manual compaction clears legacy anchor but preserves the newly authoritative stale usage'


@pytest.mark.asyncio
async def test_automatic_compaction_preserves_raw_history_and_recovery_matches_manual():
    from lamtools_core.app.command_execution import _load_effective_compaction_history
    kernel, state, store = setup_case()
    history = [ChatMessage(role='user', content='raw old', metadata={'history_seq': 1}),
               ChatMessage(role='assistant', content='retained', metadata={'history_seq': 2})]
    await store.append_history(state.session_id, [m.to_dict() for m in history])
    kernel._live_history = history
    kernel._persisted_len = len(history)
    request = LLMRequest(model='mock-model', messages=[ChatMessage(role='system', content='prefix'), *history])
    with patch.object(ContextCompactionController, 'compact', AsyncMock(return_value=execution(request, history))):
        await kernel._compact_request_if_needed(state, request, history=history)
    history.append(ChatMessage(role='assistant', content='new work'))
    await kernel._persist_history_tail(state, history)
    raw = await store.get_history(state.session_id)
    assert [m['content'] for m in raw] == ['raw old', 'retained', 'new work']
    assert [m['metadata']['history_seq'] for m in raw] == [1, 2, 3]
    restored = await _load_effective_compaction_history(store, state.session_id, state.metadata)
    assert [m.content for m in restored] == ['summary', 'retained', 'new work']


@pytest.mark.asyncio
async def test_repeated_compaction_unions_covered_rows_without_losing_new_work():
    from lamtools_core.app.command_execution import _load_effective_compaction_history
    kernel, state, store = setup_case()
    history = [ChatMessage(role='user', content='first', metadata={'history_seq': 1}),
               ChatMessage(role='assistant', content='second', metadata={'history_seq': 2})]
    await store.append_history(state.session_id, [m.to_dict() for m in history])
    kernel._live_history = history
    kernel._persisted_len = len(history)
    for number in (1, 2):
        state.metadata['runtime_context_metrics']['context_usage_prompt_tokens'] = 9000
        request = LLMRequest(model='mock-model', messages=[ChatMessage(role='system', content='prefix'), *history])
        outcome = execution(request, history)
        with patch.object(ContextCompactionController, 'compact', AsyncMock(return_value=outcome)) as compact:
            await kernel._compact_request_if_needed(state, request, history=history)
        assert compact.await_count == 1
        history.append(ChatMessage(role='assistant', content=f'new work {number}'))
        await kernel._save_checkpoint(state)
    raw = await store.get_history(state.session_id)
    assert len(raw) == 4
    restored = await _load_effective_compaction_history(store, state.session_id, state.metadata)
    assert [m.content for m in restored] == ['summary', 'new work 1', 'new work 2']


@pytest.mark.asyncio
async def test_provider_usage_refreshes_authoritative_context_value():
    from lamtools_core.llm import LLMResponse, LLMUsage
    kernel, state, _ = setup_case()
    kernel._record_context_usage(state, LLMRequest(messages=[], model='mock-model'),
        LLMResponse(content='ok', usage=LLMUsage(prompt_tokens=2345)))
    metrics = state.metadata['runtime_context_metrics']
    assert metrics['context_tokens'] == 2345
    assert metrics['context_measurement_source'] == 'usage'


@pytest.mark.asyncio
async def test_sqlite_checkpoint_after_compaction_survives_database_reopen(tmp_path):
    from lamtools_core.app import open_core_app_db
    dbpath = str(tmp_path / 'compaction.db')
    db = await open_core_app_db(dbpath)
    try:
        kernel, state, _ = setup_case()
        store = db.runtime_state_store
        kernel.state_store = store
        await store.save(state)
        history = [ChatMessage(role='user', content='raw old', metadata={'history_seq': 1}),
                   ChatMessage(role='assistant', content='retained', metadata={'history_seq': 2})]
        await store.append_history(state.session_id, [m.to_dict() for m in history])
        kernel._live_history = history
        kernel._persisted_len = len(history)
        request = LLMRequest(model='mock-model', messages=[ChatMessage(role='system', content='prefix'), *history])
        with patch.object(ContextCompactionController, 'compact', AsyncMock(return_value=execution(request, history))):
            await kernel._compact_request_if_needed(state, request, history=history)
        history.append(ChatMessage(role='assistant', content='durable result'))
        await kernel._save_checkpoint(state)
    finally:
        await db.close()
    db = await open_core_app_db(dbpath)
    try:
        raw = await db.runtime_state_store.get_history('review')
        assert [m['content'] for m in raw] == ['raw old', 'retained', 'durable result']
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_sqlite_summary_and_snapshot_rollback_together(tmp_path, monkeypatch):
    from copy import deepcopy
    from lamtools_core.app import open_core_app_db
    db = await open_core_app_db(str(tmp_path / 'atomic.db'))
    try:
        store = db.runtime_state_store
        state = RuntimeState(session_id='atomic', metadata={'sentinel': 'original'})
        await store.save(state)
        await store.append_history(state.session_id, [{'role': 'user', 'content': 'original'}])
        candidate = deepcopy(state)
        candidate.metadata['context_compaction'] = {'summary': 'new summary'}
        def fail_commit(*args, **kwargs):
            raise RuntimeError('injected commit failure')
        monkeypatch.setattr(store, '_append_runtime_change', fail_commit)
        with pytest.raises(RuntimeError, match='injected commit failure'):
            await store.save_compaction(candidate, [{'role': 'system', 'content': 'new snapshot'}])
        assert len(await store.get_history(state.session_id)) == 1
        assert 'context_compaction' not in (await store.get(state.session_id)).metadata
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_cancelled_compaction_keeps_original_baselines_and_history():
    import asyncio
    from lamtools_core.prompt.movable import MOVABLE_CONTEXT_METADATA_KEY
    kernel, state, _ = setup_case()
    state.metadata[MOVABLE_CONTEXT_METADATA_KEY] = {'system_prompt': 'original'}
    history = [ChatMessage(role='user', content='original')]
    request = LLMRequest(model='mock-model', messages=[ChatMessage(role='system', content='original'), *history])
    kernel.kit.rebuild_movable_system_context = lambda candidate: candidate.metadata.update(
        {MOVABLE_CONTEXT_METADATA_KEY: {'system_prompt': 'replacement'}})
    with patch.object(ContextCompactionController, 'compact', AsyncMock(side_effect=asyncio.CancelledError())):
        with pytest.raises(asyncio.CancelledError):
            await kernel._compact_request_if_needed(state, request, history=history)
    assert state.metadata[MOVABLE_CONTEXT_METADATA_KEY]['system_prompt'] == 'original'
    assert history[0].content == 'original'
    assert request.messages[0].content == 'original'


@pytest.mark.asyncio
async def test_complete_auto_pipeline_preserves_source_and_resumes_without_resurfacing():
    from test_kernel import CapturingLLMClient, _make_turn_input
    from lamtools_core.app.command_execution import _load_effective_compaction_history
    class HistoryKit(MockRuntimeKit):
        async def build_model_request(self, state, context):
            return LLMRequest(model='mock-model', messages=[ChatMessage(role='system', content='prefix'), *context.history])
    store = InMemoryRuntimeStateStore()
    raw = [ChatMessage(role=role, content=f'{role} {i} ' + 'x' * 1000).to_dict()
           for i in range(20) for role in ('user', 'assistant')]
    await store.save_checkpoint(RuntimeState(session_id='complete'), raw)
    kernel = _make_kernel(HistoryKit(steps=[MockKitStep(reply='complete', decision='done')]),
                          llm_client=CapturingLLMClient(), state_store=store,
                          policy=LoopPolicy(context_window_tokens=50000))
    result = await kernel.run(_make_turn_input('continue', session_id='complete'))
    assert result.decision == 'done', result.error
    assert len(await store.get_history('complete')) >= 42
    state = await store.get('complete')
    assert state.metadata['context_compaction']['summary']
    view = await _load_effective_compaction_history(store, 'complete', state.metadata)
    assert sum(m.metadata.get('key') == 'context_compaction_summary' for m in view) == 1
    assert not any(str(m.content).startswith('assistant 0 ') for m in view)
    assert any(m.content == 'complete' for m in view)


@pytest.mark.asyncio
async def test_legacy_database_zero_tail_compaction_does_not_reload_old_blob(tmp_path):
    from lamtools_core.app import open_core_app_db
    from lamtools_core.app.command_execution import _load_effective_compaction_history
    db = await open_core_app_db(str(tmp_path / 'legacy.db'))
    try:
        store = db.runtime_state_store
        kernel, state, _ = setup_case()
        kernel.state_store = store
        await store.save_checkpoint(state, [{'role': 'user', 'content': 'legacy user'}])
        history = await _load_effective_compaction_history(store, state.session_id, state.metadata)
        history.append(ChatMessage(role='assistant', content='new result'))
        kernel._live_history = history
        kernel._persisted_len = 1
        request = LLMRequest(model='mock-model', messages=[ChatMessage(role='system', content='prefix'), *history])
        outcome = execution(request, history)
        from dataclasses import replace
        result = replace(outcome.result, retained_messages=[], replacement_messages=outcome.result.replacement_messages[:2])
        with patch.object(ContextCompactionController, 'compact', AsyncMock(return_value=replace(outcome, result=result))):
            await kernel._compact_request_if_needed(state, request, history=history)
        view = await _load_effective_compaction_history(store, state.session_id, state.metadata)
        assert [m.content for m in view] == ['summary']
        assert await store.get_history(state.session_id, after_seq=2) == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_complete_manual_pipeline_reuses_saved_view_without_deleting_source():
    from test_kernel import CapturingLLMClient
    from lamtools_core.app.command_execution import compact_runtime_history, _load_effective_compaction_history
    store = InMemoryRuntimeStateStore()
    state = RuntimeState(session_id='manual', metadata={
        'runtime_context_metrics': {'model_id': 'mock-model', 'context_window_tokens': 50000,
                                    'total_context_window_tokens': 50000, 'context_usage_prompt_tokens': 45000}})
    await store.save(state)
    rows = [ChatMessage(role=role, content=f'{role} {i} ' + 'x' * 1000).to_dict()
            for i in range(20) for role in ('user', 'assistant')]
    await store.append_history(state.session_id, rows)
    result = await compact_runtime_history(runtime_state_store=store, thread_id=state.session_id,
        llm_client=CapturingLLMClient(), model='mock-model')
    assert result['status'] == 'compacted'
    assert len(await store.get_history(state.session_id)) == 40
    saved = await store.get(state.session_id)
    assert not saved.metadata['runtime_context_metrics'].get('context_usage_prompt_tokens')
    view = await _load_effective_compaction_history(store, state.session_id, saved.metadata)
    assert len(view) == 1


@pytest.mark.asyncio
async def test_child_result_arriving_during_compaction_is_not_erased():
    from lamtools_core.app.command_execution import _load_effective_compaction_history
    kernel, state, store = setup_case()
    history = [ChatMessage(role='user', content='old', metadata={'history_seq': 1}),
               ChatMessage(role='assistant', content='retained', metadata={'history_seq': 2})]
    await store.append_history(state.session_id, [m.to_dict() for m in history])
    kernel._live_history = history
    kernel._persisted_len = 2
    request = LLMRequest(model='mock-model', messages=[ChatMessage(role='system', content='prefix'), *history])
    outcome = execution(request, history)
    async def compact(*args, **kwargs):
        await store.append_history(state.session_id, [{'role': 'user', 'content': 'late child result'}])
        return outcome
    with patch.object(ContextCompactionController, 'compact', compact):
        await kernel._compact_request_if_needed(state, request, history=history)
    await kernel._persist_history_tail(state, history)
    restored = await _load_effective_compaction_history(store, state.session_id, state.metadata)
    assert [m.content for m in restored] == ['summary', 'retained', 'late child result']


@pytest.mark.asyncio
async def test_rebuilt_prefix_and_snapshot_do_not_leak_or_duplicate_in_history():
    from lamtools_core.prompt.movable import MOVABLE_CONTEXT_METADATA_KEY
    kernel, state, store = setup_case()
    history = [ChatMessage(role='user', content='old', metadata={'history_seq': 1}),
               ChatMessage(role='assistant', content='retained', metadata={'history_seq': 2})]
    await store.append_history(state.session_id, [m.to_dict() for m in history])
    kernel._live_history = history
    kernel._persisted_len = 2
    request = LLMRequest(model='mock-model', messages=[ChatMessage(role='system', content='prefix'), *history])
    kernel.kit.rebuild_movable_system_context = lambda s: s.metadata.update(
        {MOVABLE_CONTEXT_METADATA_KEY: {'system_prompt': 'new prefix'}})
    kernel.kit.emit_runtime_context_snapshot = lambda s: ChatMessage(role='system', content='new snapshot',
        metadata={'key': 'runtime_context_delta'})
    with patch.object(ContextCompactionController, 'compact', AsyncMock(return_value=execution(request, history))):
        await kernel._compact_request_if_needed(state, request, history=history)
    assert [m.content for m in history] == ['summary', 'retained', 'new snapshot']
    await kernel._save_checkpoint(state)
    raw = await store.get_history(state.session_id)
    assert [m['content'] for m in raw] == ['old', 'retained', 'new snapshot']
