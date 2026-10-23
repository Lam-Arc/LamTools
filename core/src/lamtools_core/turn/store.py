"""Durable read models for the turn-control domain.

Every write goes through the application's SQLite write coordinator, so the
compare-and-set transitions below are serialized with the rest of the Core
persistence layer.  The event log stays the immutable source of truth; these
rows are the indexed projection the coordinator and the live API read.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Iterable

from sqlalchemy import delete, func, select, update

from lamtools_core.app.core_db import (
    CoreAgentRun,
    CoreTurnControl,
    CoreTurnIntent,
    CoreTurnInteraction,
    CoreTurnJob,
    CoreTurnRun,
)
from lamtools_core.turn.model import (
    AgentRun,
    ControlIntent,
    Interaction,
    InteractionAnswer,
    InteractionOption,
    Run,
    Turn,
    now_ms,
)


def new_turn_id(thread_id: str) -> str:
    return f"{thread_id}:turn:{uuid.uuid4().hex[:12]}"


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


class TurnStore:
    """Persistence boundary for turns, runs, interactions, intents and jobs."""

    def __init__(self, session_factory: Any, write_coordinator: Any) -> None:
        self.session_factory = session_factory
        self.write_coordinator = write_coordinator

    # ------------------------------------------------------------------
    # Turns
    # ------------------------------------------------------------------
    async def get_turn(self, turn_id: str) -> Turn | None:
        async with self.session_factory() as db:
            row = await db.get(CoreTurnControl, turn_id)
        return _turn_from_row(row) if row is not None else None

    async def get_turn_for_thread(self, thread_id: str) -> Turn | None:
        async with self.session_factory() as db:
            row = (
                await db.execute(
                    select(CoreTurnControl)
                    .where(CoreTurnControl.thread_id == thread_id)
                    .order_by(CoreTurnControl.updated_seq.desc())
                    .limit(1)
                )
            ).scalars().first()
        return _turn_from_row(row) if row is not None else None

    async def list_turns(self, thread_id: str, *, limit: int = 100) -> list[Turn]:
        async with self.session_factory() as db:
            rows = (
                await db.execute(
                    select(CoreTurnControl)
                    .where(CoreTurnControl.thread_id == thread_id)
                    .order_by(CoreTurnControl.updated_seq.desc())
                    .limit(max(1, int(limit)))
                )
            ).scalars().all()
        return [_turn_from_row(row) for row in rows]

    async def create_turn(self, turn: Turn) -> Turn:
        async def write(db: Any) -> Turn:
            existing = await db.get(CoreTurnControl, turn.turn_id)
            if existing is not None:
                return _turn_from_row(existing)
            db.add(_turn_row(turn))
            await db.flush()
            return turn

        return await self.write_coordinator.run(write)

    async def save_turn(self, turn: Turn) -> Turn:
        async def write(db: Any) -> Turn:
            row = await db.get(CoreTurnControl, turn.turn_id)
            values = _turn_values(turn)
            if row is None:
                db.add(_turn_row(turn))
                await db.flush()
                return turn
            for key, value in values.items():
                setattr(row, key, value)
            await db.flush()
            return turn

        return await self.write_coordinator.run(write)

    async def transition_turn(
        self,
        turn_id: str,
        *,
        expected_epoch: int,
        expected_status: str,
        status: str,
        event: str,
        active_run_id: str | None = None,
        waiting_reason: str | None = None,
        waiting_on: list[str] | None = None,
        error: dict[str, Any] | None = None,
        bump_epoch: bool = False,
    ) -> Turn | None:
        """Apply one transition with CAS on the epoch and current status."""

        async def write(db: Any) -> Turn | None:
            values: dict[str, Any] = {
                "status": status,
                "updated_seq": int(time.time() * 1_000_000),
                "updated_at": _now_datetime(),
            }
            if active_run_id is not None:
                values["active_run_id"] = active_run_id
            if waiting_reason is not None:
                values["waiting_reason"] = waiting_reason
            if waiting_on is not None:
                values["waiting_on_json"] = list(waiting_on)
            if error is not None:
                values["error_json"] = dict(error)
            if bump_epoch:
                values["epoch"] = CoreTurnControl.epoch + 1
            result = await db.execute(
                update(CoreTurnControl)
                .where(
                    CoreTurnControl.turn_id == turn_id,
                    CoreTurnControl.epoch == int(expected_epoch),
                    CoreTurnControl.status == expected_status,
                )
                .values(**values)
            )
            if result.rowcount != 1:
                return None
            await db.flush()
            row = await db.get(CoreTurnControl, turn_id)
            return _turn_from_row(row) if row is not None else None

        return await self.write_coordinator.run(write)

    async def update_turn_if_epoch(
        self,
        turn_id: str,
        *,
        expected_epoch: int,
        values: dict[str, Any],
    ) -> bool:
        allowed = {
            "active_run_id",
            "waiting_reason",
            "waiting_on_json",
            "input_json",
            "error_json",
            "updated_seq",
        }
        payload = {key: value for key, value in values.items() if key in allowed}
        if not payload:
            return True
        payload["updated_at"] = _now_datetime()

        async def write(db: Any) -> bool:
            result = await db.execute(
                update(CoreTurnControl)
                .where(
                    CoreTurnControl.turn_id == turn_id,
                    CoreTurnControl.epoch == int(expected_epoch),
                )
                .values(**payload)
            )
            return result.rowcount == 1

        return await self.write_coordinator.run(write)

    async def delete_turn(self, turn_id: str) -> None:
        async def write(db: Any) -> None:
            await db.execute(delete(CoreTurnControl).where(CoreTurnControl.turn_id == turn_id))

        await self.write_coordinator.run(write)

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------
    async def create_run(self, run: Run) -> Run:
        async def write(db: Any) -> Run:
            existing = await db.get(CoreTurnRun, run.run_id)
            if existing is not None:
                return _run_from_row(existing)
            db.add(_run_row(run))
            await db.flush()
            return run

        return await self.write_coordinator.run(write)

    async def get_run(self, run_id: str) -> Run | None:
        async with self.session_factory() as db:
            row = await db.get(CoreTurnRun, run_id)
        return _run_from_row(row) if row is not None else None

    async def list_runs(self, turn_id: str) -> list[Run]:
        async with self.session_factory() as db:
            rows = (
                await db.execute(
                    select(CoreTurnRun)
                    .where(CoreTurnRun.turn_id == turn_id)
                    .order_by(CoreTurnRun.attempt.asc())
                )
            ).scalars().all()
        return [_run_from_row(row) for row in rows]

    async def next_run_attempt(self, turn_id: str) -> int:
        async with self.session_factory() as db:
            value = (
                await db.execute(
                    select(func.coalesce(func.max(CoreTurnRun.attempt), 0)).where(
                        CoreTurnRun.turn_id == turn_id
                    )
                )
            ).scalar_one()
        return int(value) + 1

    async def update_run(
        self,
        run_id: str,
        *,
        status: str,
        epoch: int | None = None,
        error: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        values: dict[str, Any] = {"status": status, "updated_at": _now_datetime()}
        if epoch is not None:
            values["epoch"] = int(epoch)
        if error:
            values["error"] = str(error)[:1024]
        if metadata is not None:
            values["payload_json"] = dict(metadata)
        if status in {"completed", "failed", "cancelled", "paused"}:
            values["ended_at_ms"] = now_ms()

        async def write(db: Any) -> bool:
            result = await db.execute(
                update(CoreTurnRun).where(CoreTurnRun.run_id == run_id).values(**values)
            )
            return result.rowcount == 1

        return await self.write_coordinator.run(write)

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------
    async def get_interaction(self, interaction_id: str) -> Interaction | None:
        async with self.session_factory() as db:
            row = await db.get(CoreTurnInteraction, interaction_id)
        return _interaction_from_row(row) if row is not None else None

    async def find_interaction(
        self,
        thread_id: str,
        request_id: str,
    ) -> Interaction | None:
        request_id = str(request_id or "").strip()
        if not request_id:
            return None
        async with self.session_factory() as db:
            row = (
                await db.execute(
                    select(CoreTurnInteraction)
                    .where(
                        CoreTurnInteraction.thread_id == thread_id,
                        (
                            (CoreTurnInteraction.interaction_id == request_id)
                            | (CoreTurnInteraction.legacy_request_id == request_id)
                            | (CoreTurnInteraction.tool_call_id == request_id)
                        ),
                    )
                    .order_by(CoreTurnInteraction.created_seq.desc())
                    .limit(1)
                )
            ).scalars().first()
        return _interaction_from_row(row) if row is not None else None

    async def list_open_interactions(
        self,
        *,
        turn_id: str | None = None,
        thread_id: str | None = None,
        scope: str | None = None,
    ) -> list[Interaction]:
        conditions = [CoreTurnInteraction.status.in_(("open", "deferred", "processing"))]
        if turn_id:
            conditions.append(CoreTurnInteraction.turn_id == turn_id)
        if thread_id:
            conditions.append(CoreTurnInteraction.thread_id == thread_id)
        if scope:
            conditions.append(CoreTurnInteraction.scope == scope)
        async with self.session_factory() as db:
            rows = (
                await db.execute(
                    select(CoreTurnInteraction)
                    .where(*conditions)
                    .order_by(CoreTurnInteraction.created_seq.asc())
                )
            ).scalars().all()
        return [_interaction_from_row(row) for row in rows]

    async def list_interactions(
        self,
        thread_id: str,
        *,
        status: str | None = None,
        limit: int = 200,
    ) -> list[Interaction]:
        conditions = [CoreTurnInteraction.thread_id == thread_id]
        if status:
            conditions.append(CoreTurnInteraction.status == status)
        async with self.session_factory() as db:
            rows = (
                await db.execute(
                    select(CoreTurnInteraction)
                    .where(*conditions)
                    .order_by(CoreTurnInteraction.created_seq.desc())
                    .limit(max(1, int(limit)))
                )
            ).scalars().all()
        return [_interaction_from_row(row) for row in rows]

    async def list_expired_questions(self, *, now_ms_value: int | None = None) -> list[Interaction]:
        cutoff = int(now_ms_value if now_ms_value is not None else now_ms())
        async with self.session_factory() as db:
            rows = (
                await db.execute(
                    select(CoreTurnInteraction)
                    .where(
                        CoreTurnInteraction.kind == "question",
                        CoreTurnInteraction.status == "open",
                        CoreTurnInteraction.expires_at_ms > 0,
                        CoreTurnInteraction.expires_at_ms <= cutoff,
                    )
                    .order_by(CoreTurnInteraction.expires_at_ms.asc())
                )
            ).scalars().all()
        return [_interaction_from_row(row) for row in rows]

    async def create_interaction(self, interaction: Interaction) -> Interaction:
        async def write(db: Any) -> Interaction:
            existing = await db.get(CoreTurnInteraction, interaction.interaction_id)
            if existing is not None:
                return _interaction_from_row(existing)
            interaction.thread_id = str(
                interaction.thread_id or interaction.metadata.get("thread_id") or ""
            )
            if interaction.created_seq <= 0:
                # The decision pool is ordered by appearance, not by the
                # projection's event sequence. Assigning the next value inside
                # the single-writer transaction keeps two cards from the same
                # tick in their true delivery order and never reorders on an
                # update.
                current_max = await db.scalar(
                    select(
                        func.coalesce(
                            func.max(CoreTurnInteraction.created_seq), 0
                        )
                    ).where(
                        CoreTurnInteraction.thread_id == interaction.thread_id
                    )
                )
                interaction.created_seq = int(current_max or 0) + 1
            db.add(_interaction_row(interaction))
            await db.flush()
            return interaction

        return await self.write_coordinator.run(write)

    async def resolve_interaction(
        self,
        interaction_id: str,
        *,
        status: str,
        answer: InteractionAnswer | None = None,
        claim_token: str = "",
    ) -> Interaction | None:
        """CAS one open interaction to a terminal state.

        Returns ``None`` when another writer already resolved it, which is the
        idempotency boundary for double clicks and concurrent windows.
        """

        async def write(db: Any) -> Interaction | None:
            conditions = [
                CoreTurnInteraction.interaction_id == interaction_id,
                CoreTurnInteraction.status.in_(("open", "deferred", "processing")),
            ]
            if claim_token:
                conditions.append(
                    (CoreTurnInteraction.claim_token == "")
                    | (CoreTurnInteraction.claim_token == claim_token)
                )
            values: dict[str, Any] = {
                "status": status,
                "resolved_at": _now_datetime(),
                "resolved_seq": int(time.time() * 1_000_000),
            }
            if answer is not None:
                values["answer_json"] = answer.to_dict()
            if claim_token:
                values["claim_token"] = claim_token
            result = await db.execute(
                update(CoreTurnInteraction)
                .where(*conditions)
                .values(**values)
            )
            if result.rowcount != 1:
                return None
            await db.flush()
            row = await db.get(CoreTurnInteraction, interaction_id)
            return _interaction_from_row(row) if row is not None else None

        return await self.write_coordinator.run(write)

    async def defer_interactions(self, turn_id: str) -> int:
        async def write(db: Any) -> int:
            result = await db.execute(
                update(CoreTurnInteraction)
                .where(
                    CoreTurnInteraction.turn_id == turn_id,
                    CoreTurnInteraction.status == "open",
                )
                .values(status="deferred", claim_token="")
            )
            return int(result.rowcount or 0)

        return await self.write_coordinator.run(write)

    async def reopen_interactions(self, turn_id: str) -> int:
        async def write(db: Any) -> int:
            result = await db.execute(
                update(CoreTurnInteraction)
                .where(
                    CoreTurnInteraction.turn_id == turn_id,
                    CoreTurnInteraction.status == "deferred",
                )
                .values(status="open")
            )
            return int(result.rowcount or 0)

        return await self.write_coordinator.run(write)

    async def cancel_interactions(
        self,
        *,
        thread_id: str | None = None,
        turn_id: str | None = None,
        scope: str | None = None,
        scopes: tuple[str, ...] | None = None,
        reason: str = "turn_cancelled",
    ) -> list[Interaction]:
        """Cancel every open/deferred interaction matching the selector."""

        async def write(db: Any) -> list[Interaction]:
            conditions = [CoreTurnInteraction.status.in_(("open", "deferred", "processing"))]
            if thread_id:
                conditions.append(CoreTurnInteraction.thread_id == thread_id)
            if turn_id:
                conditions.append(CoreTurnInteraction.turn_id == turn_id)
            if scope:
                conditions.append(CoreTurnInteraction.scope == scope)
            if scopes:
                # user:“暂停关闭子问题”+关闭范围必须按卡片作用域收窄，
                # 否则父回合的暂停会把子代理仍要回答的问题一起关掉。
                conditions.append(CoreTurnInteraction.scope.in_(tuple(scopes)))
            rows = (
                await db.execute(select(CoreTurnInteraction).where(*conditions))
            ).scalars().all()
            resolved: list[Interaction] = []
            for row in rows:
                row.status = "cancelled"
                row.resolved_at = _now_datetime()
                row.resolved_seq = int(time.time() * 1_000_000)
                row.metadata_json = {
                    **dict(row.metadata_json or {}),
                    "cancel_reason": reason,
                }
                resolved.append(_interaction_from_row(row))
            await db.flush()
            return resolved

        return await self.write_coordinator.run(write)

    async def mark_interaction_processing(
        self,
        interaction_id: str,
        *,
        claim_token: str = "",
    ) -> Interaction | None:
        """Move a visible card to ``processing`` when the answer is accepted.

        Idempotent: an already-processing row is returned, a terminal row is
        left untouched (the caller then reports the terminal state), and the
        original ``created_seq`` is preserved so the decision pool never
        reorders on an update.
        """
        async def write(db: Any) -> Interaction | None:
            row = await db.get(CoreTurnInteraction, interaction_id)
            if row is None:
                return None
            if row.status in {"answered", "cancelled", "expired"}:
                return _interaction_from_row(row)
            if row.status != "processing":
                row.status = "processing"
            if claim_token:
                row.claim_token = claim_token
            await db.flush()
            return _interaction_from_row(row)

        return await self.write_coordinator.run(write)

    async def revert_interaction_processing(
        self, interaction_id: str
    ) -> Interaction | None:
        """Return a processing card to appearing when the answer was refused.

        Only a processing row may revert; a terminal row stays terminal.
        """
        async def write(db: Any) -> Interaction | None:
            row = await db.get(CoreTurnInteraction, interaction_id)
            if row is None or row.status != "processing":
                return _interaction_from_row(row) if row is not None else None
            row.status = "open"
            row.claim_token = ""
            await db.flush()
            return _interaction_from_row(row)

        return await self.write_coordinator.run(write)

    async def backfill_interaction_pool(
        self, thread_id: str, *, project_id: str = ""
    ) -> int:
        """Give legacy interaction rows a pool sequence and provenance.

        Older rows were created with ``created_seq=0`` and without project or
        delivery metadata. The pool order is repaired from ``created_at`` once;
        subsequent creates keep assigning the next value.
        """
        async def write(db: Any) -> int:
            rows = (
                await db.execute(
                    select(CoreTurnInteraction)
                    .where(CoreTurnInteraction.thread_id == thread_id)
                    .order_by(
                        CoreTurnInteraction.created_at.asc(),
                        CoreTurnInteraction.interaction_id.asc(),
                    )
                )
            ).scalars().all()
            max_seq = max((int(row.created_seq or 0) for row in rows), default=0)
            changed = 0
            for row in rows:
                metadata = dict(row.metadata_json or {})
                dirty = False
                if int(row.created_seq or 0) <= 0:
                    max_seq += 1
                    row.created_seq = max_seq
                    dirty = True
                if project_id and not metadata.get("project_id"):
                    metadata["project_id"] = project_id
                    dirty = True
                scope = str(row.scope or "main")
                if scope != "main":
                    if not metadata.get("agent_session_id"):
                        metadata["agent_session_id"] = scope.split(":", 1)[-1]
                        dirty = True
                    if not metadata.get("delivered_by"):
                        metadata["delivered_by"] = (
                            "agent:" + str(metadata.get("agent_session_id") or "")
                        )
                        dirty = True
                elif not metadata.get("delivered_by"):
                    metadata["delivered_by"] = "main"
                    dirty = True
                if dirty:
                    row.metadata_json = metadata
                    changed += 1
            if changed:
                await db.flush()
            return changed

        return await self.write_coordinator.run(write)

    async def set_interaction_claim(
        self,
        interaction_id: str,
        *,
        claim_token: str,
    ) -> bool:
        async def write(db: Any) -> bool:
            result = await db.execute(
                update(CoreTurnInteraction)
                .where(
                    CoreTurnInteraction.interaction_id == interaction_id,
                    CoreTurnInteraction.status.in_(("open", "deferred")),
                    (CoreTurnInteraction.claim_token == "")
                    | (CoreTurnInteraction.claim_token == claim_token),
                )
                .values(claim_token=claim_token)
            )
            return result.rowcount == 1

        return await self.write_coordinator.run(write)

    # ------------------------------------------------------------------
    # Control intents
    # ------------------------------------------------------------------
    async def append_intent(self, intent: ControlIntent) -> ControlIntent:
        async def write(db: Any) -> ControlIntent:
            existing = await db.get(CoreTurnIntent, intent.intent_id)
            if existing is not None:
                return _intent_from_row(existing)
            db.add(_intent_row(intent))
            await db.flush()
            return intent

        return await self.write_coordinator.run(write)

    async def update_intent(
        self,
        intent_id: str,
        *,
        status: str,
        error: str = "",
        applied_at_ms: int | None = None,
    ) -> bool:
        values: dict[str, Any] = {
            "status": status,
            "error": str(error or "")[:1024],
            "updated_at": _now_datetime(),
        }
        if applied_at_ms is not None:
            values["applied_at_ms"] = int(applied_at_ms)

        async def write(db: Any) -> bool:
            result = await db.execute(
                update(CoreTurnIntent)
                .where(CoreTurnIntent.intent_id == intent_id)
                .values(**values)
            )
            return result.rowcount == 1

        return await self.write_coordinator.run(write)

    async def list_pending_intents(self, turn_id: str) -> list[ControlIntent]:
        async with self.session_factory() as db:
            rows = (
                await db.execute(
                    select(CoreTurnIntent)
                    .where(
                        CoreTurnIntent.turn_id == turn_id,
                        CoreTurnIntent.status == "pending",
                    )
                    .order_by(CoreTurnIntent.created_at_ms.asc())
                )
            ).scalars().all()
        return [_intent_from_row(row) for row in rows]

    # ------------------------------------------------------------------
    # Continuation jobs
    # ------------------------------------------------------------------
    async def enqueue_job(
        self,
        *,
        thread_id: str,
        turn_id: str,
        run_id: str,
        kind: str,
        payload: dict[str, Any],
        idempotency_key: str,
        available_at_ms: int | None = None,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        now = int(available_at_ms if available_at_ms is not None else now_ms())

        async def write(db: Any) -> dict[str, Any]:
            existing = (
                await db.execute(
                    select(CoreTurnJob).where(CoreTurnJob.idempotency_key == idempotency_key)
                )
            ).scalars().first()
            if existing is not None:
                return _job_dict(existing)
            row = CoreTurnJob(
                job_id=job_id,
                thread_id=thread_id,
                turn_id=turn_id,
                run_id=run_id,
                kind=kind,
                payload_json=dict(payload),
                idempotency_key=idempotency_key,
                status="pending",
                attempts=0,
                available_at_ms=now,
                created_at_ms=now_ms(),
                updated_at=_now_datetime(),
            )
            db.add(row)
            await db.flush()
            return _job_dict(row)

        return await self.write_coordinator.run(write)

    async def claim_job(
        self, job_id: str, *, lease_ms: int = 60_000
    ) -> dict[str, Any] | None:
        """Atomically claim one named job.

        Returns ``None`` when another worker already owns it or it is already
        finished; the caller then waits for that owner's result instead of
        running the continuation twice.
        """
        now = now_ms()
        lease_until = now + max(1_000, int(lease_ms))

        async def write(db: Any) -> dict[str, Any] | None:
            result = await db.execute(
                update(CoreTurnJob)
                .where(
                    CoreTurnJob.job_id == job_id,
                    CoreTurnJob.status.in_(("pending", "running")),
                    CoreTurnJob.available_at_ms <= now,
                )
                .values(
                    status="running",
                    attempts=CoreTurnJob.attempts + 1,
                    available_at_ms=lease_until,
                    updated_at=_now_datetime(),
                )
            )
            if result.rowcount != 1:
                return None
            row = await db.get(CoreTurnJob, job_id)
            return _job_dict(row) if row is not None else None

        return await self.write_coordinator.run(write)

    async def requeue_running_jobs(self) -> int:
        """Release leases left by a previous process.

        Called once at startup: no worker from the old process can still own a
        running row, so waiting for its lease to expire would only delay the
        continuation.
        """
        async def write(db: Any) -> int:
            result = await db.execute(
                update(CoreTurnJob)
                .where(CoreTurnJob.status == "running")
                .values(
                    status="pending",
                    available_at_ms=now_ms(),
                    last_error="requeued after process restart",
                    updated_at=_now_datetime(),
                )
            )
            return int(result.rowcount or 0)

        return await self.write_coordinator.run(write)

    async def claim_next_job(
        self, thread_id: str, *, lease_ms: int = 60_000
    ) -> dict[str, Any] | None:
        now = now_ms()
        lease_until = now + max(1_000, int(lease_ms))

        async def write(db: Any) -> dict[str, Any] | None:
            row = (
                await db.execute(
                    select(CoreTurnJob)
                    .where(
                        CoreTurnJob.thread_id == thread_id,
                        CoreTurnJob.available_at_ms <= now,
                        CoreTurnJob.status.in_(("pending", "running")),
                    )
                    .order_by(CoreTurnJob.available_at_ms.asc(), CoreTurnJob.created_at_ms.asc())
                    .limit(1)
                )
            ).scalars().first()
            if row is None:
                return None
            if row.status == "running" and int(row.available_at_ms or 0) > now:
                # The current owner's lease is still valid.
                return None
            row.status = "running"
            row.attempts = int(row.attempts or 0) + 1
            # A running row keeps its lease in available_at_ms. If the process
            # dies between claim and finish, the next worker reclaims it once
            # the lease expires instead of leaving the continuation stranded.
            row.available_at_ms = lease_until
            row.updated_at = _now_datetime()
            await db.flush()
            return _job_dict(row)

        return await self.write_coordinator.run(write)

    async def finish_job(
        self,
        job_id: str,
        *,
        status: str,
        error: str = "",
        retry_after_ms: int = 0,
    ) -> bool:
        values: dict[str, Any] = {
            "status": status,
            "last_error": str(error or "")[:1024],
            "updated_at": _now_datetime(),
        }
        if status == "pending":
            values["available_at_ms"] = now_ms() + max(0, int(retry_after_ms))

        async def write(db: Any) -> bool:
            result = await db.execute(
                update(CoreTurnJob).where(CoreTurnJob.job_id == job_id).values(**values)
            )
            return result.rowcount == 1

        return await self.write_coordinator.run(write)

    async def list_pending_job_threads(self) -> list[str]:
        now = now_ms()
        async with self.session_factory() as db:
            rows = (
                await db.execute(
                    select(CoreTurnJob.thread_id)
                    .where(
                        CoreTurnJob.available_at_ms <= now,
                        CoreTurnJob.status.in_(("pending", "running")),
                    )
                    .distinct()
                )
            ).scalars().all()
        return [str(row) for row in rows]

    async def has_pending_jobs(self, thread_id: str) -> bool:
        """True while this thread still owns a claimable or leased job.

        ``pending`` jobs waiting for a retry count: the one-shot worker sleeps
        until their delay elapses instead of dropping them.
        """
        async with self.session_factory() as db:
            row = (
                await db.execute(
                    select(CoreTurnJob.job_id)
                    .where(
                        CoreTurnJob.thread_id == thread_id,
                        CoreTurnJob.status.in_(("pending", "running")),
                    )
                    .limit(1)
                )
            ).scalars().first()
        return row is not None

    async def settle_thread_jobs(
        self,
        thread_id: str,
        *,
        status: str = "cancelled",
        error: str = "",
        turn_id: str | None = None,
    ) -> int:
        """Close every open continuation job for a thread.

        Pause and terminate own the turn after they settle it. Leaving a
        claimed job ``pending`` made a later startup or resume replay an
        approval that the control path had already superseded.
        """
        async def write(db: Any) -> int:
            # user:“修 问题严重的话 就重新设计”+(暂停只结束目标回合的续跑工作，不能关闭新回合的任务)。
            result = await db.execute(
                update(CoreTurnJob)
                .where(
                    CoreTurnJob.thread_id == thread_id,
                    CoreTurnJob.status.in_(("pending", "running")),
                    *([CoreTurnJob.turn_id == turn_id] if turn_id else []),
                )
                .values(
                    status=status,
                    last_error=str(error or "")[:1024],
                    available_at_ms=now_ms(),
                    updated_at=_now_datetime(),
                )
            )
            return int(result.rowcount or 0)

        return await self.write_coordinator.run(write)

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as db:
            row = await db.get(CoreTurnJob, job_id)
        return _job_dict(row) if row is not None else None

    async def list_jobs(self, thread_id: str, *, status: str | None = None) -> list[dict[str, Any]]:
        conditions = [CoreTurnJob.thread_id == thread_id]
        if status:
            conditions.append(CoreTurnJob.status == status)
        async with self.session_factory() as db:
            rows = (
                await db.execute(
                    select(CoreTurnJob)
                    .where(*conditions)
                    .order_by(CoreTurnJob.created_at_ms.asc())
                )
            ).scalars().all()
        return [_job_dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Agent runs
    # ------------------------------------------------------------------
    async def upsert_agent_run(self, agent_run: AgentRun) -> AgentRun:
        async def write(db: Any) -> AgentRun:
            row = await db.get(CoreAgentRun, agent_run.agent_run_id)
            values = _agent_run_values(agent_run)
            if row is None:
                db.add(_agent_run_row(agent_run))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            await db.flush()
            return agent_run

        return await self.write_coordinator.run(write)

    async def get_agent_run(self, agent_run_id: str) -> AgentRun | None:
        async with self.session_factory() as db:
            row = await db.get(CoreAgentRun, agent_run_id)
        return _agent_run_from_row(row) if row is not None else None

    async def list_agent_runs(
        self,
        *,
        parent_turn_id: str | None = None,
        parent_thread_id: str | None = None,
        live_only: bool = False,
    ) -> list[AgentRun]:
        conditions: list[Any] = []
        if parent_turn_id:
            conditions.append(CoreAgentRun.parent_turn_id == parent_turn_id)
        if parent_thread_id:
            conditions.append(CoreAgentRun.parent_thread_id == parent_thread_id)
        if live_only:
            conditions.append(
                CoreAgentRun.status.in_(("running", "paused", "suspended", "interrupted"))
            )
        async with self.session_factory() as db:
            rows = (
                await db.execute(
                    select(CoreAgentRun)
                    .where(*conditions)
                    .order_by(CoreAgentRun.started_at_ms.asc())
                )
            ).scalars().all()
        return [_agent_run_from_row(row) for row in rows]


# ---------------------------------------------------------------------------
# Row conversion helpers
# ---------------------------------------------------------------------------


def _now_datetime() -> Any:
    from datetime import datetime

    return datetime.now()


def _turn_values(turn: Turn) -> dict[str, Any]:
    return {
        "thread_id": turn.thread_id,
        "status": turn.status,
        "epoch": int(turn.epoch),
        "active_run_id": turn.active_run_id,
        "waiting_reason": turn.waiting_reason,
        "waiting_on_json": list(turn.waiting_on),
        "created_seq": int(turn.created_seq),
        "updated_seq": int(turn.updated_seq),
        "input_json": dict(turn.input),
        "error_json": dict(turn.error),
        "updated_at": _now_datetime(),
    }


def _turn_row(turn: Turn) -> CoreTurnControl:
    return CoreTurnControl(turn_id=turn.turn_id, **_turn_values(turn))


def _turn_from_row(row: CoreTurnControl) -> Turn:
    return Turn(
        turn_id=str(row.turn_id),
        thread_id=str(row.thread_id),
        status=str(row.status),  # type: ignore[arg-type]
        epoch=int(row.epoch or 0),
        active_run_id=str(row.active_run_id or ""),
        waiting_reason=str(row.waiting_reason or ""),
        waiting_on=[str(item) for item in row.waiting_on_json or []],
        created_seq=int(row.created_seq or 0),
        updated_seq=int(row.updated_seq or 0),
        input=dict(row.input_json or {}),
        error=dict(row.error_json or {}),
    )


def _run_row(run: Run) -> CoreTurnRun:
    return CoreTurnRun(
        run_id=run.run_id,
        turn_id=run.turn_id,
        attempt=int(run.attempt),
        epoch=int(run.epoch),
        status=run.status,
        started_at_ms=int(run.started_at_ms),
        ended_at_ms=int(run.ended_at_ms),
        error=run.error,
        payload_json=dict(run.metadata),
        updated_at=_now_datetime(),
    )


def _run_from_row(row: CoreTurnRun) -> Run:
    return Run(
        run_id=str(row.run_id),
        turn_id=str(row.turn_id),
        attempt=int(row.attempt or 1),
        epoch=int(row.epoch or 0),
        status=str(row.status),  # type: ignore[arg-type]
        started_at_ms=int(row.started_at_ms or 0),
        ended_at_ms=int(row.ended_at_ms or 0),
        error=str(row.error or ""),
        metadata=dict(row.payload_json or {}),
    )


def _interaction_row(interaction: Interaction) -> CoreTurnInteraction:
    return CoreTurnInteraction(
        interaction_id=interaction.interaction_id,
        thread_id=str(interaction.thread_id or interaction.metadata.get("thread_id") or ""),
        turn_id=interaction.turn_id,
        run_id=interaction.run_id,
        scope=interaction.scope,
        kind=interaction.kind,
        status=interaction.status,
        tool_call_id=interaction.tool_call_id,
        legacy_request_id=interaction.legacy_request_id,
        title=interaction.title,
        body=interaction.body,
        context_text=interaction.context,
        facts_json=list(interaction.facts),
        options_json=[option.to_dict() for option in interaction.options],
        default_answer_json=dict(interaction.default_answer),
        answer_json=interaction.answer.to_dict() if interaction.answer else None,
        expires_at_ms=int(interaction.expires_at_ms),
        claim_token=interaction.claim_token,
        created_seq=int(interaction.created_seq),
        resolved_seq=int(interaction.resolved_seq),
        metadata_json={
            **dict(interaction.metadata),
            **(
                {"project_id": interaction.project_id}
                if interaction.project_id
                else {}
            ),
            **(
                {"agent_name": interaction.agent_name}
                if interaction.agent_name
                else {}
            ),
            **(
                {"agent_session_id": interaction.agent_session_id}
                if interaction.agent_session_id
                else {}
            ),
            **(
                {"delivered_by": interaction.delivered_by}
                if interaction.delivered_by
                else {}
            ),
        },
        created_at=_now_datetime(),
        resolved_at=None,
    )


def _interaction_from_row(row: CoreTurnInteraction) -> Interaction:
    return Interaction(
        interaction_id=str(row.interaction_id),
        turn_id=str(row.turn_id),
        thread_id=str(row.thread_id or ""),
        run_id=str(row.run_id or ""),
        scope=str(row.scope or "main"),
        kind=str(row.kind),  # type: ignore[arg-type]
        status=str(row.status),  # type: ignore[arg-type]
        tool_call_id=str(row.tool_call_id or ""),
        legacy_request_id=str(row.legacy_request_id or ""),
        title=str(row.title or ""),
        body=str(row.body or ""),
        context=str(row.context_text or ""),
        facts=[dict(item) for item in row.facts_json or [] if isinstance(item, dict)],
        options=[
            InteractionOption.from_dict(item)
            for item in row.options_json or []
            if isinstance(item, dict)
        ],
        default_answer=dict(row.default_answer_json or {}),
        answer=InteractionAnswer.from_dict(row.answer_json),
        expires_at_ms=int(row.expires_at_ms or 0),
        claim_token=str(row.claim_token or ""),
        created_seq=int(row.created_seq or 0),
        resolved_seq=int(row.resolved_seq or 0),
        metadata=dict(row.metadata_json or {}),
        project_id=str((row.metadata_json or {}).get("project_id") or ""),
        agent_name=str((row.metadata_json or {}).get("agent_name") or ""),
        agent_session_id=str(
            (row.metadata_json or {}).get("agent_session_id") or ""
        ),
        delivered_by=str(
            (row.metadata_json or {}).get("delivered_by") or "main"
        ),
    )


def _intent_row(intent: ControlIntent) -> CoreTurnIntent:
    return CoreTurnIntent(
        intent_id=intent.intent_id,
        thread_id=str(intent.payload.get("thread_id") or ""),
        turn_id=intent.turn_id,
        expected_epoch=int(intent.expected_epoch),
        kind=intent.kind,
        status=intent.status,
        payload_json=dict(intent.payload),
        created_at_ms=int(intent.created_at_ms or now_ms()),
        applied_at_ms=int(intent.applied_at_ms),
        error=intent.error,
        updated_at=_now_datetime(),
    )


def _intent_from_row(row: CoreTurnIntent) -> ControlIntent:
    return ControlIntent(
        intent_id=str(row.intent_id),
        turn_id=str(row.turn_id),
        expected_epoch=int(row.expected_epoch or 0),
        kind=str(row.kind),  # type: ignore[arg-type]
        status=str(row.status),  # type: ignore[arg-type]
        payload=dict(row.payload_json or {}),
        created_at_ms=int(row.created_at_ms or 0),
        applied_at_ms=int(row.applied_at_ms or 0),
        error=str(row.error or ""),
    )


def _job_dict(row: CoreTurnJob) -> dict[str, Any]:
    return {
        "job_id": str(row.job_id),
        "thread_id": str(row.thread_id),
        "turn_id": str(row.turn_id),
        "run_id": str(row.run_id or ""),
        "kind": str(row.kind),
        "payload": dict(row.payload_json or {}),
        "idempotency_key": str(row.idempotency_key),
        "status": str(row.status),
        "attempts": int(row.attempts or 0),
        "available_at_ms": int(row.available_at_ms or 0),
        "last_error": str(row.last_error or ""),
        "created_at_ms": int(row.created_at_ms or 0),
    }


def _agent_run_values(agent_run: AgentRun) -> dict[str, Any]:
    return {
        "parent_thread_id": str(agent_run.parent_thread_id or agent_run.metadata.get("parent_thread_id") or ""),
        "parent_turn_id": agent_run.parent_turn_id,
        "parent_run_id": agent_run.parent_run_id,
        "name": agent_run.name,
        "type": agent_run.type,
        "model_id": agent_run.model_id,
        "reasoning_level": agent_run.reasoning_level,
        "status": agent_run.status,
        "lease_until_ms": int(agent_run.lease_until_ms),
        "sub_session_id": agent_run.sub_session_id,
        "source_call_id": agent_run.source_call_id,
        "source_run_id": agent_run.source_run_id,
        "source_turn_id": agent_run.source_turn_id,
        "summary": agent_run.summary,
        "started_at_ms": int(agent_run.started_at_ms),
        "completed_at_ms": int(agent_run.completed_at_ms),
        "elapsed_ms": int(agent_run.elapsed_ms),
        "payload_json": dict(agent_run.metadata),
        "updated_at": _now_datetime(),
    }


def _agent_run_row(agent_run: AgentRun) -> CoreAgentRun:
    return CoreAgentRun(agent_run_id=agent_run.agent_run_id, **_agent_run_values(agent_run))


def _agent_run_from_row(row: CoreAgentRun) -> AgentRun:
    return AgentRun(
        agent_run_id=str(row.agent_run_id),
        parent_turn_id=str(row.parent_turn_id or ""),
        parent_thread_id=str(row.parent_thread_id or ""),
        parent_run_id=str(row.parent_run_id or ""),
        name=str(row.name or ""),
        type=str(row.type or "execute"),
        model_id=str(row.model_id or ""),
        reasoning_level=str(row.reasoning_level or ""),
        status=str(row.status),  # type: ignore[arg-type]
        lease_until_ms=int(row.lease_until_ms or 0),
        sub_session_id=str(row.sub_session_id or ""),
        source_call_id=str(row.source_call_id or ""),
        source_run_id=str(row.source_run_id or ""),
        source_turn_id=str(row.source_turn_id or ""),
        summary=str(row.summary or ""),
        started_at_ms=int(row.started_at_ms or 0),
        completed_at_ms=int(row.completed_at_ms or 0),
        elapsed_ms=int(row.elapsed_ms or 0),
        metadata=dict(row.payload_json or {}),
    )


__all__ = ["TurnStore", "new_run_id", "new_turn_id"]
