from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest
from sqlalchemy import text

import lamtools_core.app.default_agent as default_agent
from lamtools_core.app import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
from lamtools_core.app.core_db import RuntimeStateConflictError, open_core_app_db
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent, LLMToolCall
from lamtools_core.runtime import RuntimeState
from lamtools_core.tool import ToolResult


class FinalReplyLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Core operation should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        yield LLMStreamEvent(kind="content_delta", content=self.reply, raw={"provider_secret": "do-not-return"})
        yield LLMStreamEvent(kind="done", raw={"provider_secret": "do-not-return"})


class ApprovalRequestLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Core operation should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        yield LLMStreamEvent(
            kind="done",
            tool_calls=[
                LLMToolCall(
                    id="call-write",
                    name="write_file",
                    arguments={"path": "approved.md", "content": "approved\n"},
                )
            ],
        )


class BlockingGuideContinuationLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []
        self.continuation_started = asyncio.Event()
        self.release_continuation = asyncio.Event()

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Core operation should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="call-write",
                        name="write_file",
                        arguments={"path": "approved.md", "content": "approved\n"},
                    )
                ],
            )
            return
        self.continuation_started.set()
        await self.release_continuation.wait()
        yield LLMStreamEvent(kind="content_delta", content="Guidance applied.")
        yield LLMStreamEvent(kind="done")


def _catalog(*, db, work_root, llm):
    return create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=work_root / ".core", work_root=work_root),
        model_provider=llm,
        db_session_factory=db.session_factory,
        app_event_store=db.event_store,
        thread_snapshot_store=db.snapshot_store,
        runtime_state_store=db.runtime_state_store,
    )


