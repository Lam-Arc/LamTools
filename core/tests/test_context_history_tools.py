"""user:“ok，那就这么做”+(保留压缩机制，验收通用历史搜索和精确召回)。"""

import asyncio
import json

import pytest

from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState
from lamtools_core.tool import ToolCall
from lamtools_core.tool.context_history import history_scope
from lamtools_core.tool.default_toolbox import build_core_toolbox


async def stored_history():
    store = InMemoryRuntimeStateStore()
    await store.append_history("a", [
        {"role": "user", "content": "最初要求：编码必须 UTF-8。", "metadata": {"turn_id": "old-turn"}},
        {"role": "assistant", "content": "已记录", "provider_state": {"private": "SIGNATURE"}},
        {"role": "tool", "content": "历史错误：编码不匹配", "tool_call_id": "read-1"},
        {"role": "system", "content": "PRIVATE SYSTEM UTF-8"},
    ])
    await store.append_history("b", [{"role": "user", "content": "其他会话私有 UTF-8"}])
    await store.save(RuntimeState(session_id="a", metadata={"context_compaction": {"summary": "压缩后的摘要", "summary_seq": 4}}))
    return store


async def execute(toolbox, store, name, **args):
    with history_scope(store, "a", []):
        return await toolbox.execute(ToolCall(id="c", name=name, arguments=args))


@pytest.mark.asyncio
async def test_search_then_recall_reads_pre_compaction_original_and_source(tmp_path):
    store = await stored_history()
    toolbox = build_core_toolbox(work_root=tmp_path)
    before = await store.get_history("a")
    found = await execute(toolbox, store, "search_context", query="utf-8")
    assert found.status == "ok", found.error
    data = json.loads(found.content)
    assert len(data["matches"]) == 1
    hit = data["matches"][0]
    assert hit["history_seq"] == 1
    assert hit["turn_id"] == "old-turn"
    assert "其他会话" not in found.content
    assert "PRIVATE SYSTEM" not in found.content
    recalled = await execute(toolbox, store, "recall_context", start_seq=hit["history_seq"], expected_hash=hit["message_hash"])
    original = json.loads(recalled.content)
    assert original["messages"][0]["text"] == "最初要求：编码必须 UTF-8。"
    assert original["messages"][0]["source_uri"].startswith("lamtools-context://sessions/a/messages/1")
    assert original["untrusted_context"] is True
    assert await store.get_history("a") == before
    assert (await store.get("a")).metadata["context_compaction"]["summary"] == "压缩后的摘要"


@pytest.mark.asyncio
async def test_same_session_only_and_unbound_execution_fails(tmp_path):
    store = await stored_history()
    toolbox = build_core_toolbox(work_root=tmp_path)
    result = await toolbox.execute(ToolCall(id="c", name="search_context", arguments={"query": "UTF-8"}, metadata={"session_id": "b"}))
    assert result.error_code == "context_unavailable"
    refused = await execute(toolbox, store, "search_context", query="UTF-8", session_id="b")
    assert refused.error_code == "invalid_argument"
    result = await execute(toolbox, store, "recall_context", start_seq=2)
    assert "SIGNATURE" not in result.content
    assert (await execute(toolbox, store, "recall_context", start_seq=4)).error_code == "source_not_found"


@pytest.mark.asyncio
async def test_long_original_is_exactly_pageable_with_bounded_output(tmp_path):
    store = InMemoryRuntimeStateStore()
    text = ('原文"\\\n' * 1800) + "END"
    await store.append_history("a", [{"role": "user", "content": text}])
    toolbox = build_core_toolbox(work_root=tmp_path)
    args = {"start_seq": 1, "max_chars": 1600}
    chunks = []
    for _ in range(100):
        result = await execute(toolbox, store, "recall_context", **args)
        assert result.status == "ok", result.error
        assert len(result.content) <= 1600
        data = json.loads(result.content)
        chunks.extend(item["text"] for item in data["messages"])
        if data["next"] is None:
            break
        args = {**data["next"], "max_chars": 1600}
    else:
        pytest.fail("Recall pagination did not converge")
    assert "".join(chunks) == text


