from __future__ import annotations

import json

import pytest

from lamtools_core.app.default_agent import (
    CoreAgentPaths,
    CoreAgentSpec,
    _persist_core_event_live,
    create_core_agent_operations,
)
from lamtools_core.app.operation_catalog import OperationResult
from lamtools_core.app import command_execution
from lamtools_core.context_compaction import CompactionExecution, ContextCompactionResult
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.base_agent import build_core_plugin_operation_catalog, core_events_to_run_items
from lamtools_core.event import CoreEvent
from lamtools_core.llm import ChatMessage, LLMRequest, LLMResponse, LLMStreamEvent, LLMToolCall
from lamtools_core.llm.shallow_thinking import SHALLOW_THINKING_PROMPT
from lamtools_core.plugins.hook_config import HookRegistry
from lamtools_core.plugins.registry import PluginRegistry, PluginStateStore
from lamtools_core.plugins.trust import HookTrustStore
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState


async def _fake_model(turn):
    from lamtools_core.app import ModelTurnOutput

    return ModelTurnOutput(message=f"core handled: {turn.user_message}")


def test_core_event_projection_preserves_canonical_live_turn_id():
    turn_id = "thread-live:turn:turn-1"
    items = core_events_to_run_items(
        [
            CoreEvent(
                name="runtime.cancelled",
                category="lifecycle",
                session_id="thread-live",
                run_id=turn_id,
                payload={"message": "approval denied"},
            )
        ],
        thread_id="thread-live",
    )

    assert {item.turn_id for item in items} == {turn_id}


@pytest.mark.asyncio
async def test_transient_model_delta_reaches_live_hub_without_becoming_history():
    hub = CoreAppEventHub()
    queue = hub.subscribe("thread-live")
    event = CoreEvent(
        name="runtime.reply_delta",
        category="message",
        session_id="thread-live",
        run_id="run-live",
        payload={
            "content": "hel",
            "part_id": "run-live:response-0:text",
            "response_index": 0,
        },
        metadata={"delivery": "transient"},
    )

    await _persist_core_event_live(
        event,
        thread_id="thread-live",
        db_session_factory=None,
        app_event_store=None,
        thread_snapshot_store=None,
        app_event_hub=hub,
    )

    published = queue.get_nowait()
    assert published.method == "core/runItem"
    assert published.seq == 0
    assert published.payload["payload"]["delta"] == "hel"
    assert core_events_to_run_items([event], thread_id="thread-live") == []


def test_transient_reasoning_delta_projects_as_append_only_run_item():
    event = CoreEvent(
        name="runtime.part",
        category="message",
        session_id="thread-live",
        run_id="run-live",
        payload={
            "part_id": "run-live:response-0:reasoning",
            "part_type": "reasoning",
            "status": "running",
            "delta": "think ",
        },
        metadata={"delivery": "transient"},
    )

    items = core_events_to_run_items(
        [event],
        thread_id="thread-live",
        include_transient=True,
    )

    assert len(items) == 1
    assert items[0].payload["delta"] == "think "
    assert "content" not in items[0].payload


class ScriptedCoreAgentLLM:
    def __init__(self, *, path: str = "input.txt") -> None:
        self.requests: list[LLMRequest] = []
        self.path = path

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("core agent operation should use streaming when available")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield LLMStreamEvent(kind="thinking_delta", content="Need to inspect the file.")
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(id="call-read", name="read_file", arguments={"path": self.path}),
                ],
            )
            return
        yield LLMStreamEvent(kind="content_delta", content="The file says hello core.")
        yield LLMStreamEvent(kind="done")


class ScriptedApprovalLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("core agent operation should use streaming when available")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield LLMStreamEvent(kind="thinking_delta", content="Need approval before writing.")
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="call-write",
                        name="write_file",
                        arguments={"path": "approved.md", "content": "approved content\n"},
                    ),
                ],
            )
            return
        yield LLMStreamEvent(kind="content_delta", content="Saved approved.md.")
        yield LLMStreamEvent(kind="done")


class ScriptedRejectedLegacySubAgentLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("core agent operation should use streaming when available")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="call-parent-sub-agent",
                        name="sub_agent",
                        arguments={"task": "write two delegated files", "agent": "writer"},
                    )
                ],
            )
            return
        tool_messages = [message for message in request.messages if message.role == "tool"]
        assert tool_messages
        assert "requires exactly" in tool_messages[-1].content.lower()
        yield LLMStreamEvent(kind="content_delta", content="Legacy delegation was rejected.")
        yield LLMStreamEvent(kind="done")


class ScriptedLoadSkillLLM:
    def __init__(self, *, skill_name: str = "sample") -> None:
        self.requests: list[LLMRequest] = []
        self.skill_name = skill_name

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("core agent operation should use streaming when available")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            tool_names = {tool["function"]["name"] for tool in request.tools or []}
            assert "load_skill" in tool_names
            assert "Available skills:" in request.messages[0].content
            assert f"- {self.skill_name}:" in request.messages[0].content
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="call-skill",
                        name="load_skill",
                        arguments={"name": self.skill_name},
                    )
                ],
            )
            return
        yield LLMStreamEvent(kind="content_delta", content=f"Loaded {self.skill_name} skill.")
        yield LLMStreamEvent(kind="done")


class CapturingCoreAgentLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("core agent operation should use streaming when available")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        yield LLMStreamEvent(kind="content_delta", content="done")
        yield LLMStreamEvent(kind="done")


@pytest.mark.asyncio
async def test_core_agent_runs_independent_turn_with_in_memory_store(tmp_path):
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path, work_root=tmp_path),
        model_provider=_fake_model,
    )

    result = await catalog.execute(
        "turn.start",
        {"thread_id": "thread-1", "message": "do work"},
    )

    assert result.status == "ok"
    assert result.payload["message"] == "core handled: do work"
    assert result.payload["snapshot"]["thread_id"] == "thread-1"
    assert result.payload["snapshot"]["status"] == "completed"


