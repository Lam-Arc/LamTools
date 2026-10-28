"""user:“上下文应当能够被精确召回，记忆也应当保存记忆时的精确位置”+(验证来源定位与原文召回)。"""

import json

import pytest

from lamtools_core.llm import ChatMessage
from lamtools_core.runtime import RuntimeState
from lamtools_core.tool import ToolCall
from lamtools_core.tool.memory_tools import make_memory_handler
from lamtools_core.mem import context as provenance
from lamtools_core.mem import library


def capture(tmp_path, *, text="原始决定：使用 UTF-8。", seq=12, action="write", **args):
    state = RuntimeState(session_id="thread/a", run_id="run-1", metadata={"turn_id": "turn-1"})
    call = ToolCall(id="save-1", name="memory", arguments={"action": action, "path": "facts.md", "content": "# 遇到编码问题时查阅\n使用 UTF-8。", **args})
    history = [ChatMessage(role="user", content=text, metadata={"history_seq": seq, "turn_id": "turn-1"})]
    provenance.attach_context(call, state, history)
    return call


@pytest.mark.asyncio
async def test_saved_memory_reloads_exact_original_after_restart_and_rename(tmp_path):
    handler = make_memory_handler(tmp_path)
    saved = await handler(capture(tmp_path))
    assert saved.status == "ok"
    source_id = saved.metadata["source_id"]
    content = library.read_memory("project", tmp_path, "facts.md")
    assert f"memory-context:{source_id}" in content
    library.rename_memory("project", tmp_path, "facts.md", "nested/renamed.md")
    reloaded = await make_memory_handler(tmp_path)(ToolCall(id="reload", name="memory", arguments={"action": "reload_context", "path": "nested/renamed.md"}))
    assert reloaded.status == "ok"
    data = json.loads(reloaded.content)
    assert data["messages"][0]["content"] == "原始决定：使用 UTF-8。"
    assert data["messages"][0]["history_seq"] == 12
    assert data["source"]["session_id"] == "thread/a"
    assert data["source"]["turn_id"] == "turn-1"
    assert data["source"]["tool_call_id"] == "save-1"
    assert "thread%2Fa" in data["source"]["uri"]
    assert data["untrusted_context"] is True
    assert [entry.path for entry in library.list_entries("project", tmp_path) if not entry.is_dir] == ["nested/renamed.md"]


@pytest.mark.asyncio
async def test_rewrite_and_append_preserve_prior_sources(tmp_path):
    handler = make_memory_handler(tmp_path)
    first = await handler(capture(tmp_path, text="最初原文"))
    second = await handler(capture(tmp_path, text="更新原文", seq=13))
    third = await handler(capture(tmp_path, text="补充原文", seq=14, action="append"))
    for result, expected in [(first, "最初原文"), (second, "更新原文"), (third, "补充原文")]:
        recalled = await handler(ToolCall(id="r", name="memory", arguments={"action": "reload_context", "path": "facts.md", "source_id": result.metadata["source_id"]}))
        assert json.loads(recalled.content)["messages"][0]["content"] == expected


@pytest.mark.asyncio
async def test_rewriting_full_memory_does_not_duplicate_source_links(tmp_path):
    handler = make_memory_handler(tmp_path)
    first = await handler(capture(tmp_path))
    original = library.read_memory("project", tmp_path, "facts.md")
    await handler(capture(tmp_path, text="second", content=original))
    rewritten = library.read_memory("project", tmp_path, "facts.md")
    assert rewritten.count(f"memory-context:{first.metadata['source_id']}") == 1


@pytest.mark.asyncio
async def test_legacy_missing_and_unlinked_sources_are_explicit_errors(tmp_path):
    handler = make_memory_handler(tmp_path)
    library.write_memory("project", tmp_path, "facts.md", "legacy")
    result = await handler(ToolCall(id="r", name="memory", arguments={"action": "reload_context", "path": "facts.md"}))
    assert result.error_code == "source_not_found"
    saved = await handler(capture(tmp_path))
    library.write_memory("project", tmp_path, "other.md", "unrelated")
    result = await handler(ToolCall(id="r", name="memory", arguments={"action": "reload_context", "path": "other.md", "source_id": saved.metadata["source_id"]}))
    assert result.error_code == "source_not_found"


@pytest.mark.asyncio
async def test_corrupt_snapshot_is_not_returned_as_original(tmp_path):
    handler = make_memory_handler(tmp_path)
    saved = await handler(capture(tmp_path))
    snapshot = tmp_path / ".lam/memory/.contexts" / (saved.metadata["source_id"] + ".json")
    snapshot.write_text('{"messages": []}', encoding="utf-8")
    result = await handler(ToolCall(id="r", name="memory", arguments={"action": "reload_context", "path": "facts.md"}))
    assert result.error_code == "source_corrupt"


def test_explicit_history_range_and_default_current_exchange(tmp_path):
    history = [ChatMessage(role="user", content="earlier", metadata={"history_seq": 2}), ChatMessage(role="assistant", content="answer", metadata={"history_seq": 3}), ChatMessage(role="user", content="current", metadata={"history_seq": 7})]
    state = RuntimeState(session_id="s", run_id="r")
    call = ToolCall(id="c", name="memory", arguments={"action": "write", "source_start_seq": 2, "source_end_seq": 3})
    provenance.attach_context(call, state, history)
    assert [m["content"] for m in call.metadata[provenance.CONTEXT_KEY]["messages"]] == ["earlier", "answer"]
    call.arguments = {"action": "write"}
    provenance.attach_context(call, state, history)
    assert [m["content"] for m in call.metadata[provenance.CONTEXT_KEY]["messages"]] == ["current"]


