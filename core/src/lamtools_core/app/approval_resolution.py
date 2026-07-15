"""Core-owned lifecycle for resolving a claimed tool approval."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from lamtools_core.event import CoreEvent
from lamtools_core.llm import ChatMessage
from lamtools_core.runtime import RuntimeCheckpointStore, RuntimeState, RuntimeStateConflictError, RuntimeStateStore

from .operation_catalog import OperationResult


PersistRunItems = Callable[[list[Any]], Awaitable[dict[str, Any] | None]]
RunItemsFactory = Callable[[list[CoreEvent]], list[Any]]
SnapshotFactory = Callable[[list[CoreEvent]], dict[str, Any]]


@dataclass
class ApprovalResolutionLifecycle:
    """Enforces claim -> durable decision -> continue -> durable terminal ordering."""

    operation_name: str
    thread_id: str
    state: RuntimeState
    state_store: RuntimeStateStore
    request_id: str
    tool_call: dict[str, Any]
    decision: str
    guidance: str
    persist_run_items: PersistRunItems
    run_items_from_events: RunItemsFactory
    snapshot_from_events: SnapshotFactory
    decision_durable: bool = field(default=False, init=False)
    decision_event: CoreEvent = field(init=False)
    decision_run_items: list[Any] = field(default_factory=list, init=False)
    decision_snapshot: dict[str, Any] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.decision_event = self.approval_response_event()

    def approval_response_event(self) -> CoreEvent:
        payload = {
            "request_id": self.request_id,
            "tool_call_id": str(self.tool_call.get("id") or ""),
            "decision": self.decision,
            "action": self.decision,
            "guidance": self.guidance,
            "status": "resolved",
        }
        return CoreEvent(
            name="runtime.approval_response",
            category="decision",
            payload=payload,
            event_id=_stable_event_id(self.thread_id, self.request_id, "decision"),
            session_id=self.thread_id,
            run_id=self.state.run_id,
            tags=["approval", "resolved"],
        )

    async def persist_decision(self) -> OperationResult | None:
        self.decision_run_items = self.run_items_from_events([self.decision_event])
        try:
            snapshot = await self.persist_run_items(self.decision_run_items)
        except BaseException as exc:
            return await self._restore_retryable_pending(exc)
        self.decision_durable = True
        self.decision_snapshot = snapshot or self.snapshot_from_events([self.decision_event])
        return None

    async def clear_pending_for_execution(self) -> None:
        self._require_durable_decision()
        candidate = deepcopy(self.state)
        self._clear_pending(candidate)
        self._set_resolution_metadata(candidate, phase="continuing", recoverable=False)
        await self._commit_state(candidate)

    async def persist_tool_history(self, tool_history: ChatMessage) -> None:
        candidate = deepcopy(self.state)
        await self._commit_state(candidate, tool_history=tool_history)

    async def finalize_cancelled(self) -> OperationResult:
        self._require_durable_decision()
        candidate = deepcopy(self.state)
        self._clear_pending(candidate)
        candidate.status = "cancelled"
        candidate.loop_state = "failed"
        self._set_resolution_metadata(candidate, phase="terminal_pending", recoverable=True)
        await self._commit_state(candidate)
        terminal_events = [
            CoreEvent(
                name="runtime.cancelled",
                category="lifecycle",
                payload={"message": "approval denied", "decision": "denied"},
                session_id=self.thread_id,
                run_id=self.state.run_id,
                tags=["terminal", "cancelled"],
            ),
        ]
        return await self._persist_terminal_events(
            terminal_events,
            status="ok",
            decision="denied",
            message="approval denied",
        )

    async def finalize_failure(
        self,
        exc: BaseException | str,
        *,
        tool_event: CoreEvent | None = None,
        tool_history: ChatMessage | None = None,
    ) -> OperationResult:
        if not self.decision_durable:
            return await self._restore_retryable_pending(exc)

        reason = _failure_reason(exc)
        candidate = deepcopy(self.state)
        self._clear_pending(candidate)
        candidate.status = "failed"
        candidate.loop_state = "failed"
        self._set_resolution_metadata(
            candidate,
            phase="terminal_pending",
            recoverable=True,
            error=reason,
        )
        await self._commit_state(candidate, tool_history=tool_history)
        failure_event = tool_event or self._failed_tool_event(reason)
        if tool_event is not None:
            metadata = tool_event.payload.get("metadata")
            tool_event.payload["metadata"] = {
                **(metadata if isinstance(metadata, dict) else {}),
                "failure_reason": reason,
            }
        terminal_events = [failure_event]
        terminal_events.append(
            CoreEvent(
                name="runtime.failed",
                category="lifecycle",
                payload={
                    "error": reason,
                    "failure_reason": reason,
                    "decision": "approval_resolution_failed",
                },
                session_id=self.thread_id,
                run_id=self.state.run_id,
                tags=["terminal", "failed"],
            )
        )
        return await self._persist_terminal_events(
            terminal_events,
            status="error",
            decision="failed",
            message=reason,
        )

    async def _restore_retryable_pending(self, exc: BaseException | str) -> OperationResult:
        reason = _failure_reason(exc)
        candidate = deepcopy(self.state)
        pending = candidate.metadata.get("pending_approval")
        if isinstance(pending, dict):
            retryable_pending = dict(pending)
            retryable_pending["status"] = "waiting"
            retryable_pending.pop("decision", None)
            candidate.metadata["pending_approval"] = retryable_pending
        candidate.status = "waiting"
        candidate.loop_state = "wait"
        self._set_resolution_metadata(
            candidate,
            phase="decision_persistence_failed",
            recoverable=True,
            error=reason,
        )
        await self._commit_state(candidate)
        return OperationResult(
            name=self.operation_name,
            status="error",
            payload={
                "thread_id": self.thread_id,
                "decision": "retryable",
                "message": reason,
                "error": reason,
            },
        )

    async def _persist_terminal_events(
        self,
        events: list[CoreEvent],
        *,
        status: str,
        decision: str,
        message: str,
    ) -> OperationResult:
        terminal_run_items = self.run_items_from_events(events)
        try:
            snapshot = await self.persist_run_items(terminal_run_items)
        except BaseException as exc:
            return await self._terminal_persistence_failed(exc, message=message)
        if snapshot is None:
            snapshot = self.snapshot_from_events([self.decision_event, *events])
        return OperationResult(
            name=self.operation_name,
            status=status,
            payload={
                "thread_id": self.thread_id,
                "run_id": self.state.run_id,
                "decision": decision,
                "message": message,
                "run_items": [item.to_dict() for item in [*self.decision_run_items, *terminal_run_items]],
                "snapshot": snapshot,
            },
        )

    async def _terminal_persistence_failed(
        self,
        exc: BaseException | str,
        *,
        message: str,
    ) -> OperationResult:
        reason = _failure_reason(exc)
        candidate = deepcopy(self.state)
        self._clear_pending(candidate)
        self._set_resolution_metadata(
            candidate,
            phase="terminal_persistence_failed",
            recoverable=True,
            error=reason,
        )
        await self._commit_state(candidate)
        return OperationResult(
            name=self.operation_name,
            status="error",
            payload={
                "thread_id": self.thread_id,
                "decision": "failed",
                "message": message or reason,
                "error": reason,
                "run_items": [item.to_dict() for item in self.decision_run_items],
                "snapshot": self.decision_snapshot or self.snapshot_from_events([self.decision_event]),
            },
        )

    async def _commit_state(self, candidate: RuntimeState, *, tool_history: ChatMessage | None = None) -> None:
        try:
            await self._save_state_once(candidate, tool_history=tool_history)
        except RuntimeStateConflictError:
            latest = await self.state_store.get(self.thread_id)
            if latest is None:
                raise
            latest.metadata = deepcopy(candidate.metadata)
            latest.status = candidate.status
            latest.loop_state = candidate.loop_state
            candidate = latest
            await self._save_state_once(candidate, tool_history=tool_history)
        self.state = candidate

    async def _save_state_once(self, state: RuntimeState, *, tool_history: ChatMessage | None) -> None:
        if tool_history is not None and isinstance(self.state_store, RuntimeCheckpointStore):
            history = await self.state_store.get_history(self.thread_id)
            history.append(tool_history.to_dict())
            await self.state_store.save_checkpoint(state, history)
            return
        await self.state_store.save(state)

    def _set_resolution_metadata(
        self,
        state: RuntimeState,
        *,
        phase: str,
        recoverable: bool,
        error: str = "",
    ) -> None:
        state.metadata["approval_resolution"] = {
            "request_id": self.request_id,
            "decision": self.decision,
            "phase": phase,
            "recoverable": recoverable,
            **({"error": error} if error else {}),
        }

    def _failed_tool_event(self, reason: str) -> CoreEvent:
        return CoreEvent(
            name="runtime.tool.finished",
            category="tool",
            payload={
                "tool_name": str(self.tool_call.get("name") or ""),
                "call_id": str(self.tool_call.get("id") or ""),
                "status": "failed",
                "content": "",
                "error": reason,
                "metadata": {"failure_reason": reason},
            },
            session_id=self.thread_id,
            run_id=self.state.run_id,
            tags=["tool", "failed"],
        )

    def _require_durable_decision(self) -> None:
        if not self.decision_durable:
            raise RuntimeError("approval decision is not durable")

    @staticmethod
    def _clear_pending(state: RuntimeState) -> None:
        state.metadata.pop("pending_approval", None)
        state.metadata.pop("pending_waiting_request", None)


def _failure_reason(exc: BaseException | str) -> str:
    reason = str(exc).strip()
    return reason or type(exc).__name__


def _stable_event_id(thread_id: str, request_id: str, suffix: str) -> str:
    digest = hashlib.sha256(f"{thread_id}:{request_id}:{suffix}".encode("utf-8")).hexdigest()
    return digest[:32]


__all__ = ["ApprovalResolutionLifecycle"]
