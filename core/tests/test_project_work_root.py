from __future__ import annotations

from types import SimpleNamespace

import pytest

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.app.default_agent import (
    CoreAgentPaths, _resolve_turn_work_root, create_core_agent_operations,
)
from lamtools_core.app.operation_catalog import OperationRequest
from lamtools_core.llm import LLMStreamEvent, LLMToolCall
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState
from lamtools_core.session import InMemorySessionStore, build_session_record


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["session", "payload", "request_metadata", "runtime", "default"])
async def test_omitted_project_root_never_overrides_a_bound_session(tmp_path, source):
    default_root = tmp_path / "MyProject"
    project_root = tmp_path / "project"
    previous_root = tmp_path / "prior_runtime"
    explicit_root = tmp_path / "explicit"
    payload = {"workRoot": str(explicit_root)} if source == "payload" else {}
    request_metadata = {"work_root": str(explicit_root)} if source == "request_metadata" else {}

    class Sessions:
        async def get(self, thread_id):
            return SimpleNamespace(metadata={"work_root": str(project_root)}) if source not in ("runtime", "default") else None

    states = InMemoryRuntimeStateStore()
    if source != "default":
        await states.save(RuntimeState(session_id="thread", metadata={"work_root": str(previous_root)}))
    root = await _resolve_turn_work_root(
        CoreAgentPaths(data_dir=tmp_path / "data", work_root=default_root),
        OperationRequest("turn.start", payload=payload, metadata=request_metadata),
        thread_id="thread", session_store=Sessions(), runtime_state_store=states,
    )
    expected = {
        "session": project_root, "payload": explicit_root,
        "request_metadata": explicit_root, "runtime": previous_root, "default": default_root,
    }[source]
    assert root == expected.resolve()


@pytest.mark.asyncio
async def test_project_root_resolution_supports_synchronous_cli_session_store(tmp_path):
    sessions = InMemorySessionStore()
    sessions.create(build_session_record(
        session_id="cli", member_id="core", title="CLI", metadata={"work_root": str(tmp_path / "project")},
    ))
    root = await _resolve_turn_work_root(
        CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "default"),
        OperationRequest("turn.start"), thread_id="cli", session_store=sessions,
        runtime_state_store=InMemoryRuntimeStateStore(),
    )
    assert root == (tmp_path / "project").resolve()


@pytest.mark.asyncio
async def test_bound_project_repairs_wrong_runtime_root_and_registers_without_moving_file(tmp_path):
    default_root = tmp_path / "MyProject"
    project_root = tmp_path / "ChatT"
    default_root.mkdir()
    project_root.mkdir()
    document = project_root / "docs" / "output.md"
    document.parent.mkdir()
    document.write_text("project deliverable", encoding="utf-8")
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        project, _ = await db.project_store.create(project_root, name="ChatT")
        session = await db.project_store.create_session(project.id)
        sessions = CoreDbSessionStore(lambda: db)
        states = InMemoryRuntimeStateStore()
        await states.save(RuntimeState(
            session_id=session.id, status="completed", loop_state="done",
            metadata={"work_root": str(default_root)},
        ))

        class Model:
            def __init__(self):
                self.requests = []
            async def complete(self, request):
                raise AssertionError("use the scripted stream")
            async def stream(self, request):
                self.requests.append(request)
                if len(self.requests) == 1:
                    yield LLMStreamEvent(kind="done", tool_calls=[LLMToolCall(
                        id="register", name="library",
                        arguments={"action": "register", "path": "docs/output.md", "folder": "docs"},
                    )])
                else:
                    yield LLMStreamEvent(kind="content_delta", content="Registered the existing project file.")
                    yield LLMStreamEvent(kind="done")

        model = Model()
        catalog = create_core_agent_operations(
            paths=CoreAgentPaths(data_dir=tmp_path / "agent-data", work_root=default_root),
            model_provider=model, session_store=sessions, runtime_state_store=states,
            db_session_factory=db.session_factory, write_coordinator=db.persistence.write_coordinator,
        )
        result = await catalog.execute("turn.start", {"thread_id": session.id, "message": "register the deliverable"})
        assert result.status == "ok"
        state = await states.get(session.id)
        assert state.metadata["work_root"] == str(project_root.resolve())
        records = await db.artifact_store.list(project.id)
        assert any(record.path == "workspace://docs/output.md" for record in records)
        prompt = "\n".join(str(message.content) for message in model.requests[0].messages)
        assert f"Current project: {project_root.resolve()}" in prompt
        assert document.read_text(encoding="utf-8") == "project deliverable"
        assert not (default_root / "docs" / "output.md").exists()
    finally:
        await db.close()