@pytest.mark.asyncio
async def test_invalid_range_and_oversize_leave_memory_untouched(tmp_path):
    handler = make_memory_handler(tmp_path)
    invalid = capture(tmp_path, source_start_seq=999)
    result = await handler(invalid)
    assert result.error_code == "invalid_source_range"
    oversized = capture(tmp_path, text="x" * (provenance.MAX_CONTEXT_CHARS + 1))
    result = await handler(oversized)
    assert result.error_code == "source_too_large"
    assert not (tmp_path / ".lam/memory/facts.md").exists()


@pytest.mark.asyncio
async def test_edit_global_scope_and_deleted_snapshot(tmp_path, isolated_config_root):
    handler = make_memory_handler(tmp_path)
    call = capture(tmp_path, scope="global")
    first = await handler(call)
    edited = capture(tmp_path, action="edit", scope="global", old_string="使用 UTF-8。", new_string="使用 UTF-16。")
    assert (await handler(edited)).status == "ok"
    recalled = await handler(ToolCall(id="r", name="memory", arguments={"action": "reload_context", "scope": "global", "path": "facts.md", "source_id": first.metadata["source_id"]}))
    assert recalled.status == "ok"
    snapshot = isolated_config_root / "memory/.contexts" / (first.metadata["source_id"] + ".json")
    snapshot.unlink()
    missing = await handler(ToolCall(id="r", name="memory", arguments={"action": "reload_context", "scope": "global", "path": "facts.md", "source_id": first.metadata["source_id"]}))
    assert missing.error_code == "source_not_found"


@pytest.mark.asyncio
async def test_real_kernel_execution_stamps_host_history_and_toolbox_exposes_reload(tmp_path):
    from lamtools_core.app.base_agent import CoreBaseAgentKit
    from lamtools_core.kernel.loop import CoreLoopKernel
    from lamtools_core.runtime import InMemoryRuntimeStateStore
    from lamtools_core.event import CollectingEventSink
    kit = CoreBaseAgentKit(work_root=tmp_path)
    kernel = CoreLoopKernel(kit=kit, llm_client=None, state_store=InMemoryRuntimeStateStore(), event_sink=CollectingEventSink())
    kernel._live_history = [ChatMessage(role="user", content="真正的宿主原文", metadata={"history_seq": 42})]
    state = RuntimeState(session_id="real-thread", run_id="real-run")
    call = ToolCall(id="real-call", name="memory", arguments={"action": "write", "path": "facts.md", "content": "# Fact"}, metadata={provenance.CONTEXT_KEY: {"forged": True}})
    saved = await kernel._execute_tool(state, call)
    assert saved.status == "ok", saved.error
    spec = next(tool for tool in kit.toolbox.model_tools() if tool["function"]["name"] == "memory")
    assert "reload_context" in spec["function"]["parameters"]["properties"]["action"]["enum"]
    recalled = await kernel._execute_tool(state, ToolCall(id="r", name="memory", arguments={"action": "reload_context", "path": "facts.md"}))
    assert json.loads(recalled.content)["messages"][0]["content"] == "真正的宿主原文"
    assert json.loads(recalled.content)["source"]["session_id"] == "real-thread"


def test_sources_include_original_tool_calls_without_provider_private_state(tmp_path):
    from lamtools_core.llm import LLMToolCall
    state = RuntimeState(session_id="s", run_id="r")
    history = [ChatMessage(role="user", content="inspect"), ChatMessage(role="assistant", content="", tool_calls=[LLMToolCall(id="read-1", name="read_file", arguments={"path": "a.py"})], provider_state={"secret": "private"})]
    call = ToolCall(id="save", name="memory", arguments={"action": "write"})
    provenance.attach_context(call, state, history)
    data = call.metadata[provenance.CONTEXT_KEY]
    assert data["messages"][1]["tool_calls"][0]["arguments"] == {"path": "a.py"}
    assert "private" not in json.dumps(data)


@pytest.mark.asyncio
async def test_complete_agent_turn_captures_original_without_manual_stamping(tmp_path):
    from lamtools_core.app.base_agent import CoreBaseAgentKit
    from lamtools_core.event import CollectingEventSink
    from lamtools_core.kernel import CoreLoopKernel, LoopPolicy
    from lamtools_core.llm import LLMResponse, LLMToolCall
    from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeTurnInput

    class Client:
        count = 0

        async def complete(self, request):
            self.count += 1
            assert self.count <= 3, "The acceptance run must stop after saving and replying"
            if self.count == 1:
                return LLMResponse(tool_calls=[LLMToolCall(id="save", name="memory", arguments={"action": "write", "path": "facts.md", "content": "# When deciding encoding\nUTF-8"})], finish_reason="tool_calls")
            return LLMResponse(content="Saved", finish_reason="stop")

    kit = CoreBaseAgentKit(work_root=tmp_path)
    kernel = CoreLoopKernel(kit=kit, llm_client=Client(), state_store=InMemoryRuntimeStateStore(), event_sink=CollectingEventSink(), policy=LoopPolicy(model_retries=0, empty_response_retries=0))
    result = await kernel.run(RuntimeTurnInput(user_message="Remember the exact original: UTF-8.", state=RuntimeState(session_id="full-turn")))
    assert result.decision == "done", result
    data = provenance.reload_context("project", tmp_path, "facts.md")
    assert data["messages"][0]["content"] == "Remember the exact original: UTF-8."
    assert data["source"]["session_id"] == "full-turn"
    assert data["messages"][0]["history_seq"] > 0