@pytest.mark.asyncio
async def test_core_agent_operations_expose_turn_start(tmp_path):
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path, work_root=tmp_path),
        model_provider=_fake_model,
    )

    assert catalog.has("turn.start")
    assert "turn.start" in catalog.list()


@pytest.mark.asyncio
async def test_disabled_workflow_operation_is_mounted_for_live_reenable(tmp_path, monkeypatch):
    """The host catalog must expose a disabled plugin after it is re-enabled."""
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    data_dir = tmp_path / "data"
    PluginStateStore(data_dir / "plugins.jsonc").set_enabled("workflow", False)
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=data_dir, work_root=tmp_path / "work"),
        model_provider=_fake_model,
    )

    assert not catalog.has("workflow.run")
    enabled = await catalog.execute("plugin.enable", {"name": "workflow"})
    assert enabled.payload["enabled"] is True
    assert catalog.has("workflow.run")

    created = await catalog.execute("workflow.create", {"name": "live-reenable", "nodes": []})
    assert created.status == "ok"
    run = await catalog.execute("workflow.run", {"name": "live-reenable", "run_id": "live-run"})
    assert run.payload["run"]["status"] == "completed"

    await catalog.execute("plugin.disable", {"name": "workflow"})
    assert not catalog.has("workflow.run")


def test_core_agent_operations_include_core_plugin_and_hook_catalog(tmp_path):
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path),
        model_provider=_fake_model,
    )

    assert {"plugin.list", "plugin.enable", "plugin.disable", "hook.list", "hook.trust"} <= set(catalog.list())


@pytest.mark.asyncio
async def test_core_agent_operations_expose_command_catalog(tmp_path):
    core_root = tmp_path / "core-root"
    command_dir = core_root / "config" / "command"
    command_dir.mkdir(parents=True)
    (command_dir / "inspect.json").write_text(
        json.dumps(
            {
                "name": "inspect",
                "title": "Inspect",
                "description": "Inspect context",
                "icon": "search",
                "action": "insert_token",
            }
        ),
        encoding="utf-8",
    )
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=_fake_model,
        command_core_roots=[core_root],
    )

    result = await catalog.execute("command.catalog", {})

    assert result.status == "ok"
    commands = {item["name"]: item for item in result.payload["commands"]}
    assert commands["inspect"] == {
        "name": "inspect",
        "title": "Inspect",
        "description": "Inspect context",
        "icon": "search",
        "action": "insert_token",
        "source": "core",
        "kind": "skill",
        "accepts_args": False,
    }


@pytest.mark.asyncio
async def test_core_agent_catalog_filters_disabled_skills(tmp_path):
    work_root = tmp_path / "work"
    skill_file = work_root / ".lam" / "skills" / "reviewer" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(
        "---\nname: reviewer\ndescription: Review changes\n---\n\nReview instructions\n",
        encoding="utf-8",
    )
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
        model_provider=_fake_model,
    )

    before = await catalog.execute("command.catalog", {})
    assert any(item["name"] == "reviewer" for item in before.payload["commands"])

    await catalog.execute("skill.disable", {"name": "reviewer"})
    after = await catalog.execute("command.catalog", {})

    assert all(item["name"] != "reviewer" for item in after.payload["commands"])


@pytest.mark.asyncio
async def test_enabled_plugin_command_is_catalogued_and_returns_validated_effect(tmp_path):
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=_fake_model,
    )

    listed = await catalog.execute("command.catalog", {})
    pet = next(item for item in listed.payload["commands"] if item["name"] == "pet")
    assert pet["source"] == "plugin"
    assert pet["metadata"]["plugin_id"] == "emotion-ball-pet"

    executed = await catalog.execute(
        "command.execute",
        {"thread_id": "thread-pet", "command": "pet"},
    )

    assert executed.status == "ok"
    assert executed.payload["result"]["effects"] == [{
        "type": "desktop_plugin",
        "action": "show",
        "plugin_id": "emotion-ball-pet",
    }]

    await catalog.execute("plugin.disable", {"name": "emotion-ball-pet"})
    disabled = await catalog.execute("command.catalog", {})
    assert all(item["name"] != "pet" for item in disabled.payload["commands"])


@pytest.mark.asyncio
async def test_core_agent_command_execute_passes_arguments_to_action_handler(tmp_path):
    core_root = tmp_path / "core-root"
    command_dir = core_root / "config" / "command"
    command_dir.mkdir(parents=True)
    (command_dir / "goal.json").write_text(
        json.dumps(
            {
                "name": "goal",
                "title": "Goal",
                "description": "Create a goal",
                "icon": "target",
                "kind": "action",
                "action": "run_action",
                "accepts_args": True,
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, str] = {}

    async def goal_action(*, thread_id: str, arguments: str, work_root: str, **_: object):
        captured.update(thread_id=thread_id, arguments=arguments, work_root=work_root)
        return {"status": "created", "objective": arguments}

    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=_fake_model,
        command_core_roots=[core_root],
        command_action_handlers={"goal": goal_action},
    )

    result = await catalog.execute(
        "command.execute",
        {
            "thread_id": "thread-goal",
            "command": "goal",
            "arguments": "创建发布计划",
            "work_root": str(tmp_path / "workspace"),
        },
    )

    assert result.status == "ok"
    assert result.payload["result"] == {"status": "created", "objective": "创建发布计划"}
    assert captured == {
        "thread_id": "thread-goal",
        "arguments": "创建发布计划",
        "work_root": str(tmp_path / "workspace"),
    }


@pytest.mark.asyncio
async def test_core_agent_command_execute_rejects_skill_commands(tmp_path):
    core_root = tmp_path / "core-root"
    command_dir = core_root / "config" / "command"
    command_dir.mkdir(parents=True)
    (command_dir / "review.json").write_text(
        json.dumps(
            {
                "name": "review",
                "title": "Review",
                "description": "Review changes",
                "icon": "scan",
                "kind": "skill",
                "action": "insert_token",
                "accepts_args": True,
            }
        ),
        encoding="utf-8",
    )
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=_fake_model,
        command_core_roots=[core_root],
    )

    result = await catalog.execute(
        "command.execute",
        {"thread_id": "thread-review", "command": "review"},
    )

    assert result.status == "error"
    assert result.payload["error"] == "Command is not executable as an action: review"