@pytest.mark.asyncio
async def test_hash_refuses_changed_original_after_rollback(tmp_path):
    store = await stored_history()
    toolbox = build_core_toolbox(work_root=tmp_path)
    found = await execute(toolbox, store, "search_context", query="UTF-8")
    hit = json.loads(found.content)["matches"][0]
    await store.replace_history("a", [{"role": "user", "content": "另一分支的新原文", "metadata": {"history_seq": 1}}])
    result = await execute(toolbox, store, "recall_context", start_seq=1, expected_hash=hit["message_hash"])
    assert result.error_code == "source_changed"


@pytest.mark.asyncio
async def test_search_cursor_and_literal_query_have_no_lost_results(tmp_path):
    store = InMemoryRuntimeStateStore()
    await store.append_history("a", [{"role": "user", "content": f"literal [x].* {i}"} for i in range(6)])
    toolbox = build_core_toolbox(work_root=tmp_path)
    cursor = 0
    seqs = []
    for _ in range(10):
        result = await execute(toolbox, store, "search_context", query="[x].*", limit=2, after_seq=cursor)
        assert result.status == "ok", result.error
        data = json.loads(result.content)
        seqs += [item["history_seq"] for item in data["matches"]]
        if data["next_after_seq"] is None:
            break
        assert data["next_after_seq"] > cursor
        cursor = data["next_after_seq"]
    assert seqs == [1, 2, 3, 4, 5, 6]


@pytest.mark.asyncio
async def test_parallel_scopes_do_not_leak_between_sessions(tmp_path):
    store = await stored_history()
    toolbox = build_core_toolbox(work_root=tmp_path)
    async def read(session):
        with history_scope(store, session, []):
            await asyncio.sleep(0)
            return await toolbox.execute(ToolCall(id=session, name="recall_context", arguments={"start_seq": 1}))
    a, b = await asyncio.gather(read("a"), read("b"))
    assert "最初要求" in a.content and "其他会话" not in a.content
    assert "其他会话" in b.content and "最初要求" not in b.content


@pytest.mark.asyncio
@pytest.mark.parametrize("name,args", [("search_context", {"query": ""}), ("search_context", {"query": "x", "limit": 0}), ("recall_context", {"start_seq": True}), ("recall_context", {"start_seq": 3, "end_seq": 1}), ("recall_context", {"start_seq": 1, "end_seq": 200})])
async def test_invalid_arguments_fail_without_reading(tmp_path, name, args):
    toolbox = build_core_toolbox(work_root=tmp_path)
    result = await execute(toolbox, await stored_history(), name, **args)
    assert result.error_code == "invalid_argument"


@pytest.mark.asyncio
async def test_kernel_binds_archive_and_honors_tool_permissions(tmp_path):
    from lamtools_core.app.base_agent import CoreBaseAgentKit
    from lamtools_core.kernel import CoreLoopKernel
    from lamtools_core.event import CollectingEventSink
    store = await stored_history()
    toolbox = build_core_toolbox(work_root=tmp_path)
    kernel = CoreLoopKernel(kit=CoreBaseAgentKit(work_root=tmp_path, toolbox=toolbox), llm_client=None, state_store=store, event_sink=CollectingEventSink())
    state = RuntimeState(session_id="a", run_id="r")
    result = await kernel._execute_tool(state, ToolCall(id="c", name="search_context", arguments={"query": "UTF-8"}))
    assert result.status == "ok", result.error
    assert json.loads(result.content)["matches"][0]["history_seq"] == 1
    toolbox.disabled_tools.add("recall_context")
    blocked = await kernel._execute_tool(state, ToolCall(id="r", name="recall_context", arguments={"start_seq": 1}))
    assert blocked.status in {"failed", "blocked"}
    assert "最初要求" not in blocked.content


@pytest.mark.asyncio
async def test_search_uses_bounded_store_pages_and_can_resume_scan(tmp_path):
    from lamtools_core.tool.context_history import MAX_SCAN_MESSAGES
    class PagedStore:
        pages = []
        async def read_history_page(self, session_id, *, after_seq=0, limit=200):
            self.pages.append((after_seq, limit))
            return [{"role": "user", "content": "target" if i == MAX_SCAN_MESSAGES + 1 else "noise", "metadata": {"history_seq": i}} for i in range(after_seq + 1, min(MAX_SCAN_MESSAGES + 2, after_seq + limit + 1))]
        async def get_history(self, *args, **kwargs):
            raise AssertionError("Must not load complete history")
    store = PagedStore()
    toolbox = build_core_toolbox(work_root=tmp_path)
    first = json.loads((await execute(toolbox, store, "search_context", query="target")).content)
    assert first["matches"] == []
    assert first["scanned_messages"] == MAX_SCAN_MESSAGES
    second = json.loads((await execute(toolbox, store, "search_context", query="target", after_seq=first["next_after_seq"])).content)
    assert second["matches"][0]["history_seq"] == MAX_SCAN_MESSAGES + 1
    assert all(limit <= 200 for _, limit in store.pages)


