from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import WriterSession
from app.models.transcript import WriterTranscriptBlock, WriterTranscriptModelCall, WriterTranscriptTurn
from lamtools_core.event.runtime_projection import (
    event_model_call_id,
    event_response_index,
    raw_tool_call_id_from_payload,
    tool_args_from_payload,
    tool_call_id_from_payload,
    usage_tokens,
    visible_runtime_part_content,
)
from app.services.transcript_service import (
    bump_transcript_revision,
    close_active_producers,
    close_open_blocks,
    ensure_active_producer,
    ensure_model_call,
    mark_turn_terminal,
    record_artifacts,
    upsert_block,
    utc_now,
)


class RuntimeTranscriptSink:
    def __init__(
        self,
        *,
        db: AsyncSession,
        turn: WriterTranscriptTurn,
        model_context: dict[str, Any] | None = None,
    ) -> None:
        self._db = db
        self._turn = turn
        self._model_context = dict(model_context or {}) if isinstance(model_context, dict) else None

    async def latest_model_call(self) -> WriterTranscriptModelCall:
        result = await self._db.execute(
            select(WriterTranscriptModelCall)
            .where(WriterTranscriptModelCall.turn_id == self._turn.id)
            .order_by(WriterTranscriptModelCall.sequence.desc())
            .limit(1)
        )
        call = result.scalar_one_or_none()
        if call is not None:
            await ensure_model_call(self._db, turn=self._turn, run_id=call.id, model_context=self._model_context)
            return call
        return await ensure_model_call(self._db, turn=self._turn, run_id=None, model_context=self._model_context)

    async def _apply_usage(self, call: WriterTranscriptModelCall, payload: dict[str, Any]) -> None:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return
        input_tokens = usage_tokens(usage, "input_tokens", "prompt_tokens")
        output_tokens = usage_tokens(usage, "output_tokens", "completion_tokens")
        changed = False
        if input_tokens is not None and call.input_tokens != input_tokens:
            call.input_tokens = input_tokens
            changed = True
        if output_tokens is not None and call.output_tokens != output_tokens:
            call.output_tokens = output_tokens
            changed = True
        if changed:
            await bump_transcript_revision(self._db, self._turn.session_id)

    async def _close_running_model_calls(self, status: str) -> None:
        rows = await self._db.execute(
            select(WriterTranscriptModelCall).where(
                WriterTranscriptModelCall.turn_id == self._turn.id,
                WriterTranscriptModelCall.completed_at.is_(None),
            )
        )
        now = utc_now()
        changed = False
        for row in rows.scalars().all():
            row.status = status
            row.completed_at = now
            changed = True
        if changed:
            await bump_transcript_revision(self._db, self._turn.session_id)

    async def _project_session_status(self, status: str) -> None:
        session = await self._db.get(WriterSession, self._turn.session_id)
        if session is None:
            return
        session.status = status
        session.phase = status
        session.updated_at = utc_now()

    async def sync_fact(
        self,
        *,
        phase: str | None,
        status: str | None,
        summary: str,
        preview: str,
        full_text: str,
        sequence: int,
        metadata: dict[str, Any] | None,
    ) -> None:
        payload = (metadata or {}).get("payload")
        payload = payload if isinstance(payload, dict) else {}
        event_name = str(phase or "")
        if event_name == "runtime.metrics":
            return
        if event_name == "runtime.done":
            terminal_at = utc_now()
            self._turn.terminal_at = terminal_at
            self._turn.last_state_changed_at = terminal_at
            self._turn.terminal_reason = "completed"
            self._turn.error = None
            self._turn.status_cache = "completed"
            await self._close_running_model_calls("completed")
            await close_open_blocks(self._db, turn=self._turn, status="completed")
            await close_active_producers(self._db, turn_id=self._turn.id, reason="completed")
            await self._project_session_status("completed")
            await bump_transcript_revision(self._db, self._turn.session_id)
            return
        if event_name == "runtime.failed":
            error = str(payload.get("error") or payload.get("message") or summary or "任务失败")
            await self._close_running_model_calls("failed")
            await mark_turn_terminal(
                self._db,
                turn=self._turn,
                reason=str(payload.get("reason") or "runtime_error"),
                error=error,
            )
            await self._project_session_status("failed")
            return
        if event_name == "runtime.cancelled":
            await self._close_running_model_calls("cancelled")
            await mark_turn_terminal(
                self._db,
                turn=self._turn,
                reason="cancelled",
                error=str(payload.get("message") or "任务已取消"),
            )
            await self._project_session_status("failed")
            return
        if event_name == "runtime.waiting":
            self._turn.status_cache = "waiting"
            self._turn.last_state_changed_at = utc_now()
            await self._project_session_status("waiting")
            await bump_transcript_revision(self._db, self._turn.session_id)
            return
        if event_name == "runtime.approval_response":
            request_id = str(payload.get("tool_call_id") or payload.get("request_id") or "").strip()
            block = await self._db.get(WriterTranscriptBlock, f"{request_id}:waiting") if request_id else None
            if block is not None and block.type == "waiting_request":
                block.status = "completed"
                block.completed_at = block.completed_at or utc_now()
                block.response_json = {
                    "action": str(payload.get("decision") or payload.get("action") or ""),
                    "response": str(payload.get("guidance") or ""),
                }
                block.metadata_ = {
                    **(block.metadata_ if isinstance(block.metadata_, dict) else {}),
                    "approval_response": {
                        "request_id": str(payload.get("request_id") or request_id),
                        "decision": str(payload.get("decision") or payload.get("action") or ""),
                        "guidance": str(payload.get("guidance") or ""),
                    },
                }
                await close_active_producers(
                    self._db,
                    turn_id=self._turn.id,
                    reason="resolved",
                    producer_id=f"{request_id}:tool",
                )
            self._turn.status_cache = "running"
            self._turn.last_state_changed_at = utc_now()
            await self._project_session_status("running")
            await bump_transcript_revision(self._db, self._turn.session_id)
            return

        fallback_model_call_id = f"{self._turn.id}:model-call-1"
        call_id = event_model_call_id(metadata, fallback_run_id=fallback_model_call_id)
        if event_name == "runtime.waiting" and not event_response_index(payload):
            call = await self.latest_model_call()
        else:
            call = await ensure_model_call(
                self._db,
                turn=self._turn,
                run_id=call_id,
                model_context=self._model_context,
            )

        part_type_for_producer = str(payload.get("part_type") or "")
        part_status_for_producer = str(payload.get("status") or status or "running")
        should_open_model_stream = (
            event_name in {"runtime.reply_delta", "runtime.usage"}
            or (
                event_name == "runtime.part"
                and part_type_for_producer != "tool_call"
                and part_status_for_producer not in {"completed", "done", "ok", "failed", "error", "cancelled"}
            )
        )
        if should_open_model_stream:
            await ensure_active_producer(
                self._db,
                turn=self._turn,
                producer_id=call.id,
                model_call_id=call.id,
                kind="model_stream",
            )
        await self._apply_usage(call, payload)

        if event_name in {"runtime.reply_delta", "runtime.usage"}:
            delta = str(payload.get("content") or "")
            if delta:
                block_id = str(payload.get("part_id") or f"{call.id}:model-text")
                existing = await self._db.get(WriterTranscriptBlock, block_id)
                if existing is not None and existing.content:
                    content = delta if delta.startswith(existing.content) else f"{existing.content}{delta}"
                else:
                    content = delta
                await upsert_block(
                    self._db,
                    turn=self._turn,
                    block_id=block_id,
                    model_call_id=call.id,
                    block_type="model_text",
                    sequence=existing.sequence if existing is not None else sequence,
                    event_sequence=existing.event_sequence if existing is not None else sequence,
                    status="running",
                    content=content,
                    producer_id=call.id,
                    metadata={"runtime_fact": metadata},
                )
            if payload.get("finish_reason") or event_name == "runtime.usage":
                call.status = "completed"
                call.completed_at = call.completed_at or utc_now()
                await close_open_blocks(self._db, turn=self._turn, model_call_id=call.id, status="completed")
                await close_active_producers(self._db, turn_id=self._turn.id, reason="completed", producer_id=call.id)
                await bump_transcript_revision(self._db, self._turn.session_id)
            return

        if event_name == "runtime.approval_request":
            tool_call_id = tool_call_id_from_payload(
                payload,
                fallback_call_id=call.id,
                sequence=sequence,
                turn_id=self._turn.id,
            )
            raw_tool_call_id = raw_tool_call_id_from_payload(payload, tool_call_id)
            tool_name = str(payload.get("tool_name") or "tool")
            tool_args = tool_args_from_payload(payload)
            request_content = str(
                payload.get("message")
                or payload.get("reason")
                or summary
                or f"需要授权后才能执行工具：{tool_name}"
            )
            request_metadata = {
                "runtime_fact": metadata,
                "tool_call_id": raw_tool_call_id,
                "tool_name": tool_name,
                "arguments": tool_args or {},
                "options": payload.get("options") if isinstance(payload.get("options"), list) else None,
                "permission": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
            }
            await upsert_block(
                self._db,
                turn=self._turn,
                block_id=f"{tool_call_id}:waiting",
                model_call_id=call.id,
                block_type="waiting_request",
                sequence=sequence,
                event_sequence=sequence,
                status="waiting",
                content=request_content,
                producer_id=f"{tool_call_id}:tool",
                request_kind=str(payload.get("request_kind") or "permission"),
                tool_name=tool_name,
                tool_call_id=raw_tool_call_id,
                tool_args_json=tool_args,
                metadata=request_metadata,
            )
            await close_active_producers(self._db, turn_id=self._turn.id, reason="waiting", producer_id=f"{tool_call_id}:tool")
            self._turn.last_state_changed_at = utc_now()
            await bump_transcript_revision(self._db, self._turn.session_id)
            return

        if event_name == "runtime.part":
            part_type = str(payload.get("part_type") or "text")
            block_type = "model_text" if part_type == "text" else part_type
            if block_type not in {"reasoning", "model_text", "tool_call", "tool_result", "status", "error", "compaction"}:
                block_type = "status"
            payload_tool_call_id = str(payload.get("tool_call_id") or payload.get("call_id") or "").strip()
            part_id = str(
                payload.get("part_id")
                or (f"{payload_tool_call_id}:result" if block_type == "tool_result" and payload_tool_call_id else "")
                or f"{call.id}:part:{sequence}"
            )
            if block_type == "tool_result" and not part_id.startswith(f"{call.id}:"):
                part_id = f"{call.id}:{part_id}"
            if block_type == "tool_call":
                is_draft = part_id.endswith(":tool-call-draft") or part_id.endswith(":tool-call")
                tool_name = str(payload.get("tool_name") or "").strip()
                tool_args = tool_args_from_payload(payload)
                tool_result = str(payload.get("tool_result") or payload.get("tool_error") or "").strip()
                if is_draft or (not tool_name and not tool_args and not tool_result):
                    return
                tool_call_id = tool_call_id_from_payload(
                    payload,
                    fallback_call_id=call.id,
                    sequence=sequence,
                    turn_id=self._turn.id,
                )
                raw_tool_call_id = raw_tool_call_id_from_payload(payload, tool_call_id)
                block_status = str(payload.get("status") or status or "running")
                await upsert_block(
                    self._db,
                    turn=self._turn,
                    block_id=f"{tool_call_id}:call",
                    model_call_id=call.id,
                    block_type="tool_call",
                    sequence=sequence,
                    event_sequence=sequence,
                    status="completed" if block_status in {"done", "completed", "ok"} else block_status,
                    content=visible_runtime_part_content(payload, full_text=full_text, preview=preview, summary=""),
                    producer_id=f"{tool_call_id}:tool",
                    tool_name=tool_name or "tool",
                    tool_call_id=raw_tool_call_id,
                    tool_args_json=tool_args,
                    metadata={"runtime_fact": metadata},
                )
                return
            content = visible_runtime_part_content(payload, full_text=full_text, preview=preview, summary=summary)
            if block_type == "status" and not content:
                return
            block_status = str(payload.get("status") or status or "running")
            await upsert_block(
                self._db,
                turn=self._turn,
                block_id=part_id,
                model_call_id=call.id,
                block_type=block_type,
                sequence=sequence,
                event_sequence=sequence,
                status="completed" if block_status in {"done", "completed"} else block_status,
                content=content,
                producer_id=call.id,
                tool_name=str(payload.get("tool_name") or "") or None,
                tool_call_id=payload_tool_call_id or None,
                tool_args_json=tool_args_from_payload(payload),
                tool_result_preview=content if block_type == "tool_result" else None,
                error=str(payload.get("tool_error") or payload.get("error") or "") or None,
                metadata={"runtime_fact": metadata},
            )
            return
        if event_name == "runtime.tool.started":
            tool_call_id = tool_call_id_from_payload(
                payload,
                fallback_call_id=call.id,
                sequence=sequence,
                turn_id=self._turn.id,
            )
            raw_tool_call_id = raw_tool_call_id_from_payload(payload, tool_call_id)
            tool_producer_id = f"{tool_call_id}:tool"
            await ensure_active_producer(
                self._db,
                turn=self._turn,
                producer_id=tool_producer_id,
                model_call_id=call.id,
                parent_block_id=f"{tool_call_id}:call",
                kind="tool_execution",
            )
            await upsert_block(
                self._db,
                turn=self._turn,
                block_id=f"{tool_call_id}:call",
                model_call_id=call.id,
                block_type="tool_call",
                sequence=sequence,
                event_sequence=sequence,
                status="running",
                content=summary or preview,
                producer_id=tool_producer_id,
                tool_name=str(payload.get("tool_name") or "tool"),
                tool_call_id=raw_tool_call_id,
                tool_args_json=tool_args_from_payload(payload),
                metadata={"runtime_fact": metadata},
            )
            return
        if event_name == "runtime.tool.finished":
            tool_call_id = tool_call_id_from_payload(
                payload,
                fallback_call_id=call.id,
                sequence=sequence,
                turn_id=self._turn.id,
            )
            raw_tool_call_id = raw_tool_call_id_from_payload(payload, tool_call_id)
            tool_status = "completed" if str(payload.get("status") or status or "ok") in {"ok", "completed", "done"} else "failed"
            tool_producer_id = f"{tool_call_id}:tool"
            await upsert_block(
                self._db,
                turn=self._turn,
                block_id=f"{tool_call_id}:call",
                model_call_id=call.id,
                block_type="tool_call",
                sequence=sequence,
                event_sequence=sequence,
                status=tool_status,
                content=summary or preview,
                producer_id=tool_producer_id,
                tool_name=str(payload.get("tool_name") or "tool"),
                tool_call_id=raw_tool_call_id,
                tool_args_json=tool_args_from_payload(payload),
                metadata={"runtime_fact": metadata},
            )
            block = await upsert_block(
                self._db,
                turn=self._turn,
                block_id=f"{tool_call_id}:result",
                model_call_id=call.id,
                block_type="tool_result",
                sequence=sequence,
                event_sequence=sequence,
                status=tool_status,
                content=preview or summary,
                producer_id=tool_producer_id,
                tool_name=str(payload.get("tool_name") or "tool"),
                tool_call_id=raw_tool_call_id,
                tool_result_preview=preview or summary,
                error=str(payload.get("error") or "") or None,
                metadata={"runtime_fact": metadata},
            )
            artifact_source = payload.get("artifacts")
            payload_metadata = payload.get("metadata")
            if not artifact_source and isinstance(payload_metadata, dict):
                artifact_source = payload_metadata.get("artifacts")
            await record_artifacts(self._db, turn_id=self._turn.id, block_id=block.id, artifacts=artifact_source)
            await close_active_producers(self._db, turn_id=self._turn.id, reason=tool_status, producer_id=tool_producer_id)
            return
        if event_name == "runtime.waiting":
            question = str(payload.get("message") or payload.get("question") or summary or "等待用户输入")
            waiting_tool_call_id = str(payload.get("tool_call_id") or "").strip()
            waiting_tool_name = str(payload.get("tool_name") or "").strip() or None
            waiting_tool_args = tool_args_from_payload(payload)
            waiting_metadata = {
                "runtime_fact": metadata,
                "tool_call_id": waiting_tool_call_id or None,
                "tool_name": waiting_tool_name,
                "arguments": waiting_tool_args or {},
                "options": payload.get("options") if isinstance(payload.get("options"), list) else None,
                "permission": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
            }
            waiting_block_id = f"{waiting_tool_call_id}:waiting" if waiting_tool_call_id else f"{call.id}:waiting:{sequence}"
            waiting_producer_id = f"{waiting_tool_call_id}:tool" if waiting_tool_call_id else call.id
            existing_waiting = await self._db.get(WriterTranscriptBlock, waiting_block_id)
            if existing_waiting is not None and existing_waiting.type == "waiting_request":
                existing_metadata = existing_waiting.metadata_ if isinstance(existing_waiting.metadata_, dict) else {}
                if waiting_metadata.get("options") is None and isinstance(existing_metadata.get("options"), list):
                    waiting_metadata["options"] = existing_metadata.get("options")
                if not waiting_metadata.get("permission") and isinstance(existing_metadata.get("permission"), dict):
                    waiting_metadata["permission"] = existing_metadata.get("permission")
            await upsert_block(
                self._db,
                turn=self._turn,
                block_id=waiting_block_id,
                model_call_id=call.id,
                block_type="waiting_request",
                sequence=existing_waiting.sequence if existing_waiting is not None else sequence,
                event_sequence=existing_waiting.event_sequence if existing_waiting is not None else sequence,
                status="waiting",
                content=question,
                producer_id=waiting_producer_id,
                request_kind=str(payload.get("request_kind") or "ask"),
                tool_name=waiting_tool_name,
                tool_call_id=waiting_tool_call_id or None,
                tool_args_json=waiting_tool_args,
                metadata=waiting_metadata,
            )
            await close_active_producers(self._db, turn_id=self._turn.id, reason="waiting", producer_id=waiting_producer_id)
            self._turn.last_state_changed_at = utc_now()
            await bump_transcript_revision(self._db, self._turn.session_id)
