from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.base import now
from app.models.message import WriterMessage
from app.models.session import WriterSession
from app.models.transcript import WriterTranscriptTurn
from app.services.runtime_runner import WriterRuntimeRunner
from app.database import writer_write_coordinator
from lamtools_core.kernel import KernelResult
from lamtools_core.llm import LLMResponse


class _ProjectionSink:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def publish(self, events, *, session_id: str, source_event_id: str) -> None:
        self.events.extend(events)
        return None

    async def persist_in_transaction(self, db, events):
        del db
        return list(events)

    async def broadcast(self, events):
        self.events.extend(events)


class _NoopCheckpointService:
    async def checkpoint_if_dirty(self, *args, **kwargs) -> None:
        return None


class _NoopCommitReviewService:
    def latest_request(self, summary: dict[str, Any]) -> None:
        return None


class _RuntimeTaskRegistry:
    def get_cancel_event(self, session_id: str):
        return None


class _CompactionClient:
    async def complete(self, request):
        return LLMResponse(
            content=(
                "1. Current Goal\n"
                "- Continue.\n\n"
                "2. User History, Instructions, And Decisions\n"
                "- Preserved old request message-0 before runtime history capping.\n\n"
                "3. Completed Work\n"
                "- Prior turns summarized.\n\n"
                "4. Key Decisions And Constraints\n"
                "- Durable summary before truncation.\n\n"
                "5. Files, APIs, Commands, And Results\n"
                "- None.\n\n"
                "6. Open Issues Or Risks\n"
                "- None.\n\n"
                "7. Next Best Actions\n"
                "- Continue."
            ),
            finish_reason="stop",
        )

    async def stream(self, request):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_runtime_runner_compacts_long_history_before_recent_history_cap(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runtime-runner-compact.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    captured: dict[str, Any] = {}

    async def _run_core_kernel(**kwargs):
        captured["history"] = kwargs["history"]
        return KernelResult(
            session_id=kwargs["session_id"],
            run_id="run-precompact",
            decision="done",
            message="Done.",
            metadata={
                "core_events": [],
                "steps_count": 0,
                "tool_results_summary": [],
                "verification_summaries": [],
                "runtime_metrics": {},
            },
        )

    try:
        async with session_factory() as db:
            session_id = "runtime-precompact"
            db.add(WriterSession(id=session_id, title="Runtime Precompact"))
            db.add(
                WriterTranscriptTurn(
                    id="turn-1",
                    session_id=session_id,
                    sequence=1,
                    user_text="continue",
                )
            )
            base_time = now()
            for index in range(25):
                db.add(
                    WriterMessage(
                        id=f"m-{index}",
                        session_id=session_id,
                        role="user" if index % 2 == 0 else "assistant",
                        content=f"message-{index}",
                        created_at=base_time + timedelta(seconds=index),
                    )
                )
            await db.commit()

            projection_sink = _ProjectionSink()
            runner = WriterRuntimeRunner(
                app_projection_sink=projection_sink,
                state_store=object(),
                checkpoint_service=_NoopCheckpointService(),
                commit_review_service=_NoopCommitReviewService(),
                run_core_kernel=_run_core_kernel,
                summarize_result=lambda result: dict(result.metadata),
                schedule_prewarm=lambda work_root: None,
                runtime_task_registry=lambda: _RuntimeTaskRegistry(),
                write_coordinator=writer_write_coordinator(session_factory),
            )
            await runner.run(
                db=db,
                session_id=session_id,
                transcript_turn_id="turn-1",
                user_message="continue",
                raw_user_message="continue",
                llm_client=_CompactionClient(),
                work_root=str(tmp_path),
                model_context={"model": "compact-model"},
            )

            history = captured["history"]
            assert history[0]["role"] == "system"
            assert history[0]["content"].startswith("[Compacted Context]")
            assert "message-0" in history[0]["content"]
            assert "message-0" not in [item["content"] for item in history[1:]]

            session = await db.get(WriterSession, session_id)
            assert session is not None
            compaction = session.runtime_state["manual_compaction"]
            assert compaction["trigger"] == "auto"
            assert compaction["compacted_message_ids"][:2] == ["m-0", "m-1"]
            assert compaction["retained_message_ids"] == ["m-19", "m-20", "m-21", "m-22", "m-23", "m-24"]

            compaction_events = [
                event
                for event in projection_sink.events
                if getattr(event, "payload", {}).get("type") == "compaction"
            ]
            assert len(compaction_events) == 1
            assert compaction_events[0].payload["trigger"] == "auto"
            assert compaction_events[0].payload["content"].startswith("[Compacted Context]")
    finally:
        await engine.dispose()