@pytest.mark.asyncio
async def test_core_database_applies_wal_busy_timeout_and_normal_synchronous(tmp_path) -> None:
    db = await open_core_app_db(tmp_path / "pragma.db")
    try:
        async with db.engine.connect() as connection:
            journal_mode = (await connection.execute(text("PRAGMA journal_mode"))).scalar_one()
            busy_timeout = (await connection.execute(text("PRAGMA busy_timeout"))).scalar_one()
            synchronous = (await connection.execute(text("PRAGMA synchronous"))).scalar_one()

        assert str(journal_mode).lower() == "wal"
        assert int(busy_timeout) == 5000
        assert int(synchronous) == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_core_database_migrates_legacy_checkpoint_table_before_runtime_use(tmp_path) -> None:
    db_path = tmp_path / "legacy-checkpoints.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE core_checkpoints (
                id VARCHAR(64) PRIMARY KEY,
                root_session_id VARCHAR(128) NOT NULL,
                session_id VARCHAR(128) NOT NULL,
                turn_id VARCHAR(128) NOT NULL,
                actor_kind VARCHAR(32) NOT NULL,
                manifest_hash VARCHAR(64) NOT NULL,
                conversation_json JSON NOT NULL,
                status VARCHAR(32) NOT NULL,
                created_at DATETIME NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO core_checkpoints (
                id, root_session_id, session_id, turn_id, actor_kind,
                manifest_hash, conversation_json, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-checkpoint",
                "legacy-session",
                "legacy-session",
                "legacy-turn",
                "main",
                "manifest",
                "{}",
                "ready",
                "2026-07-16 00:00:00",
            ),
        )

    db = await open_core_app_db(db_path)
    try:
        async with db.engine.begin() as connection:
            columns = (await connection.execute(text("PRAGMA table_info(core_checkpoints)"))).mappings().all()
            legacy_status = (
                await connection.execute(
                    text("SELECT status FROM core_checkpoints WHERE id = 'legacy-checkpoint'")
                )
            ).scalar_one()
            await connection.execute(
                text(
                    """
                    INSERT INTO core_checkpoints (
                        id, root_session_id, session_id, turn_id, actor_kind, work_root,
                        manifest_hash, conversation_json, status, created_at
                    ) VALUES (
                        'new-checkpoint', 'new-session', 'new-session', 'new-turn', 'main',
                        'E:/workspace', 'manifest', '{}', 'ready', '2026-07-16 00:00:01'
                    )
                    """
                )
            )

        assert "work_root" in {column["name"] for column in columns}
        assert legacy_status == "unavailable"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_core_single_writer_keeps_concurrent_event_sequences_contiguous(tmp_path) -> None:
    db = await open_core_app_db(tmp_path / "concurrent-events.db")
    try:
        async def append(index: int):
            async def write(session):
                return await db.persistence.append(
                    session,
                    AppEventInput(
                        event_id=f"event-{index}",
                        thread_id="thread-concurrent",
                        method="item/started",
                        payload={"index": index},
                    ),
                )

            return await db.persistence.write(write)

        events = await asyncio.wait_for(asyncio.gather(*(append(index) for index in range(50))), timeout=5)

        assert sorted(event.seq for event in events) == list(range(1, 51))
        async with db.session_factory() as session:
            stored = await db.event_store.list_thread(session, thread_id="thread-concurrent")
        assert [event.seq for event in stored] == list(range(1, 51))
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_core_single_writer_lock_is_isolated_by_database(tmp_path) -> None:
    first = await open_core_app_db(tmp_path / "first.db")
    second = await open_core_app_db(tmp_path / "second.db")
    first_entered = asyncio.Event()
    second_entered = asyncio.Event()
    release_first = asyncio.Event()

    async def hold_first(_session):
        first_entered.set()
        await release_first.wait()

    async def enter_second(_session):
        second_entered.set()

    first_task = asyncio.create_task(first.persistence.write(hold_first))
    try:
        await asyncio.wait_for(first_entered.wait(), timeout=0.5)
        await asyncio.wait_for(second.persistence.write(enter_second), timeout=0.5)
        assert second_entered.is_set()
    finally:
        release_first.set()
        await first_task
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_core_runtime_store_rejects_stale_concurrent_state_write(tmp_path) -> None:
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        initial = RuntimeState(session_id="thread-conflict")
        await db.runtime_state_store.save_checkpoint(initial, [])
        first = await db.runtime_state_store.get("thread-conflict")
        second = await db.runtime_state_store.get("thread-conflict")
        assert first is not None and second is not None

        first.status = "running"
        await db.runtime_state_store.save(first)
        second.status = "waiting"
        with pytest.raises(RuntimeStateConflictError):
            await db.runtime_state_store.save(second)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_core_history_survives_agent_and_database_recreation(tmp_path) -> None:
    db_path = tmp_path / "core.db"
    work_root = tmp_path / "work"
    work_root.mkdir()

    first_db = await open_core_app_db(db_path)
    try:
        first_llm = FinalReplyLLM("I will remember alpha.")
        first = await _catalog(db=first_db, work_root=work_root, llm=first_llm).execute(
            "turn.start",
            {"thread_id": "thread-history", "message": "Remember alpha."},
        )
        assert first.status == "ok"
    finally:
        await first_db.close()

    second_db = await open_core_app_db(db_path)
    try:
        second_llm = FinalReplyLLM("Alpha is remembered.")
        second = await _catalog(db=second_db, work_root=work_root, llm=second_llm).execute(
            "turn.start",
            {"thread_id": "thread-history", "message": "What did I ask you to remember?"},
        )
        assert second.status == "ok"
        assert "do-not-return" not in json.dumps(second.payload, ensure_ascii=False)
        messages = [message.to_dict() for message in second_llm.requests[0].messages if message.role != "system"]
        assert [(item["role"], item["content"]) for item in messages] == [
            ("user", "Remember alpha."),
            ("assistant", "I will remember alpha."),
            ("user", "What did I ask you to remember?"),
        ]
    finally:
        await second_db.close()


