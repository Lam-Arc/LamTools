from __future__ import annotations

"""Writer service — closure-based DI orchestration.

Follows the artist_orchestrate pattern from LamImager:
- Creates all dependencies once
- Returns a dict of async service functions
- Functions close over shared state (settings, clients, stores)
"""
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from lamtools_core.kernel import LoopPolicy, summarize_kernel_result
from lamtools_core.llm.shallow_thinking import ShallowThinkingClient
from lamtools_core.llm.policy import RetryPolicy

from app.config import Settings
from app.database import writer_write_coordinator
from lamtools_core.app.sqlite_write import configure_sqlite_engine
from lamtools_core.app.approval_continuation import CoreApprovalContinuationCoordinator
from app.core.writer.state_store import WriterStateStore
from app.core.writer.core_kernel_adapter import (
    resume_sub_agent_turn,
    run_core_kernel,
    schedule_writer_startup_prewarm,
)
from app.core.writer.llm_bridge import WriterLLMClientAdapter
from app.core.writer.git import WriterGitManager
from app.models.base import gen_uuid
from app.models.session import WriterSession
from app.models.message import WriterMessage
from app.models.attachment import WriterAttachment
from app.models.transcript import WriterTranscriptTurn
from app.shared_config_database import shared_config_session
from app.services.app_projection_sink import AppProjectionSink
from app.services.attachment_service import WriterAttachmentRepository
from app.services.checkpoint_service import WriterCheckpointService
from app.services.commit_review_service import WriterCommitReviewService
from app.services.runtime_approved_tool import (
    execute_approved_tool,
)
from app.services.runtime_capabilities import runtime_controls
from app.services.runtime_fact_recorder import RuntimeFactRecorder
from app.services.runtime_runner import WriterRuntimeRunner
from app.services.session_compaction_service import (
    apply_session_context_compaction,
    execute_session_context_compaction,
    prepare_session_context_compaction,
)
from app.services.llm_config_service import build_llm_client, resolve_llm_config
from app.services.transcript_service import create_user_message_turn
from lamtools_core.runtime import RuntimeState, default_runtime_task_registry
from lamtools_core.attachment import build_attachment_runtime_input

logger = logging.getLogger(__name__)

def _with_shallow_thinking_client(client: Any, enabled: bool | None) -> Any:
    if not enabled:
        return client
    if hasattr(client, "complete"):
        return ShallowThinkingClient(client)
    if hasattr(client, "chat_full"):
        return ShallowThinkingClient(WriterLLMClientAdapter(writer_client=client))
    return client


def _model_context_from_resolved(
    resolved: Any,
    *,
    thinking_enabled: bool | None,
    thinking_budget: int | None,
    shallow_thinking_enabled: bool | None = None,
) -> dict[str, Any]:
    if isinstance(resolved, dict):
        context = {
            "provider": str(resolved.get("provider") or ""),
            "model": str(resolved.get("model") or ""),
        }
        if thinking_enabled is not None:
            context["thinking_enabled"] = bool(thinking_enabled)
        if thinking_budget is not None:
            context["thinking_budget"] = thinking_budget
        if shallow_thinking_enabled is not None:
            context["shallow_thinking_enabled"] = bool(shallow_thinking_enabled)
        return {key: value for key, value in context.items() if value != ""}

    provider = getattr(resolved, "provider", None)
    model = getattr(resolved, "model", None)
    actual_thinking_enabled = thinking_enabled
    if actual_thinking_enabled is None and model is not None:
        actual_thinking_enabled = bool(getattr(model, "thinking_supported", False))
    actual_thinking_budget = thinking_budget
    if actual_thinking_budget is None and model is not None:
        actual_thinking_budget = int(getattr(model, "thinking_budget", 0) or 0)
    context = {
        "provider": str(getattr(provider, "name", "") or getattr(provider, "id", "") or ""),
        "provider_id": str(getattr(provider, "id", "") or ""),
        "provider_api_type": str(getattr(provider, "api_type", "") or ""),
        "provider_base_url": str(getattr(provider, "base_url", "") or ""),
        "model": str(getattr(model, "model_id", "") or getattr(model, "display_name", "") or ""),
        "model_record_id": str(getattr(model, "id", "") or ""),
        "model_display_name": str(getattr(model, "display_name", "") or ""),
        "task_type": str(getattr(resolved, "task_type", "") or ""),
        "matched_rule": bool(getattr(resolved, "matched_rule", False)),
        "thinking_enabled": bool(actual_thinking_enabled),
        "thinking_budget": actual_thinking_budget,
        "shallow_thinking_enabled": bool(shallow_thinking_enabled) if shallow_thinking_enabled is not None else None,
    }
    return {key: value for key, value in context.items() if value not in {"", None}}


