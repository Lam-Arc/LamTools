from __future__ import annotations

from typing import Any, Callable

from app.models.session import WriterSession
from app.core.writer.skills import WriterSkillRegistry
from app.core.resource_dirs import writer_resource_roots
from app.services.project_management import ensure_writer_project
from app.services.session_management import resolve_writer_session_work_root
from app.services.session_projection import session_response_projected
from app.services.session_compaction_service import compact_session_context_response
from app.services.session_fork_service import fork_session_response
from app.services.transcript_service import create_user_message_turn
from app.services.attachment_service import WriterAttachmentRepository
from lamtools_core.app.live_member import (
    PreparedLiveInput,
    QueueMaterialization,
    TurnMaterialization,
)
from lamtools_core.app.queue_state import input_item_attachment_ids as input_attachment_ids
from lamtools_core.composer_commands import prepare_composer_input


class WriterLiveMemberAdapter:
    def __init__(self, *, session_factory: Callable[[], Any], runtime: Any) -> None:
        self._session_factory = session_factory
        self._runtime = runtime

    def command_member_roots(self):
        return writer_resource_roots()

    def attachment_repository(self, db):
        return WriterAttachmentRepository(db)

    def command_skill_registry(self):
        return WriterSkillRegistry()

    def command_action_handlers(self):
        return {
            "compact": self._compact_command,
            "fork": self._fork_command,
        }

    async def _compact_command(self, *, thread_id: str, on_delta=None):
        writer_service = self._runtime.writer_service_or_none()
        compact = writer_service.get("compact_session_context") if isinstance(writer_service, dict) else None
        if callable(compact):
            return await compact(session_id=thread_id, on_summary_delta=on_delta)
        async with self._session_factory() as db:
            result = await compact_session_context_response(
                db,
                session_id=thread_id,
                on_summary_delta=on_delta,
            )
            await db.commit()
            return result

    async def _fork_command(self, *, thread_id: str, work_root: str = ""):
        del work_root
        async with self._session_factory() as db:
            session = await db.get(WriterSession, thread_id)
            title = f"{session.title if session else 'Session'} fork"
            result = await fork_session_response(
                db,
                thread_id,
                title=title,
                isolated_worktree=True,
            )
            await db.commit()
            return {"status": "forked", "session": result}

    async def augment_thread_read(self, *, db, thread_id, result):
        del result
        session = await db.get(WriterSession, thread_id)
        return {"session": await session_response_projected(db, session) if session is not None else None}

    async def materialize_thread(self, *, db, thread_id, params):
        session = await db.get(WriterSession, thread_id)
        if session is None:
            requested_root = str(params.get("work_root") or params.get("workRoot") or "")
            project = await ensure_writer_project(db, work_root=requested_root) if requested_root.strip() else None
            if project is not None:
                await db.flush()
            session = WriterSession(
                id=thread_id,
                title=str(params.get("title") or "Untitled"),
                work_root=project.work_root if project is not None else "",
                project_id=project.id if project is not None else None,
                status="active",
                phase="idle",
            )
            db.add(session)
            await db.flush()
        return {"session_id": thread_id}

    async def prepare_turn_input(self, *, thread_id, params, input_items):
        async with self._session_factory() as db:
            session = await db.get(WriterSession, thread_id)
        if session is None:
            raise ValueError("Thread/session not found")
        requested_root = str(params.get("work_root") or params.get("workRoot") or session.work_root or "")
        async with self._session_factory() as db:
            work_root = await resolve_writer_session_work_root(
                db,
                work_root=requested_root,
                project_id=session.project_id,
            )
        prepared = prepare_composer_input(
            work_root=work_root,
            input_items=input_items,
            skill_registry=WriterSkillRegistry(),
        )
        return PreparedLiveInput(
            visible_input=prepared.visible_items,
            runtime_input=prepared.runtime_items,
            visible_text=prepared.visible_text,
            runtime_text=prepared.runtime_text,
            work_root=str(work_root or ""),
            runtime_extras={"attachment_ids": input_attachment_ids(prepared.runtime_items)},
        )

    async def materialize_turn(
        self, *, db, thread_id, turn_id, user_item_id, client_message_id, prepared, params
    ):
        del client_message_id, params
        attachment_ids = input_attachment_ids(prepared.visible_input)
        transcript_turn, user_message = await create_user_message_turn(
            db,
            session_id=thread_id,
            user_text=prepared.visible_text,
            message_id=user_item_id,
            turn_id=turn_id,
            message_parts={
                "app_server_input": prepared.visible_input,
                **({"attachments": attachment_ids} if attachment_ids else {}),
            },
            attachment_ids=attachment_ids,
        )
        return TurnMaterialization(
            turn_id=transcript_turn.id,
            user_item_id=user_message.id,
            turn_payload_extra={
                "transcript_turn_id": transcript_turn.id,
                "user_message_id": user_message.id,
            },
            user_payload_extra={
                "message_id": user_message.id,
                "user_message_id": user_message.id,
            },
            include_turn_status=False,
            runtime_extras={"attachment_ids": attachment_ids},
        )

    async def start_runtime(self, *, runtime_start):
        await self._runtime.run_accepted_turn(**self._runtime_kwargs(runtime_start))

    async def prepare_queue_input(self, *, thread_id, params, input_items):
        return await self.prepare_turn_input(thread_id=thread_id, params=params, input_items=input_items)

    async def materialize_queue(
        self, *, db, thread_id, queue_item_id, client_message_id, prepared, params
    ):
        del db, thread_id, queue_item_id, client_message_id, params
        return QueueMaterialization(payload_extra={"work_root": prepared.work_root})

    @staticmethod
    def _runtime_kwargs(runtime_start: dict[str, Any]) -> dict[str, Any]:
        names = {
            "thread_id", "turn_id", "user_message_id", "text", "work_root",
            "thinking_enabled", "thinking_budget", "shallow_thinking_enabled",
            "model_id", "attachment_ids",
        }
        return {name: value for name, value in runtime_start.items() if name in names}


__all__ = ["WriterLiveMemberAdapter"]