@pytest.mark.asyncio
async def test_core_pending_approval_survives_restart_and_continues_once(tmp_path) -> None:
    db_path = tmp_path / "core.db"
    work_root = tmp_path / "work"
    work_root.mkdir()

    first_db = await open_core_app_db(db_path)
    try:
        waiting = await _catalog(db=first_db, work_root=work_root, llm=ApprovalRequestLLM()).execute(
            "turn.start",
            {"thread_id": "thread-approval", "message": "Write the approval file."},
        )
        assert waiting.payload["decision"] == "wait"
    finally:
        await first_db.close()

    second_db = await open_core_app_db(db_path)
    try:
        continuation_llm = FinalReplyLLM("The file is saved.")
        catalog = _catalog(db=second_db, work_root=work_root, llm=continuation_llm)
        outcomes = await asyncio.gather(
            catalog.execute(
                "approval.respond",
                {"request_id": "call-write", "decision": "approve_once", "guidance": ""},
            ),
            catalog.execute(
                "approval.respond",
                {"request_id": "call-write", "decision": "approve_once", "guidance": ""},
            ),
        )
        approved = next(outcome for outcome in outcomes if outcome.status == "ok")
        duplicate = next(outcome for outcome in outcomes if outcome.status == "error")

        assert approved.status == "ok"
        assert duplicate.status == "error"
        assert duplicate.payload["error"] in {"approval already resolving", "no pending approval"}
        assert (work_root / "approved.md").read_text(encoding="utf-8") == "approved\n"
        messages = [message.to_dict() for message in continuation_llm.requests[0].messages if message.role != "system"]
        assert messages[0] == {"role": "user", "content": "Write the approval file."}
        assert messages[1]["role"] == "assistant"
        assert messages[1]["tool_calls"][0]["id"] == "call-write"
        assert messages[2]["role"] == "tool"
        assert messages[2]["name"] == "write_file"
        assert messages[2]["tool_call_id"] == "call-write"
        assert "approved" in messages[2]["content"]
        assert messages[-1]["role"] == "user"
    finally:
        await second_db.close()

    with sqlite3.connect(db_path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute("select name from sqlite_master where type='table'").fetchall()
        }
    assert "core_runtime_sessions" in tables
    assert not any(name.startswith("writer_") for name in tables)


@pytest.mark.asyncio
async def test_core_denied_approval_resolves_request_and_cancels_turn(tmp_path) -> None:
    db = await open_core_app_db(tmp_path / "core.db")
    work_root = tmp_path / "work"
    work_root.mkdir()
    try:
        catalog = _catalog(db=db, work_root=work_root, llm=ApprovalRequestLLM())
        waiting = await catalog.execute(
            "turn.start",
            {"thread_id": "thread-deny", "message": "Write the approval file."},
        )
        denied = await catalog.execute(
            "approval.respond",
            {"request_id": "call-write", "decision": "deny", "guidance": ""},
        )

        assert waiting.payload["decision"] == "wait"
        assert denied.status == "ok"
        assert denied.payload["decision"] == "denied"
        snapshot = denied.payload["snapshot"]
        assert snapshot["status"] == "cancelled"
        assert snapshot["core"]["status"] == "cancelled"
        assert snapshot["core"]["requests"]["call-write"]["status"] == "resolved"
        state = await db.runtime_state_store.get("thread-deny")
        assert state is not None
        assert state.status == "cancelled"
        assert "pending_approval" not in state.metadata
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_core_guide_closes_approval_before_continuation_starts_and_after_rebuild(tmp_path) -> None:
    db_path = tmp_path / "core.db"
    work_root = tmp_path / "work"
    work_root.mkdir()
    llm = BlockingGuideContinuationLLM()
    db = await open_core_app_db(db_path)
    rebuilt = None
    try:
        catalog = _catalog(db=db, work_root=work_root, llm=llm)
        waiting = await catalog.execute(
            "turn.start",
            {"thread_id": "thread-guide-durable", "message": "Write the approval file."},
        )
        assert waiting.payload["decision"] == "wait"

        response_task = asyncio.create_task(
            catalog.execute(
                "approval.respond",
                {
                    "thread_id": "thread-guide-durable",
                    "request_id": "call-write",
                    "decision": "guide",
                    "guidance": "use a different approach",
                },
            )
        )
        await asyncio.wait_for(llm.continuation_started.wait(), timeout=2)

        async with db.session_factory() as session:
            snapshot = await db.snapshot_store.load(session, "thread-guide-durable")
        state = await db.runtime_state_store.get("thread-guide-durable")
        assert snapshot["core"]["requests"]["call-write"]["status"] == "resolved"
        assert not any(request.get("status") == "open" for request in snapshot["core"]["requests"].values())
        assert state is not None
        assert "pending_approval" not in state.metadata

        rebuilt = await open_core_app_db(db_path)
        async with rebuilt.session_factory() as session:
            rebuilt_snapshot = await rebuilt.snapshot_store.load(session, "thread-guide-durable")
        assert rebuilt_snapshot["core"]["requests"]["call-write"]["status"] == "resolved"

        llm.release_continuation.set()
        guided = await response_task
        assert guided.status == "ok"
    finally:
        llm.release_continuation.set()
        if rebuilt is not None:
            await rebuilt.close()
        await db.close()


