"""Contract tests for the append-only dialogue control records."""

from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.app.core_db import (
    CoreThreadSnapshot,
    open_core_app_db,
)
from lamtools_core.checkpoint_maintenance import verify_dialogue_records
from lamtools_core.dialogue_records import (
    COMPACTION_RECORD,
    ROLLBACK_RECORD,
    build_compaction_record,
    build_rollback_record,
    message_identity,
    verify_compaction_record,
)
from lamtools_core.llm import ChatMessage


def _message(role: str, content: str, *, seq: int | None = None, message_id: str = "") -> ChatMessage:
    metadata: dict = {}
    if seq is not None:
        metadata["history_seq"] = seq
    if message_id:
        metadata["message_id"] = message_id
    return ChatMessage(role=role, content=content, metadata=metadata)  # type: ignore[arg-type]


def _record() -> dict:
    folded = [
        _message("user", "old question one", seq=1),
        _message("assistant", "old answer one", seq=2),
    ]
    retained = [
        _message("user", "newest question", seq=5, message_id="m-5"),
        _message("assistant", "newest answer", seq=6),
    ]
    summary = ChatMessage(
        role="system",
        content="[Compacted Context]\n\n1. Current Objective And Done Criteria\n- None.",
        metadata={"key": "context_compaction_summary"},
    )
    return build_compaction_record(
        trigger="auto",
        summary_message=summary,
        retained=retained,
        folded=folded,
        sent_messages=[summary, *retained],
        prefix_count=2,
        limit_tokens=4096,
        trigger_tokens=8000,
        retained_steps=3,
        before_tokens=12000,
        after_tokens=900,
        before_messages=40,
        after_messages=3,
        segments=2,
        strategy="current_model",
        execution_model="model-x",
        recent_user_messages=["newest question"],
    )


def test_message_identity_prefers_stable_id_then_history_seq() -> None:
    assert message_identity(_message("user", "x", message_id="abc")) == "message_id:abc"
    assert message_identity(_message("user", "x", seq=7)) == "history_seq:7"
    assert message_identity(_message("user", "x")) is None


def test_compaction_record_rebuilds_exactly_what_was_sent() -> None:
    record = _record()
    assert record["kind"] == COMPACTION_RECORD
    assert record["digest_match"] is True
    assert record["effective_digest"] == record["sent_digest"]
    # Full summary, not the 20k-truncated UI card copy.
    assert "Compacted Context" in record["summary"]
    # Folded and retained identity both captured.
    assert record["folded"]["count"] == 2
    assert [entry["ref"] for entry in record["retained"]] == ["message_id:m-5", "history_seq:6"]
    # Parameters and watermark present.
    assert record["params"]["trigger"] == "auto"
    assert record["params"]["execution_model"] == "model-x"
    assert record["watermark"] == 6

    check = verify_compaction_record(record)
    assert check["integrity"] is True
    assert check["fidelity"] is True


def test_compaction_record_digest_detects_tampering() -> None:
    record = _record()
    record["summary"] = record["summary"] + " tampered"
    record["summary_message"] = {**record["summary_message"], "content": record["summary"]}
    check = verify_compaction_record(record)
    assert check["integrity"] is False
    assert check["fidelity"] is False


def test_rollback_record_shape() -> None:
    record = build_rollback_record(
        scope="conversation_only",
        target_event_seq=120,
        target_history_seq=30,
        detached_event_count=4,
        detached_event_min=121,
        detached_event_max=124,
        detached_history_count=5,
        detached_history_min=31,
        detached_history_max=35,
        branch_epoch=2,
        operation_id="op-1",
    )
    assert record["kind"] == ROLLBACK_RECORD
    assert record["branch_epoch"] == 2
    assert record["target_event_seq"] == 120
    assert record["detached"]["events"] == {"count": 4, "min": 121, "max": 124}
    assert record["detached"]["history"]["count"] == 5


