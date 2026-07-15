from __future__ import annotations

import json

import pytest

from lamtools_core.app.default_agent import (
    CoreAgentPaths,
    CoreAgentSpec,
    _persist_core_event_live,
    create_core_agent_operations,
)
from lamtools_core.app import command_execution
from lamtools_core.context_compaction import ContextCompactionResult
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.base_agent import build_core_plugin_operation_catalog, core_events_to_run_items
from lamtools_core.event import CoreEvent
from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent, LLMToolCall
from lamtools_core.llm.shallow_thinking import SHALLOW_THINKING_PROMPT
from lamtools_core.plugins.hook_config import HookRegistry
from lamtools_core.plugins.registry import PluginRegistry
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


class ScriptedRepeatedSubAgentApprovalLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("core agent operation should use streaming when available")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        request_number = len(self.requests)
        if request_number == 1:
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
        if request_number == 2:
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="call-child-write-one",
                        name="write_file",
                        arguments={"path": "first.md", "content": "first\n"},
                    )
                ],
            )
            return
        if request_number == 3:
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="call-child-write-two",
                        name="write_file",
                        arguments={"path": "second.md", "content": "second\n"},
                    )
                ],
            )
            return
        if request_number == 4:
            yield LLMStreamEvent(kind="content_delta", content="Child saved both files.")
            yield LLMStreamEvent(kind="done")
            return
        yield LLMStreamEvent(kind="content_delta", content="Parent received the completed files.")
        yield LLMStreamEvent(kind="done")


class ScriptedLoadSkillLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("core agent operation should use streaming when available")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            tool_names = {tool["function"]["name"] for tool in request.tools or []}
            assert "load_skill" in tool_names
            assert "Available skills:" in request.messages[0].content
            assert "<name>sample</name>" in request.messages[0].content
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[LLMToolCall(id="call-skill", name="load_skill", arguments={"name": "sample"})],
            )
            return
        yield LLMStreamEvent(kind="content_delta", content="Loaded sample skill.")
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
    command_dir = core_root / "command"
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
        "accepts_args": False,
    }


@pytest.mark.asyncio
async def test_core_agent_command_execute_compacts_runtime_history(tmp_path):
    core_root = tmp_path / "core-root"
    command_dir = core_root / "command"
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
    state = RuntimeState(session_id="thread-compact")
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
    state_store = InMemoryRuntimeStateStore()
    state = RuntimeState(
        session_id="thread-large-compact",
        metadata={"model_id": "session-model", "context_window_tokens": 256_000},
    )
    await state_store.save_checkpoint(
        state,
        [{"role": "user", "content": "large history"}],
    )
    captured = {}

    async def capture(request):
        captured["request"] = request
        return ContextCompactionResult(
            status="not_needed",
            trigger="manual",
            display_payload={"status": "not_needed", "reason": "no_gain"},
        )

    monkeypatch.setattr(command_execution, "compact_context", capture)

    await command_execution.compact_runtime_history(
        runtime_state_store=state_store,
        thread_id=state.session_id,
        model="default-model",
    )

    request = captured["request"]
    assert request.model == "session-model"
    assert request.input_limit_tokens == 64_000


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
    assert llm.requests[0].metadata["context_window_tokens"] == 128_000
    assert llm.requests[0].max_tokens == 777
    assert llm.requests[0].temperature == 0.4
    state = await state_store.get("thread-runtime-options")
    assert state is not None
    policy = state.metadata["runtime_audit"]["loop_policy"]
    assert policy["compact_trigger_tokens"] == 100_000
    assert policy["compact_limit_tokens"] == 75_000
    terminal = next(item for item in result.payload["run_items"] if item["kind"] == "status")
    assert terminal["usage"]["context_window_tokens"] == 128_000
    assert terminal["usage"]["estimated_prompt_tokens"] > 0
    assert any(message.content == SHALLOW_THINKING_PROMPT for message in llm.requests[0].messages)


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
    assert "delegate the complete requested deliverable" in system_prompt
    assert "Parent Agent should verify the result" in system_prompt
    assert "Treat successful tool results as reusable evidence" in system_prompt
    assert "confirmed facts, remaining uncertainty, and the next action" in system_prompt


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
    skill_dir = work_root / ".agents" / "skills" / "sample"
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
    appdata = tmp_path / "appdata"
    data_dir = tmp_path / "data"
    work_root = tmp_path / "work"
    user_plugin = appdata / "LamTools" / "plugins" / "user-policy"
    project_plugin = work_root / ".lamtools" / "plugins" / "project-policy"
    monkeypatch.setenv("APPDATA", str(appdata))
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

    assert {item["name"] for item in listed.payload["plugins"]} == {"user-policy", "project-policy"}
    assert (data_dir / "plugins.json").exists()
    assert not (data_dir / "core-plugin-state.json").exists()


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
async def test_core_agent_sub_agent_can_request_approval_twice_before_completing(tmp_path):
    work_root = tmp_path / "work"
    work_root.mkdir()
    state_store = InMemoryRuntimeStateStore()
    llm = ScriptedRepeatedSubAgentApprovalLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
        model_provider=llm,
        runtime_state_store=state_store,
    )

    first_wait = await catalog.execute(
        "turn.start",
        {"thread_id": "thread-repeated-sub-approval", "message": "delegate two files"},
    )
    second_wait = await catalog.execute(
        "approval.respond",
        {"thread_id": "thread-repeated-sub-approval", "action": "approve"},
    )
    parent_state = await state_store.get("thread-repeated-sub-approval")

    assert first_wait.payload["decision"] == "wait"
    assert second_wait.status == "ok"
    assert second_wait.payload["decision"] == "wait"
    assert parent_state is not None
    assert parent_state.status == "waiting"
    assert parent_state.metadata["pending_approval"]["tool_call"]["id"] == "call-child-write-two"
    assert parent_state.metadata["pending_approval"]["delegated_session"]["session_id"].endswith(":sub:writer")
    assert any(
        event["name"] == "runtime.approval_request"
        and event["payload"]["tool_call_id"] == "call-child-write-two"
        for event in second_wait.payload["events"]
    )
    assert not any(event["name"] == "runtime.approval_response" for event in second_wait.payload["events"])
    assert sum(item["kind"] == "approval_response" for item in second_wait.payload["run_items"]) == 1
    assert (work_root / "first.md").read_text(encoding="utf-8") == "first\n"
    assert not (work_root / "second.md").exists()

    completed = await catalog.execute(
        "approval.respond",
        {"thread_id": "thread-repeated-sub-approval", "action": "approve"},
    )

    assert completed.status == "ok"
    assert completed.payload["decision"] == "done"
    assert completed.payload["message"] == "Parent received the completed files."
    assert not any(event["name"] == "runtime.approval_response" for event in completed.payload["events"])
    assert sum(item["kind"] == "approval_response" for item in completed.payload["run_items"]) == 1
    assert (work_root / "second.md").read_text(encoding="utf-8") == "second\n"
    assert len(llm.requests) == 5


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
