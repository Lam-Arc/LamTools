from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import asyncio
import subprocess
from time import perf_counter

import pytest
import lamtools_core.app.live_operations as core_live_operations_module
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.app_server.connection as connection_module
import app.app_server.operations as operations_module
import app.app_server.reducer as reducer_module
from app.app_server.runtime_bridge import persist_run_item_events_as_app_events
from app.app_server.operations import (
    WRITER_OVERLAY_OPERATION_NAMES,
    build_writer_operation_catalog,
    handle_config_adapter_profiles_list_operation,
    handle_config_provider_create_operation,
    handle_config_provider_delete_operation,
    handle_config_provider_update_operation,
    handle_config_runtime_capabilities_get_operation,
    handle_config_subagent_delete_operation,
    handle_config_subagent_upsert_operation,
    handle_config_model_create_operation,
    handle_config_model_delete_operation,
    handle_config_model_update_operation,
    handle_config_models_list_operation,
    handle_config_import_env_operation,
    handle_config_providers_list_operation,
    handle_config_resolved_get_operation,
    handle_attachment_get_operation,
    handle_attachment_list_operation,
    handle_attachment_open_operation,
    handle_attachment_preview_operation,
    handle_artifact_open_operation,
    handle_artifact_read_operation,
    handle_command_catalog_operation,
    handle_command_execute_operation,
    handle_project_agents_md_get_operation,
    handle_project_agents_md_update_operation,
    handle_project_create_operation,
    handle_project_delete_operation,
    handle_project_directory_pick_operation,
    handle_project_get_operation,
    handle_project_list_operation,
    handle_project_sessions_list_operation,
    handle_project_update_operation,
    handle_session_create_operation,
    handle_session_checkpoint_create_operation,
    handle_session_checkpoint_restore_operation,
    handle_session_checkpoints_list_operation,
    handle_session_agent_branch_abandon_operation,
    handle_session_changes_get_operation,
    handle_session_agent_branch_diff_operation,
    handle_session_agent_branch_merge_operation,
    handle_session_agent_branches_list_operation,
    handle_session_change_file_undo_operation,
    handle_session_changes_undo_operation,
    handle_session_commit_review_decide_operation,
    handle_session_commit_review_get_operation,
    handle_session_delete_operation,
    handle_session_get_operation,
    handle_session_git_graph_get_operation,
    handle_session_fork_operation,
    handle_session_list_operation,
    handle_session_rollback_turn_operation,
    handle_session_update_operation,
    handle_settings_get_operation,
    handle_settings_update_operation,
    operation_name,
)
from app.app_server.protocol import AppendEventInput, InitializeParams, rpc_error, rpc_result
from app.app_server.connection import WriterAppServerConnection
from app.app_server.ledger import _EVENT_STORE, _to_writer_envelope, _to_writer_event_input, list_events_after
from app.app_server.persistence import _PERSISTENCE_HOST
from app.app_server.reducer import apply_event, apply_event_in_place, empty_thread_state, reduce_events
from app.app_server.runtime import WriterRuntimeLifecycle
from app.app_server.snapshot import apply_event_to_snapshot, load_snapshot, rebuild_snapshot
from app.app_server.protocol import WriterAppEventEnvelope
from app.database import Base, async_session
from app.models.app_setting import AppSetting
from app.models.app_server import WriterAppEvent, WriterThreadSnapshot
from app.models.attachment import WriterAttachment
from app.models.llm_config import LLMModel, LLMProvider
from app.models.message import WriterMessage
from app.models.project import WriterProject
from app.models.session import WriterSession
from app.models.transcript import WriterTranscriptBlock, WriterTranscriptTurn
from app.services.runtime_input_context import prepare_runtime_input_context
from app.services.transcript_service import project_transcript
from lamtools_core.app import CORE_WORKBENCH_OPERATION_NAMES, CoreLiveContext, OperationCatalog, OperationResult
from lamtools_core.app.live_operations import (
    handle_queue_delete_operation as handle_core_queue_delete_operation,
    handle_queue_update_operation as handle_core_queue_update_operation,
    handle_thread_read_operation as handle_core_thread_read_operation,
    handle_thread_resume_operation as handle_core_thread_resume_operation,
    handle_thread_start_operation as handle_core_thread_start_operation,
    handle_turn_cancel_operation as handle_core_turn_cancel_operation,
)
from lamtools_core.app.live_router import CoreLiveConnection
from lamtools_core.config.shared_database import init_shared_config_schema
from lamtools_core.event import RunItemEvent
from lamtools_core.runtime import RuntimeTaskRegistry


@asynccontextmanager
async def dummy_shared_config_session():
    yield object()


class DummyWebSocket:
    async def accept(self):
        return None

    async def send_json(self, message):
        return None

    async def close(self, code=1000, reason=""):
        return None


async def _append_event_without_projection(db, event: AppendEventInput):
    return _to_writer_envelope(await _EVENT_STORE.append(db, _to_writer_event_input(event)))


async def _append_run_item_without_projection(db, event: RunItemEvent):
    return _to_writer_envelope(await _EVENT_STORE.append_run_item_event(db, event))


def _core_live_context(session_factory=async_session) -> CoreLiveContext:
    return CoreLiveContext(
        session_factory=session_factory,
        persistence=_PERSISTENCE_HOST,
        operations=OperationCatalog(),
    )


def app_event(event_id, seq, method, payload, **extra):
    return WriterAppEventEnvelope(
        event_id=event_id,
        seq=seq,
        thread_id=extra.pop("thread_id", "thread-1"),
        method=method,
        payload=payload,
        created_at=datetime.now(timezone.utc),
        **extra,
    )


def test_initialize_params_require_client_info():
    params = InitializeParams.model_validate(
        {"clientInfo": {"name": "writer_frontend", "title": "Writer", "version": "0.1.0"}}
    )

    assert params.clientInfo.name == "writer_frontend"
    assert params.capabilities == {}


def test_json_rpc_response_shapes_omit_jsonrpc_header():
    assert rpc_result(1, {"ok": True}) == {"id": 1, "result": {"ok": True}}

    error = rpc_error("r1", code=-32002, message="Not initialized")
    assert error == {"id": "r1", "error": {"code": -32002, "message": "Not initialized"}}


def test_json_rpc_result_is_json_safe():
    response = rpc_result(1, {"updated_at": datetime(2026, 7, 2, 1, 2, 3, tzinfo=timezone.utc)})

    assert response == {"id": 1, "result": {"updated_at": "2026-07-02T01:02:03Z"}}


def test_initialize_params_reject_missing_client_info():
    with pytest.raises(Exception):
        InitializeParams.model_validate({})


def test_connection_exposes_required_request_handlers():
    for name in (
        "_project_directory_pick",
        "_attachment_list",
        "_attachment_get",
        "_attachment_preview",
        "_attachment_open",
        "_session_create",
        "_session_get",
        "_session_list",
        "_session_update",
        "_session_delete",
        "_session_fork",
        "_session_git_graph",
        "_session_changes_get",
        "_session_checkpoints_list",
        "_session_checkpoint_create",
        "_session_checkpoint_restore",
        "_session_commit_review_get",
        "_session_commit_review_decide",
        "_session_agent_branches_list",
        "_session_agent_branch_diff",
        "_session_agent_branch_merge",
        "_session_agent_branch_abandon",
        "_session_rollback_turn",
        "_session_changes_undo",
        "_session_change_file_undo",
    ):
        assert hasattr(WriterAppServerConnection, name)
    for core_owned_name in (
        "_project_create",
        "_project_get",
        "_project_list",
        "_project_update",
        "_project_delete",
        "_project_agents_md_get",
        "_project_agents_md_update",
        "_project_sessions_list",
        "_turn_start",
        "_turn_steer",
        "_approval_respond",
        "_queue_create",
        "_queue_guidance",
        "_artifact_read",
        "_artifact_open",
        "_command_catalog",
        "_command_execute",
        "_settings_get",
        "_settings_update",
        "_config_providers_list",
        "_plugin_list",
        "_hook_list",
    ):
        assert not hasattr(WriterAppServerConnection, core_owned_name)


def test_writer_reuses_all_core_live_handlers_and_augments_thread_read_with_hook():
    connection = WriterAppServerConnection(DummyWebSocket())
    catalog = connection._operation_catalog()
    host = connection.context.host

    assert connection.context.persistence is connection_module._PERSISTENCE_HOST
    assert "event_store=object()" not in Path(connection_module.__file__).read_text(encoding="utf-8")
    for name in (
        "thread.resume",
        "turn.start",
        "turn.steer",
        "turn.cancel",
        "approval.respond",
        "queue.create",
        "queue.update",
        "queue.delete",
        "queue.guide",
    ):
        assert catalog._handlers[name] is host.operation_handlers()[name]
    assert catalog._handlers["thread.read"] is host.operation_handlers()["thread.read"]
    assert hasattr(host.member_hooks, "augment_thread_read")


def test_writer_connection_has_no_generic_lifecycle_executors():
    source = Path(connection_module.__file__).read_text(encoding="utf-8")
    for name in (
        "_writer_turn_start_executor",
        "_writer_turn_steer_executor",
        "_writer_queue_create_executor",
        "_writer_queue_guidance_executor",
        "_writer_approval_respond_executor",
    ):
        assert name not in source
    assert "operation_executors=" not in source


def test_writer_catalog_has_no_core_fallback_or_legacy_thread_start():
    source = Path(operations_module.__file__).read_text(encoding="utf-8")

    assert "fallback_handlers" not in source
    assert "def handle_thread_start_operation" not in source
    assert "thread_start:" not in source


def test_writer_service_has_no_member_owned_llm_fallback():
    service_path = Path(connection_module.__file__).parents[1] / "services" / "writer_service.py"
    source = service_path.read_text(encoding="utf-8")

    assert "_FallbackLLMClient" not in source
    assert "falling back to Writer model" not in source


def test_writer_approval_uses_core_operation_without_member_lifecycle_hook():
    runtime_path = Path(connection_module.__file__).with_name("runtime.py")
    adapter_path = Path(connection_module.__file__).with_name("member_adapter.py")
    runtime_source = runtime_path.read_text(encoding="utf-8")
    adapter_source = adapter_path.read_text(encoding="utf-8")

    assert "_find_single_open_waiting_block" not in runtime_source
    assert "continue_approval" not in adapter_source
    assert "approval.respond" in connection_module.build_writer_core_operation_adapter_catalog(
        session_factory=lambda: None,
        config_session_factory=lambda: None,
        runtime=type("Runtime", (), {
            "writer_service_or_none": lambda self: None,
            "approval_coordinator": lambda self, _thread_id: None,
        })(),
        emit_event=lambda _event: None,
    ).list()


def test_writer_member_modules_do_not_reimplement_core_lifecycle_plans():
    operations_source = Path(operations_module.__file__).read_text(encoding="utf-8")
    approvals_path = Path(connection_module.__file__).with_name("approvals.py")
    queue_path = Path(connection_module.__file__).with_name("queue.py")

    for handler_name in (
        "handle_turn_start_operation",
        "handle_turn_steer_operation",
        "handle_queue_create_operation",
        "handle_queue_guidance_operation",
        "handle_approval_respond_operation",
    ):
        assert f"def {handler_name}" not in operations_source
    assert not approvals_path.exists()
    assert not queue_path.exists()


def test_writer_connection_reuses_core_live_connection_loop():
    for name in (
        "_hub_reader",
        "_subscribe",
        "_unsubscribe",
        "_handle_client_response",
        "_handle_control_request",
        "_handle_operation_request",
        "_initialize",
    ):
        assert getattr(WriterAppServerConnection, name) is getattr(CoreLiveConnection, name)


def test_writer_connection_uses_core_operation_dispatch_adapter():
    connection = WriterAppServerConnection(DummyWebSocket())

    assert connection.adapter.handle_operation_request is None
    assert connection.adapter.operation_catalog_factory is not None
    assert connection.adapter.handle_unknown_operations is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation_name", "wire_method", "params"),
    [
        ("turn.start", "turn/start", {"input": [{"type": "text", "text": "hello"}]}),
        (
            "turn.steer",
            "turn/steer",
            {"turn_id": "turn-core-spy", "input": [{"type": "text", "text": "guide"}]},
        ),
        (
            "queue.guide",
            "queue/guide",
            {"turn_id": "turn-core-spy", "queue_item_id": "queue-core-spy"},
        ),
    ],
)
async def test_writer_websocket_base_operations_enter_core_handler(
    monkeypatch, operation_name, wire_method, params
):
    connection = WriterAppServerConnection(DummyWebSocket())
    connection.initialized = True
    entered = asyncio.Event()

    async def core_base_spy(*, request_id, params, context):
        entered.set()
        return core_live_operations_module.CoreLiveOperationOutcome(
            response=rpc_result(request_id, {"trace": "core-base", "thread_id": params["thread_id"]})
        )

    monkeypatch.setitem(
        core_live_operations_module._CORE_LIVE_OPERATION_EXECUTORS,
        operation_name,
        core_base_spy,
    )
    await connection._handle_raw(
        {
            "id": 11,
            "method": wire_method,
            "params": {"thread_id": "thread-core-spy", **params},
        }
    )

    response = await asyncio.wait_for(connection.outbound.get(), timeout=0.5)
    assert entered.is_set()
    assert response["result"]["trace"] == "core-base"


