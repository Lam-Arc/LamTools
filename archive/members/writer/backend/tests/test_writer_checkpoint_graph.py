from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.writer.checkpoint_backend import WriterCheckpointConversationBackend
from app.app_server.runtime import WriterRuntimeLifecycle
from app.database import Base, writer_write_coordinator
from app.models.message import WriterMessage
from app.models.session import WriterSession
from app.models.transcript import WriterTranscriptTurn
from app.services.session_rollback_markers import is_rolled_back_metadata
from lamtools_core.checkpoint import CoreCheckpointCoordinator


async def _database(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_writer_runtime_exposes_checkpoint_cache_invalidation() -> None:
    invalidated: list[str] = []
    runtime = WriterRuntimeLifecycle(
        service_provider=lambda: {"invalidate_checkpoint_state": invalidated.append},
    )

    runtime.invalidate_checkpoint_state("writer-session")

    assert invalidated == ["writer-session"]


@pytest.mark.asyncio
async def test_writer_conversation_and_workspace_restore_share_core_checkpoint_graph(tmp_path: Path) -> None:
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    file = work_root / "draft.txt"
    file.write_text("before", encoding="utf-8")
    engine, sessions = await _database(tmp_path)
    try:
        async with sessions() as db:
            db.add(WriterSession(
                id="writer-session",
                title="Writer",
                work_root=str(work_root),
                status="completed",
                runtime_state={"stage": "before"},
            ))
            db.add(WriterMessage(
                id="message-1", session_id="writer-session", role="user", content="first",
            ))
            db.add(WriterTranscriptTurn(
                id="turn-1", session_id="writer-session", sequence=1,
                user_text="first", user_message_id="message-1", status_cache="completed",
            ))
            await db.commit()

        invalidated: list[str] = []
        coordinator = CoreCheckpointCoordinator(
            work_root,
            sessions,
            write_coordinator=writer_write_coordinator(sessions),
            storage_root=tmp_path / "checkpoint-data",
            conversation_backend=WriterCheckpointConversationBackend(
                sessions,
                state_invalidator=invalidated.append,
            ),
        )
        checkpoint = await coordinator.save(
            session_id="writer-session",
            turn_id="manual-1",
            reason="manual",
        )

        file.write_text("after", encoding="utf-8")
        async with sessions() as db:
            session = await db.get(WriterSession, "writer-session")
            session.runtime_state = {"stage": "after"}
            db.add(WriterMessage(
                id="message-2", session_id="writer-session", role="user", content="second",
            ))
            db.add(WriterTranscriptTurn(
                id="turn-2", session_id="writer-session", sequence=2,
                user_text="second", user_message_id="message-2", status_cache="completed",
            ))
            await db.commit()

        conversation_restore = await coordinator.load(checkpoint.id, scope="conversation")
        assert invalidated == ["writer-session"]
        assert file.read_text(encoding="utf-8") == "after"
        async with sessions() as db:
            session = await db.get(WriterSession, "writer-session")
            turn = await db.get(WriterTranscriptTurn, "turn-2")
            message = await db.get(WriterMessage, "message-2")
            assert session.runtime_state == {"stage": "before"}
            assert is_rolled_back_metadata(turn.metadata_)
            assert is_rolled_back_metadata(message.metadata_)

        workspace_restore = await coordinator.load(checkpoint.id, scope="workspace")
        assert file.read_text(encoding="utf-8") == "before"
        graph = await coordinator.graph("writer-session")
        nodes = {node.id: node for node in graph.nodes}
        assert nodes[conversation_restore.derived_checkpoint_id].reason == "rollback_conversation"
        assert nodes[workspace_restore.derived_checkpoint_id].reason == "rollback_workspace"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_writer_checkpoint_fork_creates_writer_session_and_graph_edge(tmp_path: Path) -> None:
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    (work_root / "draft.txt").write_text("source", encoding="utf-8")
    engine, sessions = await _database(tmp_path)
    try:
        async with sessions() as db:
            db.add(WriterSession(
                id="writer-source", title="Source", work_root=str(work_root), status="completed",
            ))
            db.add(WriterMessage(
                id="source-message", session_id="writer-source", role="user", content="source",
            ))
            db.add(WriterTranscriptTurn(
                id="source-turn", session_id="writer-source", sequence=1,
                user_text="source", user_message_id="source-message", status_cache="completed",
            ))
            await db.commit()
        coordinator = CoreCheckpointCoordinator(
            work_root,
            sessions,
            write_coordinator=writer_write_coordinator(sessions),
            storage_root=tmp_path / "checkpoint-data",
            conversation_backend=WriterCheckpointConversationBackend(sessions),
        )
        source = await coordinator.save(session_id="writer-source", turn_id="manual", reason="manual")
        forked = await coordinator.fork(source.id, new_session_id="writer-fork", title="Fork")
        async with sessions() as db:
            fork_session = await db.get(WriterSession, "writer-fork")
            assert fork_session is not None
            assert fork_session.title == "Fork"
        assert forked.edge_kind == "session_fork"
        assert forked.label == "分叉到新会话"
        assert forked.session_payload["id"] == "writer-fork"
    finally:
        await engine.dispose()