async def test_dialogue_records_append_monotonically_and_verify(tmp_path: Path) -> None:
    db_path = tmp_path / "core.db"
    db = await open_core_app_db(db_path)
    try:
        async with db.session_factory() as session:
            session.add(CoreThreadSnapshot(thread_id="t-1", snapshot_json={}))
            await session.commit()

        first = _record()
        second = _record()
        seq1 = await db.runtime_state_store.append_dialogue_record(
            "t-1", kind=COMPACTION_RECORD, record=first, watermark=first["watermark"]
        )
        seq2 = await db.runtime_state_store.append_dialogue_record(
            "t-1", kind=COMPACTION_RECORD, record=second, watermark=second["watermark"]
        )
        rollback = build_rollback_record(
            scope="conversation_only",
            target_event_seq=10,
            target_history_seq=4,
            branch_epoch=1,
        )
        seq3 = await db.runtime_state_store.append_dialogue_record(
            "t-1",
            kind=ROLLBACK_RECORD,
            record=rollback,
            branch_epoch=1,
            watermark=10,
        )
        assert (seq1, seq2, seq3) == (1, 2, 3)
        assert await db.runtime_state_store.dialogue_record_epoch("t-1") == 1

        stored = await db.runtime_state_store.list_dialogue_records("t-1")
        assert [item["seq"] for item in stored] == [1, 2, 3]
        assert [item["kind"] for item in stored] == [
            COMPACTION_RECORD,
            COMPACTION_RECORD,
            ROLLBACK_RECORD,
        ]
    finally:
        await db.close()

    report = await verify_dialogue_records(db_path)
    assert report["records_total"] == 3
    assert report["compaction_total"] == 2
    assert report["compaction_ok"] == 2
    assert report["ok"] is True


async def test_verify_dialogue_records_filters_by_thread(tmp_path: Path) -> None:
    db_path = tmp_path / "core.db"
    db = await open_core_app_db(db_path)
    try:
        async with db.session_factory() as session:
            session.add(CoreThreadSnapshot(thread_id="a", snapshot_json={}))
            session.add(CoreThreadSnapshot(thread_id="b", snapshot_json={}))
            await session.commit()
        record = _record()
        await db.runtime_state_store.append_dialogue_record(
            "a", kind=COMPACTION_RECORD, record=record, watermark=record["watermark"]
        )
        await db.runtime_state_store.append_dialogue_record(
            "b", kind=COMPACTION_RECORD, record=_record(), watermark=1
        )
    finally:
        await db.close()

    report = await verify_dialogue_records(db_path, thread_id="a")
    assert report["records_total"] == 1
    assert report["ok"] is True


class _SummaryLLM:
    """Stub compactor: returns a valid nine-section summary."""

    async def complete(self, request):
        from lamtools_core.llm import LLMResponse

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


async def test_manual_compaction_double_writes_a_verifiable_record(tmp_path: Path) -> None:
    from lamtools_core.app import command_execution
    from lamtools_core.runtime import RuntimeState

    db_path = tmp_path / "core.db"
    db = await open_core_app_db(db_path)
    try:
        store = db.runtime_state_store
        state = RuntimeState(
            session_id="thread-manual-1",
            metadata={
                "context_window_tokens": 256_000,
                # Keep a retained tail so the record carries both halves.
                "runtime_audit": {"loop_policy": {"compact_retained_steps": 2}},
            },
        )
        history = [
            item
            for index in range(13)
            for item in (
                {"role": "user", "content": f"old question {index} " + ("x" * 4000)},
                {"role": "assistant", "content": f"old answer {index} " + ("y" * 4000)},
            )
        ]
        await store.save_checkpoint(state, history)
        result = await command_execution.compact_runtime_history(
            runtime_state_store=store,
            thread_id="thread-manual-1",
            llm_client=_SummaryLLM(),
            model="mock-model",
        )
        assert result["status"] == "compacted"
        records = await store.list_dialogue_records("thread-manual-1")
        assert len(records) == 1
        assert records[0]["kind"] == COMPACTION_RECORD
        record = records[0]["record"]
        assert record["trigger"] == "manual"
        assert "Compacted Context" in record["summary"]
        # Folded and retained identity are both captured (identities only; the
        # message bodies live in the durable history rows).
        assert record["folded"]["count"] > 0
        assert record["retained"]
        # The record rebuilds exactly what the next load will send.
        assert record["digest_match"] is True
    finally:
        await db.close()

    report = await verify_dialogue_records(db_path, thread_id="thread-manual-1")
    assert report["compaction_total"] == 1
    assert report["ok"] is True
    # Record size is observable (inline retained copy is kept until step 3).
    assert report["max_record_bytes"] > 0
    assert report["max_record"]["kind"] == COMPACTION_RECORD
    assert report["records_bytes_total"] == report["max_record_bytes"]