@pytest.mark.parametrize(
    ("run_status", "thread_status"),
    [
        ("running", "running"),
        ("waiting", "waiting"),
        ("completed", "completed"),
        ("failed", "failed"),
    ],
)
def test_writer_replay_syncs_outer_turn_status_from_core_run_item(run_status, thread_status):
    turn_id = "writer-turn-1"
    events = [
        app_event("accepted", 1, "turn/accepted", {"type": "turn", "status": "running"}, turn_id=turn_id),
        app_event(
            f"core-{run_status}",
            2,
            "core/runItem",
            RunItemEvent(
                event_id=f"core-item-{run_status}",
                kind="status",
                thread_id="thread-1",
                run_id=turn_id,
                turn_id=turn_id,
                item_id=f"{turn_id}:{run_status}",
                status=run_status,
                payload={"type": "turn", "status": run_status},
            ).to_dict(),
            turn_id=turn_id,
        ),
    ]

    state = reduce_events("thread-1", events)

    assert state["core"]["turns"][turn_id]["status"] == run_status
    assert state["turns"][turn_id]["status"] == run_status
    assert state["core"]["turns"][turn_id]["last_seq"] == 2
    assert state["turns"][turn_id]["last_seq"] == 2
    assert state["core"]["status"] == thread_status
    assert state["status"] == thread_status

def test_connection_accepts_runtime_lifecycle_dependency():
    class FakeRuntime:
        def writer_service_or_none(self):
            return None

        async def approval_coordinator(self, _thread_id):
            return None

    runtime = FakeRuntime()
    connection = WriterAppServerConnection(DummyWebSocket(), runtime=runtime)

    assert connection.runtime is runtime


def test_operation_names_normalize_transport_aliases():
    assert operation_name("turn/start") == "turn.start"
    assert operation_name("turn/interrupt") == "turn.cancel"
    assert operation_name("turn.interrupt") == "turn.cancel"
    assert operation_name("approval/respond") == "approval.respond"


def _build_test_writer_catalog(handler):
    overlay_arguments = (
        "project_directory_pick", "attachment_list",
        "attachment_get", "attachment_preview", "attachment_open", "session_create",
        "session_get", "session_list", "session_update", "session_delete", "session_fork",
        "session_git_graph", "session_changes_get", "session_checkpoints_list",
        "session_checkpoint_create", "session_checkpoint_restore", "session_commit_review_get",
        "session_commit_review_decide", "session_agent_branches_list",
        "session_agent_branch_diff", "session_agent_branch_merge",
        "session_agent_branch_abandon", "session_rollback_turn", "session_changes_undo",
        "session_change_file_open", "session_change_file_undo",
    )

    async def core_handler(request):
        return OperationResult(name=request.name)

    return build_writer_operation_catalog(
        core_handlers={name: core_handler for name in CORE_WORKBENCH_OPERATION_NAMES},
        **{name: handler for name in overlay_arguments},
    )


@pytest.mark.asyncio
async def test_writer_operation_catalog_wraps_rpc_handlers():
    called = []

    async def fake_handler(request):
        called.append(request.method)

    catalog = _build_test_writer_catalog(fake_handler)

    await catalog.execute(
        "project.create",
        metadata={"rpc_request": connection_module.JsonRpcRequest(id=1, method="project.create", params={})},
    )

    assert called == []


def test_plugin_operations_are_registered_in_writer_catalog():
    async def fake_handler(request):
        return None

    catalog = _build_test_writer_catalog(fake_handler)

    assert catalog.has("plugin.list")
    assert catalog.has("plugin.enable")
    assert catalog.has("plugin.disable")
    assert catalog.has("hook.list")
    assert catalog.has("hook.trust")


def test_writer_plugin_hook_wiring_uses_core_helpers():
    app_root = Path(__file__).resolve().parents[1] / "app"
    operations_source = (app_root / "app_server/operations.py").read_text(encoding="utf-8")
    kernel_source = (app_root / "core/writer/core_kernel_adapter.py").read_text(encoding="utf-8")

    assert "build_core_plugin_operation_catalog" in operations_source
    assert "assemble_core_agent_plugins" in kernel_source
    assert "core-plugin-state.json" not in operations_source + kernel_source
    assert "core-hook-trust.json" not in operations_source + kernel_source
    assert "PluginRegistry" not in operations_source
    assert "HookTrustStore" not in operations_source


def test_writer_operation_catalog_covers_app_server_rpc_methods():
    async def fake_handler(request):
        return None

    catalog = _build_test_writer_catalog(fake_handler)

    assert catalog.list() == [
        "approval.respond",
        "artifact.open",
        "artifact.read",
        "attachment.get",
        "attachment.list",
        "attachment.open",
        "attachment.preview",
        "command.catalog",
        "command.execute",
        "config.adapter_profiles.list",
        "config.import_env",
        "config.model.create",
        "config.model.delete",
        "config.model.update",
        "config.models.list",
        "config.provider.create",
        "config.provider.delete",
        "config.provider.update",
        "config.providers.list",
        "config.resolved.get",
        "config.runtime_capabilities.get",
        "config.subagent.delete",
        "config.subagent.upsert",
        "hook.list",
        "hook.trust",
        "plugin.disable",
        "plugin.enable",
        "plugin.list",
        "project.agents_md.get",
        "project.agents_md.update",
        "project.create",
        "project.delete",
        "project.directory.pick",
            "project.get",
            "project.list",
            "project.sessions.create",
            "project.sessions.list",
        "project.update",
            "queue.create",
            "queue.delete",
            "queue.guide",
            "queue.update",
        "session.agent_branch.abandon",
        "session.agent_branch.diff",
        "session.agent_branch.merge",
        "session.agent_branches.list",
        "session.change_file.open",
        "session.change_file.undo",
        "session.changes.get",
        "session.changes.undo",
        "session.checkpoint.create",
        "session.checkpoint.restore",
        "session.checkpoints.list",
        "session.commit_review.decide",
        "session.commit_review.get",
        "session.create",
        "session.delete",
        "session.fork",
        "session.get",
        "session.git_graph.get",
        "session.list",
        "session.rollback_turn",
        "session.update",
        "settings.get",
        "settings.update",
        "thread.read",
        "thread.resume",
        "thread.start",
        "turn.cancel",
        "turn.start",
        "turn.steer",
    ]


def test_writer_operation_catalog_is_core_workbench_plus_writer_overlay():
    async def fake_handler(request):
        return None

    catalog = _build_test_writer_catalog(fake_handler)

    assert set(catalog.list()) == set(CORE_WORKBENCH_OPERATION_NAMES) | set(WRITER_OVERLAY_OPERATION_NAMES)
    assert not (set(CORE_WORKBENCH_OPERATION_NAMES) & set(WRITER_OVERLAY_OPERATION_NAMES))
    assert WRITER_OVERLAY_OPERATION_NAMES.count("project.directory.pick") == 1


@pytest.mark.asyncio
async def test_turn_cancel_operation_returns_error_without_thread_id():
    outcome = await handle_core_turn_cancel_operation(request_id=1, params={}, context=_core_live_context())

    assert outcome.response["error"]["message"] == "thread_id is required"
    assert outcome.publish_events == []




@pytest.mark.asyncio
async def test_command_catalog_includes_core_and_dynamic_skills(tmp_path):
    skill_dir = tmp_path / ".codex" / "skills" / "reviewer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: reviewer\ndescription: Review code\n---\nREVIEW BODY\n",
        encoding="utf-8",
    )

    outcome = await handle_command_catalog_operation(
        request_id=1,
        params={"work_root": str(tmp_path)},
    )

    names = [item["name"] for item in outcome.response["result"]["commands"]]
    assert "compact" in names
    assert "fork" in names
    assert "reviewer" in names