@pytest.mark.asyncio
async def test_core_agent_fork_command_delegates_to_session_fork_operation(tmp_path):
    core_root = tmp_path / "core-root"
    command_dir = core_root / "config" / "command"
    command_dir.mkdir(parents=True)
    (command_dir / "fork.json").write_text(
        json.dumps(
            {
                "name": "fork",
                "title": "Fork",
                "description": "Fork session",
                "icon": "git-branch",
                "kind": "action",
                "action": "run_action",
                "accepts_args": False,
            }
        ),
        encoding="utf-8",
    )
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=_fake_model,
        command_core_roots=[core_root],
    )
    calls: list[dict[str, object]] = []

    async def session_fork(request):
        calls.append(dict(request.payload))
        return OperationResult(name=request.name, payload={"session_id": "forked-thread"})

    catalog.register("session.fork", session_fork)

    result = await catalog.execute(
        "command.execute",
        {"thread_id": "thread-source", "command": "fork"},
    )

    assert result.status == "ok"
    assert result.payload["result"] == {"session_id": "forked-thread"}
    assert calls == [{"thread_id": "thread-source"}]


@pytest.mark.asyncio
async def test_core_agent_command_execute_compacts_runtime_history(tmp_path):
    core_root = tmp_path / "core-root"
    command_dir = core_root / "config" / "command"
    command_dir.mkdir(parents=True)
    (command_dir / "compact.json").write_text(
        json.dumps(
            {
                "name": "compact",
                "title": "Compact",
                "description": "Compact context",
                "icon": "archive",
                "action": "run_action",
            }
        ),
        encoding="utf-8",
    )
    state_store = InMemoryRuntimeStateStore()
    state = RuntimeState(
        session_id="thread-compact",
        metadata={"context_window_tokens": 8_000},
    )
    history = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"message-{index}"}
        for index in range(8)
    ]
    await state_store.save_checkpoint(state, history)
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=_fake_model,
        command_core_roots=[core_root],
        runtime_state_store=state_store,
    )

    result = await catalog.execute(
        "command.execute",
        {"thread_id": "thread-compact", "command": "compact"},
    )

    assert result.status == "ok"
    assert result.payload["result"]["status"] == "not_needed"
    compacted_history = await state_store.get_history("thread-compact")
    assert compacted_history == history


@pytest.mark.asyncio
async def test_manual_compaction_uses_session_model_and_safe_segment_input_limit(monkeypatch):
    class RuntimeProvider:
        def __init__(self):
            self.options = None

        def with_runtime_options(self, **options):
            self.options = options
            return self

    provider = RuntimeProvider()
    state_store = InMemoryRuntimeStateStore()
    state = RuntimeState(
        session_id="thread-large-compact",
        metadata={
            "model_id": "session-model",
            "context_window_tokens": 256_000,
            "max_tokens": 25_565,
            "runtime_snapshot": {
                "model_id": "session-model",
                "reasoning_level": "light",
                "thinking_enabled": True,
                "thinking_budget": 10_000,
            },
            "runtime_context_metrics": {
                "context_window_tokens": 230_435,
                "total_context_window_tokens": 256_000,
                "reserved_output_tokens": 25_565,
            },
            "context_compaction": {"summary": "previous compacted summary"},
        },
    )
    await state_store.save_checkpoint(
        state,
        [{"role": "user", "content": "large history"}],
    )
    captured = {}

    async def capture(self, messages, **kwargs):
        captured["controller"] = self
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return CompactionExecution(
            result=ContextCompactionResult(
                status="not_needed",
                trigger="manual",
                display_payload={"status": "not_needed", "reason": "no_gain"},
            ),
            measurement=kwargs["measurement"],
        )

    monkeypatch.setattr(command_execution.ContextCompactionController, "compact", capture)

    await command_execution.compact_runtime_history(
        runtime_state_store=state_store,
        thread_id=state.session_id,
        llm_client=provider,
        model="default-model",
    )

    kwargs = captured["kwargs"]
    assert kwargs["current_model"] == "session-model"
    assert kwargs["force"] is True
    assert kwargs["budget"].context_window == 230_435
    assert kwargs["budget"].trigger_tokens == 184_348
    assert kwargs["budget"].target_tokens == 138_261
    assert captured["controller"]._summary_output_tokens is None
    assert captured["messages"][0].metadata["key"] == "context_compaction_summary"
    assert captured["messages"][0].content == "previous compacted summary"
    assert provider.options == {
        "model_id": "session-model",
        "reasoning_level": "light",
        "thinking_enabled": True,
        "thinking_budget": 10_000,
    }