async def test_rollback_event_double_writes_a_marker_with_monotonic_epoch(tmp_path: Path) -> None:
    from lamtools_core.checkpoint import CoreCheckpointConversationBackend

    db_path = tmp_path / "core.db"
    db = await open_core_app_db(db_path)
    try:
        backend = CoreCheckpointConversationBackend(
            db.session_factory,
            event_store=db.event_store,
            snapshot_store=db.snapshot_store,
        )

        async def first(session):
            return await backend.append_rollback_event(
                session,
                session_id="t-rb",
                target_checkpoint_id="ck",
                target_turn_id="turn-3",
                target_event_seq=40,
                target_revision=0,
                scope="conversation_only",
                operation_id="op-1",
                target_history_seq=12,
                detached={
                    "events": {"count": 3, "min": 41, "max": 43},
                    "history": {"count": 2, "min": 13, "max": 14},
                },
            )

        async def second(session):
            return await backend.append_rollback_event(
                session,
                session_id="t-rb",
                target_checkpoint_id="ck",
                target_turn_id="turn-5",
                target_event_seq=60,
                target_revision=0,
                scope="conversation_only",
                target_history_seq=20,
                detached={},
            )

        await db.persistence.write(first)
        await db.persistence.write(second)

        records = await db.runtime_state_store.list_dialogue_records("t-rb")
        assert [item["kind"] for item in records] == [ROLLBACK_RECORD, ROLLBACK_RECORD]
        assert [item["branch_epoch"] for item in records] == [1, 2]
        assert records[0]["record"]["detached"]["events"]["count"] == 3
        assert records[0]["record"]["target_event_seq"] == 40
        assert await db.runtime_state_store.dialogue_record_epoch("t-rb") == 2
    finally:
        await db.close()


async def test_kernel_auto_compaction_double_writes_a_verifiable_record(tmp_path: Path) -> None:
    """The automatic path writes the same complete record the manual path does."""
    from lamtools_core.kernel import LoopPolicy
    from lamtools_core.llm import ChatMessage, LLMRequest
    from tests.test_kernel import (
        CapturingLLMClient,
        MockKitStep,
        MockRuntimeKit,
        _make_kernel,
        _make_turn_input,
    )

    class BigKit(MockRuntimeKit):
        async def build_model_request(self, state, context):
            messages = [ChatMessage(role="system", content="stable prefix")]
            for index in range(5):
                messages.append(
                    ChatMessage(
                        role="user",
                        content=f"old user {index} " + ("x" * 500),
                        metadata={"message_id": f"user-{index}"},
                    )
                )
                messages.append(
                    ChatMessage(
                        role="assistant",
                        content=f"old assistant {index} " + ("y" * 500),
                        metadata={"message_id": f"assistant-{index}"},
                    )
                )
            messages.append(ChatMessage(role="user", content="current task"))
            return LLMRequest(messages=messages, model="mock-model")

    db_path = tmp_path / "core.db"
    db = await open_core_app_db(db_path)
    try:
        kernel = _make_kernel(
            BigKit(steps=[MockKitStep(decision="done")]),
            llm_client=CapturingLLMClient(),
            state_store=db.runtime_state_store,
            policy=LoopPolicy(
                context_window_tokens=2_000,
                compact_trigger_ratio=0.8,
                compact_limit_ratio=0.6,
            ),
        )
        result = await kernel.run(_make_turn_input())
        assert result.decision == "done"
        records = await db.runtime_state_store.list_dialogue_records("test-session")
        assert len(records) == 1
        assert records[0]["kind"] == COMPACTION_RECORD
        record = records[0]["record"]
        assert record["trigger"] == "auto"
        assert record["params"]["strategy"]
        assert record["digest_match"] is True
        # Identity comes from the stable message ids the kit stamped.
        assert record["folded"]["count"] > 0
        assert record["folded"]["items"][0]["ref"].startswith("message_id:")
    finally:
        await db.close()

    report = await verify_dialogue_records(db_path, thread_id="test-session")
    assert report["compaction_total"] == 1
    assert report["ok"] is True