@pytest.mark.asyncio
async def test_model_receives_complete_paginated_json_without_generic_truncation(tmp_path):
    from lamtools_core.app.base_agent import CoreBaseAgentKit
    store = InMemoryRuntimeStateStore()
    await store.append_history("a", [{"role": "user", "content": 'quoted " text\\\n' * 20000}])
    toolbox = build_core_toolbox(work_root=tmp_path)
    call = ToolCall(id="c", name="recall_context", arguments={"start_seq": 1, "max_chars": 32000})
    with history_scope(store, "a", []):
        result = await toolbox.execute(call)
    assert len(result.content) > 12000
    message = await CoreBaseAgentKit(work_root=tmp_path, toolbox=toolbox).format_tool_result_for_model(RuntimeState(session_id="a"), call, result)
    assert message.content == result.content
    assert json.loads(message.content)["next"]["offset"] > 0


@pytest.mark.asyncio
async def test_complete_agent_searches_archive_and_reads_exact_text_after_compaction(tmp_path):
    from lamtools_core.app.base_agent import CoreBaseAgentKit
    from lamtools_core.event import CollectingEventSink
    from lamtools_core.kernel import CoreLoopKernel, LoopPolicy
    from lamtools_core.llm import LLMResponse, LLMToolCall
    from lamtools_core.runtime import RuntimeTurnInput
    store = await stored_history()
    class Client:
        requests = []
        async def complete(self, request):
            self.requests.append(request)
            assert len(self.requests) <= 3, "The run must finish after search, recall and reply"
            if len(self.requests) == 1:
                assert not any(m.content == "最初要求：编码必须 UTF-8。" for m in request.messages)
                return LLMResponse(tool_calls=[LLMToolCall(id="search", name="search_context", arguments={"query": "UTF-8"})], finish_reason="tool_calls")
            data = json.loads(next(m.content for m in reversed(request.messages) if m.role == "tool"))
            if len(self.requests) == 2:
                hit = data["matches"][0]
                return LLMResponse(tool_calls=[LLMToolCall(id="recall", name="recall_context", arguments={"start_seq": hit["history_seq"], "expected_hash": hit["message_hash"]})], finish_reason="tool_calls")
            assert data["messages"][0]["text"] == "最初要求：编码必须 UTF-8。"
            return LLMResponse(content="原始要求为 UTF-8。", finish_reason="stop")
    client = Client()
    kernel = CoreLoopKernel(kit=CoreBaseAgentKit(work_root=tmp_path), llm_client=client, state_store=store, event_sink=CollectingEventSink(), policy=LoopPolicy(model_retries=0, empty_response_retries=0))
    result = await kernel.run(RuntimeTurnInput(user_message="查回原始编码要求", state=await store.get("a")))
    assert result.decision == "done", result
    assert len(client.requests) == 3
    # Runtime notices can append at the tail; the frozen system and tool
    # definitions must remain byte-for-byte stable across the recall loop.
    assert len({request.messages[0].content for request in client.requests}) == 1
    assert client.requests[0].tools == client.requests[1].tools == client.requests[2].tools
    assert (await store.get_history("a"))[0]["content"] == "最初要求：编码必须 UTF-8。"


@pytest.mark.asyncio
async def test_search_does_not_match_its_own_prior_results(tmp_path):
    store = await stored_history()
    await store.append_history("a", [{"role": "tool", "name": "search_context", "content": "UTF-8 earlier search preview"}, {"role": "tool", "name": "recall_context", "content": "UTF-8 earlier recalled content"}])
    found = await execute(build_core_toolbox(work_root=tmp_path), store, "search_context", query="UTF-8")
    assert [m["history_seq"] for m in json.loads(found.content)["matches"]] == [1]
