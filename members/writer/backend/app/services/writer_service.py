from __future__ import annotations

"""Writer service — closure-based DI orchestration.

Follows the artist_orchestrate pattern from LamImager:
- Creates all dependencies once
- Returns a dict of async service functions
- Functions close over shared state (settings, clients, stores)
"""
import logging
import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lamtools_core.kernel import LoopPolicy, summarize_kernel_result
from lamtools_core.llm.shallow_thinking import ShallowThinkingClient
from lamtools_core.llm.policy import RetryPolicy

from app.config import Settings
from app.core.writer.state_store import WriterStateStore
from app.core.writer.core_kernel_adapter import (
    run_core_kernel,
    schedule_writer_startup_prewarm,
)
from app.core.writer.llm_bridge import WriterLLMClientAdapter
from app.core.writer.agent_runtime import AgentCall, SubAgentDefinition
from app.core.writer.git import WriterGitManager
from app.models.base import gen_uuid
from app.models.session import WriterSession
from app.models.message import WriterMessage
from app.models.attachment import WriterAttachment
from app.models.app_setting import AppSetting
from app.models.transcript import WriterTranscriptBlock, WriterTranscriptTurn
from app.services.app_projection_sink import AppProjectionSink
from app.services.attachment_service import read_text_preview
from app.services.checkpoint_service import WriterCheckpointService
from app.services.commit_review_service import WriterCommitReviewService
from app.services.runtime_approved_tool import APPROVABLE_TOOL_NAMES, execute_approved_waiting_tool
from app.services.runtime_continuation_prompts import (
    approved_tool_continuation_prompt,
    guidance_continuation_prompt,
)
from app.services.runtime_capabilities import WRITER_DEFAULT_COMMAND_POLICIES
from app.services.runtime_runner import WriterRuntimeRunner
from app.services.runtime_waiting_request import resolve_waiting_request_response
from app.services.session_compaction_service import compact_session_context_response
from app.services.llm_config_service import build_llm_client, resolve_llm_config
from app.services.transcript_service import (
    close_open_blocks,
    create_user_message_turn,
    bump_transcript_revision,
    mark_turn_terminal,
)
from lamtools_core.runtime import RuntimeState, default_runtime_task_registry

logger = logging.getLogger(__name__)

def _is_llm_auth_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "401" in text or "authentication" in text or "api key" in text or "unauthorized" in text


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