class _ManualCompactionLLM:
    def __init__(self) -> None:
        self.last_request = None

    async def complete(self, request):
        self.last_request = request
        return LLMResponse(
            content=(
                "[Compacted Context]\n"
                "1. Current Objective And Done Criteria\n- Continue.\n\n"
                "2. Active User Instructions\n- Preserve constraints.\n\n"
                "3. External Action Authorization\n- None confirmed.\n\n"
                "4. Confirmed Facts And Decisions\n- None.\n\n"
                "5. Current Execution State\n- Manual compaction.\n\n"
                "6. Verification Evidence\n- None.\n\n"
                "7. Open Issues, Risks, And Hypotheses\n- None.\n\n"
                "8. Rejected Or Superseded Directions\n- None.\n\n"
                "9. Next Actions\n- Continue."
            ),
            finish_reason="stop",
        )

    async def stream(self, request):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_manual_compaction_anchors_boundary_at_first_retained_message():
    class TrackingStore(InMemoryRuntimeStateStore):
        def __init__(self):
            super().__init__()
            self.history_requests: list[int] = []

        async def get_history(self, session_id, *, after_seq=0):
            self.history_requests.append(after_seq)
            return await super().get_history(session_id, after_seq=after_seq)

    store = TrackingStore()
    state = RuntimeState(
        session_id="thread-manual-anchor",
        metadata={"context_window_tokens": 256_000},
    )
    # The planner protects the latest twenty user messages by default; keep
    # one older span so this manual-boundary test reaches the compaction path.
    history = [
        {"role": "user", "content": f"old message {index} " + ("x" * 5000)}
        for index in range(25)
    ]
    await store.save_checkpoint(state, history)
    llm = _ManualCompactionLLM()

    result = await command_execution.compact_runtime_history(
        runtime_state_store=store,
        thread_id="thread-manual-anchor",
        llm_client=llm,
        model="mock-model",
    )

    assert result["status"] == "compacted"
    saved = await store.get("thread-manual-anchor")
    compaction = saved.metadata["context_compaction"]
    boundary = compaction["summary_seq"]
    # Default zero-Step retention summarizes the complete durable transcript;
    # manual compaction leaves durable rows untouched and records the current
    # high-water mark so a subsequent loader can legitimately return no rows.
    stored_history = await store.get_history("thread-manual-anchor")
    assert boundary == await store.history_max_seq("thread-manual-anchor")
    assert boundary == len(stored_history)
    assert stored_history == history
    # Summary rows never leak into persisted history.
    assert all(
        item.get("metadata", {}).get("key") != "context_compaction_summary"
        for item in stored_history
    )

    # An empty incremental tail at the current max sequence is valid; the
    # effective-history loader must not fall back to the full legacy blob.
    store.history_requests.clear()
    effective = await command_execution._load_effective_compaction_history(
        store,
        "thread-manual-anchor",
        saved.metadata,
    )
    assert store.history_requests == [boundary]
    assert len(effective) == 1
    assert effective[0].metadata["key"] == "context_compaction_summary"


@pytest.mark.asyncio
async def test_repeated_manual_compaction_preserves_prior_compacted_sequences_and_retained_tail(
    monkeypatch,
):
    state_store = InMemoryRuntimeStateStore()
    state = RuntimeState(
        session_id="thread-manual-repeat",
        metadata={
            "context_window_tokens": 256_000,
            "runtime_audit": {"loop_policy": {"compact_retained_steps": 2}},
        },
    )
    await state_store.save_checkpoint(
        state,
        [
            {"role": "user", "content": f"message-{seq}"}
            for seq in range(1, 8)
        ],
    )
    calls: list[list[ChatMessage]] = []

    async def fake_compact(self, messages, **kwargs):
        _ = self
        calls.append(list(messages))
        by_seq = {
            int(message.metadata["history_seq"]): message
            for message in messages
            if isinstance(message.metadata.get("history_seq"), int)
        }
        summary = ChatMessage(
            role="system",
            content=f"summary-{len(calls)}",
            metadata={"key": "context_compaction_summary"},
        )
        if len(calls) == 1:
            compacted = [by_seq[seq] for seq in (1, 2, 3, 4, 7)]
            retained = [by_seq[seq] for seq in (5, 6)]
        elif len(calls) == 2:
            # The second run may compact only the prior summary, which has no
            # durable history_seq.  The retained rows must still anchor the
            # boundary and the first run's folded set must remain persisted.
            assert [message.metadata["history_seq"] for message in messages[1:]] == [5, 6, 8]
            compacted = [messages[0]]
            retained = list(messages[1:])
        else:
            # A later exact-budget fit can drop the previously retained Step
            # rows.  They are absent from both result lists, so persistence
            # must derive their sequence numbers from source_messages.
            assert [message.metadata["history_seq"] for message in messages[1:]] == [5, 6, 8]
            compacted = [messages[0]]
            retained = [messages[-1]]
        result = ContextCompactionResult(
            status="compacted",
            trigger="manual",
            summary=summary.content,
            summary_message=summary,
            compacted_messages=compacted,
            retained_messages=retained,
            replacement_messages=[summary, *retained],
            before_tokens=100,
            after_tokens=50,
            limit_tokens=200,
        )
        return CompactionExecution(result=result, measurement=kwargs["measurement"])

    monkeypatch.setattr(command_execution.ContextCompactionController, "compact", fake_compact)

    first = await command_execution.compact_runtime_history(
        runtime_state_store=state_store,
        thread_id=state.session_id,
        llm_client=object(),
        model="mock-model",
    )
    assert first["status"] == "compacted"
    saved = await state_store.get(state.session_id)
    assert saved is not None
    first_meta = saved.metadata["context_compaction"]
    assert first_meta["summary_seq"] == 4
    assert first_meta["compacted_history_seqs"] == [1, 2, 3, 4, 7]

    await state_store.append_history(
        state.session_id,
        [{"role": "user", "content": "message-8", "metadata": {"history_seq": 8}}],
    )
    second = await command_execution.compact_runtime_history(
        runtime_state_store=state_store,
        thread_id=state.session_id,
        llm_client=object(),
        model="mock-model",
    )
    assert second["status"] == "compacted"
    saved = await state_store.get(state.session_id)
    assert saved is not None
    second_meta = saved.metadata["context_compaction"]
    assert second_meta["summary_seq"] == 4
    assert second_meta["compacted_history_seqs"] == [1, 2, 3, 4, 7]

    third = await command_execution.compact_runtime_history(
        runtime_state_store=state_store,
        thread_id=state.session_id,
        llm_client=object(),
        model="mock-model",
    )
    assert third["status"] == "compacted"
    saved = await state_store.get(state.session_id)
    assert saved is not None
    third_meta = saved.metadata["context_compaction"]
    assert third_meta["summary_seq"] == 7
    assert third_meta["compacted_history_seqs"] == [1, 2, 3, 4, 5, 6, 7]

    effective = await command_execution._load_effective_compaction_history(
        state_store,
        state.session_id,
        saved.metadata,
    )
    assert [message.metadata.get("history_seq") for message in effective[1:]] == [8]
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_manual_compaction_applies_summary_seq_to_legacy_history_fallback(monkeypatch):
    class LegacyBlobStore:
        def __init__(self):
            self.state = RuntimeState(
                session_id="thread-legacy-history",
                metadata={
                    "context_window_tokens": 8_000,
                    "context_compaction": {
                        "summary": "prior summary",
                        "summary_seq": 2,
                    },
                },
            )
            self.history = [
                {"role": "user", "content": f"message-{index}"}
                for index in range(5)
            ]
            self.requested_after_seq: list[int] = []

        async def get(self, _session_id):
            return self.state

        async def save(self, state):
            self.state = state

        async def get_history(self, _session_id, *, after_seq=0):
            # This is the SqlAlchemy store's legacy history_json fallback:
            # it has no incremental rows and currently returns the whole blob.
            self.requested_after_seq.append(after_seq)
            return list(self.history)

        async def history_max_seq(self, _session_id):
            return len(self.history)

        async def save_checkpoint(self, state, history):
            self.state = state
            self.history = list(history)

        async def append_history(self, _session_id, messages):
            self.history.extend(messages)

        async def replace_history(self, _session_id, messages):
            self.history = list(messages)

    store = LegacyBlobStore()
    captured: list[str] = []

    async def capture(self, messages, **kwargs):
        captured.extend(message.content for message in messages)
        return CompactionExecution(
            result=ContextCompactionResult(status="not_needed", trigger="manual"),
            measurement=kwargs["measurement"],
        )

    monkeypatch.setattr(command_execution.ContextCompactionController, "compact", capture)

    await command_execution.compact_runtime_history(
        runtime_state_store=store,
        thread_id="thread-legacy-history",
        llm_client=object(),
        model="mock-model",
    )

    assert store.requested_after_seq == [2]
    assert captured == ["prior summary", "message-2", "message-3", "message-4"]


