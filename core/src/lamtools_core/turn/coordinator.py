"""Single-writer turn state machine over the durable read model.

Every control request becomes a durable ``ControlIntent``.  The coordinator
applies it under a per-turn lock and bumps the turn epoch, so a stale run's
detached finalizer can no longer overwrite a newer decision.  The coordinator
does not execute models or tools; the app layer supplies those as hooks.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Awaitable, Callable

from lamtools_core.async_tasks import finish_on_cancel

from .model import (
    ControlIntent,
    Interaction,
    Run,
    Turn,
    can_transition,
    new_id,
    now_ms,
)
from .store import TurnStore

_logger = logging.getLogger(__name__)


@dataclass
class TurnHooks:
    """Actuators the coordinator calls after it has committed a transition."""

    pause_run: Callable[[Turn, str], Awaitable[None]] | None = None
    cancel_run: Callable[[Turn, bool], Awaitable[None]] | None = None
    start_run: Callable[[Turn, Run], Awaitable[None]] | None = None
    reopen_interactions: Callable[[Turn, list[Interaction]], Awaitable[None]] | None = None


def _atomic_control(operation):
    # user:“该修修，相关插件也要修”+(控制操作完整提交后才启动外部动作，避免半提交状态和事务内运行模型)。
    @wraps(operation)
    async def execute(self, *args, **kwargs):
        pending_hooks = []

        def defer(hook):
            if hook is None:
                return None

            async def record(*hook_args):
                pending_hooks.append((hook, hook_args))

            return record

        async def write(store):
            # A lock-contention retry reruns this callback. Only hooks from
            # the transaction that eventually commits may be activated.
            pending_hooks.clear()
            # A new scope shares the transaction's store, never the caller's
            # mutable store. Concurrent operations cannot inherit this session.
            scoped = TurnCoordinator(store, hooks=TurnHooks(
                pause_run=defer(self.hooks.pause_run),
                cancel_run=defer(self.hooks.cancel_run),
                start_run=defer(self.hooks.start_run),
                reopen_interactions=defer(self.hooks.reopen_interactions),
            ))
            return await operation(scoped, *args, **kwargs)

        turn_id = str(kwargs.get("turn_id") or (args[0] if args else ""))

        async def commit_and_actuate():
            async with self._lock(turn_id):
                result = await self.store.transaction(write)
                for hook, hook_args in pending_hooks:
                    await hook(*hook_args)
                return result

        return await finish_on_cancel(commit_and_actuate(), name=f"turn-control:{turn_id}")

    return execute


@dataclass
class TurnCoordinator:
    store: TurnStore
    hooks: TurnHooks = field(default_factory=TurnHooks)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict, repr=False)

    def _lock(self, turn_id: str) -> asyncio.Lock:
        lock = self._locks.get(turn_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[turn_id] = lock
        return lock

    @_atomic_control
    async def ensure_turn(
        self,
        *,
        thread_id: str,
        turn_id: str,
        input_payload: dict[str, Any] | None = None,
        status: str = "queued",
    ) -> Turn:
        turn = await self.store.get_turn(turn_id)
        if turn is not None:
            return turn
        return await self.store.create_turn(
            Turn(
                turn_id=turn_id,
                thread_id=thread_id,
                status=status,  # type: ignore[arg-type]
                epoch=0,
                created_seq=now_ms(),
                updated_seq=now_ms(),
                input=dict(input_payload or {}),
            )
        )

    @_atomic_control
    async def start_run(self, turn_id: str, run_id: str, *, epoch: int | None = None) -> Run | None:
        async with self._lock(turn_id):
            turn = await self.store.get_turn(turn_id)
            if turn is None or turn.terminal:
                return None
            if turn.status == "running":
                return await self.store.get_run(run_id)
            if turn.status != "queued":
                return None
            transitioned = await self.store.transition_turn(
                turn_id,
                expected_epoch=turn.epoch,
                expected_status="queued",
                status="running",
                event="run_started",
                active_run_id=run_id,
            )
            if transitioned is None:
                return None
            attempt = await self.store.next_run_attempt(turn_id)
            run = Run(
                run_id=run_id,
                turn_id=turn_id,
                attempt=attempt,
                epoch=int(transitioned.epoch if epoch is None else epoch),
                status="running",
                started_at_ms=now_ms(),
            )
            await self.store.create_run(run)
            if self.hooks.start_run is not None:
                await self.hooks.start_run(transitioned, run)
            return run

    @_atomic_control
    async def begin_resumed_run(self, turn_id: str, run_id: str) -> Run | None:
        """Start a new execution for a paused turn with caller-supplied id."""
        async with self._lock(turn_id):
            turn = await self.store.get_turn(turn_id)
            if turn is None or turn.status != "paused":
                return None
            transitioned = await self.store.transition_turn(
                turn_id,
                expected_epoch=turn.epoch,
                expected_status="paused",
                status="running",
                event="resume_applied",
                active_run_id=run_id,
                bump_epoch=True,
            )
            if transitioned is None:
                return None
            attempt = await self.store.next_run_attempt(turn_id)
            run = Run(
                run_id=run_id,
                turn_id=turn_id,
                attempt=attempt,
                epoch=transitioned.epoch,
                status="running",
                started_at_ms=now_ms(),
            )
            await self.store.create_run(run)
            if self.hooks.start_run is not None:
                await self.hooks.start_run(transitioned, run)
            return run

    @_atomic_control
    async def open_interactions(self, turn_id: str, interaction_ids: list[str]) -> Turn | None:
        async with self._lock(turn_id):
            turn = await self.store.get_turn(turn_id)
            if turn is None or turn.status != "running":
                return turn
            target = can_transition(turn.status, "interaction_opened")
            if target is None:
                return turn
            transitioned = await self.store.transition_turn(
                turn_id,
                expected_epoch=turn.epoch,
                expected_status=turn.status,
                status=target,
                event="interaction_opened",
                waiting_reason="interaction",
                waiting_on=list(interaction_ids),
                active_run_id="",
            )
            return transitioned

    @_atomic_control
    async def pause(self, turn_id: str, *, reason: str = "user_pause") -> Turn | None:
        async with self._lock(turn_id):
            turn = await self.store.get_turn(turn_id)
            if turn is None or turn.terminal:
                return turn
            intent = await self._intent(turn, "pause", {"reason": reason})
            if turn.status not in {"running", "waiting"}:
                await self._reject(intent, f"cannot pause from {turn.status}")
                return turn
            target = can_transition(turn.status, "pause_applied")
            transitioned = await self.store.transition_turn(
                turn_id,
                expected_epoch=turn.epoch,
                expected_status=turn.status,
                status=target or "paused",
                event="pause_applied",
                active_run_id="",
                bump_epoch=True,
            )
            if transitioned is None:
                await self._reject(intent, "state changed")
                return await self.store.get_turn(turn_id)
            deferred = await self.store.defer_interactions(turn_id)
            transitioned.waiting_reason = "user_pause"
            await self.store.save_turn(transitioned)
            await self._apply(intent)
            if self.hooks.pause_run is not None:
                await self.hooks.pause_run(transitioned, reason)
            return transitioned

    @_atomic_control
    async def resume(self, turn_id: str) -> tuple[Turn, Run | None] | None:
        async with self._lock(turn_id):
            turn = await self.store.get_turn(turn_id)
            if turn is None or turn.status != "paused":
                return None
            intent = await self._intent(turn, "resume", {})
            open_interactions = await self.store.list_open_interactions(turn_id=turn_id)
            target = "waiting" if open_interactions else "running"
            transitioned = await self.store.transition_turn(
                turn_id,
                expected_epoch=turn.epoch,
                expected_status="paused",
                status=target,
                event="resume_applied",
                waiting_reason="interaction" if open_interactions else "",
                waiting_on=[item.interaction_id for item in open_interactions],
                bump_epoch=True,
            )
            if transitioned is None:
                await self._reject(intent, "state changed")
                return None
            await self.store.reopen_interactions(turn_id)
            run: Run | None = None
            if target == "running":
                attempt = await self.store.next_run_attempt(turn_id)
                run = Run(
                    run_id=new_id(),
                    turn_id=turn_id,
                    attempt=attempt,
                    epoch=transitioned.epoch,
                    status="running",
                    started_at_ms=now_ms(),
                )
                await self.store.create_run(run)
                transitioned.active_run_id = run.run_id
                await self.store.save_turn(transitioned)
                if self.hooks.start_run is not None:
                    await self.hooks.start_run(transitioned, run)
            await self._apply(intent)
            if open_interactions and self.hooks.reopen_interactions is not None:
                await self.hooks.reopen_interactions(transitioned, open_interactions)
            return transitioned, run

    @_atomic_control
    async def cancel(self, turn_id: str, *, terminate: bool = False) -> Turn | None:
        async with self._lock(turn_id):
            turn = await self.store.get_turn(turn_id)
            if turn is None:
                return None
            if turn.terminal:
                return turn
            intent = await self._intent(turn, "terminate" if terminate else "cancel", {})
            target = can_transition(turn.status, "cancel_applied")
            if target is None:
                await self._reject(intent, f"cannot cancel from {turn.status}")
                return turn
            if turn.status == "running":
                transitioned = await self.store.transition_turn(
                    turn_id,
                    expected_epoch=turn.epoch,
                    expected_status="running",
                    status="stopping",
                    event="cancel_applied",
                    bump_epoch=True,
                )
                if transitioned is not None:
                    await self.store.cancel_interactions(
                        turn_id=turn_id, reason="turn_cancelled"
                    )
                    await self._apply(intent)
                    if self.hooks.cancel_run is not None:
                        await self.hooks.cancel_run(transitioned, terminate)
                    return transitioned
            # A waiting/paused/queued turn has no run to drain; close it now.
            transitioned = await self.store.transition_turn(
                turn_id,
                expected_epoch=turn.epoch,
                expected_status=turn.status,
                status="cancelled",
                event="cancel_settled",
                bump_epoch=True,
            )
            if transitioned is not None:
                await self.store.cancel_interactions(
                    turn_id=turn_id, reason="turn_cancelled"
                )
                await self._apply(intent)
                if self.hooks.cancel_run is not None:
                    await self.hooks.cancel_run(transitioned, terminate)
            return transitioned

    @_atomic_control
    async def settle_stopped(self, turn_id: str) -> Turn | None:
        """Move a draining ``stopping`` turn to its single terminal state."""
        async with self._lock(turn_id):
            turn = await self.store.get_turn(turn_id)
            if turn is None or turn.status != "stopping":
                return turn
            return await self.store.transition_turn(
                turn_id,
                expected_epoch=turn.epoch,
                expected_status="stopping",
                status="cancelled",
                event="run_ended",
                bump_epoch=True,
            )

    @_atomic_control
    async def finish_run(
        self,
        turn_id: str,
        run_id: str,
        *,
        status: str,
        error: str = "",
    ) -> Turn | None:
        """Apply a run result unless a newer control intent already won."""
        async with self._lock(turn_id):
            turn = await self.store.get_turn(turn_id)
            run = await self.store.get_run(run_id)
            if turn is None or run is None:
                return turn
            if turn.terminal or turn.status in {"paused", "stopping"}:
                # A pause/cancel intent owns the state; the run result must not
                # overwrite it. This is the epoch guard in practice.
                return turn
            if int(run.epoch) < int(turn.epoch):
                return turn
            target = "completed" if status == "completed" else "failed"
            transitioned = await self.store.transition_turn(
                turn_id,
                expected_epoch=turn.epoch,
                expected_status=turn.status,
                status=target,
                event="run_completed" if target == "completed" else "run_failed",
                active_run_id="",
                error={"message": error} if error else None,
            )
            await self.store.update_run(
                run_id,
                status=status,
                error=error,
                epoch=turn.epoch,
            )
            return transitioned

    @_atomic_control
    async def force_reset(self, turn_id: str) -> Turn | None:
        async with self._lock(turn_id):
            turn = await self.store.get_turn(turn_id)
            if turn is None:
                return None
            intent = await self._intent(turn, "force_reset", {})
            if turn.terminal:
                await self._apply(intent)
                return turn
            transitioned = await self.store.transition_turn(
                turn_id,
                expected_epoch=turn.epoch,
                expected_status=turn.status,
                status="cancelled",
                event="cancel_settled",
                bump_epoch=True,
            )
            await self.store.cancel_interactions(turn_id=turn_id, reason="force_reset")
            await self._apply(intent)
            return transitioned

    async def _intent(self, turn: Turn, kind: str, payload: dict[str, Any]) -> ControlIntent:
        return await self.store.append_intent(
            ControlIntent(
                intent_id=new_id(),
                turn_id=turn.turn_id,
                expected_epoch=turn.epoch,
                kind=kind,  # type: ignore[arg-type]
                payload={"thread_id": turn.thread_id, **payload},
                created_at_ms=now_ms(),
            )
        )

    async def _apply(self, intent: ControlIntent) -> None:
        await self.store.update_intent(
            intent.intent_id, status="applied", applied_at_ms=now_ms()
        )

    async def _reject(self, intent: ControlIntent, reason: str) -> None:
        _logger.warning(
            "[turn-coordinator] rejected %s for %s: %s",
            intent.kind,
            intent.turn_id,
            reason,
        )
        await self.store.update_intent(
            intent.intent_id, status="rejected", error=reason
        )


__all__ = ["TurnCoordinator", "TurnHooks"]