class _FallbackLLMClient:
    """Use an agent-specific model first, then fall back to Writer's model on auth/config failure."""

    def __init__(self, primary: Any, fallback: Any) -> None:
        self._primary = primary
        self._fallback = fallback
        for attr in (
            "api_type",
            "base_url",
            "model_id",
            "temperature",
            "max_tokens",
            "adapter_profile",
            "api_key",
        ):
            if hasattr(primary, attr):
                setattr(self, attr, getattr(primary, attr))

    async def chat_full(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return await self._primary.chat_full(*args, **kwargs)
        except Exception as exc:
            if not _is_llm_auth_error(exc):
                raise
            logger.warning("SubAgent primary LLM failed authentication; falling back to Writer model: %s", exc)
            return await self._fallback.chat_full(*args, **kwargs)

    async def complete(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return await self._primary.complete(*args, **kwargs)
        except Exception as exc:
            if not _is_llm_auth_error(exc):
                raise
            logger.warning("SubAgent primary Core LLM failed authentication; falling back to Writer model: %s", exc)
            return await self._fallback.complete(*args, **kwargs)

    def stream(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return self._primary.stream(*args, **kwargs)
        except Exception as exc:
            if not _is_llm_auth_error(exc):
                raise
            logger.warning("SubAgent primary LLM stream failed authentication; falling back to Writer model: %s", exc)
            return self._fallback.stream(*args, **kwargs)


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


def writer_orchestrate(settings: Settings) -> dict[str, Any]:
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
    state_engine = create_async_engine(settings.database_url, echo=settings.debug)
    state_session_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    app_projection_sink = AppProjectionSink(database_url=settings.database_url, debug=settings.debug)
    state_store = WriterStateStore(state_session_factory)
    core_state_store = _WriterCoreStateStore(state_store)
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
        if model_id is None:
            resolved = await resolve_llm_config(db, "writer")
        else:
            resolved = await resolve_llm_config(db, "writer", model_id=model_id)
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

    async def _resolve_sub_agent_llm_client(
        db: AsyncSession,
        definition: SubAgentDefinition,
        call: AgentCall,
        *,
        thinking_enabled: bool | None = None,
        thinking_budget: int | None = None,
        shallow_thinking_enabled: bool | None = None,
    ):
        model_override = str(call.options.get("model") or definition.model or "").strip()
        if model_override:
            resolved = await resolve_llm_config(db, "sub_agent", model_id=model_override)
        else:
            resolved = await resolve_llm_config(db, "sub_agent")
        if resolved is None:
            resolved = await resolve_llm_config(db, "sub_agent")
        if resolved is None:
            raise RuntimeError("No LLM provider/model configured in DB")
        primary = _with_shallow_thinking_client(
            build_llm_client(
                resolved,
                thinking_enabled=thinking_enabled,
                thinking_budget=thinking_budget,
            ),
            shallow_thinking_enabled,
        )
        writer_resolved = await resolve_llm_config(db, "writer")
        if writer_resolved is None or writer_resolved.model.id == resolved.model.id:
            return primary
        fallback = _with_shallow_thinking_client(
            build_llm_client(
                writer_resolved,
                thinking_enabled=thinking_enabled,
                thinking_budget=thinking_budget,
            ),
            shallow_thinking_enabled,
        )
        return _FallbackLLMClient(primary, fallback)

    # --- Service functions ---

    async def _runtime_controls(db: AsyncSession) -> dict[str, dict[str, Any]]:
        setting = await db.get(AppSetting, "lamwriter.runtimeControls")
        value = setting.value if setting is not None and isinstance(setting.value, dict) else {}
        agents = value.get("agents") if isinstance(value.get("agents"), dict) else {}
        tools = value.get("tools") if isinstance(value.get("tools"), dict) else {}
        command_policies = value.get("command_policies") if isinstance(value.get("command_policies"), dict) else {}
        normalized_command_policies = dict(WRITER_DEFAULT_COMMAND_POLICIES)
        normalized_command_policies.update({
            str(k): str(v)
            for k, v in command_policies.items()
            if k in {"regular", "dangerous"} and v in {"auto_allow", "ask_user"}
        })
        return {
            "agents": {str(k): bool(v) for k, v in agents.items()},
            "tools": {str(k): bool(v) for k, v in tools.items()},
            "command_policies": normalized_command_policies,
        }

    runtime_runner = WriterRuntimeRunner(
        app_projection_sink=app_projection_sink,
        state_store=core_state_store,
        checkpoint_service=checkpoint_service,
        commit_review_service=commit_review_service,
        run_core_kernel=run_core_kernel,
        summarize_result=summarize_kernel_result,
        schedule_prewarm=schedule_writer_startup_prewarm,
        runtime_task_registry=default_runtime_task_registry,
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
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return _session_to_dict(session)

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
        session = await db.get(WriterSession, session_id)
        if session is None:
            return None

        for key, value in kwargs.items():
            if value is not None and hasattr(session, key):
                setattr(session, key, value)

        session.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(session)
        return _session_to_dict(session)

    async def delete_session(db: AsyncSession, session_id: str) -> None:
        """Delete a session and its messages."""
        session = await db.get(WriterSession, session_id)
        if session is not None:
            await db.delete(session)
            await db.commit()
        # Also clean up state store
        await state_store.delete(session_id)

    def _core_kernel_session_status(decision: str) -> str:
        if decision == "done":
            return "completed"
        if decision == "wait":
            return "waiting"
        if decision == "failed":
            return "failed"
        return "active"

    def _mark_session_executing(session: WriterSession) -> None:
        session.status = "active"
        session.phase = "executing"
        session.updated_at = datetime.now(timezone.utc)

    def _apply_kernel_summary_to_session(session: WriterSession, summary: dict[str, Any]) -> str:
        decision = str(summary.get("decision") or "")
        session.status = "failed" if summary.get("error") == "cancelled" else _core_kernel_session_status(decision)
        if decision == "done":
            session.phase = "completed"
        elif decision == "failed":
            session.phase = "failed"
        elif decision == "wait":
            session.phase = "waiting"
        else:
            session.phase = "executing"
        session.updated_at = datetime.now(timezone.utc)
        return decision

    async def _run_core_kernel_path(
        db: AsyncSession,
        session_id: str,
        transcript_turn_id: str,
        user_message: str,
        raw_user_message: str,
        llm_client: Any,
        work_root: str,
        runtime_controls: dict[str, dict[str, bool]] | None = None,
        user_content_blocks: list[dict[str, Any]] | None = None,
        thinking_enabled: bool | None = None,
        thinking_budget: int | None = None,
        shallow_thinking_enabled: bool | None = None,
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
            sub_agent_llm_client_factory=lambda definition, call: _resolve_sub_agent_llm_client(
                db,
                definition,
                call,
                thinking_enabled=thinking_enabled,
                thinking_budget=thinking_budget,
                shallow_thinking_enabled=shallow_thinking_enabled,
            ),
            model_context=model_context,
        )

    async def run_turn(
        db: AsyncSession,
        session_id: str,
        user_message: str,
        thinking_enabled: bool | None = None,
        thinking_budget: int | None = None,
        shallow_thinking_enabled: bool | None = None,
        attachment_ids: list[str] | None = None,
        model_id: str | None = None,
        user_message_id: str | None = None,
        transcript_turn_id: str | None = None,
    ) -> None:
        """Run Writer for one transcript turn."""
        # 0. Load session
        session = await db.get(WriterSession, session_id)
        if session is None:
            raise ValueError("Session not found")

        work_root = session.work_root or settings.writer_work_root
        _mark_session_executing(session)
        await db.commit()
        try:
            if transcript_turn_id:
                await checkpoint_service.checkpoint_if_dirty(
                    db,
                    session,
                    reason="本轮开始前自动存档",
                    turn_id=transcript_turn_id,
                    stage="before_turn",
                )
            else:
                await checkpoint_service.checkpoint_if_dirty(db, session, reason="本轮开始前自动存档")
            await db.refresh(session)
        except Exception:
            logger.debug("Unexpected error during pre-run Writer checkpoint for session %s", session_id, exc_info=True)

        transcript_turn = await db.get(WriterTranscriptTurn, transcript_turn_id) if transcript_turn_id else None
        if transcript_turn_id:
            if transcript_turn is None or transcript_turn.session_id != session_id:
                raise RuntimeError("App-server transcript turn does not exist for this session")
            if user_message_id:
                existing_user_msg = await db.get(WriterMessage, user_message_id)
                if (
                    existing_user_msg is None
                    or existing_user_msg.session_id != session_id
                    or existing_user_msg.role != "user"
                ):
                    raise RuntimeError("App-server user message does not exist for this session")
                if transcript_turn.user_message_id != user_message_id:
                    raise RuntimeError("App-server user message does not match transcript turn")
            elif transcript_turn.user_message_id:
                user_message_id = transcript_turn.user_message_id
            else:
                raise RuntimeError("App-server transcript turn is missing its user message")
        else:
            transcript_turn, _user_msg = await create_user_message_turn(
                db,
                session_id=session_id,
                user_text=user_message,
                message_id=user_message_id,
                message_parts={"attachments": attachment_ids} if attachment_ids else None,
                attachment_ids=attachment_ids,
            )
            await db.commit()

        resolved_config = await _resolve_writer_llm_config(db, model_id=model_id)
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
        attachment_context, user_content_blocks = await _session_attachment_input(
            db,
            session_id,
            attachment_ids or [],
        )
        runtime_user_message = user_message + attachment_context

        summary = await _run_core_kernel_path(
            db=db,
            session_id=session_id,
            transcript_turn_id=transcript_turn.id,
            user_message=runtime_user_message,
            raw_user_message=user_message,
            user_content_blocks=user_content_blocks,
            llm_client=resolved_client,
            work_root=work_root,
            runtime_controls=await _runtime_controls(db),
            thinking_enabled=thinking_enabled,
            thinking_budget=thinking_budget,
            shallow_thinking_enabled=shallow_thinking_enabled,
            model_context=model_context,
        )
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
        if standalone_content:
            assistant_msg = WriterMessage(
                id=gen_uuid(),
                session_id=session_id,
                role="assistant",
                content=standalone_content,
                parts={"core_kernel_summary": summary},
            )
            db.add(assistant_msg)
        _apply_kernel_summary_to_session(session, summary)
        await db.commit()

    async def respond_waiting_request(
        db: AsyncSession,
        session_id: str,
        block_id: str,
        action: str,
        response: str = "",
    ) -> dict[str, Any]:
        """Resolve a persisted user gate and continue the same transcript turn."""
        session = await db.get(WriterSession, session_id)
        if session is None:
            raise ValueError("Session not found")
        block = await db.get(WriterTranscriptBlock, block_id)
        if block is None or block.turn_id is None:
            raise ValueError("Waiting request not found")
        turn = await db.get(WriterTranscriptTurn, block.turn_id)
        if turn is None or turn.session_id != session_id:
            raise ValueError("Waiting request does not belong to this session")
        if block.type != "waiting_request" or block.completed_at is not None:
            raise ValueError("Waiting request is not open")

        resolved_request = await resolve_waiting_request_response(
            db,
            session_id=session_id,
            turn=turn,
            block=block,
            action=action,
            response=response,
            state_store=core_state_store,
        )
        normalized_action = resolved_request.action
        guidance_text = resolved_request.guidance_text

        if normalized_action == "deny":
            await mark_turn_terminal(
                db,
                turn=turn,
                reason="user_denied_permission",
                error="用户拒绝执行需要授权的工具调用。",
            )
            session.status = "failed"
            session.phase = "failed"
            session.updated_at = datetime.now(timezone.utc)
            await db.commit()
            return {"status": "failed", "decision": "deny"}

        if normalized_action == "guide":
            resolved_client = await _resolve_llm_client(db)
            work_root = session.work_root or settings.writer_work_root
            continuation = guidance_continuation_prompt(
                turn=turn,
                block=block,
                guidance_text=guidance_text,
            )
            _mark_session_executing(session)
            await db.commit()
            summary = await _run_core_kernel_path(
                db=db,
                session_id=session_id,
                transcript_turn_id=turn.id,
                user_message=continuation,
                raw_user_message=turn.user_text,
                llm_client=resolved_client,
                work_root=work_root,
                runtime_controls=await _runtime_controls(db),
            )
            decision = _apply_kernel_summary_to_session(session, summary)
            await db.commit()
            return {"status": session.status, "decision": normalized_action, "run_decision": decision}

        if block.request_kind != "permission":
            return {"status": "recorded", "decision": normalized_action}

        if (block.tool_name or "") not in APPROVABLE_TOOL_NAMES:
            return {"status": "recorded", "decision": normalized_action}

        work_root = session.work_root or settings.writer_work_root
        approved_tool = await execute_approved_waiting_tool(db, turn=turn, block=block, work_root=work_root)

        if not approved_tool.completed:
            await mark_turn_terminal(
                db,
                turn=turn,
                reason="approved_tool_failed",
                error=approved_tool.tool_content or "已批准的工具执行失败。",
            )
            session.status = "failed"
            session.phase = "failed"
            session.updated_at = datetime.now(timezone.utc)
            await db.commit()
            return {"status": "failed", "decision": "approve"}

        resolved_client = await _resolve_llm_client(db)
        continuation = approved_tool_continuation_prompt(
            turn=turn,
            approved_tool=approved_tool,
        )
        _mark_session_executing(session)
        await db.commit()
        summary = await _run_core_kernel_path(
            db=db,
            session_id=session_id,
            transcript_turn_id=turn.id,
            user_message=continuation,
            raw_user_message=turn.user_text,
            llm_client=resolved_client,
            work_root=work_root,
            runtime_controls=await _runtime_controls(db),
        )
        decision = _apply_kernel_summary_to_session(session, summary)
        await db.commit()
        return {"status": session.status, "decision": normalized_action, "run_decision": decision}

    async def compact_session_context(
        db: AsyncSession,
        *,
        session_id: str,
        on_summary_delta: Any | None = None,
    ) -> dict[str, Any]:
        loop_policy = LoopPolicy()
        resolved_config = await _resolve_writer_llm_config(db)
        resolved_client = WriterLLMClientAdapter(writer_client=build_llm_client(resolved_config))
        model_context = _model_context_from_resolved(
            resolved_config,
            thinking_enabled=None,
            thinking_budget=None,
        )
        return await compact_session_context_response(
            db,
            session_id=session_id,
            llm_client=resolved_client,
            model=str(model_context.get("model") or ""),
            on_summary_delta=on_summary_delta,
            model_retries=loop_policy.model_retries,
            model_timeout_seconds=loop_policy.model_timeout_seconds,
            retry_policy=RetryPolicy(),
        )

    # --- Return service dict ---

    return {
        "create_session": create_session,
        "list_sessions": list_sessions,
        "get_session": get_session,
        "update_session": update_session,
        "delete_session": delete_session,
        "run_turn": run_turn,
        "respond_waiting_request": respond_waiting_request,
        "compact_session_context": compact_session_context,
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
    current = set(current_ids)
    lines = ["", "当前会话附件索引（本地存储路径不会提供给模型）："]
    content_blocks: list[dict[str, Any]] = []
    for attachment in attachments:
        marker = "本条消息附件" if attachment.id in current else "历史附件"
        if attachment.id in current and _is_image_attachment(attachment):
            block = _image_attachment_content_block(attachment)
            if block is not None:
                content_blocks.append(block)
                lines.append(
                    f"- [{marker}] {attachment.filename} | {attachment.mime_type} | {attachment.size} bytes | 已作为图片输入提供"
                )
            else:
                lines.append(
                    f"- [{marker}] {attachment.filename} | {attachment.mime_type} | {attachment.size} bytes | 图片文件缺失，未能提供给模型"
                )
            continue
        if attachment.id in current and attachment.preview_type == "text":
            lines.append(_text_attachment_context_line(marker, attachment))
            continue
        lines.append(
            f"- [{marker}] {attachment.filename} | {attachment.mime_type} | {attachment.size} bytes | {_attachment_label(attachment)}"
        )
    return "\n".join(lines), content_blocks


def _is_image_attachment(attachment: WriterAttachment) -> bool:
    return attachment.preview_type == "image" or str(attachment.mime_type or "").startswith("image/")


def _image_attachment_content_block(attachment: WriterAttachment) -> dict[str, Any] | None:
    path = Path(attachment.storage_path)
    if not path.exists() or not path.is_file():
        return None
    mime_type = str(attachment.mime_type or "application/octet-stream")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{mime_type};base64,{encoded}",
            "detail": "auto",
        },
    }


def _text_attachment_context_line(marker: str, attachment: WriterAttachment) -> str:
    path = Path(attachment.storage_path)
    if not path.exists() or not path.is_file():
        return (
            f"- [{marker}] {attachment.filename} | {attachment.mime_type} | "
            f"{attachment.size} bytes | 文本文件缺失，未能提供内容"
        )
    preview = read_text_preview(path)
    return (
        f"- [{marker}] {attachment.filename} | {attachment.mime_type} | {attachment.size} bytes | 文本内容如下：\n"
        f"{preview}"
    )


def _attachment_label(attachment: WriterAttachment) -> str:
    if _is_image_attachment(attachment):
        return "图片附件；仅本条消息图片会直接提供给模型"
    if attachment.preview_type == "text":
        return "文本附件；仅本条消息文本会直接提供给模型"
    if attachment.preview_type == "pdf" or attachment.mime_type == "application/pdf":
        return "PDF 附件；当前未自动解析"
    return "二进制附件；当前未自动解析"