def test_core_agent_spec_accepts_member_paths_without_product_names(tmp_path):
    spec = CoreAgentSpec(member_id="sample", name="Sample Agent")
    paths = CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work")

    assert spec.member_id == "sample"
    assert spec.id == "core-agent"
    assert paths.data_dir.name == "data"
    assert paths.work_root.name == "work"


@pytest.mark.asyncio
async def test_core_agent_operation_runs_kernel_tool_loop_and_projects_snapshot(tmp_path):
    work_root = tmp_path / "work"
    work_root.mkdir()
    (work_root / "input.txt").write_text("hello core\n", encoding="utf-8")
    llm = ScriptedCoreAgentLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
        model_provider=llm,
    )

    result = await catalog.execute(
        "turn.start",
        {"thread_id": "thread-kernel", "message": "read the file"},
    )

    assert result.status == "ok"
    assert result.payload["message"] == "The file says hello core."
    assert result.payload["snapshot"]["status"] == "completed"
    assert any(item["kind"] == "tool_call" for item in result.payload["run_items"])
    assert any(item["kind"] == "tool_result" for item in result.payload["run_items"])
    assert len(llm.requests) == 2
    assert {tool["function"]["name"] for tool in llm.requests[0].tools or []} >= {"read_file", "write_file"}


@pytest.mark.asyncio
async def test_core_agent_turn_uses_request_work_root(tmp_path):
    default_root = tmp_path / "default-work"
    runtime_root = tmp_path / "project-work"
    default_root.mkdir()
    runtime_root.mkdir()
    (runtime_root / "input.txt").write_text("project scoped\n", encoding="utf-8")
    llm = ScriptedCoreAgentLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=default_root),
        model_provider=llm,
    )

    result = await catalog.execute(
        "turn.start",
        {
            "thread_id": "thread-project-root",
            "message": "read the project file",
            "work_root": str(runtime_root),
        },
    )

    tool_result = next(item for item in result.payload["run_items"] if item["kind"] == "tool_result")
    assert tool_result["status"] == "completed"
    assert "project scoped" in tool_result["payload"]["tool_result"]


@pytest.mark.asyncio
async def test_core_agent_kernel_uses_supplied_live_turn_as_run_and_turn_identity(tmp_path):
    llm = CapturingCoreAgentLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=llm,
    )

    result = await catalog.execute(
        "turn.start",
        {
            "thread_id": "thread-supplied-id",
            "message": "complete",
            "run_id": "turn-live-1",
            "turn_id": "turn-live-1",
        },
    )

    assert result.payload["run_id"] == "turn-live-1"
    assert result.payload["turn_id"] == "turn-live-1"
    assert {item["run_id"] for item in result.payload["run_items"]} == {"turn-live-1"}
    assert {item["turn_id"] for item in result.payload["run_items"]} == {"turn-live-1"}


@pytest.mark.asyncio
async def test_core_agent_direct_turn_generates_its_own_run_id(tmp_path):
    llm = CapturingCoreAgentLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=llm,
    )

    result = await catalog.execute("turn.start", {"thread_id": "thread-direct-id", "message": "complete"})

    assert result.payload["run_id"]
    assert result.payload["turn_id"] == f"thread-direct-id:turn:{result.payload['run_id']}"