@pytest.mark.asyncio
async def test_command_catalog_hides_skill_names_disabled_by_member_config(tmp_path, monkeypatch):
    member_root = tmp_path / "member-writer"
    skill_dir = member_root / "skills" / "disabled-skill-catalog"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: /Disabled Skill Catalog\ndescription: Review code\n---\nREVIEW BODY\n",
        encoding="utf-8",
    )
    (member_root / "command").mkdir(parents=True)
    (member_root / "command" / "config.json").write_text(
        '{"disabled_core_commands":["disabled skill catalog"]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("LAMWRITER_MEMBER_RESOURCE_DIR", str(member_root))

    outcome = await handle_command_catalog_operation(
        request_id=1,
        params={"work_root": str(tmp_path)},
    )

    names = [item["name"] for item in outcome.response["result"]["commands"]]
    assert "disabled-skill-catalog" not in names
    assert "disabled skill catalog" not in names
    assert "/Disabled Skill Catalog" not in names


@pytest.mark.asyncio
async def test_command_catalog_hides_skill_names_that_collide_with_core_commands(tmp_path, monkeypatch):
    member_root = tmp_path / "member-writer"
    skill_dir = member_root / "skills" / "fork"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: fork\ndescription: Review code\n---\nREVIEW BODY\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LAMWRITER_MEMBER_RESOURCE_DIR", str(member_root))

    outcome = await handle_command_catalog_operation(
        request_id=1,
        params={"work_root": str(tmp_path)},
    )

    matching = [item for item in outcome.response["result"]["commands"] if item["name"] == "fork"]
    assert len(matching) == 1
    assert matching[0]["action"] == "run_action"


@pytest.mark.asyncio
async def test_command_catalog_hides_mixed_case_skill_names_that_collide_with_core_commands(
    tmp_path, monkeypatch
):
    member_root = tmp_path / "member-writer"
    skill_dir = member_root / "skills" / "fork-mixed"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: /Fork\ndescription: Review code\n---\nREVIEW BODY\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LAMWRITER_MEMBER_RESOURCE_DIR", str(member_root))

    outcome = await handle_command_catalog_operation(
        request_id=1,
        params={"work_root": str(tmp_path)},
    )

    names = [item["name"] for item in outcome.response["result"]["commands"]]
    assert "/Fork" not in names
    matching = [item for item in outcome.response["result"]["commands"] if item["name"] == "fork"]
    assert len(matching) == 1
    assert matching[0]["action"] == "run_action"




@pytest.mark.asyncio
async def test_command_execute_forks_session_and_compacts_session_context(tmp_path):
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    for args in (
        ["git", "init"],
        ["git", "config", "user.email", "writer@example.test"],
        ["git", "config", "user.name", "Writer Test"],
    ):
        subprocess.run(args, cwd=work_root, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (work_root / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=work_root, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(
        ["git", "commit", "-m", "test: baseline"],
        cwd=work_root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'command-execute.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="thread-command", title="Command", work_root=str(work_root)))
            base_time = datetime.now(timezone.utc)
            for index in range(8):
                db.add(
                    WriterMessage(
                        id=f"cmd-{index}",
                        session_id="thread-command",
                        role="user" if index % 2 == 0 else "assistant",
                        content=f"cmd-message-{index}",
                        created_at=base_time + timedelta(seconds=index),
                    )
                )
            await db.commit()

        fork = await handle_command_execute_operation(
            request_id=1,
            params={"session_id": "thread-command", "command": "fork", "work_root": str(work_root)},
            session_factory=session_factory,
        )
        compact = await handle_command_execute_operation(
            request_id=2,
            params={"session_id": "thread-command", "command": "compact", "work_root": str(work_root)},
            session_factory=session_factory,
        )

        assert fork.response["result"]["result"]["status"] == "forked"
        assert fork.response["result"]["result"]["session"]["id"] != "thread-command"
        assert compact.response["result"]["result"]["status"] == "compacted"
        assert compact.response["result"]["result"]["compacted_messages"] == 2
        compact_snapshot = compact.response["result"]["snapshot"]
        compact_items = compact_snapshot["core"]["items"]
        compact_item = next(
            item
            for item in compact_items.values()
            if item.get("payload", {}).get("type") == "compaction"
            and item.get("payload", {}).get("compacted_messages") == 2
        )
        assert compact_item["last_seq"] == compact.response["result"]["snapshot"]["snapshot_seq"]
        assert compact_snapshot["core"]["turns"][compact_item["turn_id"]]["last_seq"] == compact_snapshot["snapshot_seq"]
        assert any(
            event.method == "core/runItem"
            and event.payload.get("payload", {}).get("type") == "compaction"
            and event.payload.get("payload", {}).get("compacted_messages") == 2
            for event in compact.publish_events
        )

        async with session_factory() as db:
            session = await db.get(WriterSession, "thread-command")
            assert session is not None
            assert "cmd-message-0" in (session.context_summary or "")
            assert session.runtime_state["manual_compaction"]["retained_message_count"] == 6
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_command_execute_compact_uses_injected_core_compaction_interface(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'command-compact-injected.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    calls: list[str] = []

    async def compact_session_context(*, session_id: str, on_summary_delta=None):
        del on_summary_delta
        calls.append(session_id)
        summary = "[Compacted Context]\n1. Current Goal\n- From injected interface."
        return {
            "status": "compacted",
            "session_id": session_id,
            "compacted_at": datetime.now(timezone.utc).isoformat(),
            "compacted_messages": 7,
            "retained_messages": 6,
            "summary": summary,
        }

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="thread-injected-compact", title="Command"))
            await db.commit()

        compact = await handle_command_execute_operation(
            request_id=1,
            params={"session_id": "thread-injected-compact", "command": "compact"},
            session_factory=session_factory,
            writer_service={"compact_session_context": compact_session_context},
        )

        assert calls == ["thread-injected-compact"]
        assert compact.response["result"]["result"]["status"] == "compacted"
        assert compact.response["result"]["result"]["compacted_messages"] == 7
        compact_items = compact.response["result"]["snapshot"]["core"]["items"]
        assert any(
            item.get("payload", {}).get("type") == "compaction"
            and item.get("payload", {}).get("content", "").startswith("[Compacted Context]")
            for item in compact_items.values()
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_command_execute_compact_emits_running_delta_and_completed_events(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'command-compact-events.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    emitted = []
    summary = "[Compacted Context]\n1. Current Goal\n- streamed compact summary"

    async def compact_session_context(*, session_id: str, on_summary_delta=None):
        if on_summary_delta is not None:
            await on_summary_delta("[Compacted Context]\n")
            await on_summary_delta("1. Current Goal\n- streamed compact summary")
        return {
            "status": "compacted",
            "session_id": session_id,
            "compacted_at": datetime.now(timezone.utc).isoformat(),
            "compacted_messages": 4,
            "retained_messages": 6,
            "summary": summary,
        }

    async def emit_event(event):
        emitted.append(event)

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="thread-streaming-compact", title="Command"))
            await db.commit()

        compact = await handle_command_execute_operation(
            request_id=1,
            params={"session_id": "thread-streaming-compact", "command": "compact"},
            session_factory=session_factory,
            writer_service={"compact_session_context": compact_session_context},
            emit_event=emit_event,
        )

        assert compact.response["result"]["result"]["status"] == "compacted"
        assert compact.publish_events == []
        assert [event.payload.get("status") for event in emitted] == [
            "running",
            "running",
            "running",
            "completed",
        ]
        payloads = [event.payload.get("payload", {}) for event in emitted]
        assert payloads[0]["type"] == "compaction"
        assert payloads[0]["label"] == "正在压缩"
        assert payloads[1]["delta"] == "[Compacted Context]\n"
        assert payloads[2]["delta"] == "1. Current Goal\n- streamed compact summary"
        assert payloads[3]["label"] == "上下文已压缩"
        assert payloads[3]["content"] == summary
        assert len({event.payload.get("item_id") for event in emitted}) == 1
        compact_items = compact.response["result"]["snapshot"]["core"]["items"]
        compact_item = next(item for item in compact_items.values() if item.get("payload", {}).get("type") == "compaction")
        assert compact_item["content"] == summary
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_command_execute_compact_failure_marks_thread_terminal(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'command-compact-failure-terminal.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def compact_session_context(*, session_id: str, on_summary_delta=None):
        raise ValueError("forced compaction failure")

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="thread-failing-compact", title="Command"))
            await db.commit()

        compact = await handle_command_execute_operation(
            request_id=1,
            params={"session_id": "thread-failing-compact", "command": "compact"},
            session_factory=session_factory,
            writer_service={"compact_session_context": compact_session_context},
        )

        async with session_factory() as db:
            after_failure = await load_snapshot(db, "thread-failing-compact")

        stop = await handle_core_turn_cancel_operation(
            request_id=2,
            params={"thread_id": "thread-failing-compact"},
            context=_core_live_context(session_factory),
        )

        async with session_factory() as db:
            after_stop = await load_snapshot(db, "thread-failing-compact")

        assert compact.response["error"]["message"] == "forced compaction failure"
        assert after_failure["status"] == "failed"
        assert after_failure["core"]["status"] == "failed"
        compact_items = after_failure["core"]["items"]
        assert any(
            item.get("payload", {}).get("type") == "compaction"
            and item.get("payload", {}).get("label") == "压缩失败"
            and item.get("status") == "failed"
            for item in compact_items.values()
        )
        assert stop.response["result"]["status"] == "idle"
        assert after_stop["status"] == "failed"
        assert after_stop["core"]["status"] == "failed"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_command_execute_compact_returns_clear_errors(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'command-compact-errors.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="thread-short", title="Short"))
            base_time = datetime.now(timezone.utc)
            for index in range(6):
                db.add(
                    WriterMessage(
                        id=f"short-{index}",
                        session_id="thread-short",
                        role="user" if index % 2 == 0 else "assistant",
                        content=f"short-message-{index}",
                        created_at=base_time + timedelta(seconds=index),
                    )
                )
            await db.commit()

        missing = await handle_command_execute_operation(
            request_id=1,
            params={"session_id": "missing-session", "command": "compact"},
            session_factory=session_factory,
        )
        short = await handle_command_execute_operation(
            request_id=2,
            params={"session_id": "thread-short", "command": "compact"},
            session_factory=session_factory,
        )

        assert missing.response["error"]["message"] == "Session not found"
        assert short.response["result"]["result"]["status"] == "compacted"
        assert short.response["result"]["result"]["compacted_messages"] == 1
        assert short.response["result"]["result"]["retained_messages"] == 5
        compact_items = short.response["result"]["snapshot"]["core"]["items"]
        assert any(
            item.get("payload", {}).get("type") == "compaction"
            and item.get("payload", {}).get("label") == "上下文已压缩"
            and item.get("payload", {}).get("compacted_messages") == 1
            and item.get("payload", {}).get("retained_messages") == 5
            for item in compact_items.values()
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_settings_operations_return_validation_errors():
    get_result = await handle_settings_get_operation(request_id=1, params={})
    update_result = await handle_settings_update_operation(request_id=2, params={"namespace": "x"})

    assert get_result.response["error"]["message"] == "namespace is required"
    assert update_result.response["error"]["message"] == "namespace and value are required"


@pytest.mark.asyncio
async def test_provider_write_operations_return_validation_errors():
    create = await handle_config_provider_create_operation(request_id=1, params={})
    update = await handle_config_provider_update_operation(request_id=2, params={})
    delete = await handle_config_provider_delete_operation(request_id=3, params={})

    assert create.response["error"]["message"] == "name, base_url and api_key are required"
    assert update.response["error"]["message"] == "provider_id is required"
    assert delete.response["error"]["message"] == "provider_id is required"


@pytest.mark.asyncio
async def test_provider_create_retries_when_sqlite_database_is_locked(monkeypatch):
    attempts = 0

    async def flaky_create_provider_config(db, payload):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OperationalError("INSERT INTO llm_providers", {}, Exception("database is locked"))
        return {"id": "provider-retry", "name": payload["name"], "api_key": "sk-r...cret"}

    monkeypatch.setattr(operations_module, "create_provider_config", flaky_create_provider_config)

    outcome = await handle_config_provider_create_operation(
        request_id=1,
        params={
            "name": "Retry Provider",
            "api_type": "openai",
            "base_url": "https://api.retry.test/v1",
            "api_key": "sk-retry-secret",
        },
        config_session_factory=dummy_shared_config_session,
    )

    assert attempts == 3
    assert outcome.response["result"]["provider"]["id"] == "provider-retry"


@pytest.mark.asyncio
async def test_provider_create_returns_clear_error_when_sqlite_database_stays_locked(monkeypatch):
    attempts = 0

    async def locked_create_provider_config(db, payload):
        nonlocal attempts
        attempts += 1
        raise OperationalError("INSERT INTO llm_providers", {}, Exception("database is locked"))

    monkeypatch.setattr(operations_module, "create_provider_config", locked_create_provider_config)

    outcome = await handle_config_provider_create_operation(
        request_id=1,
        params={
            "name": "Locked Provider",
            "api_type": "openai",
            "base_url": "https://api.locked.test/v1",
            "api_key": "sk-locked-secret",
        },
        config_session_factory=dummy_shared_config_session,
    )

    assert attempts == 3
    assert outcome.response["error"]["message"] == "数据库正忙，请稍后重试"


@pytest.mark.asyncio
async def test_project_write_operations_return_validation_errors():
    get_result = await handle_project_get_operation(request_id=1, params={})
    update_result = await handle_project_update_operation(request_id=2, params={})
    delete_result = await handle_project_delete_operation(request_id=3, params={})
    agents_get = await handle_project_agents_md_get_operation(request_id=4, params={})
    agents_update = await handle_project_agents_md_update_operation(request_id=5, params={"project_id": "p"})
    sessions = await handle_project_sessions_list_operation(request_id=6, params={})

    assert get_result.response["error"]["message"] == "project_id is required"
    assert update_result.response["error"]["message"] == "project_id is required"
    assert delete_result.response["error"]["message"] == "project_id is required"
    assert agents_get.response["error"]["message"] == "project_id is required"
    assert agents_update.response["error"]["message"] == "content is required"
    assert sessions.response["error"]["message"] == "project_id is required"


@pytest.mark.asyncio
async def test_model_write_operations_return_validation_errors():
    create = await handle_config_model_create_operation(request_id=1, params={})
    update = await handle_config_model_update_operation(request_id=2, params={})
    delete = await handle_config_model_delete_operation(request_id=3, params={})

    assert create.response["error"]["message"] == "provider_id and model_id are required"
    assert update.response["error"]["message"] == "model_record_id is required"
    assert delete.response["error"]["message"] == "model_record_id is required"


@pytest.mark.asyncio
async def test_subagent_write_operations_return_validation_errors():
    upsert = await handle_config_subagent_upsert_operation(request_id=1, params={})
    delete = await handle_config_subagent_delete_operation(request_id=2, params={})

    assert upsert.response["error"]["message"] == "name is required"
    assert delete.response["error"]["message"] == "name is required"


@pytest.mark.asyncio
async def test_artifact_operations_return_validation_errors():
    read = await handle_artifact_read_operation(request_id=1, params={})
    open_result = await handle_artifact_open_operation(request_id=2, params={})

    assert read.response["error"]["message"] == "thread_id and artifact_id are required"
    assert open_result.response["error"]["message"] == "thread_id and artifact_id are required"


@pytest.mark.asyncio
async def test_attachment_operations_return_validation_errors():
    listed = await handle_attachment_list_operation(request_id=1, params={})
    read = await handle_attachment_get_operation(request_id=2, params={})
    preview = await handle_attachment_preview_operation(request_id=3, params={})
    open_result = await handle_attachment_open_operation(request_id=4, params={})

    assert listed.response["error"]["message"] == "session_id is required"
    assert read.response["error"]["message"] == "attachment_id is required"
    assert preview.response["error"]["message"] == "attachment_id is required"
    assert open_result.response["error"]["message"] == "attachment_id is required"


@pytest.mark.asyncio
async def test_thread_operations_return_validation_errors_without_thread_id():
    start = await handle_core_thread_start_operation(request_id=1, params={}, context=_core_live_context())
    resume = await handle_core_thread_resume_operation(request_id=2, params={}, context=_core_live_context())
    read = await handle_core_thread_read_operation(request_id=3, params={}, context=_core_live_context())

    assert start.response["error"]["message"] == "thread_id is required"
    assert resume.response["error"]["message"] == "thread_id is required"
    assert read.response["error"]["message"] == "thread_id is required"


@pytest.mark.asyncio
async def test_session_get_update_delete_operations_return_validation_errors():
    get_result = await handle_session_get_operation(request_id=1, params={})
    update_result = await handle_session_update_operation(request_id=2, params={})
    delete_result = await handle_session_delete_operation(request_id=3, params={})
    fork = await handle_session_fork_operation(request_id=4, params={})
    git_graph = await handle_session_git_graph_get_operation(request_id=5, params={})
    changes = await handle_session_changes_get_operation(request_id=6, params={})
    checkpoints = await handle_session_checkpoints_list_operation(request_id=7, params={})
    checkpoint_create = await handle_session_checkpoint_create_operation(request_id=8, params={})
    checkpoint_restore = await handle_session_checkpoint_restore_operation(request_id=9, params={})
    commit_review = await handle_session_commit_review_get_operation(request_id=10, params={})
    commit_decision = await handle_session_commit_review_decide_operation(request_id=11, params={})
    agent_branches = await handle_session_agent_branches_list_operation(request_id=12, params={})
    agent_branch_diff = await handle_session_agent_branch_diff_operation(request_id=13, params={})
    agent_branch_merge = await handle_session_agent_branch_merge_operation(request_id=14, params={})
    agent_branch_abandon = await handle_session_agent_branch_abandon_operation(request_id=15, params={})
    rollback_turn = await handle_session_rollback_turn_operation(request_id=16, params={})
    undo_changes = await handle_session_changes_undo_operation(request_id=17, params={})
    undo_file = await handle_session_change_file_undo_operation(request_id=18, params={})

    assert get_result.response["error"]["message"] == "session_id is required"
    assert update_result.response["error"]["message"] == "session_id is required"
    assert delete_result.response["error"]["message"] == "session_id is required"
    assert fork.response["error"]["message"] == "session_id is required"
    assert git_graph.response["error"]["message"] == "session_id is required"
    assert changes.response["error"]["message"] == "session_id is required"
    assert checkpoints.response["error"]["message"] == "session_id is required"
    assert checkpoint_create.response["error"]["message"] == "session_id is required"
    assert checkpoint_restore.response["error"]["message"] == "session_id and commit are required"
    assert commit_review.response["error"]["message"] == "session_id is required"
    assert commit_decision.response["error"]["message"] == "session_id and action are required"
    assert agent_branches.response["error"]["message"] == "session_id is required"
    assert agent_branch_diff.response["error"]["message"] == "session_id and branch are required"
    assert agent_branch_merge.response["error"]["message"] == "session_id and branch are required"
    assert agent_branch_abandon.response["error"]["message"] == "session_id and branch are required"
    assert rollback_turn.response["error"]["message"] == "session_id is required"
    assert undo_changes.response["error"]["message"] == "session_id is required"
    assert undo_file.response["error"]["message"] == "session_id and path are required"


@pytest.mark.asyncio
async def test_thread_read_operation_returns_session_projection(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'thread-read.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(
                WriterSession(
                    id="session-1",
                    title="Readable",
                    status="active",
                    phase="idle",
                    mode="PLAN",
                    work_root="E:\\work",
                )
            )
            await db.commit()

        monkeypatch.setattr(connection_module, "async_session", session_factory)
        connection = WriterAppServerConnection(DummyWebSocket())
        connection.initialized = True
        await connection._handle_raw(
            {"id": 1, "method": "thread.read", "params": {"thread_id": "session-1"}}
        )

        result = (await connection.outbound.get())["result"]
        assert result["thread"] == {"id": "session-1"}
        assert result["session"]["id"] == "session-1"
        assert result["session"]["mode"] == "PLAN"
        assert result["snapshot"]["thread_id"] == "session-1"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_rollback_turn_hides_rolled_back_turn_from_transcript(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rollback-turn.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="session-rollback", title="Rollback", status="active", mode="EXECUTE"))
            db.add_all(
                [
                    WriterMessage(id="user-1", session_id="session-rollback", role="user", content="第一轮"),
                    WriterMessage(id="assistant-1", session_id="session-rollback", role="assistant", content="第一轮完成"),
                    WriterTranscriptTurn(
                        id="turn-1",
                        session_id="session-rollback",
                        sequence=1,
                        user_text="第一轮",
                        user_message_id="user-1",
                        status_cache="completed",
                        final_reply_block_id="final-1",
                        terminal_reason="completed",
                    ),
                    WriterTranscriptBlock(
                        id="final-1",
                        turn_id="turn-1",
                        sequence=1,
                        event_sequence=1,
                        type="model_text",
                        status="completed",
                        content="第一轮完成",
                    ),
                    WriterMessage(id="user-2", session_id="session-rollback", role="user", content="第二轮"),
                    WriterMessage(id="assistant-2", session_id="session-rollback", role="assistant", content="第二轮完成"),
                    WriterTranscriptTurn(
                        id="turn-2",
                        session_id="session-rollback",
                        sequence=2,
                        user_text="第二轮",
                        user_message_id="user-2",
                        status_cache="completed",
                        final_reply_block_id="final-2",
                        terminal_reason="completed",
                    ),
                    WriterTranscriptBlock(
                        id="final-2",
                        turn_id="turn-2",
                        sequence=1,
                        event_sequence=1,
                        type="model_text",
                        status="completed",
                        content="第二轮完成",
                    ),
                ]
            )
            await db.commit()

        outcome = await handle_session_rollback_turn_operation(
            request_id=1,
            params={"session_id": "session-rollback", "turn_id": "turn-2", "reason": "结果不对"},
            session_factory=session_factory,
        )

        assert outcome.response["result"]["rolled_back_turn_ids"] == ["turn-2"]
        async with session_factory() as db:
            projected = await project_transcript(db, "session-rollback")

        assert [turn["turn_id"] for turn in projected["turns"]] == ["turn-1"]
        assert "第二轮完成" not in str(projected)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_rollback_turn_updates_app_server_snapshot(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rollback-snapshot.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="session-snapshot", title="Snapshot", status="active", mode="EXECUTE"))
            db.add_all(
                [
                    WriterMessage(id="user-snap-1", session_id="session-snapshot", role="user", content="第一轮"),
                    WriterTranscriptTurn(
                        id="turn-snap-1",
                        session_id="session-snapshot",
                        sequence=1,
                        user_text="第一轮",
                        user_message_id="user-snap-1",
                        status_cache="completed",
                    ),
                    WriterMessage(id="user-snap-2", session_id="session-snapshot", role="user", content="第二轮"),
                    WriterTranscriptTurn(
                        id="turn-snap-2",
                        session_id="session-snapshot",
                        sequence=2,
                        user_text="第二轮",
                        user_message_id="user-snap-2",
                        status_cache="completed",
                    ),
                    WriterAppEvent(
                        event_id="snapshot-history-7",
                        thread_id="session-snapshot",
                        seq=7,
                        method="turn/accepted",
                        turn_id="turn-snap-2",
                        payload_json={"type": "turn", "status": "completed"},
                    ),
                    WriterThreadSnapshot(
                        thread_id="session-snapshot",
                        snapshot_seq=7,
                        snapshot_json={
                            "thread_id": "session-snapshot",
                            "snapshot_seq": 7,
                            "seen_event_ids": [],
                            "turns": {
                                "turn-snap-1": {"turn_id": "turn-snap-1", "status": "completed", "items": ["outer-1"]},
                                "turn-snap-2": {"turn_id": "turn-snap-2", "status": "completed", "items": ["outer-2"]},
                            },
                            "items": {
                                "outer-1": {"item_id": "outer-1", "turn_id": "turn-snap-1", "type": "userMessage", "content": "第一轮"},
                                "outer-2": {"item_id": "outer-2", "turn_id": "turn-snap-2", "type": "userMessage", "content": "第二轮"},
                            },
                            "item_order": ["outer-1", "outer-2"],
                            "queue": [],
                            "requests": {},
                            "artifacts": {},
                            "core": {
                                "thread_id": "session-snapshot",
                                "status": "completed",
                                "turns": {
                                    "turn-snap-1": {"turn_id": "turn-snap-1", "status": "completed"},
                                    "turn-snap-2": {"turn_id": "turn-snap-2", "status": "completed"},
                                },
                                "items": {
                                    "core-1": {"item_id": "core-1", "turn_id": "turn-snap-1", "kind": "message", "status": "completed"},
                                    "core-2": {"item_id": "core-2", "turn_id": "turn-snap-2", "kind": "message", "status": "completed"},
                                },
                                "item_order": ["core-1", "core-2"],
                                "requests": {},
                                "artifacts": {},
                            },
                            "status": "completed",
                        },
                    ),
                ]
            )
            await db.commit()

        outcome = await handle_session_rollback_turn_operation(
            request_id=1,
            params={"session_id": "session-snapshot", "turn_id": "turn-snap-2"},
            session_factory=session_factory,
        )

        snapshot = outcome.response["result"]["snapshot"]
        assert "turn-snap-2" not in snapshot["turns"]
        assert "outer-2" not in snapshot["items"]
        assert "turn-snap-2" not in snapshot["core"]["turns"]
        assert "core-2" not in snapshot["core"]["items"]
        assert snapshot["item_order"] == ["outer-1"]
        assert snapshot["core"]["item_order"] == ["core-1"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_rollback_turn_excludes_rolled_back_messages_from_runtime_history(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rollback-history.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="session-history", title="History", status="active", mode="EXECUTE"))
            db.add_all(
                [
                    WriterMessage(id="user-1", session_id="session-history", role="user", content="保留第一轮"),
                    WriterMessage(id="assistant-1", session_id="session-history", role="assistant", content="第一轮完成"),
                    WriterTranscriptTurn(
                        id="turn-1",
                        session_id="session-history",
                        sequence=1,
                        user_text="保留第一轮",
                        user_message_id="user-1",
                        status_cache="completed",
                        final_reply_block_id="final-1",
                        terminal_reason="completed",
                    ),
                    WriterTranscriptBlock(
                        id="final-1",
                        turn_id="turn-1",
                        sequence=1,
                        event_sequence=1,
                        type="model_text",
                        status="completed",
                        content="第一轮完成",
                    ),
                    WriterMessage(id="user-2", session_id="session-history", role="user", content="需要回退的第二轮"),
                    WriterMessage(id="assistant-2", session_id="session-history", role="assistant", content="第二轮错误结果"),
                    WriterTranscriptTurn(
                        id="turn-2",
                        session_id="session-history",
                        sequence=2,
                        user_text="需要回退的第二轮",
                        user_message_id="user-2",
                        status_cache="completed",
                        final_reply_block_id="final-2",
                        terminal_reason="completed",
                    ),
                    WriterTranscriptBlock(
                        id="final-2",
                        turn_id="turn-2",
                        sequence=1,
                        event_sequence=1,
                        type="model_text",
                        status="completed",
                        content="第二轮错误结果",
                    ),
                ]
            )
            await db.commit()

        await handle_session_rollback_turn_operation(
            request_id=1,
            params={"session_id": "session-history", "turn_id": "turn-2", "reason": "上下文污染"},
            session_factory=session_factory,
        )

        async with session_factory() as db:
            db.add(WriterMessage(id="user-3", session_id="session-history", role="user", content="重新继续"))
            db.add(
                WriterTranscriptTurn(
                    id="turn-3",
                    session_id="session-history",
                    sequence=3,
                    user_text="重新继续",
                    user_message_id="user-3",
                    status_cache="running",
                )
            )
            await db.commit()

            context = await prepare_runtime_input_context(
                db,
                session_id="session-history",
                transcript_turn_id="turn-3",
                user_message="重新继续",
                raw_user_message="重新继续",
            )

        assert context.history == [
            {"role": "user", "content": "保留第一轮", "id": "user-1"},
            {"role": "assistant", "content": "第一轮完成", "id": "assistant-1"},
        ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_rollback_turn_restores_bound_checkpoint(tmp_path):
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    for args in (
        ["git", "init"],
        ["git", "config", "user.email", "writer@example.test"],
        ["git", "config", "user.name", "Writer Test"],
    ):
        subprocess.run(args, cwd=work_root, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    target_file = work_root / "README.md"
    target_file.write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=work_root, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(
        ["git", "commit", "-m", "test: baseline"],
        cwd=work_root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    baseline = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=work_root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()
    target_file.write_text("bad change from turn 2\n", encoding="utf-8")

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rollback-checkpoint.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(
                WriterSession(
                    id="session-checkpoint-rollback",
                    title="Checkpoint Rollback",
                    status="active",
                    mode="EXECUTE",
                    work_root=str(work_root),
                    runtime_state={
                        "git_state": {
                            "checkpoints": [
                                {
                                    "label": "checkpoint",
                                    "reason": "第二轮完成后自动存档",
                                    "commit": baseline,
                                    "base_head": baseline,
                                    "turn_id": "turn-2",
                                    "stage": "after_turn",
                                    "storage": "checkpoint_branch",
                                }
                            ]
                        }
                    },
                )
            )
            db.add_all(
                [
                    WriterMessage(id="user-2", session_id="session-checkpoint-rollback", role="user", content="第二轮"),
                    WriterTranscriptTurn(
                        id="turn-2",
                        session_id="session-checkpoint-rollback",
                        sequence=2,
                        user_text="第二轮",
                        user_message_id="user-2",
                        status_cache="completed",
                    ),
                ]
            )
            await db.commit()

        outcome = await handle_session_rollback_turn_operation(
            request_id=1,
            params={"session_id": "session-checkpoint-rollback", "turn_id": "turn-2"},
            session_factory=session_factory,
        )

        assert outcome.response["result"]["restore"]["ref"] == baseline
        assert target_file.read_text(encoding="utf-8") == "baseline\n"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_fork_copies_context_up_to_selected_turn(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'session-fork.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="session-source", title="Source", status="active", mode="PLAN", work_root="E:\\work"))
            db.add_all(
                [
                    WriterMessage(id="source-user-1", session_id="session-source", role="user", content="第一轮需求"),
                    WriterMessage(id="source-assistant-1", session_id="session-source", role="assistant", content="第一轮答复"),
                    WriterTranscriptTurn(
                        id="source-turn-1",
                        session_id="session-source",
                        sequence=1,
                        user_text="第一轮需求",
                        user_message_id="source-user-1",
                        status_cache="completed",
                        final_reply_block_id="source-final-1",
                        terminal_reason="completed",
                    ),
                    WriterTranscriptBlock(
                        id="source-final-1",
                        turn_id="source-turn-1",
                        sequence=1,
                        event_sequence=1,
                        type="model_text",
                        status="completed",
                        content="第一轮答复",
                    ),
                    WriterMessage(id="source-user-2", session_id="session-source", role="user", content="第二轮需求"),
                    WriterMessage(id="source-assistant-2", session_id="session-source", role="assistant", content="第二轮答复"),
                    WriterTranscriptTurn(
                        id="source-turn-2",
                        session_id="session-source",
                        sequence=2,
                        user_text="第二轮需求",
                        user_message_id="source-user-2",
                        status_cache="completed",
                        final_reply_block_id="source-final-2",
                        terminal_reason="completed",
                    ),
                    WriterTranscriptBlock(
                        id="source-final-2",
                        turn_id="source-turn-2",
                        sequence=1,
                        event_sequence=1,
                        type="model_text",
                        status="completed",
                        content="第二轮答复",
                    ),
                ]
            )
            await db.commit()

        outcome = await handle_session_fork_operation(
            request_id=1,
            params={"session_id": "session-source", "after_turn_id": "source-turn-1", "title": "Forked"},
            session_factory=session_factory,
        )

        forked = outcome.response["result"]["session"]
        assert forked["id"] != "session-source"
        assert forked["title"] == "Forked"
        assert forked["mode"] == "PLAN"

        async with session_factory() as db:
            source_projection = await project_transcript(db, "session-source")
            fork_projection = await project_transcript(db, forked["id"])
            fork_messages = (
                await db.execute(
                    select(WriterMessage)
                    .where(WriterMessage.session_id == forked["id"])
                    .order_by(WriterMessage.created_at.asc())
                )
            ).scalars().all()

        assert [turn["user_text"] for turn in source_projection["turns"]] == ["第一轮需求", "第二轮需求"]
        assert [turn["user_text"] for turn in fork_projection["turns"]] == ["第一轮需求"]
        assert [message.content for message in fork_messages] == ["第一轮需求", "第一轮答复"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_fork_can_create_isolated_worktree_branch(tmp_path):
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    for args in (
        ["git", "init"],
        ["git", "config", "user.email", "writer@example.test"],
        ["git", "config", "user.name", "Writer Test"],
    ):
        subprocess.run(args, cwd=work_root, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (work_root / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=work_root, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(
        ["git", "commit", "-m", "test: baseline"],
        cwd=work_root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'session-fork-worktree.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(
                WriterSession(
                    id="session-worktree-source",
                    title="Source",
                    status="active",
                    mode="EXECUTE",
                    work_root=str(work_root),
                )
            )
            await db.commit()

        outcome = await handle_session_fork_operation(
            request_id=1,
            params={"session_id": "session-worktree-source", "isolated_worktree": True},
            session_factory=session_factory,
        )

        forked = outcome.response["result"]["session"]
        fork_root = Path(forked["work_root"])
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=fork_root,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.strip()

        assert fork_root != work_root
        assert fork_root.is_dir()
        assert branch.startswith("writer/session/")
        assert (fork_root / "README.md").read_text(encoding="utf-8") == "baseline\n"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_list_operation_returns_recent_sessions(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'session-list.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            older = WriterSession(
                id="session-old",
                title="Old",
                status="active",
                mode="EXECUTE",
                updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            newer = WriterSession(
                id="session-new",
                title="New",
                status="active",
                mode="PLAN",
                updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            )
            db.add_all([older, newer])
            await db.commit()

        outcome = await handle_session_list_operation(
            request_id=1,
            params={"limit": 1},
            session_factory=session_factory,
        )

        rows = outcome.response["result"]["sessions"]
        assert [row["id"] for row in rows] == ["session-new"]
        assert rows[0]["title"] == "New"
        assert rows[0]["mode"] == "PLAN"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_create_operation_creates_project_backed_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'session-create.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        work_root = tmp_path / "workspace"
        outcome = await handle_session_create_operation(
            request_id=1,
            params={"title": "Created", "work_root": str(work_root), "mode": "plan"},
            session_factory=session_factory,
        )

        row = outcome.response["result"]["session"]
        assert row["title"] == "Created"
        assert row["work_root"] == str(work_root.resolve())
        assert row["mode"] == "PLAN"
        assert row["project_id"]
        assert work_root.is_dir()
        assert not (work_root / ".git").exists()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_create_operation_rejects_client_project_id(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'session-create-invalid-project.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        outcome = await handle_session_create_operation(
            request_id=1,
            params={"title": "Invalid", "project_id": "missing-project"},
            session_factory=session_factory,
        )
        assert outcome.response["error"]["message"] == "Use project.sessions.create for project-owned sessions"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_get_update_delete_operations_round_trip(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'session-crud.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(
                WriterSession(
                    id="session-crud",
                    title="Original",
                    status="active",
                    phase="idle",
                    mode="EXECUTE",
                    work_root="",
                )
            )
            db.add(WriterMessage(id="message-crud", session_id="session-crud", role="user", content="hello"))
            db.add(
                WriterAppEvent(
                    event_id="event-crud",
                    thread_id="session-crud",
                    seq=1,
                    method="thread/test",
                    payload_json={"thread_id": "session-crud"},
                )
            )
            db.add(
                WriterThreadSnapshot(
                    thread_id="session-crud",
                    snapshot_seq=1,
                    snapshot_json={"thread_id": "session-crud"},
                )
            )
            db.add(
                WriterAttachment(
                    id="attachment-crud",
                    session_id="session-crud",
                    filename="note.txt",
                    storage_path=str(tmp_path / "note.txt"),
                )
            )
            await db.commit()

        read = await handle_session_get_operation(
            request_id=1,
            params={"session_id": "session-crud"},
            session_factory=session_factory,
        )
        assert read.response["result"]["session"]["title"] == "Original"

        updated_root = tmp_path / "app-server-updated"
        updated = await handle_session_update_operation(
            request_id=2,
            params={
                "session_id": "session-crud",
                "title": "Renamed",
                "mode": "plan",
                "work_root": str(updated_root),
            },
            session_factory=session_factory,
        )
        assert updated.response["result"]["session"]["title"] == "Renamed"
        assert updated.response["result"]["session"]["mode"] == "PLAN"
        assert updated_root.is_dir()
        assert not (updated_root / ".git").exists()

        deleted = await handle_session_delete_operation(
            request_id=3,
            params={"session_id": "session-crud"},
            session_factory=session_factory,
        )
        assert deleted.response["result"] == {"ok": True}

        async with session_factory() as db:
            assert await db.get(WriterSession, "session-crud") is None
            assert await db.get(WriterMessage, "message-crud") is None
            assert await db.get(WriterAppEvent, "event-crud") is None
            assert await db.get(WriterThreadSnapshot, "session-crud") is None
            assert await db.get(WriterAttachment, "attachment-crud") is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_git_graph_and_changes_operations_return_git_state(tmp_path):
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    for args in (
        ["git", "init"],
        ["git", "config", "user.email", "writer@example.test"],
        ["git", "config", "user.name", "Writer Test"],
    ):
        subprocess.run(args, cwd=work_root, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (work_root / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=work_root, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(
        ["git", "commit", "-m", "test: baseline"],
        cwd=work_root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    current_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=work_root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()
    subprocess.run(
        ["git", "checkout", "-b", "writer/agent/demo"],
        cwd=work_root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    (work_root / "agent.txt").write_text("agent branch\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=work_root, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(
        ["git", "commit", "-m", "test: agent branch"],
        cwd=work_root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "checkout", current_branch],
        cwd=work_root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    (work_root / "README.md").write_text("baseline\nchanged\n", encoding="utf-8")

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'session-git.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="session-git", title="Git Session", work_root=str(work_root)))
            await db.commit()

        graph = await handle_session_git_graph_get_operation(
            request_id=1,
            params={"session_id": "session-git"},
            session_factory=session_factory,
        )
        assert "lanes" in graph.response["result"]["graph"]

        changes = await handle_session_changes_get_operation(
            request_id=2,
            params={"session_id": "session-git"},
            session_factory=session_factory,
        )
        result = changes.response["result"]["changes"]
        assert result["source"] == "working_tree"
        assert [item["path"] for item in result["files"]] == ["README.md"]
        assert result["total_additions"] == 1

        branches = await handle_session_agent_branches_list_operation(
            request_id=3,
            params={"session_id": "session-git"},
            session_factory=session_factory,
        )
        assert branches.response["result"]["branches"][0]["branch"] == "writer/agent/demo"

        diff = await handle_session_agent_branch_diff_operation(
            request_id=4,
            params={"session_id": "session-git", "branch": "writer/agent/demo"},
            session_factory=session_factory,
        )
        assert diff.response["result"]["branch"] == "writer/agent/demo"
        assert "agent.txt" in diff.response["result"]["diff"]

        subprocess.run(
            ["git", "checkout", "--", "README.md"],
            cwd=work_root,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        merged = await handle_session_agent_branch_merge_operation(
            request_id=5,
            params={"session_id": "session-git", "branch": "writer/agent/demo"},
            session_factory=session_factory,
        )
        assert merged.response["result"]["status"] == "merged"
        assert merged.response["result"]["branch"] == "writer/agent/demo"
        assert (work_root / "agent.txt").read_text(encoding="utf-8") == "agent branch\n"

        subprocess.run(
            ["git", "checkout", "-b", "writer/agent/remove"],
            cwd=work_root,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        (work_root / "remove.txt").write_text("remove branch\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=work_root, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(
            ["git", "commit", "-m", "test: removable agent branch"],
            cwd=work_root,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["git", "checkout", current_branch],
            cwd=work_root,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        abandoned = await handle_session_agent_branch_abandon_operation(
            request_id=6,
            params={"session_id": "session-git", "branch": "writer/agent/remove"},
            session_factory=session_factory,
        )
        assert abandoned.response["result"] == {
            "status": "abandoned",
            "branch": "writer/agent/remove",
            "message": "Agent branch removed",
        }
        after_abandon = await handle_session_agent_branches_list_operation(
            request_id=7,
            params={"session_id": "session-git"},
            session_factory=session_factory,
        )
        assert "writer/agent/remove" not in {
            item["branch"] for item in after_abandon.response["result"]["branches"]
        }

        (work_root / "README.md").write_text("baseline\nchanged\n", encoding="utf-8")
        created = await handle_session_checkpoint_create_operation(
            request_id=8,
            params={"session_id": "session-git", "reason": "test checkpoint"},
            session_factory=session_factory,
        )
        checkpoint = created.response["result"]["checkpoint"]
        assert checkpoint["commit"]
        assert checkpoint["reason"] == "test checkpoint"

        listed = await handle_session_checkpoints_list_operation(
            request_id=9,
            params={"session_id": "session-git"},
            session_factory=session_factory,
        )
        assert listed.response["result"]["checkpoints"][0]["commit"] == checkpoint["commit"]

        (work_root / "README.md").write_text("broken\n", encoding="utf-8")
        restored = await handle_session_checkpoint_restore_operation(
            request_id=10,
            params={"session_id": "session-git", "commit": checkpoint["commit"]},
            session_factory=session_factory,
        )
        assert restored.response["result"]["status"] == "undone"
        assert (work_root / "README.md").read_text(encoding="utf-8") == "baseline\nchanged\n"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_attachment_operations_list_read_preview_and_open(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'attachments.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    opened: list[str] = []

    async def fake_open_attachment_response(db, attachment_id):
        from app.services.attachment_service import open_attachment_response

        return await open_attachment_response(db, attachment_id, opener=lambda path: opened.append(str(path)))

    try:
        attachment_path = tmp_path / "note.txt"
        attachment_path.write_text("hello attachment", encoding="utf-8")
        async with session_factory() as db:
            db.add(WriterSession(id="session-attachment", title="Attachment Session", work_root=str(tmp_path)))
            db.add(
                WriterAttachment(
                    id="attachment-text",
                    session_id="session-attachment",
                    filename="note.txt",
                    mime_type="text/plain",
                    size=16,
                    storage_path=str(attachment_path),
                    preview_type="text",
                    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                )
            )
            await db.commit()

        listed = await handle_attachment_list_operation(
            request_id=1,
            params={"session_id": "session-attachment"},
            session_factory=session_factory,
        )
        assert listed.response["result"]["attachments"][0]["id"] == "attachment-text"

        read = await handle_attachment_get_operation(
            request_id=2,
            params={"attachment_id": "attachment-text"},
            session_factory=session_factory,
        )
        assert read.response["result"]["attachment"]["filename"] == "note.txt"

        preview = await handle_attachment_preview_operation(
            request_id=3,
            params={"attachment_id": "attachment-text"},
            session_factory=session_factory,
        )
        assert preview.response["result"]["preview"]["text"] == "hello attachment"

        monkeypatch.setattr(operations_module, "open_attachment_response", fake_open_attachment_response)
        opened_result = await handle_attachment_open_operation(
            request_id=4,
            params={"attachment_id": "attachment-text"},
            session_factory=session_factory,
        )
        assert opened_result.response["result"] == {"status": "opened", "id": "attachment-text"}
        assert opened == [str(attachment_path)]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_commit_review_operations_read_and_request_changes(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'commit-review.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(
                WriterSession(
                    id="session-review-op",
                    title="Review Operation",
                    runtime_state={
                        "pending_commit_review": {
                            "id": "review-1",
                            "status": "pending",
                            "title": "Review",
                            "summary": "summary",
                            "how_to_review": "inspect",
                            "self_check": "checked",
                            "commit_message": "test: review",
                            "files": [{"path": "README.md", "additions": 1, "deletions": 0, "binary": False}],
                            "total_additions": 1,
                            "total_deletions": 0,
                            "source": "working_tree",
                            "ref": None,
                            "created_at": "2026-07-02T00:00:00+00:00",
                            "updated_at": "2026-07-02T00:00:00+00:00",
                        }
                    },
                )
            )
            await db.commit()

        read = await handle_session_commit_review_get_operation(
            request_id=1,
            params={"session_id": "session-review-op"},
            session_factory=session_factory,
        )
        assert read.response["result"]["review"]["id"] == "review-1"

        decided = await handle_session_commit_review_decide_operation(
            request_id=2,
            params={"session_id": "session-review-op", "action": "request_changes", "feedback": "fix it"},
            session_factory=session_factory,
        )
        review = decided.response["result"]["review"]
        assert review["status"] == "changes_requested"
        assert review["feedback"] == "fix it"

        async with session_factory() as db:
            count = (await db.execute(select(func.count()).select_from(WriterMessage))).scalar_one()
            assert count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_undo_operation_restores_worktree(tmp_path):
    work_root = tmp_path / "undo-workspace"
    work_root.mkdir()
    for args in (
        ["git", "init"],
        ["git", "config", "user.email", "writer@example.test"],
        ["git", "config", "user.name", "Writer Test"],
    ):
        subprocess.run(args, cwd=work_root, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (work_root / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=work_root, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(
        ["git", "commit", "-m", "test: baseline"],
        cwd=work_root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    (work_root / "README.md").write_text("changed\n", encoding="utf-8")
    (work_root / "scratch.txt").write_text("scratch\n", encoding="utf-8")

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'undo-operation.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="session-undo-op", title="Undo Operation", work_root=str(work_root)))
            await db.commit()

        single = await handle_session_change_file_undo_operation(
            request_id=1,
            params={"session_id": "session-undo-op", "path": "README.md"},
            session_factory=session_factory,
        )
        assert single.response["result"]["status"] == "undone"
        assert single.response["result"]["paths"] == ["README.md"]
        assert (work_root / "README.md").read_text(encoding="utf-8") == "baseline\n"

        outcome = await handle_session_changes_undo_operation(
            request_id=2,
            params={"session_id": "session-undo-op"},
            session_factory=session_factory,
        )
        assert outcome.response["result"]["status"] == "undone"
        assert set(outcome.response["result"]["paths"]) == {"scratch.txt"}
        assert (work_root / "README.md").read_text(encoding="utf-8") == "baseline\n"
        assert not (work_root / "scratch.txt").exists()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_project_operations_create_list_update_get_and_delete(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'projects.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        work_root = tmp_path / "project-a"
        created = await handle_project_create_operation(
            request_id=1,
            params={"work_root": str(work_root), "name": "Custom Project"},
            session_factory=session_factory,
        )
        project = created.response["result"]["project"]
        assert project["name"] == "Custom Project"
        assert project["work_root"] == str(work_root.resolve())

        default_root = tmp_path / "default-project"
        default_created = await handle_project_create_operation(
            request_id=2,
            params={"work_root": str(default_root)},
            session_factory=session_factory,
        )
        assert default_created.response["result"]["project"]["name"] == "default-project"

        listed = await handle_project_list_operation(
            request_id=3,
            params={},
            session_factory=session_factory,
        )
        assert {row["id"] for row in listed.response["result"]["projects"]} == {
            project["id"],
            default_created.response["result"]["project"]["id"],
        }

        updated = await handle_project_update_operation(
            request_id=4,
            params={
                "project_id": project["id"],
                "name": "Renamed Project",
                "config": {"defaultMode": "plan"},
            },
            session_factory=session_factory,
        )
        assert updated.response["result"]["project"]["config"] == {"defaultMode": "plan"}
        assert updated.response["result"]["project"]["name"] == "Renamed Project"

        read = await handle_project_get_operation(
            request_id=5,
            params={"project_id": project["id"]},
            session_factory=session_factory,
        )
        assert read.response["result"]["project"]["id"] == project["id"]
        async with session_factory() as db:
            db.add(
                WriterSession(
                    id="project-session",
                    title="Project Session",
                    work_root=project["work_root"],
                    project_id=project["id"],
                )
            )
            await db.commit()

        deleted = await handle_project_delete_operation(
            request_id=6,
            params={"project_id": project["id"]},
            session_factory=session_factory,
        )
        assert deleted.response["result"] == {"deleted": True}
        async with session_factory() as db:
            assert await db.get(WriterProject, project["id"]) is None
            assert await db.get(WriterSession, "project-session") is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_project_directory_pick_operation_returns_selected_path(tmp_path):
    selected_dir = tmp_path / "picked"
    selected_dir.mkdir()

    outcome = await handle_project_directory_pick_operation(
        request_id=1,
        params={},
        directory_picker=lambda: str(selected_dir),
    )

    assert outcome.response["result"] == {"path": str(selected_dir)}


@pytest.mark.asyncio
async def test_project_agents_md_operations_read_and_write_file(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'project-agents.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        work_root = tmp_path / "agents-project"
        work_root.mkdir()
        async with session_factory() as db:
            db.add(
                WriterProject(
                    id="project-agents",
                    name="Agents",
                    work_root=str(work_root),
                )
            )
            await db.commit()

        missing = await handle_project_agents_md_get_operation(
            request_id=1,
            params={"project_id": "project-agents"},
            session_factory=session_factory,
        )
        assert missing.response["result"] == {"agents_md": {"content": "", "exists": False}}
        async with session_factory() as db:
            project = await db.get(WriterProject, "project-agents")
            assert project is not None
            assert project.agents_md is None

        updated = await handle_project_agents_md_update_operation(
            request_id=2,
            params={"project_id": "project-agents", "content": "Use UTF-8."},
            session_factory=session_factory,
        )
        assert updated.response["result"] == {"agents_md": {"content": "Use UTF-8.", "exists": True}}
        assert (work_root / "AGENTS.md").read_text(encoding="utf-8") == "Use UTF-8."

        read = await handle_project_agents_md_get_operation(
            request_id=3,
            params={"project_id": "project-agents"},
            session_factory=session_factory,
        )
        assert read.response["result"] == {"agents_md": {"content": "Use UTF-8.", "exists": True}}
        async with session_factory() as db:
            project = await db.get(WriterProject, "project-agents")
            assert project is not None
            assert project.agents_md == "Use UTF-8."
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_project_sessions_list_operation_returns_recent_project_sessions(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'project-sessions.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(WriterProject(id="project-sessions", name="Project", work_root=str(tmp_path)))
            db.add_all([
                WriterSession(
                    id="project-session-old",
                    title="Old",
                    project_id="project-sessions",
                    updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                ),
                WriterSession(
                    id="project-session-new",
                    title="New",
                    project_id="project-sessions",
                    updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                ),
                WriterSession(
                    id="other-project-session",
                    title="Other",
                    project_id="other-project",
                    updated_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
                ),
            ])
            await db.commit()

        outcome = await handle_project_sessions_list_operation(
            request_id=1,
            params={"project_id": "project-sessions", "limit": 1},
            session_factory=session_factory,
        )

        rows = outcome.response["result"]["sessions"]
        assert [row["id"] for row in rows] == ["project-session-new"]
        assert rows[0]["title"] == "New"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_settings_operations_round_trip_app_setting(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'settings.db'}", future=True)
    shared_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'settings-shared.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    shared_session = async_sessionmaker(shared_engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await init_shared_config_schema(shared_engine)

    try:
        missing = await handle_settings_get_operation(
            request_id=1,
            params={"namespace": "lamwriter.test"},
            session_factory=session_factory,
            config_session_factory=shared_session,
        )
        assert missing.response["result"]["setting"]["value"] == {}

        updated = await handle_settings_update_operation(
            request_id=2,
            params={"namespace": "lamwriter.test", "value": {"enabled": True}},
            session_factory=session_factory,
            config_session_factory=shared_session,
        )
        assert updated.response["result"]["setting"]["value"] == {"enabled": True}

        read = await handle_settings_get_operation(
            request_id=3,
            params={"namespace": "lamwriter.test"},
            session_factory=session_factory,
            config_session_factory=shared_session,
        )
        assert read.response["result"]["setting"]["value"] == {"enabled": True}
    finally:
        await engine.dispose()
        await shared_engine.dispose()


@pytest.mark.asyncio
async def test_runtime_capabilities_operation_returns_settings_payload(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runtime-capabilities.db'}", future=True)
    shared_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runtime-capabilities-shared.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    shared_session = async_sessionmaker(shared_engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await init_shared_config_schema(shared_engine)

    try:
        async with session_factory() as db:
            db.add(
                AppSetting(
                    namespace="lamwriter.runtimeControls",
                    value={
                        "tools": {"run_command": False},
                        "command_policies": {"regular": "ask_before_run"},
                    },
                )
            )
            await db.commit()

        outcome = await handle_config_runtime_capabilities_get_operation(
            request_id=1,
            params={"work_root": str(tmp_path)},
            session_factory=session_factory,
            config_session_factory=shared_session,
        )

        capabilities = outcome.response["result"]["runtime_capabilities"]
        assert capabilities["agents"]
        assert capabilities["tools"]
        assert capabilities["command_policies"]["regular"] == "ask_before_run"
        run_command = next(tool for tool in capabilities["tools"] if tool["name"] == "run_command")
        assert run_command["enabled"] is False
        assert run_command["permission_group"] == "command"
    finally:
        await engine.dispose()
        await shared_engine.dispose()


@pytest.mark.asyncio
async def test_subagent_operations_create_update_and_delete_project_definition(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'subagents.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        work_root = tmp_path / "workspace"
        work_root.mkdir()
        created = await handle_config_subagent_upsert_operation(
            request_id=1,
            params={
                "work_root": str(work_root),
                "name": "project-worker",
                "description": "Project worker",
                "role": "Reviewer",
                "developer_instructions": "Review the project.",
                "tools": ["read_file"],
                "model": "gpt-test",
                "max_tool_rounds": 4,
                "aliases": ["worker"],
            },
            session_factory=session_factory,
        )

        subagent = created.response["result"]["subagent"]
        assert subagent["name"] == "project-worker"
        assert subagent["role"] == "Reviewer"
        assert subagent["tools"] == ["read_file"]
        assert subagent["enabled"] is True
        assert (work_root / ".lamtools" / "agents" / "project-worker.md").is_file()

        deleted = await handle_config_subagent_delete_operation(
            request_id=2,
            params={"work_root": str(work_root), "name": "project-worker"},
        )

        assert deleted.response["result"] == {"ok": True}
        assert not (work_root / ".lamtools" / "agents" / "project-worker.md").exists()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_config_read_operations_return_provider_model_and_resolution(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'config-read.db'}", future=True)
    shared_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'config-read-shared.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    shared_session = async_sessionmaker(shared_engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await init_shared_config_schema(shared_engine)

    try:
        async with shared_session() as db:
            provider = LLMProvider(
                id="provider-1",
                name="OpenAI",
                api_type="openai",
                base_url="https://api.openai.test/v1",
                api_key="sk-1234567890",
            )
            model = LLMModel(
                id="model-1",
                provider_id="provider-1",
                model_id="gpt-test",
                display_name="GPT Test",
                context_window=128000,
                max_output_tokens=16000,
            )
            db.add_all([provider, model])
            await db.commit()

        providers = await handle_config_providers_list_operation(
            request_id=1,
            params={},
            session_factory=session_factory,
            config_session_factory=shared_session,
        )
        provider_rows = providers.response["result"]["providers"]
        assert provider_rows[0]["id"] == "provider-1"
        assert provider_rows[0]["api_key"] == "********"
        assert provider_rows[0]["has_api_key"] is True

        models = await handle_config_models_list_operation(
            request_id=2,
            params={"provider_id": "provider-1"},
            session_factory=session_factory,
            config_session_factory=shared_session,
        )
        model_rows = models.response["result"]["models"]
        assert [row["id"] for row in model_rows] == ["model-1"]

        resolved = await handle_config_resolved_get_operation(
            request_id=3,
            params={"task_type": "writer"},
            session_factory=session_factory,
            config_session_factory=shared_session,
        )
        payload = resolved.response["result"]["resolved"]
        assert payload["provider"]["id"] == "provider-1"
        assert payload["model"]["id"] == "model-1"
        assert payload["task_type"] == "writer"
    finally:
        await engine.dispose()
        await shared_engine.dispose()


@pytest.mark.asyncio
async def test_provider_write_operations_create_update_and_delete_provider(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'provider-write.db'}", future=True)
    shared_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'provider-write-shared.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    shared_session = async_sessionmaker(shared_engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await init_shared_config_schema(shared_engine)

    try:
        created = await handle_config_provider_create_operation(
            request_id=1,
            params={
                "name": "Provider",
                "api_type": "openai",
                "base_url": "https://api.provider.test/v1",
                "api_key": "sk-provider-secret",
            },
            session_factory=session_factory,
            config_session_factory=shared_session,
        )
        provider = created.response["result"]["provider"]
        assert provider["name"] == "Provider"
        assert provider["api_key"] == "********"

        async with shared_session() as db:
            db.add(
                LLMModel(
                    id="model-to-delete",
                    provider_id=provider["id"],
                    model_id="model",
                    display_name="Model",
                )
            )
            await db.commit()

        updated = await handle_config_provider_update_operation(
            request_id=2,
            params={
                "provider_id": provider["id"],
                "name": "Renamed",
                "api_key": "********",
            },
            session_factory=session_factory,
            config_session_factory=shared_session,
        )
        assert updated.response["result"]["provider"]["name"] == "Renamed"

        async with shared_session() as db:
            row = await db.get(LLMProvider, provider["id"])
            assert row is not None
            assert row.api_key == "sk-provider-secret"

        deleted = await handle_config_provider_delete_operation(
            request_id=3,
            params={"provider_id": provider["id"]},
            session_factory=session_factory,
            config_session_factory=shared_session,
        )
        assert deleted.response["result"] == {"ok": True}

        async with shared_session() as db:
            assert await db.get(LLMProvider, provider["id"]) is None
            assert await db.get(LLMModel, "model-to-delete") is None
    finally:
        await engine.dispose()
        await shared_engine.dispose()


@pytest.mark.asyncio
async def test_model_write_operations_create_update_and_delete_model(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'model-write.db'}", future=True)
    shared_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'model-write-shared.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    shared_session = async_sessionmaker(shared_engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await init_shared_config_schema(shared_engine)

    try:
        async with shared_session() as db:
            db.add(
                LLMProvider(
                    id="provider-1",
                    name="Provider",
                    api_type="openai",
                    base_url="https://api.provider.test/v1",
                    api_key="sk-provider-secret",
                )
            )
            await db.commit()

        created = await handle_config_model_create_operation(
            request_id=1,
            params={
                "provider_id": "provider-1",
                "model_id": "gpt-test",
                "display_name": "GPT Test",
                "context_window": 128000,
                "max_output_tokens": 16000,
            },
            session_factory=session_factory,
            config_session_factory=shared_session,
        )
        model = created.response["result"]["model"]
        assert model["model_id"] == "gpt-test"
        assert model["display_name"] == "GPT Test"

        updated = await handle_config_model_update_operation(
            request_id=2,
            params={
                "model_record_id": model["id"],
                "display_name": "GPT Updated",
                "thinking_supported": True,
            },
            session_factory=session_factory,
            config_session_factory=shared_session,
        )
        assert updated.response["result"]["model"]["display_name"] == "GPT Updated"
        assert updated.response["result"]["model"]["thinking_supported"] is True

        deleted = await handle_config_model_delete_operation(
            request_id=3,
            params={"model_record_id": model["id"]},
            session_factory=session_factory,
            config_session_factory=shared_session,
        )
        assert deleted.response["result"] == {"ok": True}

        async with shared_session() as db:
            assert await db.get(LLMModel, model["id"]) is None
    finally:
        await engine.dispose()
        await shared_engine.dispose()


@pytest.mark.asyncio
async def test_import_env_operation_creates_provider_model_and_writer_route(tmp_path, monkeypatch):
    from app.config import settings
    from app.models.app_setting import AppSetting

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'import-env.db'}", future=True)
    shared_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'import-env-shared.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    shared_session = async_sessionmaker(shared_engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await init_shared_config_schema(shared_engine)

    monkeypatch.setattr(settings, "llm_api_key", "sk-env-secret")
    monkeypatch.setattr(settings, "llm_base_url", "https://api.env.test/v1")
    monkeypatch.setattr(settings, "llm_api_type", "openai")
    monkeypatch.setattr(settings, "llm_model", "gpt-env")
    monkeypatch.setattr(settings, "llm_context_window", 128000)
    monkeypatch.setattr(settings, "llm_max_tokens", 16000)
    monkeypatch.setattr(settings, "llm_thinking_enabled", True)
    monkeypatch.setattr(settings, "llm_thinking_budget", 12000)
    monkeypatch.setattr(settings, "llm_temperature", 0.2)

    try:
        outcome = await handle_config_import_env_operation(
            request_id=1,
            params={},
            session_factory=session_factory,
            config_session_factory=shared_session,
        )

        result = outcome.response["result"]
        assert result["provider"]["base_url"] == "https://api.env.test/v1"
        assert result["provider"]["api_key"] == "********"
        assert result["model"]["model_id"] == "gpt-env"
        assert result["model"]["thinking_supported"] is True
        assert result["route_updated"] is True

        async with shared_session() as db:
            setting = await db.get(AppSetting, "lamwriter.modelRouting")
            assert setting is not None
            writer_route = setting.value["routes"]["writer"]
            assert writer_route["mode"] == "model"
            assert writer_route["model_id"] == result["model"]["id"]
    finally:
        await engine.dispose()
        await shared_engine.dispose()


@pytest.mark.asyncio
async def test_config_adapter_profiles_operation_returns_profiles():
    outcome = await handle_config_adapter_profiles_list_operation(request_id=1, params={})

    profiles = outcome.response["result"]["adapter_profiles"]
    assert profiles
    assert {"id", "label", "protocol", "match_base_url", "endpoint"} <= set(profiles[0])


def test_connection_routes_dot_operations_through_core_catalog():
    connection = WriterAppServerConnection(DummyWebSocket())
    catalog = connection._operation_catalog()
    host_handlers = connection.context.host.operation_handlers()
    for operation in CORE_WORKBENCH_OPERATION_NAMES:
        assert catalog._handlers[operation] is host_handlers[operation]


def test_writer_injects_only_non_lifecycle_core_operation_adapters():
    connection = WriterAppServerConnection(DummyWebSocket())
    lifecycle_names = {
        "thread.start", "thread.read", "thread.resume", "turn.start", "turn.steer",
        "turn.cancel", "queue.create", "queue.update", "queue.delete",
        "queue.guide",
    }

    assert set(connection.context.operations.list()) == set(CORE_WORKBENCH_OPERATION_NAMES) - lifecycle_names


def test_backend_reducer_resolves_core_approval_request():
    state = empty_thread_state("thread-1")
    state = apply_event(
        state,
        app_event(
            "event-1",
            1,
            "core/runItem",
            RunItemEvent(
                kind="approval_request",
                thread_id="thread-1",
                event_id="approval-request-1",
                turn_id="turn-1",
                item_id="request-1",
                status="waiting",
                payload={"request_id": "request-1", "message": "Approve?"},
            ).to_dict(),
        ),
    )
    assert state["core"]["status"] == "waiting"
    assert state["core"]["requests"]["request-1"]["status"] == "open"

    state = apply_event(
        state,
        app_event(
            "event-2",
            2,
            "core/runItem",
            RunItemEvent(
                kind="approval_response",
                thread_id="thread-1",
                event_id="approval-response-1",
                turn_id="turn-1",
                item_id="request-1",
                status="completed",
                payload={"request_id": "request-1", "decision": "approve_once"},
            ).to_dict(),
        ),
    )

    assert state["core"]["requests"]["request-1"]["status"] == "resolved"
    assert state["core"]["requests"]["request-1"]["decision"] == "approve_once"


def test_backend_reducer_keeps_server_request_resolution_out_of_items():
    state = apply_event(
        empty_thread_state("thread-1"),
        app_event(
            "event-1",
            1,
            "serverRequest/resolved",
            {
                "type": "serverRequest",
                "request_id": "request-1",
                "kind": "approval",
                "status": "resolved",
                "decision": "approve_once",
            },
            turn_id="turn-1",
            item_id="tool-1",
        ),
    )

    assert state["requests"]["request-1"]["status"] == "resolved"
    assert state["items"] == {}
    assert state["item_order"] == []


def test_backend_reducer_core_status_sets_failed_status():
    state = apply_event(
        empty_thread_state("thread-1"),
        app_event(
            "event-1",
            1,
            "core/runItem",
            RunItemEvent(
                kind="status",
                thread_id="thread-1",
                event_id="run-status-1",
                status="failed",
                payload={"type": "runtime", "status": "failed", "message": "boom"},
            ).to_dict(),
        ),
    )

    assert state["core"]["status"] == "failed"
    assert state["status"] == "failed"


def test_backend_reducer_replays_legacy_turn_started_as_running():
    state = empty_thread_state("thread-1")
    state = apply_event(
        state,
        app_event("event-1", 1, "turn/started", {"type": "turn", "status": "running"}, turn_id="turn-1"),
    )

    assert state["status"] == "running"
    assert state["turns"]["turn-1"]["status"] == "running"
    assert state["turns"]["turn-1"]["last_method"] == "turn/started"


@pytest.mark.parametrize(
    "method",
    [
        "thread/started",
        "turn/accepted",
        "turn/started",
        "item/started",
        "turn/interrupted",
        "turn/steered",
        "serverRequest/resolved",
        "queue/itemAccepted",
        "queue/itemUpdated",
        "queue/itemDispatched",
        "queue/itemDeleted",
        "core/runItem",
    ],
)
def test_backend_reducer_delegates_generic_events_to_core_projector(monkeypatch, method):
    delegated = []

    def apply_in_place(state, event):
        delegated.append(event)
        return state

    monkeypatch.setattr(reducer_module._CORE_PROJECTOR, "apply_in_place", apply_in_place)

    apply_event_in_place(
        empty_thread_state("thread-1"),
        app_event("event-1", 1, method, {"request_id": "request-1"}, turn_id="turn-1", item_id="item-1"),
    )

    assert [event.method for event in delegated] == [method]


def test_backend_reducer_late_interrupt_does_not_resurrect_completed_turn():
    state = empty_thread_state("thread-1")
    state = apply_event(
        state,
        app_event("event-1", 1, "turn/accepted", {"type": "turn"}, turn_id="turn-1"),
    )
    state = apply_event(
        state,
        app_event(
            "event-2",
            2,
            "core/runItem",
            RunItemEvent(
                kind="status",
                thread_id="thread-1",
                event_id="core-failed",
                turn_id="turn-1",
                status="failed",
                payload={"type": "turn", "status": "failed"},
            ).to_dict(),
        ),
    )
    state = apply_event(
        state,
        app_event("event-3", 3, "turn/interrupted", {"type": "turn", "reason": "user_interrupt"}, turn_id="turn-1"),
    )

    assert state["core"]["status"] == "failed"
    assert state["core"]["turns"]["turn-1"]["status"] == "failed"
    assert state["status"] == "failed"


def test_backend_reducer_preserves_cancelled_status():
    state = apply_event(
        empty_thread_state("thread-1"),
        app_event(
            "event-1",
            1,
            "core/runItem",
            RunItemEvent(
                kind="status",
                thread_id="thread-1",
                event_id="turn-1:cancelled",
                run_id="turn-1",
                turn_id="turn-1",
                item_id="turn-1:cancelled",
                status="cancelled",
                payload={"type": "turn", "status": "cancelled"},
            ).to_dict(),
            turn_id="turn-1",
        ),
    )

    assert state["core"]["status"] == "cancelled"
    assert state["status"] == "cancelled"
    assert state["turns"]["turn-1"]["status"] == "cancelled"


def test_backend_reducer_in_place_replay_matches_copying_apply():
    events = [
        app_event("event-1", 1, "turn/accepted", {"type": "turn"}, turn_id="turn-1"),
        app_event("event-2", 2, "item/started", {"type": "agentMessage"}, turn_id="turn-1", item_id="item-1"),
        app_event(
            "event-3",
            3,
            "core/runItem",
            RunItemEvent(
                event_id="core-1",
                kind="message",
                thread_id="thread-1",
                turn_id="turn-1",
                item_id="item-1",
                payload={"delta": "done"},
            ).to_dict(),
        ),
    ]
    copied = empty_thread_state("thread-1")
    for event in events:
        copied = apply_event(copied, event)

    in_place = empty_thread_state("thread-1")
    for event in events:
        apply_event_in_place(in_place, event)

    assert in_place == copied == reduce_events("thread-1", events)


@pytest.mark.asyncio
async def test_snapshot_rebuild_includes_events_after_five_thousand(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'snapshot-rebuild.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add_all(
                [
                    WriterAppEvent(
                        event_id="turn-accepted",
                        thread_id="thread-1",
                        seq=1,
                        turn_id="turn-1",
                        method="turn/accepted",
                        payload_json={"type": "turn"},
                    ),
                    *[
                        WriterAppEvent(
                            event_id=f"item-{index}",
                            thread_id="thread-1",
                            seq=index + 2,
                            turn_id="turn-1",
                            item_id=f"item-{index}",
                            method="item/started",
                            payload_json={"type": "reasoning", "status": "running"},
                        )
                        for index in range(5000)
                    ],
                    WriterAppEvent(
                        event_id="core-failed",
                        thread_id="thread-1",
                        seq=5002,
                        turn_id="turn-1",
                        method="core/runItem",
                        payload_json=RunItemEvent(
                            kind="status",
                            thread_id="thread-1",
                            event_id="core-failed",
                            turn_id="turn-1",
                            status="failed",
                            payload={"type": "turn", "status": "failed"},
                        ).to_dict(),
                    ),
                ]
            )
            await db.flush()
            started = perf_counter()
            state = await rebuild_snapshot(db, "thread-1")
            elapsed = perf_counter() - started
            print(f"5002 snapshot rebuild: {elapsed:.3f}s")

            assert state["snapshot_seq"] == 5002
            assert state["status"] == "failed"
            assert state["core"]["status"] == "failed"
            assert state["core"]["turns"]["turn-1"]["status"] == "failed"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_turn_start_passes_existing_app_server_message_and_turn_to_runtime(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'connection-start.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    captured: dict[str, object] = {}

    async def fake_run_turn(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(connection_module, "async_session", session_factory)
    from app.routers import session as session_router

    monkeypatch.setattr(session_router, "_service", {"run_turn": fake_run_turn})

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="thread-1", title="Test"))
            await db.commit()

        connection = WriterAppServerConnection(DummyWebSocket())
        connection.initialized = True
        connection.thread_id = "thread-1"

        await connection._handle_raw(
            {
                "id": 1,
                "method": "turn/start",
                "params": {
                    "thread_id": "thread-1",
                    "client_message_id": "client-1",
                    "input": [{"type": "text", "text": "hello"}],
                },
            }
        )

        for _ in range(30):
            if captured:
                break
            await connection_module.asyncio.sleep(0.01)

        start_response = await connection.outbound.get()
        assert start_response["result"]["snapshot"]["snapshot_seq"] == 3
        assert start_response["result"]["snapshot"]["status"] == "running"
        assert start_response["result"]["snapshot"]["core"]["status"] == "running"

        assert captured["user_message_id"]
        assert captured["transcript_turn_id"]
        async with session_factory() as db:
            user_count = (await db.execute(select(func.count()).select_from(WriterMessage))).scalar_one()
            turn_count = (await db.execute(select(func.count()).select_from(WriterTranscriptTurn))).scalar_one()
            turn = await db.get(WriterTranscriptTurn, captured["transcript_turn_id"])
            assert user_count == 1
            assert turn_count == 1
            assert turn is not None
            assert turn.user_message_id == captured["user_message_id"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_turn_start_binds_attachment_ids_and_passes_them_to_runtime(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'connection-attachment-start.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    captured: dict[str, object] = {}

    async def fake_run_turn(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(connection_module, "async_session", session_factory)
    from app.routers import session as session_router

    monkeypatch.setattr(session_router, "_service", {"run_turn": fake_run_turn})

    try:
        attachment_path = tmp_path / "note.md"
        attachment_path.write_text("attachment body", encoding="utf-8")
        async with session_factory() as db:
            db.add(WriterSession(id="thread-1", title="Test"))
            db.add(
                WriterAttachment(
                    id="att-1",
                    session_id="thread-1",
                    filename="note.md",
                    storage_path=str(attachment_path),
                    mime_type="text/markdown",
                    size=15,
                    preview_type="text",
                )
            )
            await db.commit()

        connection = WriterAppServerConnection(DummyWebSocket())
        connection.initialized = True
        connection.thread_id = "thread-1"

        await connection._handle_raw(
            {
                "id": 1,
                "method": "turn/start",
                "params": {
                    "thread_id": "thread-1",
                    "client_message_id": "client-attachment-1",
                    "input": [
                        {"type": "text", "text": "看附件"},
                        {
                            "type": "attachment",
                            "attachment_id": "att-1",
                            "filename": "note.md",
                            "mime_type": "text/markdown",
                            "preview_type": "text",
                        },
                    ],
                },
            }
        )

        for _ in range(30):
            if captured:
                break
            await connection_module.asyncio.sleep(0.01)

        await connection.outbound.get()
        assert captured["attachment_ids"] == ["att-1"]
        async with session_factory() as db:
            attachment = await db.get(WriterAttachment, "att-1")
            assert attachment is not None
            assert attachment.message_id == captured["user_message_id"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_lifecycle_accepts_injected_writer_service(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runtime-service-provider.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    captured: dict[str, object] = {}

    async def fake_run_turn(**kwargs):
        captured.update(kwargs)

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="thread-1", title="Test"))
            await db.commit()

        runtime = WriterRuntimeLifecycle(
            session_factory=session_factory,
            service_provider=lambda: {"run_turn": fake_run_turn},
        )
        await runtime.run_accepted_turn(
            thread_id="thread-1",
            turn_id="turn-1",
            user_message_id="message-1",
            text="hello",
        )

        assert captured["session_id"] == "thread-1"
        assert captured["transcript_turn_id"] == "turn-1"
        assert captured["user_message_id"] == "message-1"
        assert captured["user_message"] == "hello"
    finally:
        await engine.dispose()




@pytest.mark.asyncio
async def test_turn_interrupt_cancels_app_server_runtime_task(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'connection-interrupt.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    started = connection_module.asyncio.Event()
    cancelled = connection_module.asyncio.Event()
    captured_tasks = []
    real_create_task = connection_module.asyncio.create_task

    async def fake_run_turn(**kwargs):
        started.set()
        try:
            await connection_module.asyncio.sleep(60)
        except connection_module.asyncio.CancelledError:
            cancelled.set()
            raise

    def capture_create_task(coro):
        task = real_create_task(coro)
        captured_tasks.append(task)
        return task

    monkeypatch.setattr(connection_module.asyncio, "create_task", capture_create_task)
    monkeypatch.setattr(connection_module, "async_session", session_factory)
    from app.routers import session as session_router

    monkeypatch.setattr(session_router, "_service", {"run_turn": fake_run_turn})

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="thread-1", title="Test"))
            await db.commit()

        connection = WriterAppServerConnection(DummyWebSocket())
        connection.initialized = True
        connection.thread_id = "thread-1"

        await connection._handle_raw(
            {
                "id": 1,
                "method": "turn/start",
                "params": {
                    "thread_id": "thread-1",
                    "client_message_id": "client-1",
                    "input": [{"type": "text", "text": "long run"}],
                },
            }
        )
        await connection_module.asyncio.wait_for(started.wait(), timeout=1)
        start_response = await connection.outbound.get()
        turn_id = start_response["result"]["events"][0]["turn_id"]
        while not connection.outbound.empty():
            await connection.outbound.get()

        await connection._handle_raw(
            {
                "id": 2,
                "method": "turn/interrupt",
                "params": {"thread_id": "thread-1", "turn_id": turn_id},
            }
        )
        interrupt_response = await connection.outbound.get()
        assert interrupt_response["result"]["snapshot"]["core"]["status"] == "interrupting"
        assert interrupt_response["result"]["snapshot"]["core"]["turns"][turn_id]["status"] == "interrupting"

        await connection_module.asyncio.wait_for(cancelled.wait(), timeout=1)

        cancelled_events = []
        interrupting = []
        for _ in range(30):
            async with session_factory() as db:
                events = await list_events_after(db, thread_id="thread-1")
                interrupting = [
                    event
                    for event in events
                    if event.method == "core/runItem"
                    and event.payload.get("kind") == "status"
                    and event.payload.get("status") == "interrupting"
                ]
                cancelled_events = [
                    event
                    for event in events
                    if event.method == "core/runItem"
                    and event.payload.get("kind") == "status"
                    and event.payload.get("status") == "cancelled"
                ]
            if cancelled_events:
                break
            await connection_module.asyncio.sleep(0.01)

        assert interrupting
        assert len(cancelled_events) == 1
        assert cancelled_events[0].turn_id == turn_id
        assert cancelled_events[0].payload["run_id"] == turn_id
        assert cancelled_events[0].payload["turn_id"] == turn_id
        assert cancelled_events[0].payload["payload"]["raw_end_reason"] == "user_interrupt"
        async with session_factory() as db:
            snapshot = await load_snapshot(db, "thread-1")
        assert snapshot["status"] == "cancelled"
        assert snapshot["core"]["status"] == "cancelled"
        assert snapshot["turns"][turn_id]["status"] == "cancelled"
    finally:
        for task in captured_tasks:
            if not task.done():
                task.cancel()
        await connection_module.asyncio.gather(*captured_tasks, return_exceptions=True)
        await engine.dispose()


@pytest.mark.asyncio
async def test_turn_interrupt_ignores_core_terminal_turn(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'connection-interrupt-terminal.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(connection_module, "async_session", session_factory)

    try:
        async with session_factory() as db:
            turn = await _append_event_without_projection(
                db,
                AppendEventInput(
                    thread_id="thread-1",
                    turn_id="turn-1",
                    method="turn/accepted",
                    payload={"type": "turn"},
                ),
            )
            await apply_event_to_snapshot(db, turn)
            completed = await _append_run_item_without_projection(
                db,
                RunItemEvent(
                    kind="status",
                    thread_id="thread-1",
                    event_id="core-completed",
                    turn_id="turn-1",
                    status="completed",
                    payload={"type": "turn", "status": "completed"},
                ),
            )
            await apply_event_to_snapshot(db, completed)
            await db.commit()

        connection = WriterAppServerConnection(DummyWebSocket())
        connection.initialized = True
        connection.thread_id = "thread-1"

        await connection._handle_raw(
            {
                "id": 2,
                "method": "turn/interrupt",
                "params": {"thread_id": "thread-1", "turn_id": "turn-1"},
            }
        )

        response = await connection.outbound.get()
        assert response["result"]["event"] is None
        assert response["result"]["status"] == "idle"
        assert response["result"]["snapshot"]["core"]["turns"]["turn-1"]["status"] == "completed"

        async with session_factory() as db:
            events = await list_events_after(db, thread_id="thread-1")
        assert [event.method for event in events] == ["turn/accepted", "core/runItem"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_writer_ws_approval_delegates_to_core_operation(monkeypatch):
    connection = WriterAppServerConnection(DummyWebSocket())
    connection.initialized = True
    calls = []

    async def respond(request):
        calls.append(dict(request.payload))
        return OperationResult(name=request.name, payload={"decision": "approve"})

    monkeypatch.setitem(connection.context.operations._handlers, "approval.respond", respond)
    await connection._handle_raw({
        "id": 9,
        "method": "approval.respond",
        "params": {"thread_id": "thread-1", "request_id": "request-1", "decision": "approve_once"},
    })

    response = await connection.outbound.get()
    assert response == {"id": 9, "result": {"decision": "approve"}}
    assert calls == [{
        "request_id": "request-1", "thread_id": "thread-1",
        "decision": "approve", "guidance": "",
    }]


@pytest.mark.asyncio
async def test_writer_ws_approval_does_not_lookup_missing_request_id(monkeypatch):
    connection = WriterAppServerConnection(DummyWebSocket())
    connection.initialized = True
    calls = []

    async def respond(request):
        calls.append(dict(request.payload))
        return OperationResult(name=request.name, status="error", payload={"error": "request_id is required"})

    monkeypatch.setitem(connection.context.operations._handlers, "approval.respond", respond)
    await connection._handle_raw({
        "id": 10,
        "method": "approval.respond",
        "params": {"thread_id": "thread-1", "decision": "approve"},
    })

    response = await connection.outbound.get()
    assert response["id"] == 10
    assert response["error"]["message"] == "request_id and decision are required"
    assert calls == []


@pytest.mark.asyncio
async def test_connection_returns_rpc_error_when_operation_handler_raises(monkeypatch):
    connection = WriterAppServerConnection(DummyWebSocket())
    connection.initialized = True
    connection.thread_id = "thread-1"

    async def failing_command_execute(request):
        raise RuntimeError("compact failed")

    monkeypatch.setitem(connection.context.operations._handlers, "command.execute", failing_command_execute)

    await connection._handle_raw(
        {
            "id": 9,
            "method": "command.execute",
            "params": {"thread_id": "thread-1", "command": "compact"},
        }
    )

    response = await connection.outbound.get()
    assert response["id"] == 9
    assert response["error"]["code"] == -32000
    assert response["error"]["message"] == "compact failed"


@pytest.mark.asyncio
async def test_connection_returns_compacted_result_when_compact_history_is_short(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'connection-command-compact-short.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(connection_module, "async_session", session_factory)

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="thread-short", title="Short"))
            base_time = datetime.now(timezone.utc)
            for index in range(6):
                db.add(
                    WriterMessage(
                        id=f"connection-short-{index}",
                        session_id="thread-short",
                        role="user" if index % 2 == 0 else "assistant",
                        content=f"short-message-{index}",
                        created_at=base_time + timedelta(seconds=index),
                    )
                )
            await db.commit()

        connection = WriterAppServerConnection(DummyWebSocket())
        connection.initialized = True
        connection.thread_id = "thread-short"

        await connection._handle_raw(
            {
                "id": 10,
                "method": "command.execute",
                "params": {"thread_id": "thread-short", "command": "compact"},
            }
        )

        response = await connection.outbound.get()
        assert response["id"] == 10
        assert response["result"]["result"]["status"] == "compacted"
        assert response["result"]["result"]["compacted_messages"] == 1
        assert response["result"]["result"]["retained_messages"] == 5
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_approval_operation_failure_returns_rpc_error(monkeypatch):
    connection = WriterAppServerConnection(DummyWebSocket())

    async def fail(request):
        return OperationResult(name=request.name, status="error", payload={"error": "approval failed"})

    monkeypatch.setitem(connection.context.operations._handlers, "approval.respond", fail)
    outcome = await connection.context.host.execute(
        "approval.respond",
        request_id=1,
        params={"thread_id": "thread-1", "request_id": "request-1", "decision": "approve"},
        context=connection.context,
    )
    assert outcome.response["error"]["message"] == "approval failed"