class _WriterCoreStateStore:
    """Persist Core runtime state inside the existing Writer session state."""

    _KEY = "_core_runtime_state"

    def __init__(self, store: WriterStateStore) -> None:
        self._store = store

    async def get(self, session_id: str) -> RuntimeState | None:
        writer_state = await self._store.get(session_id)
        if writer_state is None:
            return None
        raw = writer_state.session_memory.get(self._KEY)
        if not isinstance(raw, dict):
            return RuntimeState(
                session_id=session_id,
                turn_count=writer_state.turn_count or 0,
            )
        runtime_keys = {"session_id", "run_id", "status", "position", "loop_state", "turn_count", "metadata"}
        return RuntimeState(**{key: value for key, value in raw.items() if key in runtime_keys})

    async def save(self, state: RuntimeState) -> None:
        writer_state = await self._store.get(state.session_id)
        if writer_state is None:
            writer_state = await self._store.create(state.session_id)
        writer_state.turn_count = state.turn_count
        writer_state.session_memory[self._KEY] = state.to_dict()
        await self._store.save(writer_state)


def writer_orchestrate(
    settings: Settings,
    *,
    config_session_factory: Any | None = None,
) -> dict[str, Any]:
    """Create the Writer service with closure-based DI.

    Returns a dict of async service functions:
    - create_session, list_sessions, get_session, update_session, delete_session
    - run_turn
    """
    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Keep runtime state in the same database selected by this service's
    # settings. Tests and alternate Writer instances pass their own DB URL; the
    # state store must not fall back to the desktop default database.
    state_engine = create_async_engine(settings.database_url, echo=settings.debug, poolclass=NullPool)
    if state_engine.url.get_backend_name().startswith("sqlite"):
        configure_sqlite_engine(state_engine)
    state_session_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    writer_coordinator = writer_write_coordinator(state_session_factory)
    app_projection_sink = AppProjectionSink(
        database_url=settings.database_url,
        debug=settings.debug,
        session_factory=state_session_factory,
        write_coordinator=writer_coordinator,
    )
    state_store = WriterStateStore(state_session_factory, write_coordinator=writer_coordinator)
    core_state_store = _WriterCoreStateStore(state_store)
    effective_config_session_factory = config_session_factory or shared_config_session
    git_manager = WriterGitManager()
    checkpoint_service = WriterCheckpointService(
        git_manager=git_manager,
        default_work_root=settings.writer_work_root,
    )

    commit_review_service = WriterCommitReviewService(
        git_manager=git_manager,
        default_work_root=settings.writer_work_root,
        ensure_repo=checkpoint_service.ensure_repo,
    )

    async def _resolve_writer_llm_config(
        db: AsyncSession,
        model_id: str | None = None,
    ):
        _ = db
        async with effective_config_session_factory() as config_db:
            if model_id is None:
                resolved = await resolve_llm_config(config_db, "writer")
            else:
                resolved = await resolve_llm_config(config_db, "writer", model_id=model_id)
        if resolved is None:
            raise RuntimeError("No LLM provider/model configured in DB")
        return resolved

    async def _resolve_llm_client(
        db: AsyncSession,
        thinking_enabled: bool | None = None,
        thinking_budget: int | None = None,
        shallow_thinking_enabled: bool | None = None,
        model_id: str | None = None,
    ):
        """Resolve Writer LLM from DB route `writer`, falling back to DB `default`.

        .env is not used here. If DB has no model, startup seed/config setup is broken
        and the user must configure a provider in Settings.

        When `model_id` is provided, it bypasses routing rules and resolves
        the specified model directly (per-request model switching).
        """
        resolved = await _resolve_writer_llm_config(db, model_id=model_id)
        return _with_shallow_thinking_client(
            build_llm_client(
                resolved,
                thinking_enabled=thinking_enabled,
                thinking_budget=thinking_budget,
            ),
            shallow_thinking_enabled,
        )

    # --- Service functions ---

    async def _runtime_controls(db: AsyncSession) -> dict[str, dict[str, Any]]:
        async with effective_config_session_factory() as shared_db:
            return await runtime_controls(db, shared_db=shared_db)

    runtime_runner = WriterRuntimeRunner(
        app_projection_sink=app_projection_sink,
        state_store=core_state_store,
        checkpoint_service=checkpoint_service,
        commit_review_service=commit_review_service,
        run_core_kernel=run_core_kernel,
        summarize_result=summarize_kernel_result,
        schedule_prewarm=schedule_writer_startup_prewarm,
        runtime_task_registry=default_runtime_task_registry,
        write_coordinator=writer_coordinator,
    )

    async def create_session(
        db: AsyncSession,
        title: str = "Untitled",
        work_root: str = "",
        mode: str = "EXECUTE",
    ) -> dict[str, Any]:
        """Create a new Writer session."""
        session_id = gen_uuid()
        session = WriterSession(
            id=session_id,
            title=title,
            work_root=work_root or settings.writer_work_root,
            mode=mode,
            phase="idle",
            status="active",
            todos=[],
            open_loops=[],
            context_summary="",
        )
        async def write(write_db: AsyncSession):
            write_db.add(session)
            await write_db.flush()
            return _session_to_dict(session)
        return await writer_coordinator.run(write)

    async def list_sessions(
        db: AsyncSession,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List sessions with pagination."""
        # Count
        count_q = select(func.count()).select_from(WriterSession)
        total = (await db.execute(count_q)).scalar() or 0

        # Query
        q = (
            select(WriterSession)
            .order_by(WriterSession.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(q)
        sessions = result.scalars().all()

        return {
            "sessions": [_session_to_dict(s) for s in sessions],
            "total": total,
        }

    async def get_session(db: AsyncSession, session_id: str) -> dict[str, Any] | None:
        """Get a session by ID."""
        session = await db.get(WriterSession, session_id)
        if session is None:
            return None
        return _session_to_dict(session)

    async def update_session(
        db: AsyncSession,
        session_id: str,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """Update a session."""
        async def write(write_db: AsyncSession):
            session = await write_db.get(WriterSession, session_id)
            if session is None:
                return None
            for key, value in kwargs.items():
                if value is not None and hasattr(session, key):
                    setattr(session, key, value)
            session.updated_at = datetime.now(timezone.utc)
            await write_db.flush()
            return _session_to_dict(session)
        return await writer_coordinator.run(write)

    async def delete_session(db: AsyncSession, session_id: str) -> None:
        """Delete a session and its messages."""
        async def write(write_db: AsyncSession):
            session = await write_db.get(WriterSession, session_id)
            if session is not None:
                await write_db.delete(session)
        await writer_coordinator.run(write)
        state_store._cache.pop(session_id, None)

    def _mark_session_executing(session: WriterSession) -> None:
        session.status = "active"
        session.phase = "executing"
        session.updated_at = datetime.now(timezone.utc)

    async def _run_core_kernel_path(
        db: AsyncSession | None,
        session_id: str,
        transcript_turn_id: str,
        user_message: str,
        raw_user_message: str,
        llm_client: Any,
        work_root: str,
        runtime_controls: dict[str, dict[str, bool]] | None = None,
        user_content_blocks: list[dict[str, Any]] | None = None,
        model_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run Writer through the CoreLoopKernel path.

        Args:
            db: Database session for loading runtime input and saving events.
            session_id: Session identifier.
            user_message: The current user message with attachment_context
                appended (this is passed as ``goal`` to run_core_kernel).
            raw_user_message: The original user message without
                attachment_context (this is what was saved to the DB).
                Used to identify and exclude the just-saved current user
                message from history, preventing duplication.
            llm_client: LLM client for the kernel.
            work_root: Working directory for file tools.

        Returns a summary dict with decision, steps_count, core_events,
        and other observable metadata from the kernel run.
        """
        return await runtime_runner.run(
            db=db,
            session_id=session_id,
            transcript_turn_id=transcript_turn_id,
            user_message=user_message,
            raw_user_message=raw_user_message,
            user_content_blocks=user_content_blocks,
            llm_client=llm_client,
            work_root=work_root,
            runtime_controls=runtime_controls,
            model_context=model_context,
        )

    async def run_turn(
        db: AsyncSession | None = None,
        session_id: str = "",
        user_message: str = "",
        thinking_enabled: bool | None = None,
        thinking_budget: int | None = None,
        shallow_thinking_enabled: bool | None = None,
        attachment_ids: list[str] | None = None,
        model_id: str | None = None,
        user_message_id: str | None = None,
        transcript_turn_id: str | None = None,
    ) -> None:
        """Run Writer for one transcript turn."""
        caller_db = db
        async def prepare(write_db: AsyncSession):
            session = await write_db.get(WriterSession, session_id)
            if session is None:
                raise ValueError("Session not found")
            _mark_session_executing(session)
            transcript_turn = await write_db.get(WriterTranscriptTurn, transcript_turn_id) if transcript_turn_id else None
            actual_user_message_id = user_message_id
            if transcript_turn_id:
                if transcript_turn is None or transcript_turn.session_id != session_id:
                    raise RuntimeError("App-server transcript turn does not exist for this session")
                if actual_user_message_id:
                    existing = await write_db.get(WriterMessage, actual_user_message_id)
                    if existing is None or existing.session_id != session_id or existing.role != "user":
                        raise RuntimeError("App-server user message does not exist for this session")
                    if transcript_turn.user_message_id != actual_user_message_id:
                        raise RuntimeError("App-server user message does not match transcript turn")
                else:
                    actual_user_message_id = transcript_turn.user_message_id
            else:
                transcript_turn, message = await create_user_message_turn(
                    write_db,
                    session_id=session_id,
                    user_text=user_message,
                    message_id=actual_user_message_id,
                    message_parts={"attachments": attachment_ids} if attachment_ids else None,
                    attachment_ids=attachment_ids,
                )
                actual_user_message_id = message.id
            return {
                "turn_id": transcript_turn.id,
                "work_root": session.work_root or settings.writer_work_root,
                "user_message_id": actual_user_message_id,
            }

        prepared = await writer_coordinator.run(prepare)
        work_root = prepared["work_root"]
        try:
            checkpoint = await checkpoint_service.create_checkpoint_if_dirty(
                session_id=session_id,
                work_root=work_root,
                reason="本轮开始前自动存档",
                turn_id=prepared["turn_id"],
                stage="before_turn",
            )
            if checkpoint is not None:
                await writer_coordinator.run(
                    lambda write_db: checkpoint_service.persist_checkpoint(
                        write_db, session_id=session_id, record=checkpoint,
                    )
                )
        except Exception:
            logger.debug("Unexpected error during pre-run Writer checkpoint for session %s", session_id, exc_info=True)
        async with state_session_factory() as read_db:
            resolved_config = await _resolve_writer_llm_config(read_db, model_id=model_id)
            attachment_context, user_content_blocks = await _session_attachment_input(
                read_db, session_id, attachment_ids or [],
            )
            controls = await _runtime_controls(read_db)
        resolved_client = build_llm_client(
            resolved_config,
            thinking_enabled=thinking_enabled,
            thinking_budget=thinking_budget,
        )
        resolved_client = _with_shallow_thinking_client(resolved_client, shallow_thinking_enabled)
        model_context = _model_context_from_resolved(
            resolved_config,
            thinking_enabled=thinking_enabled,
            thinking_budget=thinking_budget,
            shallow_thinking_enabled=shallow_thinking_enabled,
        )
        runtime_user_message = user_message + attachment_context
        try:
            summary = await _run_core_kernel_path(
                db=None,
                session_id=session_id,
                transcript_turn_id=prepared["turn_id"],
                user_message=runtime_user_message,
                raw_user_message=user_message,
                user_content_blocks=user_content_blocks,
                llm_client=resolved_client,
                work_root=work_root,
                runtime_controls=controls,
                model_context=model_context,
            )
        except BaseException:
            if caller_db is not None:
                caller_db.expire_all()
            raise
        # _run_core_kernel_path stores the final visible assistant message
        # when the kernel returns one. If it fails before that point, persist
        # the visible error here so the user is not left with a silent run.
        standalone_content = ""
        if (
            not str(summary.get("final_answer") or "").strip()
            and not str(summary.get("failure_summary") or "").strip()
        ):
            decision = str(summary.get("decision") or "")
            if decision != "done":
                standalone_content = str(summary.get("message") or summary.get("error") or "").strip()
        async def finish(write_db: AsyncSession):
            session = await write_db.get(WriterSession, session_id)
            if session is None:
                raise ValueError("Session not found")
            if standalone_content:
                write_db.add(WriterMessage(
                    id=gen_uuid(), session_id=session_id, role="assistant",
                    content=standalone_content, parts={"core_kernel_summary": summary},
                ))
        await writer_coordinator.run(finish)
        if caller_db is not None:
            caller_db.expire_all()

    async def create_approval_coordinator(session_id: str) -> CoreApprovalContinuationCoordinator:
        """Supply Writer-specific adapters to Core's approval operation."""
        state = await core_state_store.get(session_id)
        if state is None or not state.run_id:
            raise ValueError("Runtime state not found")
        async with state_session_factory() as read_db:
            session = await read_db.get(WriterSession, session_id)
            turn = await read_db.get(WriterTranscriptTurn, state.run_id)
        if session is None or turn is None or turn.session_id != session_id:
            raise ValueError("Approval turn not found")
        state.metadata.setdefault("original_user_message", turn.user_text)
        await core_state_store.save(state)
        recorder = RuntimeFactRecorder(
            session_id=session_id,
            turn_id=turn.id,
            app_projection_sink=app_projection_sink,
            write_coordinator=writer_coordinator,
        )
        work_root = session.work_root or settings.writer_work_root

        async def continue_turn(prompt: str, _state: RuntimeState) -> None:
            async with state_session_factory() as read_db:
                resolved_client = await _resolve_llm_client(read_db)
                controls = await _runtime_controls(read_db)
            await _run_core_kernel_path(
                db=None,
                session_id=session_id,
                transcript_turn_id=turn.id,
                user_message=prompt,
                raw_user_message=turn.user_text,
                llm_client=resolved_client,
                work_root=work_root,
                runtime_controls=controls,
            )

        async def continue_delegated_turn(
            prompt: str,
            state: RuntimeState,
            delegated_session: dict[str, Any],
        ) -> None:
            async with state_session_factory() as read_db:
                resolved_client = await _resolve_llm_client(read_db)
                controls = await _runtime_controls(read_db)
            sub_result = await resume_sub_agent_turn(
                parent_state=state,
                delegated_session=delegated_session,
                prompt=prompt,
                llm_client=resolved_client,
                work_root=work_root,
                runtime_controls=controls,
                live_event_callback=recorder.record_core_event,
            )
            await core_state_store.save(state)
            if sub_result.decision == "wait":
                return
            handoff = str(sub_result.message or sub_result.error or "子 Agent 未返回正文").strip()
            await _run_core_kernel_path(
                db=None,
                session_id=session_id,
                transcript_turn_id=turn.id,
                user_message=f"子 Agent 已在审批后继续执行，返回结果：\n{handoff}",
                raw_user_message=turn.user_text,
                llm_client=resolved_client,
                work_root=work_root,
                runtime_controls=controls,
            )

        return CoreApprovalContinuationCoordinator(
            state_store=core_state_store,
            emit_event=recorder.record_core_event,
            execute_tool=lambda tool_call: execute_approved_tool(tool_call, work_root=work_root),
            continue_turn=continue_turn,
            continue_delegated_turn=continue_delegated_turn,
        )

    async def compact_session_context(
        db: AsyncSession | None = None,
        *,
        session_id: str,
        on_summary_delta: Any | None = None,
    ) -> dict[str, Any]:
        del db
        loop_policy = LoopPolicy()
        async with state_session_factory() as read_db:
            resolved_config = await _resolve_writer_llm_config(read_db)
            plan = await prepare_session_context_compaction(read_db, session_id=session_id)
        resolved_client = WriterLLMClientAdapter(writer_client=build_llm_client(resolved_config))
        model_context = _model_context_from_resolved(
            resolved_config,
            thinking_enabled=None,
            thinking_budget=None,
        )
        _result, payload = await execute_session_context_compaction(
            plan,
            llm_client=resolved_client,
            model=str(model_context.get("model") or ""),
            on_summary_delta=on_summary_delta,
            model_retries=loop_policy.model_retries,
            model_timeout_seconds=loop_policy.model_timeout_seconds,
            retry_policy=RetryPolicy(),
        )
        return await writer_coordinator.run(
            lambda write_db: apply_session_context_compaction(write_db, plan=plan, payload=payload)
        )

    async def close() -> None:
        await app_projection_sink.close()
        await state_engine.dispose()

    # --- Return service dict ---

    return {
        "create_session": create_session,
        "list_sessions": list_sessions,
        "get_session": get_session,
        "update_session": update_session,
        "delete_session": delete_session,
        "run_turn": run_turn,
        "create_approval_coordinator": create_approval_coordinator,
        "compact_session_context": compact_session_context,
        "close": close,
    }


# --- Helpers ---

def _session_to_dict(session: WriterSession) -> dict[str, Any]:
    """Convert a WriterSession model to response dict."""
    return {
        "id": session.id,
        "title": session.title,
        "work_root": session.work_root,
        "branch": session.branch,
        "phase": session.phase,
        "mode": session.mode,
        "status": session.status,
        "todos": session.todos or [],
        "open_loops": session.open_loops or [],
        "context_summary": session.context_summary,
        "created_at": session.created_at.isoformat() if session.created_at else "",
        "updated_at": session.updated_at.isoformat() if session.updated_at else "",
    }


def _attachment_ids_from_parts(parts: dict[str, Any] | None) -> list[str]:
    raw = (parts or {}).get("attachments")
    if not isinstance(raw, list):
        return []
    ids: list[str] = []
    for item in raw:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.append(item["id"])
    return ids


async def _session_attachment_input(
    db: AsyncSession,
    session_id: str,
    current_ids: list[str],
) -> tuple[str, list[dict[str, Any]]]:
    result = await db.execute(
        select(WriterAttachment)
        .where(WriterAttachment.session_id == session_id)
        .order_by(WriterAttachment.created_at.desc())
        .limit(50)
    )
    attachments = list(reversed(result.scalars().all()))
    if not attachments:
        return "", []
    return build_attachment_runtime_input(
        [WriterAttachmentRepository._record(item) for item in attachments],
        current_ids,
    )