@pytest.mark.asyncio
async def test_core_agent_operation_applies_per_turn_model_and_shallow_thinking(tmp_path):
    llm = CapturingCoreAgentLLM()
    state_store = InMemoryRuntimeStateStore()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(default_model="default-model"),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=llm,
        runtime_state_store=state_store,
    )

    result = await catalog.execute(
        "turn.start",
        {
            "thread_id": "thread-runtime-options",
            "message": "hello",
            "model_id": "turn-model",
            "thinking_enabled": False,
            "thinking_budget": 1234,
            "shallow_thinking_enabled": True,
            "context_window_tokens": 128_000,
            "max_tokens": 777,
            "temperature": 0.4,
            "compact_trigger_tokens": 100_000,
            "compact_limit_tokens": 75_000,
        },
    )

    assert result.status == "ok"
    assert llm.requests
    assert llm.requests[0].model == "turn-model"
    assert llm.requests[0].metadata["thinking_enabled"] is False
    assert llm.requests[0].metadata["thinking_budget"] == 1234
    assert llm.requests[0].metadata["context_window_tokens"] == 127_223
    assert llm.requests[0].metadata["total_context_window_tokens"] == 128_000
    assert llm.requests[0].metadata["reserved_output_tokens"] == 777
    assert llm.requests[0].max_tokens == 777
    assert llm.requests[0].temperature == 0.4
    state = await state_store.get("thread-runtime-options")
    assert state is not None
    policy = state.metadata["runtime_audit"]["loop_policy"]
    assert policy["compact_trigger_tokens"] == 100_000
    assert policy["compact_limit_tokens"] == 75_000
    terminal = next(item for item in result.payload["run_items"] if item["kind"] == "status")
    assert terminal["usage"]["context_window_tokens"] == 127_223
    assert terminal["usage"]["estimated_prompt_tokens"] > 0
    assert any(message.content == SHALLOW_THINKING_PROMPT for message in llm.requests[0].messages)


@pytest.mark.asyncio
async def test_core_agent_leaves_model_output_limit_unset_without_turn_override(tmp_path):
    llm = CapturingCoreAgentLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(default_model="default-model"),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=llm,
    )

    result = await catalog.execute(
        "turn.start",
        {
            "thread_id": "thread-model-output-limit",
            "message": "hello",
        },
    )

    assert result.status == "ok"
    assert llm.requests[0].max_tokens is None


@pytest.mark.asyncio
async def test_core_agent_instructs_parent_to_delegate_complete_deliverable(tmp_path):
    llm = CapturingCoreAgentLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=llm,
    )

    await catalog.execute(
        "turn.start",
        {"thread_id": "thread-complete-delegation", "message": "delegate a file deliverable"},
    )

    system_prompt = llm.requests[0].messages[0].content
    # The delegation contract is English now: the guide, the binding strategy
    # line, and the evidence/summary discipline the parent must follow.
    assert "## Sub-agent Delegation Guide" in system_prompt
    assert "the prompt must specify at least the scope of work, task goal, and output format" in system_prompt
    assert "## Sub-agent Delegation Strategy" in system_prompt
    assert "Treat successful tool results as reusable evidence." in system_prompt
    assert "confirmed facts, remaining uncertainties, and the next step" in system_prompt


@pytest.mark.asyncio
async def test_core_agent_operation_loads_plugin_skill_roots(tmp_path):
    plugin_root = tmp_path / "plugins"
    sample = plugin_root / "sample"
    skill_dir = sample / "skills"
    skill_dir.mkdir(parents=True)
    (sample / "plugin.json").write_text(
        '{"name":"sample","version":"1.0.0","skills":["./skills"]}',
        encoding="utf-8",
    )
    (skill_dir / "shared.md").write_text("plugin skill resource\n", encoding="utf-8")
    llm = ScriptedCoreAgentLLM(path="shared.md")
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=llm,
        plugin_roots=[plugin_root],
    )

    result = await catalog.execute(
        "turn.start",
        {"thread_id": "thread-plugin", "message": "read plugin skill resource"},
    )

    tool_results = [item for item in result.payload["run_items"] if item["kind"] == "tool_result"]
    assert result.status == "ok"
    assert tool_results
    assert tool_results[0]["status"] == "completed"
    assert "plugin skill resource" in tool_results[0]["payload"]["tool_result"]


@pytest.mark.asyncio
async def test_core_agent_operation_exposes_load_skill_to_model(tmp_path):
    work_root = tmp_path / "work"
    skill_dir = work_root / ".lam" / "skills" / "sample"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: sample\n"
        "description: Sample Core skill.\n"
        "---\n"
        "# Sample Core Skill\n"
        "Use this content in the answer.\n",
        encoding="utf-8",
    )
    llm = ScriptedLoadSkillLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
        model_provider=llm,
    )

    result = await catalog.execute("turn.start", {"thread_id": "thread-skill", "message": "use sample skill"})

    tool_results = [item for item in result.payload["run_items"] if item["kind"] == "tool_result"]
    assert result.status == "ok"
    assert result.payload["message"] == "Loaded sample skill."
    assert tool_results
    assert "<skill_content name=\"sample\">" in tool_results[0]["payload"]["tool_result"]
    assert len(llm.requests) == 2


