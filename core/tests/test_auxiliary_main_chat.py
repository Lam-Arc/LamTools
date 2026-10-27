"""Main-chat context inheritance and hard read-only auxiliary tools."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json
import pytest

from lamtools_core.app.auxiliary_chat import prepare_auxiliary_runtime, lock_auxiliary_toolbox, main_chat_page, bind_auxiliary_session
from lamtools_core.app.live.turn_options import _resolve_turn_approval_policy, _queue_runtime_snapshot
from lamtools_core.tool.default_toolbox import build_core_toolbox
from lamtools_core.tool import ToolCall
from lamtools_core.app.default_agent import _runtime_snapshot_from_payload, _build_core_runtime_toolbox


def context():
    sessions = {
        "aux": SimpleNamespace(id="aux", metadata={"ui_surface": "auxiliary", "parent_session_id": "main", "auxiliary_additional_information": {"selected_text": "Selected passage"}}),
        "main": SimpleNamespace(id="main", title="Source discussion", metadata={}),
    }
    history = [{"role": "user", "content": "Main task: compare two designs"}, {"role": "assistant", "content": "Design A is simpler"}]
    store = SimpleNamespace(get=AsyncMock(side_effect=lambda key: sessions.get(key)))
    states = SimpleNamespace(get_history=AsyncMock(side_effect=lambda key: history if key == "main" else []), get=AsyncMock(return_value=SimpleNamespace(status="running", metadata={"plan": {"step": "Compare"}})))
    return SimpleNamespace(host=SimpleNamespace(session_store=store), runtime_state_store=states, operations=SimpleNamespace(has=lambda _: False)), sessions, history


# user:“做成真正的“主聊天助手””+(每轮使用来源的最新语义历史，附加选文与问题正文分离，读取不改变主会话)。
@pytest.mark.asyncio
async def test_parent_context_is_fresh_and_additional_information_is_separate():
    ctx, sessions, history = context()
    original = {"thread_id": "aux", "text": "Which one should I choose?", "active_mode": "execute", "permission_preset": "full_access"}
    first = await prepare_auxiliary_runtime(ctx, original)
    payload = first["request_local_late_context"]
    assert "Main task: compare two designs" in payload
    assert "Selected passage" in payload
    assert "[Additional information]" in payload
    assert first["text"] == original["text"]
    assert first["active_mode"] == "consider"
    assert first["active_tier"] == "read_only"
    assert first["runtime_snapshot"]["auxiliary_read_only"] is True
    assert original["active_mode"] == "execute"
    history.append({"role": "assistant", "content": "New finding: Design B is faster"})
    second = await prepare_auxiliary_runtime(ctx, original)
    assert "Design B is faster" in second["request_local_late_context"]
    assert sessions["main"].metadata == {}


@pytest.mark.asyncio
async def test_missing_source_fails_instead_of_using_another_chat():
    ctx, sessions, _ = context()
    del sessions["main"]
    with pytest.raises(ValueError, match="来源"):
        await prepare_auxiliary_runtime(ctx, {"thread_id": "aux", "source_session_id": "unrelated"})


@pytest.mark.asyncio
async def test_ordinary_chat_is_untouched_and_empty_source_stays_read_only():
    ctx, sessions, _ = context()
    ordinary = {"thread_id": "main", "text": "continue", "active_mode": "execute"}
    assert await prepare_auxiliary_runtime(ctx, ordinary) == ordinary
    sessions["aux"].metadata["parent_session_id"] = ""
    isolated = await prepare_auxiliary_runtime(ctx, {"thread_id": "aux", "text": "hello"})
    assert isolated["active_mode"] == "consider"


@pytest.mark.asyncio
async def test_client_and_global_full_access_cannot_override_auxiliary_mode():
    ctx, sessions, _ = context()
    sessions["aux"].metadata["runtime_preferences"] = {"permission_preset": "full_access", "base_tier": "full_edit", "base_allow_access_outside_workdir": True}
    result = await _resolve_turn_approval_policy(context=ctx, params={"thread_id": "aux", "active_mode": "execute", "permission_preset": "full_access", "active_tier": "full_edit"})
    assert result["active_mode"] == "consider"
    assert result["active_tier"] == "read_only"
    assert result["runtime_snapshot"]["auxiliary_read_only"] is True


# user:“工具组可以用consider模式（只读）”+(工具名白名单在真正执行时也生效，伪造审批或自动访问不能打开写入能力)。
@pytest.mark.asyncio
@pytest.mark.parametrize("name,args", [("write_file", {"path": "bad.txt", "content": "bad"}), ("run_command", {"command": "echo bad"}), ("memory", {"action": "write", "content": "bad"}), ("message", {"action": "send", "content": "bad"}), ("sub_agent", {"type": "execute"})])
async def test_mutating_tools_are_hard_blocked(tmp_path, name, args):
    toolbox = build_core_toolbox(work_root=tmp_path, permission_preset="full_access", approval_policy="auto_approve")
    lock_auxiliary_toolbox(toolbox)
    toolbox.agent_tool_whitelist = None  # Simulate a plugin rebuilding its own agent plan.
    toolbox.active_mode = "execute"
    result = await toolbox.execute(ToolCall(id="call", name=name, arguments=args, metadata={"approval": {"blocked": False}}))
    assert result.status == "blocked"
    assert not (tmp_path / "bad.txt").exists()
    assert name not in {tool["function"]["name"] for tool in toolbox.model_tools(active_mode="execute")}


@pytest.mark.asyncio
async def test_read_tool_stays_usable(tmp_path):
    (tmp_path / "note.txt").write_text("readable", encoding="utf-8")
    toolbox = build_core_toolbox(work_root=tmp_path, permission_preset="full_access", approval_policy="auto_approve")
    lock_auxiliary_toolbox(toolbox)
    result = await toolbox.execute(ToolCall(id="read", name="read_file", arguments={"path": "note.txt"}))
    assert result.status == "ok" and "readable" in result.content


def test_history_pagination_does_not_lose_the_middle_of_a_large_tool_result():
    text = "ab中" * 12000
    history = [{"role": "tool", "content": text}, {"role": "assistant", "content": "done"}]
    cursor, collected = {}, ""
    for _ in range(50):
        page = main_chat_page(history, **cursor, max_chars=2048)
        collected += "".join(row["content"] for row in page["messages"])
        if not page["next_cursor"]: break
        cursor = page["next_cursor"]
    assert collected == text + "done"


def test_capability_and_source_survive_approval_snapshot_reconstruction():
    snapshot = {"active_mode": "consider", "active_tier": "read_only", "permission_preset": "ask", "approval_policy": "require", "allow_access_outside_workdir": False,
        "tier_tools": {"read_only": ["read_file"], "limited_edit": [], "full_edit": []}, "auxiliary_read_only": True, "auxiliary_parent_session_id": "main", "instructions": "helper role", "request_local_late_context": "fresh source"}
    rebuilt = _runtime_snapshot_from_payload({"runtime_snapshot": snapshot})
    assert rebuilt["auxiliary_read_only"] is True
    assert rebuilt["auxiliary_parent_session_id"] == "main"
    assert rebuilt["instructions"] == "helper role"
    assert rebuilt["request_local_late_context"] == "fresh source"


@pytest.mark.asyncio
async def test_real_toolbox_contains_bound_read_main_chat_and_blocks_writes(tmp_path):
    ctx, _, history = context()
    prepared = await prepare_auxiliary_runtime(ctx, {"thread_id": "aux", "text": "inspect"})
    toolbox, registry = await _build_core_runtime_toolbox(work_root=tmp_path, plugin_assembly={}, approval_policy="require", active_mode="consider", runtime_snapshot=prepared["runtime_snapshot"], sub_agent_state_store=ctx.runtime_state_store)
    try:
        assert "read_main_chat" in {tool["function"]["name"] for tool in toolbox.model_tools(active_mode="consider")}
        result = await toolbox.execute(ToolCall(id="main-read", name="read_main_chat", arguments={"offset": 0}))
        assert result.status == "ok", result.error
        content = json.loads(result.content)
        assert content["source_session_id"] == "main"
        assert "Main task" in content["messages"][0]["content"]
        history.append({"role": "assistant", "content": "new result"})
        stale = await toolbox.execute(ToolCall(id="stale", name="read_main_chat", arguments={"expected_version": content["version"]}))
        assert stale.status == "failed" and "changed" in stale.error
        blocked = await toolbox.execute(ToolCall(id="blocked", name="write_file", arguments={"path": "no.txt", "content": "no"}))
        assert blocked.status == "blocked" and not (tmp_path / "no.txt").exists()
    finally:
        await registry.close()


@pytest.mark.asyncio
async def test_model_request_receives_context_and_supplement_without_rewriting_user_history(tmp_path):
    from lamtools_core.app.base_agent import CoreBaseAgentKit, CoreBaseAgentConfig
    from lamtools_core.llm import ChatMessage
    from lamtools_core.prompt import PromptContext
    from lamtools_core.runtime import RuntimeState
    ctx, _, _ = context()
    prepared = await prepare_auxiliary_runtime(ctx, {"thread_id": "aux", "text": "My actual question"})
    toolbox = build_core_toolbox(work_root=tmp_path)
    lock_auxiliary_toolbox(toolbox)
    kit = CoreBaseAgentKit(work_root=tmp_path, toolbox=toolbox, config=CoreBaseAgentConfig(active_mode="consider", instructions=prepared["instructions"], request_local_late_context=prepared["request_local_late_context"]))
    history = [ChatMessage(role="user", content="My actual question")]
    prompt = PromptContext(session_id="aux", history=history)
    request = await kit.build_model_request(RuntimeState(session_id="aux", metadata={"runtime_snapshot": prepared["runtime_snapshot"]}), prompt)
    body = "\n".join(str(message.content) for message in request.messages)
    assert "Main task: compare two designs" in body and "Selected passage" in body
    assert "[Additional information]" in body
    assert any(message.content == "My actual question" for message in request.messages)
    assert len(history) == 1 and history[0].content == "My actual question"


@pytest.mark.asyncio
async def test_main_tool_calls_and_compaction_summaries_remain_visible_to_assistant():
    ctx, _, history = context()
    history[:] = [{"role": "system", "content": "Earlier discussion summary: chosen design A"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "internal-id", "name": "read_file", "arguments": {"path": "src/main.py"}}]},
        {"role": "tool", "tool_call_id": "internal-id", "content": "implementation evidence"}]
    prepared = await prepare_auxiliary_runtime(ctx, {"thread_id": "aux", "text": "what was read?"})
    content = prepared["request_local_late_context"]
    assert "chosen design A" in content
    assert "read_file" in content and "src/main.py" in content and "implementation evidence" in content
    assert "internal-id" not in content
    assert history[1]["content"] == ""


@pytest.mark.asyncio
async def test_queue_snapshots_keep_source_capability_and_additional_information():
    ctx, _, _ = context()
    prepared = await prepare_auxiliary_runtime(ctx, {"thread_id": "aux", "text": "question"})
    snapshot = {**prepared["runtime_snapshot"], "auxiliary_additional_information": {"selected_text": "extra"}}
    queued = _queue_runtime_snapshot({"runtime_snapshot": snapshot})
    assert queued["auxiliary_read_only"] is True
    assert queued["auxiliary_parent_session_id"] == "main"
    assert queued["auxiliary_additional_information"]["selected_text"] == "extra"


@pytest.mark.asyncio
async def test_source_project_and_read_only_settings_are_bound_at_creation():
    ctx, sessions, _ = context()
    sessions["main"].metadata = {"work_root": "E:/source", "project_id": "source-project"}
    child = sessions["aux"]
    child.metadata.update(work_root="E:/different-project", model_id="chosen-helper-model", runtime_preferences={"permission_preset": "full_access"})
    await bind_auxiliary_session(ctx.host.session_store, child)
    assert child.metadata["work_root"] == "E:/source"
    assert child.metadata["project_id"] == "source-project"
    assert child.metadata["model_id"] == "chosen-helper-model"
    assert child.metadata["runtime_preferences"]["base_tier"] == "read_only"
    prepared = await prepare_auxiliary_runtime(ctx, {"thread_id": "aux", "work_root": "E:/wrong"})
    assert prepared["work_root"] == "E:/source"
    assert sessions["main"].metadata == {"work_root": "E:/source", "project_id": "source-project"}


@pytest.mark.asyncio
async def test_database_creation_and_context_inheritance_leave_source_history_unchanged(tmp_path):
    from lamtools_core.app.core_db import open_core_app_db
    from lamtools_core.app.core_session_store import CoreDbSessionStore
    from lamtools_core.session import SessionRecord
    from lamtools_core.runtime import RuntimeState
    db = await open_core_app_db(tmp_path / "helper.db", project_roots=[])
    try:
        store = CoreDbSessionStore(lambda: db)
        parent = await store.create(SessionRecord(id="main", member_id="core", title="Main", status="idle", metadata={"work_root": str(tmp_path)}))
        await db.runtime_state_store.save(RuntimeState(session_id="main", status="completed"))
        await db.runtime_state_store.append_history("main", [{"role": "user", "content": "Persisted source task"}, {"role": "assistant", "content": "Persisted evidence"}])
        before = await db.runtime_state_store.get_history("main")
        child = await store.create(SessionRecord(id="aux", member_id="core", title="Helper", status="idle", metadata={"ui_surface": "auxiliary", "parent_session_id": "main", "work_root": "wrong"}))
        assert child.metadata["work_root"] == str(tmp_path)
        assert child.metadata["runtime_preferences"]["base_tier"] == "read_only"
        ctx = SimpleNamespace(host=SimpleNamespace(session_store=store), runtime_state_store=db.runtime_state_store)
        prepared = await prepare_auxiliary_runtime(ctx, {"thread_id": "aux", "text": "Explain"})
        assert "Persisted source task" in prepared["request_local_late_context"]
        assert "Persisted evidence" in prepared["request_local_late_context"]
        assert await db.runtime_state_store.get_history("main") == before
        assert (await store.get("main")).metadata == parent.metadata
    finally:
        await db.close()