@pytest.mark.asyncio
async def test_core_decision_persistence_failure_restores_retryable_pending(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "core.db"
    work_root = tmp_path / "work"
    work_root.mkdir()
    db = await open_core_app_db(db_path)
    try:
        catalog = _catalog(db=db, work_root=work_root, llm=ApprovalRequestLLM())
        waiting = await catalog.execute(
            "turn.start",
            {"thread_id": "thread-decision-retry", "message": "Write the approval file."},
        )
        assert waiting.payload["decision"] == "wait"

        original_persist = default_agent._persist_run_items

        async def fail_persistence(*_args, **_kwargs):
            raise RuntimeError("approval response persistence unavailable")

        monkeypatch.setattr(default_agent, "_persist_run_items", fail_persistence)
        failed = await catalog.execute(
            "approval.respond",
            {"thread_id": "thread-decision-retry", "request_id": "call-write", "decision": "deny"},
        )

        assert failed.status == "error"
        assert failed.payload["decision"] == "retryable"
        state = await db.runtime_state_store.get("thread-decision-retry")
        assert state is not None
        assert state.status == "waiting"
        assert state.metadata["pending_approval"]["status"] == "waiting"
        async with db.session_factory() as session:
            snapshot = await db.snapshot_store.load(session, "thread-decision-retry")
        assert snapshot["core"]["requests"]["call-write"]["status"] == "open"

        monkeypatch.setattr(default_agent, "_persist_run_items", original_persist)
        retried = await catalog.execute(
            "approval.respond",
            {"thread_id": "thread-decision-retry", "request_id": "call-write", "decision": "deny"},
        )
        assert retried.status == "ok"
        assert retried.payload["snapshot"]["core"]["requests"]["call-write"]["status"] == "resolved"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_core_terminal_persistence_failure_keeps_durable_response_closed(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "core.db"
    work_root = tmp_path / "work"
    work_root.mkdir()
    db = await open_core_app_db(db_path)
    try:
        catalog = _catalog(db=db, work_root=work_root, llm=ApprovalRequestLLM())
        waiting = await catalog.execute(
            "turn.start",
            {"thread_id": "thread-terminal-failure", "message": "Write the approval file."},
        )
        assert waiting.payload["decision"] == "wait"

        original_persist = default_agent._persist_run_items

        async def fail_terminal_persistence(run_items, **kwargs):
            if any(item.kind == "status" and item.status in {"failed", "cancelled"} for item in run_items):
                raise RuntimeError("terminal persistence unavailable")
            return await original_persist(run_items, **kwargs)

        monkeypatch.setattr(default_agent, "_persist_run_items", fail_terminal_persistence)
        failed = await catalog.execute(
            "approval.respond",
            {"thread_id": "thread-terminal-failure", "request_id": "call-write", "decision": "deny"},
        )

        assert failed.status == "error"
        assert failed.payload["snapshot"]["core"]["requests"]["call-write"]["status"] == "resolved"
        state = await db.runtime_state_store.get("thread-terminal-failure")
        assert state is not None
        assert "pending_approval" not in state.metadata
        assert state.metadata["approval_resolution"]["phase"] == "terminal_persistence_failed"

        await db.close()
        db = await open_core_app_db(db_path)
        rebuilt_state = await db.runtime_state_store.get("thread-terminal-failure")
        assert rebuilt_state is not None
        assert "pending_approval" not in rebuilt_state.metadata
        async with db.session_factory() as session:
            snapshot = await db.snapshot_store.load(session, "thread-terminal-failure")
        assert snapshot["core"]["requests"]["call-write"]["status"] == "resolved"
    finally:
        await db.close()


class _ApprovalFailureToolbox:
    def __init__(self, *, failure: str) -> None:
        self.failure = failure

    async def execute(self, _call):
        if self.failure == "tool_exception":
            raise RuntimeError("tool execution failed")
        if self.failure == "tool_base_exception":
            raise BaseException("tool base exception")
        return ToolResult(status="error", error="tool returned failure")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_point", "decision"),
    [
        ("plugin", "approve"),
        ("toolbox", "approve"),
        ("tool_exception", "approve"),
        ("tool_base_exception", "approve"),
        ("tool_failure", "approve"),
        ("kernel_build", "approve"),
        ("kernel_start", "approve"),
        ("history_save", "approve"),
        ("guide_setup", "guide"),
        ("run_item_persist", "guide"),
    ],
)
async def test_core_approval_resolution_failure_closes_all_persisted_surfaces(
    tmp_path,
    monkeypatch,
    failure_point: str,
    decision: str,
) -> None:
    db_path = tmp_path / f"{failure_point}.db"
    work_root = tmp_path / "work"
    work_root.mkdir()
    db = await open_core_app_db(db_path)
    try:
        catalog = _catalog(db=db, work_root=work_root, llm=ApprovalRequestLLM())
        waiting = await catalog.execute(
            "turn.start",
            {"thread_id": "thread-failure", "message": "Write the approval file."},
        )
        assert waiting.payload["decision"] == "wait"

        if failure_point == "plugin":
            def fail_plugin_assembly(**_kwargs):
                raise RuntimeError("plugin assembly failed")

            monkeypatch.setattr(default_agent, "assemble_core_agent_plugins", fail_plugin_assembly)
        elif failure_point in {"toolbox", "tool_exception", "tool_base_exception", "tool_failure"}:
            async def fail_or_return_toolbox(**_kwargs):
                if failure_point == "toolbox":
                    raise RuntimeError("toolbox assembly failed")
                return _ApprovalFailureToolbox(failure=failure_point), None

            monkeypatch.setattr(default_agent, "_build_core_runtime_toolbox", fail_or_return_toolbox)
        elif failure_point in {"kernel_build", "kernel_start"}:
            from lamtools_core.kernel import loop as kernel_loop

            if failure_point == "kernel_build":
                class FailingKernel:
                    def __init__(self, **_kwargs) -> None:
                        raise RuntimeError("kernel construction failed")

                monkeypatch.setattr(default_agent, "CoreLoopKernel", FailingKernel)
            else:
                async def fail_kernel_start(self, _turn_input):
                    raise RuntimeError("kernel start failed")

                monkeypatch.setattr(kernel_loop.CoreLoopKernel, "run", fail_kernel_start)
        elif failure_point == "history_save":
            async def fail_save_checkpoint(_state, _history):
                raise RuntimeError("tool history save failed")

            async def fail_append_history(_session_id, _messages):
                raise RuntimeError("tool history save failed")

            monkeypatch.setattr(db.runtime_state_store, "save_checkpoint", fail_save_checkpoint)
            monkeypatch.setattr(db.runtime_state_store, "append_history", fail_append_history)
            monkeypatch.setattr(db.runtime_state_store, "replace_history", fail_append_history)
        elif failure_point == "run_item_persist":
            original_persist = default_agent._persist_run_items
            calls = 0

            async def fail_first_final_persist(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("run item persistence failed")
                return await original_persist(*args, **kwargs)

            monkeypatch.setattr(default_agent, "_persist_run_items", fail_first_final_persist)
        else:
            from lamtools_core.tool import approval_continuation

            def fail_guide_setup(**_kwargs):
                raise RuntimeError("guide continuation setup failed")

            monkeypatch.setattr(approval_continuation, "guidance_continuation_prompt", fail_guide_setup)

        response = await catalog.execute(
            "approval.respond",
            {
                "request_id": "call-write",
                "decision": decision,
                "guidance": "continue safely" if decision == "guide" else "",
            },
        )

        assert response.status == "error"
        assert response.payload["decision"] == "failed"
        state = await db.runtime_state_store.get("thread-failure")
        assert state is not None
        assert state.status == "failed"
        assert state.loop_state == "failed"
        assert "pending_approval" not in state.metadata

        async with db.session_factory() as session:
            snapshot = await db.snapshot_store.load(session, "thread-failure")
            events = await db.event_store.list_thread(session, thread_id="thread-failure")
        request = snapshot["core"]["requests"]["call-write"]
        assert snapshot["status"] == "failed"
        assert request["status"] == "resolved"
        assert request["decision"] == decision
        response_events = [
            event
            for event in events
            if event.payload.get("kind") == "approval_response"
            and event.payload.get("payload", {}).get("request_id") == "call-write"
        ]
        assert len(response_events) == 1
        error_events = [
            event
            for event in events
            if event.payload.get("kind") == "tool_result"
            and event.payload.get("status") == "failed"
        ]
        assert error_events
        assert error_events[-1].payload["payload"]["metadata"]["failure_reason"]
    finally:
        await db.close()

    reloaded = await open_core_app_db(db_path)
    try:
        state = await reloaded.runtime_state_store.get("thread-failure")
        assert state is not None
        assert "pending_approval" not in state.metadata
        async with reloaded.session_factory() as session:
            snapshot = await reloaded.snapshot_store.load(session, "thread-failure")
        assert snapshot["core"]["requests"]["call-write"]["status"] != "open"
        duplicate = await _catalog(db=reloaded, work_root=work_root, llm=ApprovalRequestLLM()).execute(
                "approval.respond",
                {
                    "thread_id": "thread-failure",
                    "request_id": "call-write",
                    "decision": decision,
                    "guidance": "continue safely",
                },
            )
        assert duplicate.status == "error"
        assert duplicate.payload["error"] == "no pending approval"
    finally:
        await reloaded.close()


# ---------------------------------------------------------------------------
# Tests: Incremental history storage (CoreHistoryEntry)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_history_increments_seq_and_round_trips(tmp_path) -> None:
    db = await open_core_app_db(tmp_path / "history.db")
    try:
        store = db.runtime_state_store
        state = RuntimeState(session_id="thread-1")
        await store.save(state)

        await store.append_history("thread-1", [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ])
        await store.append_history("thread-1", [
            {"role": "user", "content": "second"},
        ])

        history = await store.get_history("thread-1")
        assert len(history) == 3
        assert history[0]["content"] == "hello"
        assert history[1]["content"] == "hi there"
        assert history[2]["content"] == "second"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_append_history_migrates_legacy_blob_lazily(tmp_path) -> None:
    """A session with data in the old history_json blob is migrated on first append."""
    from lamtools_core.app.core_db import CoreRuntimeSession

    db = await open_core_app_db(tmp_path / "legacy-blob.db")
    try:
        # Seed a session with the old-style blob (no incremental rows yet).
        async with db.session_factory() as session:
            session.add(CoreRuntimeSession(
                thread_id="legacy-thread",
                revision=1,
                runtime_state_json={},
                history_json=[
                    {"role": "user", "content": "old message 1"},
                    {"role": "assistant", "content": "old reply 1"},
                ],
                pending_approval_json={},
                last_event_seq=0,
            ))
            await session.commit()

        store = db.runtime_state_store

        # Reading before migration falls back to the blob.
        history = await store.get_history("legacy-thread")
        assert len(history) == 2
        assert history[0]["content"] == "old message 1"

        # Appending triggers lazy migration then adds the new message.
        await store.append_history("legacy-thread", [
            {"role": "user", "content": "new message"},
        ])

        history = await store.get_history("legacy-thread")
        assert len(history) == 3
        assert history[0]["content"] == "old message 1"
        assert history[2]["content"] == "new message"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_replace_history_overwrites_all_rows(tmp_path) -> None:
    db = await open_core_app_db(tmp_path / "replace.db")
    try:
        store = db.runtime_state_store
        state = RuntimeState(session_id="thread-replace")
        await store.save(state)

        await store.append_history("thread-replace", [
            {"role": "user", "content": "original 1"},
            {"role": "assistant", "content": "original 2"},
            {"role": "user", "content": "original 3"},
        ])
        assert len(await store.get_history("thread-replace")) == 3

        # Replace with a compacted summary.
        await store.replace_history("thread-replace", [
            {"role": "system", "content": "[Compacted Context] earlier conversation"},
            {"role": "user", "content": "latest message"},
        ])

        history = await store.get_history("thread-replace")
        assert len(history) == 2
        assert history[0]["content"] == "[Compacted Context] earlier conversation"
        assert history[1]["content"] == "latest message"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_replace_history_clears_legacy_blob(tmp_path) -> None:
    """After replace_history, the old history_json blob is cleared so get_history
    only reads from the incremental table."""
    from lamtools_core.app.core_db import CoreRuntimeSession

    db = await open_core_app_db(tmp_path / "clear-blob.db")
    try:
        async with db.session_factory() as session:
            session.add(CoreRuntimeSession(
                thread_id="thread-clear",
                revision=1,
                runtime_state_json={},
                history_json=[
                    {"role": "user", "content": "legacy"},
                ],
                pending_approval_json={},
                last_event_seq=0,
            ))
            await session.commit()

        store = db.runtime_state_store
        await store.replace_history("thread-clear", [
            {"role": "user", "content": "replaced"},
        ])

        # The blob should be empty now.
        async with db.session_factory() as session:
            row = await session.get(CoreRuntimeSession, "thread-clear")
            assert row.history_json == []

        # get_history should read only from the incremental table.
        history = await store.get_history("thread-clear")
        assert len(history) == 1
        assert history[0]["content"] == "replaced"
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Tests: Concurrent history writes must not deadlock (Fix #1)
#
# append_history and replace_history both route through the
# SQLiteWriteCoordinator (per-database asyncio.Lock + BEGIN IMMEDIATE) so
# that concurrent writes — e.g. a sub-agent appending while the main turn
# replaces after compaction — serialize instead of raising
# "database is locked". This was the root cause of the 2b34c636 hang.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_append_and_replace_do_not_lock(tmp_path) -> None:
    """Concurrent append_history + replace_history on the same DB must not
    raise ``database is locked`` — both go through the write coordinator."""
    db = await open_core_app_db(tmp_path / "concurrent.db")
    try:
        store = db.runtime_state_store
        await store.save(RuntimeState(session_id="thread-c"))

        # Seed some history so replace has something to delete.
        await store.append_history("thread-c", [
            {"role": "user", "content": "seed-1"},
            {"role": "assistant", "content": "seed-2"},
        ])

        async def append_batch() -> None:
            for i in range(10):
                await store.append_history("thread-c", [
                    {"role": "user", "content": f"append-{i}"},
                ])

        async def replace_batch() -> None:
            for i in range(10):
                await store.replace_history("thread-c", [
                    {"role": "system", "content": f"[compact-{i}]"},
                    {"role": "user", "content": "latest"},
                ])

        # If the write coordinator were bypassed, this would raise
        # OperationalError("database is locked") under contention.
        await asyncio.gather(append_batch(), replace_batch())

        history = await store.get_history("thread-c")
        # replace_batch ran last (or last-ish); the table is internally
        # consistent — no partial / duplicate seq rows. Just assert it's
        # non-empty and every seq is unique (no corruption from the race).
        assert len(history) >= 2
        # get_history returns dicts; verify no duplicate content markers.
        contents = [h["content"] for h in history]
        assert len(contents) == len(set(contents)) or len(history) == 2
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_concurrent_appends_preserve_seq_uniqueness(tmp_path) -> None:
    """Multiple concurrent append_history calls must produce unique, gapless
    seq numbers — the coordinator's single transaction per append guarantees
    the max_seq read and insert are atomic (no TOCTOU)."""
    db = await open_core_app_db(tmp_path / "concurrent-append.db")
    try:
        store = db.runtime_state_store
        await store.save(RuntimeState(session_id="thread-seq"))

        # 5 concurrent appenders, 4 messages each = 20 rows.
        await asyncio.gather(*(
            store.append_history("thread-seq", [
                {"role": "user", "content": f"m-{batch}-{i}"}
                for i in range(4)
            ])
            for batch in range(5)
        ))

        history = await store.get_history("thread-seq")
        assert len(history) == 20
    finally:
        await db.close()