@pytest.mark.asyncio
async def test_core_agent_operation_exposes_builtin_observer_skill_outside_repo(tmp_path):
    work_root = tmp_path / "external-workspace"
    work_root.mkdir()
    llm = ScriptedLoadSkillLLM(skill_name="observe-events")
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
        model_provider=llm,
    )

    result = await catalog.execute(
        "turn.start",
        {"thread_id": "thread-observe-events", "message": "monitor external events"},
    )

    tool_result = next(item for item in result.payload["run_items"] if item["kind"] == "tool_result")
    assert result.status == "ok"
    assert result.payload["message"] == "Loaded observe-events skill."
    assert tool_result["status"] == "completed"
    assert '<skill_content name="observe-events">' in tool_result["payload"]["tool_result"]


@pytest.mark.asyncio
async def test_core_agent_operation_runs_trusted_pre_tool_hook(tmp_path):
    data_dir = tmp_path / "data"
    work_root = tmp_path / "work"
    work_root.mkdir()
    (work_root / "input.txt").write_text("hook should block this\n", encoding="utf-8")
    plugin_root = tmp_path / "plugins"
    sample = plugin_root / "sample"
    hooks_dir = sample / "hooks"
    hooks_dir.mkdir(parents=True)
    hook_script = sample / "block_read.py"
    hook_script.write_text(
        "import json\n"
        "print(json.dumps({'decision':'block','reason':'blocked by trusted hook'}))\n",
        encoding="utf-8",
    )
    (sample / "plugin.json").write_text(
        '{"name":"sample","version":"1.0.0","hooks":["./hooks/hooks.json"]}',
        encoding="utf-8",
    )
    (hooks_dir / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "read_file",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'py -3.14 "{hook_script}"',
                                    "timeout": 5,
                                    "required": True,
                                }
                            ],
                        }
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    plugins = PluginRegistry(plugin_roots=[plugin_root]).discover()
    hooks = HookRegistry(
        project_root=work_root,
        plugins=plugins,
        trust_store=HookTrustStore(data_dir / "hook_trust.json"),
    ).load()
    trust_store = HookTrustStore(data_dir / "hook_trust.json")
    trust_store.trust(hooks[0].definition_hash)
    llm = ScriptedCoreAgentLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=data_dir, work_root=work_root),
        model_provider=llm,
        plugin_roots=[plugin_root],
    )

    result = await catalog.execute("turn.start", {"thread_id": "thread-hook", "message": "read the file"})

    tool_results = [item for item in result.payload["run_items"] if item["kind"] == "tool_result"]
    assert result.status == "ok"
    assert tool_results
    assert tool_results[0]["status"] == "failed"
    assert "blocked by trusted hook" in tool_results[0]["payload"]["tool_result"]


@pytest.mark.asyncio
async def test_core_plugin_operation_catalog_uses_user_and_project_roots(tmp_path, monkeypatch):
    # isolated_config_root (autouse) pins LAMTOOLS_HOME, so the user plugin
    # root resolves to {lam_home}/plugins (green/portable layout).
    from lamtools_core.config.root import lam_home

    data_dir = tmp_path / "data"
    work_root = tmp_path / "work"
    user_plugin = lam_home() / "plugins" / "user-policy"
    project_plugin = work_root / ".lamtools" / "plugins" / "project-policy"
    user_plugin.mkdir(parents=True)
    project_plugin.mkdir(parents=True)
    (user_plugin / "plugin.json").write_text('{"name":"user-policy","version":"1.0.0"}', encoding="utf-8")
    (project_plugin / "plugin.json").write_text('{"name":"project-policy","version":"1.0.0"}', encoding="utf-8")

    catalog = build_core_plugin_operation_catalog(
        data_dir=data_dir,
        work_root=work_root,
        include_user_plugins=True,
    )
    listed = await catalog.execute("plugin.list")
    await catalog.execute("plugin.disable", {"name": "user-policy"})

    # 缺口 #3/D3：catalog 统一扫内置根——bundled 插件也在列表中
    names = {item["name"] for item in listed.payload["plugins"]}
    assert {"user-policy", "project-policy"} <= names
    assert {"git", "websearch", "imagegen"} <= names
    assert (data_dir / "plugins.jsonc").exists()
    assert not (data_dir / "core-plugin-state.json").exists()


@pytest.mark.asyncio
async def test_core_plugin_catalog_default_chain_includes_user_root(tmp_path):
    """H 组缺口回归（2026-08-16）：默认扫描链必须含用户级插件根——
    不显式传 include_user_plugins / plugin_roots 时，用户级安装的插件
    默认可见（与 plugin.install 默认装用户级根的产品语义对齐）。

    isolated_config_root（autouse）把 LAMTOOLS_HOME 钉到临时目录，
    用户级根解析为 {lam_home}/plugins（green/portable 布局）。
    """
    from lamtools_core.config.root import lam_home

    data_dir = tmp_path / "data"
    work_root = tmp_path / "work"
    work_root.mkdir()
    user_plugin = lam_home() / "plugins" / "user-default"
    user_plugin.mkdir(parents=True)
    (user_plugin / "plugin.json").write_text('{"name":"user-default","version":"1.0.0"}', encoding="utf-8")

    catalog = build_core_plugin_operation_catalog(data_dir=data_dir, work_root=work_root)
    listed = await catalog.execute("plugin.list")
    names = {item["name"] for item in listed.payload["plugins"]}
    assert "user-default" in names


def test_default_core_agent_plugin_roots_includes_user_root(tmp_path):
    """H 组缺口回归：default_core_agent_plugin_roots 默认链含用户级根；
    显式 include_user_plugins=False 仍可排除（向后兼容）。"""
    from lamtools_core.app.base_agent import default_core_agent_plugin_roots
    from lamtools_core.plugins.registry import default_user_plugin_root

    roots = default_core_agent_plugin_roots(work_root=tmp_path)
    assert default_user_plugin_root() in roots
    roots_no_user = default_core_agent_plugin_roots(work_root=tmp_path, include_user_plugins=False)
    assert default_user_plugin_root() not in roots_no_user


