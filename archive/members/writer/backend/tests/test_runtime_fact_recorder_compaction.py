from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.session import WriterSession
from app.models.transcript import WriterTranscriptTurn
from app.services.runtime_fact_recorder import RuntimeFactRecorder
from lamtools_core.event import CoreEvent


class _ProjectionSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def publish(
        self,
        events,
        *,
        session_id: str,
        source_event_id: str,
    ) -> None:
        self.events.append(
            {
                "events": events,
                "session_id": session_id,
                "source_event_id": source_event_id,
            }
        )


@pytest.mark.asyncio
async def test_auto_context_compaction_event_persists_session_summary_and_message_ids(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runtime-compaction.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="auto-compact", title="Auto Compact"))
            turn = WriterTranscriptTurn(
                id="turn-1",
                session_id="auto-compact",
                sequence=1,
                user_text="continue",
            )
            db.add(turn)
            await db.commit()

            recorder = RuntimeFactRecorder(
                db=db,
                session_id="auto-compact",
                turn=turn,
                app_projection_sink=_ProjectionSink(),
            )
            await recorder.start_runtime_producer()

            await recorder.record_core_event(
                CoreEvent(
                    name="runtime.context_compacted",
                    category="progress",
                    payload={
                        "summary": "[Compacted Context]\n1. Current Goal\n- Continue.",
                        "trigger": "auto",
                        "before_tokens": 220000,
                        "after_tokens": 120000,
                        "compacted_message_ids": ["m-1", "m-2"],
                        "retained_message_ids": ["m-3"],
                    },
                    session_id="auto-compact",
                    run_id="run-1",
                )
            )

            session = await db.get(WriterSession, "auto-compact")
            assert session is not None
            assert session.context_summary == "[Compacted Context]\n1. Current Goal\n- Continue."
            compaction = session.runtime_state["manual_compaction"]
            assert compaction["trigger"] == "auto"
            assert compaction["compacted_message_ids"] == ["m-1", "m-2"]
            assert compaction["retained_message_ids"] == ["m-3"]
            assert compaction["retained_message_count"] == 1
            assert compaction["before_tokens"] == 220000
            assert compaction["after_tokens"] == 120000
    finally:
        await engine.dispose()