@pytest.mark.asyncio
async def test_core_agent_approval_respond_executes_pending_tool_and_continues(tmp_path):
    work_root = tmp_path / "work"
    work_root.mkdir()
    llm = ScriptedApprovalLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
        model_provider=llm,
    )

    waiting = await catalog.execute("turn.start", {"thread_id": "thread-approval", "message": "write a file"})
    approved = await catalog.execute("approval.respond", {"thread_id": "thread-approval", "action": "approve"})

    assert waiting.status == "ok"
    assert waiting.payload["decision"] == "wait"
    assert approved.status == "ok"
    assert approved.payload["decision"] == "done"
    assert approved.payload["message"] == "Saved approved.md."
    assert approved.payload["run_id"] == waiting.payload["run_id"]
    assert approved.payload["turn_id"] == waiting.payload["turn_id"]
    assert {item["turn_id"] for item in approved.payload["run_items"]} == {waiting.payload["turn_id"]}
    assert (work_root / "approved.md").read_text(encoding="utf-8") == "approved content\n"
    assert len(llm.requests) == 2


@pytest.mark.asyncio
async def test_core_agent_approval_continues_in_request_work_root(tmp_path):
    default_root = tmp_path / "default-work"
    runtime_root = tmp_path / "project-work"
    default_root.mkdir()
    runtime_root.mkdir()
    llm = ScriptedApprovalLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=default_root),
        model_provider=llm,
    )

    waiting = await catalog.execute(
        "turn.start",
        {
            "thread_id": "thread-project-approval",
            "message": "write a file",
            "work_root": str(runtime_root),
        },
    )
    approved = await catalog.execute(
        "approval.respond",
        {"thread_id": "thread-project-approval", "action": "approve"},
    )

    assert waiting.payload["decision"] == "wait"
    assert approved.payload["decision"] == "done"
    assert (runtime_root / "approved.md").read_text(encoding="utf-8") == "approved content\n"
    assert not (default_root / "approved.md").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        (
            "sub_agent",
            {
                "action": "create",
                "type": "consider",
                "name": "reviewer",
                "model": "model-a",
                "reasoning_level": "medium",
            },
        ),
        (
            "sub_agent_message",
            {"type": "consider", "name": "reviewer", "prompt": "continue"},
        ),
    ],
)
async def test_approval_respond_rechecks_forbidden_delegation_strategy(
    tmp_path, isolated_config_root, tool_name, arguments
):
    from lamtools_core.config.subagent_prompt import write_subagent_settings

    work_root = tmp_path / "work"
    work_root.mkdir()
    state_store = InMemoryRuntimeStateStore()
    call_id = f"pending-{tool_name}"
    state = RuntimeState(
        session_id=f"thread-{tool_name}",
        run_id=f"run-{tool_name}",
        status="waiting",
        loop_state="wait",
        metadata={
            "work_root": str(work_root),
            "turn_id": f"turn-{tool_name}",
            "original_user_message": "delegate work",
            "pending_approval": {
                "request_id": call_id,
                "status": "waiting",
                "tool_call": {
                    "id": call_id,
                    "name": tool_name,
                    "arguments": arguments,
                    "metadata": {},
                },
            },
        },
    )
    await state_store.save(state)
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
        model_provider=CapturingCoreAgentLLM(),
        runtime_state_store=state_store,
    )

    # The call was already persisted while delegation was available. The
    # approval continuation must use the current project policy, not the old
    # pending-call snapshot.
    write_subagent_settings(
        {"delegation_strategy": "forbidden"},
        scope="project",
        work_root=work_root,
    )
    result = await catalog.execute(
        "approval.respond",
        {
            "thread_id": state.session_id,
            "request_id": call_id,
            "action": "approve",
        },
    )

    assert result.status == "error"
    assert result.payload["decision"] == "failed"
    tool_results = [
        item
        for item in result.payload["run_items"]
        if item["kind"] == "tool_result"
        and item["payload"].get("tool_name") == tool_name
    ]
    assert tool_results
    assert tool_results[-1]["status"] == "failed"
    assert "disabled" in str(tool_results[-1]["payload"]).lower() or "blocked" in str(
        tool_results[-1]["payload"]
    ).lower()


@pytest.mark.asyncio
async def test_core_agent_rejects_removed_blocking_sub_agent_contract(tmp_path):
    work_root = tmp_path / "work"
    work_root.mkdir()
    llm = ScriptedRejectedLegacySubAgentLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
        model_provider=llm,
    )

    result = await catalog.execute(
        "turn.start",
        {"thread_id": "thread-repeated-sub-approval", "message": "delegate two files"},
    )

    failed_sub_agent = [
        item for item in result.payload["run_items"]
        if item["kind"] == "tool_result" and item["payload"].get("tool_name") == "sub_agent"
    ]
    assert result.status == "ok"
    assert result.payload["decision"] == "done"
    assert result.payload["message"] == "Legacy delegation was rejected."
    assert len(failed_sub_agent) == 1
    assert failed_sub_agent[0]["status"] == "failed"
    assert not (work_root / "first.md").exists()
    assert not (work_root / "second.md").exists()
    assert len(llm.requests) == 2


@pytest.mark.asyncio
async def test_core_agent_approval_respond_normalizes_legacy_thread_action_and_response(tmp_path):
    work_root = tmp_path / "work"
    work_root.mkdir()
    llm = ScriptedApprovalLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
        model_provider=llm,
    )

    waiting = await catalog.execute("turn.start", {"thread_id": "thread-legacy", "message": "write a file"})
    approved = await catalog.execute(
        "approval.respond",
        {"thread_id": "thread-legacy", "action": "approve_for_session", "response": ""},
    )

    assert waiting.payload["decision"] == "wait"
    assert approved.status == "ok"
    assert (work_root / "approved.md").read_text(encoding="utf-8") == "approved content\n"
