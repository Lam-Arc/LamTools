"""Durable, product-neutral Goal lifecycle."""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, runtime_checkable
import uuid

from lamtools_core.llm import ChatMessage, LLMRequest

from . import CompletionResult, RuntimeState


GoalStatus = Literal["pending", "active", "blocked", "completed", "failed", "cancelled"]
_TERMINAL_STATUSES: frozenset[GoalStatus] = frozenset({"completed", "failed", "cancelled"})
_ALLOWED_TRANSITIONS: dict[GoalStatus, frozenset[GoalStatus]] = {
    "pending": frozenset({"active", "blocked", "completed", "failed", "cancelled"}),
    "active": frozenset({"blocked", "completed", "failed", "cancelled"}),
    "blocked": frozenset({"active", "completed", "failed", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Goal:
    id: str
    thread_id: str
    objective: str
    completion_criteria: tuple[str, ...] = ()
    status: GoalStatus = "pending"
    status_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    revision: int = 1
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "objective": self.objective,
            "completion_criteria": list(self.completion_criteria),
            "status": self.status,
            "status_reason": self.status_reason,
            "metadata": deepcopy(self.metadata),
            "revision": self.revision,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@runtime_checkable
class GoalStore(Protocol):
    async def insert(self, goal: Goal) -> Goal: ...
    async def get(self, goal_id: str) -> Goal | None: ...
    async def list(self, *, thread_id: str | None = None, status: GoalStatus | None = None) -> list[Goal]: ...
    async def replace(self, goal: Goal, *, expected_revision: int) -> Goal: ...


class InMemoryGoalStore:
    def __init__(self) -> None:
        self._goals: dict[str, Goal] = {}

    async def insert(self, goal: Goal) -> Goal:
        if goal.id in self._goals:
            raise ValueError(f"Goal already exists: {goal.id}")
        self._goals[goal.id] = deepcopy(goal)
        return deepcopy(goal)

    async def get(self, goal_id: str) -> Goal | None:
        goal = self._goals.get(goal_id)
        return deepcopy(goal) if goal is not None else None

    async def list(self, *, thread_id: str | None = None, status: GoalStatus | None = None) -> list[Goal]:
        goals = [
            deepcopy(goal)
            for goal in self._goals.values()
            if (thread_id is None or goal.thread_id == thread_id)
            and (status is None or goal.status == status)
        ]
        return sorted(goals, key=lambda goal: (goal.created_at, goal.id))

    async def replace(self, goal: Goal, *, expected_revision: int) -> Goal:
        current = self._goals.get(goal.id)
        if current is None:
            raise LookupError(f"Goal not found: {goal.id}")
        if current.revision != expected_revision:
            raise RuntimeError(f"Goal revision conflict: {goal.id}")
        self._goals[goal.id] = deepcopy(goal)
        return deepcopy(goal)


class GoalManager:
    """Small lifecycle interface over any durable Goal adapter."""

    def __init__(self, store: GoalStore) -> None:
        self.store = store

    async def create(
        self,
        *,
        thread_id: str,
        objective: str,
        completion_criteria: list[str] | tuple[str, ...] = (),
        metadata: dict[str, Any] | None = None,
        goal_id: str = "",
    ) -> Goal:
        clean_thread = str(thread_id or "").strip()
        clean_objective = str(objective or "").strip()
        if not clean_thread:
            raise ValueError("thread_id is required")
        if not clean_objective:
            raise ValueError("goal objective is required")
        criteria = tuple(value for item in completion_criteria if (value := str(item or "").strip()))
        now = _utcnow()
        return await self.store.insert(Goal(
            id=str(goal_id or "").strip() or f"goal_{uuid.uuid4().hex}",
            thread_id=clean_thread,
            objective=clean_objective,
            completion_criteria=criteria,
            metadata=deepcopy(metadata or {}),
            created_at=now,
            updated_at=now,
        ))

    async def get(self, goal_id: str) -> Goal | None:
        return await self.store.get(str(goal_id or "").strip())

    async def list(self, *, thread_id: str | None = None, status: GoalStatus | None = None) -> list[Goal]:
        return await self.store.list(thread_id=thread_id, status=status)

    async def update(
        self,
        goal_id: str,
        *,
        objective: str | None = None,
        completion_criteria: list[str] | tuple[str, ...] | None = None,
        status: GoalStatus | None = None,
        status_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Goal:
        current = await self.store.get(str(goal_id or "").strip())
        if current is None:
            raise LookupError(f"Goal not found: {goal_id}")
        if current.status in _TERMINAL_STATUSES:
            if (
                (status is None or status == current.status)
                and objective is None
                and completion_criteria is None
                and status_reason is None
                and metadata is None
            ):
                return current
            raise ValueError(f"Goal is terminal and cannot be updated: {goal_id}")
        next_status = status or current.status
        if next_status != current.status and next_status not in _ALLOWED_TRANSITIONS[current.status]:
            raise ValueError(f"Invalid Goal transition: {current.status} -> {next_status}")
        next_objective = current.objective if objective is None else str(objective or "").strip()
        if not next_objective:
            raise ValueError("goal objective is required")
        criteria = current.completion_criteria
        if completion_criteria is not None:
            criteria = tuple(
                value for item in completion_criteria if (value := str(item or "").strip())
            )
        now = _utcnow()
        updated = replace(
            current,
            objective=next_objective,
            completion_criteria=criteria,
            status=next_status,
            status_reason=current.status_reason if status_reason is None else str(status_reason or "").strip(),
            metadata=deepcopy(current.metadata if metadata is None else metadata),
            revision=current.revision + 1,
            updated_at=now,
            completed_at=now if next_status == "completed" else current.completed_at,
        )
        return await self.store.replace(updated, expected_revision=current.revision)


GoalEvaluator = Callable[[Goal, dict[str, Any]], CompletionResult | Awaitable[CompletionResult]]


class GoalCompletionGate:
    """Binds one explicit Goal to Kernel's natural completion boundary."""

    def __init__(
        self,
        manager: GoalManager,
        goal_id: str | GoalEvaluator = "",
        evaluator: GoalEvaluator | None = None,
        *,
        max_repair_attempts: int = 10,
    ) -> None:
        if callable(goal_id) and evaluator is None:
            evaluator = goal_id
            goal_id = ""
        if evaluator is None:
            raise ValueError("Goal evaluator is required")
        self.manager = manager
        self.goal_id = str(goal_id or "").strip()
        self.evaluator = evaluator
        self.max_repair_attempts = max(1, max_repair_attempts)

    def should_verify(self, state: RuntimeState) -> bool:
        return bool(str(state.metadata.get("goal_id") or self.goal_id or "").strip())

    async def verify(self, state: RuntimeState, context: dict[str, Any]) -> CompletionResult:
        goal_id = str(state.metadata.get("goal_id") or self.goal_id or "").strip()
        if not goal_id:
            return CompletionResult(passed=True, summary="no goal bound")
        goal = await self.manager.get(goal_id)
        if goal is None:
            return CompletionResult(
                passed=False,
                blocked=True,
                summary=f"Goal not found: {goal_id}",
            )
        if goal.thread_id != state.session_id:
            return CompletionResult(
                passed=False,
                blocked=True,
                summary="Goal belongs to a different thread",
            )
        if goal.status == "completed":
            return CompletionResult(passed=True, summary=goal.status_reason or "goal completed")
        if goal.status in {"failed", "cancelled"}:
            return CompletionResult(
                passed=False,
                blocked=True,
                summary=goal.status_reason or f"goal is {goal.status}",
            )
        if goal.status in {"pending", "blocked"}:
            goal = await self.manager.update(goal.id, status="active", status_reason="")

        evaluated = self.evaluator(goal, {**context, "state": state})
        if inspect.isawaitable(evaluated):
            evaluated = await evaluated
        if not isinstance(evaluated, CompletionResult):
            raise TypeError("Goal evaluator must return CompletionResult")

        attempts_key = f"goal_completion_attempts:{goal.id}"
        attempts = int(state.metadata.get(attempts_key) or 0)
        result = evaluated
        if not evaluated.passed and not evaluated.blocked:
            attempts += 1
            state.metadata[attempts_key] = attempts
            if attempts >= self.max_repair_attempts:
                result = CompletionResult(
                    passed=False,
                    blocked=True,
                    summary=(
                        evaluated.summary
                        or f"Goal remains incomplete after {attempts} completion checks"
                    ),
                    checks=evaluated.checks,
                    repair_instruction=evaluated.repair_instruction,
                )
        elif evaluated.passed:
            state.metadata.pop(attempts_key, None)

        status: GoalStatus = "completed" if result.passed else "blocked" if result.blocked else "active"
        await self.manager.update(
            goal.id,
            status=status,
            status_reason=result.summary,
            metadata={
                **goal.metadata,
                "last_completion": result.to_dict(),
                "completion_attempts": attempts,
            },
        )
        return result


class ModelGoalEvaluator:
    """Uses the configured model only for explicitly Goal-bound turns."""

    def __init__(self, llm_client: Any, *, model_id: str = "") -> None:
        self.llm_client = llm_client
        self.model_id = str(model_id or "")

    async def __call__(self, goal: Goal, context: dict[str, Any]) -> CompletionResult:
        evidence = _completion_evidence(context)
        request = LLMRequest(
            model=self.model_id,
            temperature=0,
            max_tokens=600,
            response_format={"type": "json_object"},
            messages=[
                ChatMessage(
                    role="system",
                    content=(
                        "Evaluate whether the explicit goal is complete from the supplied evidence. "
                        "Do not infer unshown work. Return JSON only with status equal to complete, "
                        "continue, or blocked; summary; and repair_instruction. Use blocked only when "
                        "external input, permission, or unavailable evidence prevents progress."
                    ),
                ),
                ChatMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "goal": goal.to_dict(),
                            "evidence": evidence,
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                ),
            ],
        )
        response = await self.llm_client.complete(request)
        payload = _json_object(str(getattr(response, "content", "") or ""))
        if payload is None:
            return CompletionResult(
                passed=False,
                summary="Goal completion evaluation returned invalid JSON",
                repair_instruction="Continue the goal and retry its completion check",
            )
        status = str(payload.get("status") or "").strip().lower()
        summary = str(payload.get("summary") or "").strip()
        repair = str(payload.get("repair_instruction") or "").strip()
        if status == "complete":
            return CompletionResult(passed=True, summary=summary or "goal complete")
        if status == "continue":
            return CompletionResult(
                passed=False,
                summary=summary or "goal incomplete",
                repair_instruction=repair,
            )
        if status == "blocked":
            return CompletionResult(
                passed=False,
                blocked=True,
                summary=summary or "goal completion is blocked",
                repair_instruction=repair,
            )
        return CompletionResult(
            passed=False,
            summary=summary or "goal completion evaluator returned an invalid status",
            repair_instruction=repair or "Continue the goal and retry its completion check",
        )


def _completion_evidence(context: dict[str, Any]) -> dict[str, Any]:
    turn = context.get("turn")
    verification = context.get("verification")
    tool_results = context.get("tool_results")
    state = context.get("state")
    metadata = getattr(state, "metadata", {})
    kernel_steps = metadata.get("kernel_steps") if isinstance(metadata, dict) else None
    return {
        "final_reply": str(getattr(turn, "reply", "") or "")[-12000:],
        "verification": {
            "passed": bool(getattr(verification, "passed", False)),
            "summary": str(getattr(verification, "summary", "") or "")[-2000:],
        },
        "tool_results": [
            {
                "name": str(getattr(item, "name", "") or ""),
                "status": str(getattr(item, "status", "") or ""),
                "content": str(getattr(item, "content", "") or "")[-2000:],
                "error": str(getattr(item, "error", "") or "")[-1000:],
            }
            for item in (tool_results or [])[-20:]
        ],
        "recent_steps": deepcopy(kernel_steps[-12:]) if isinstance(kernel_steps, list) else [],
    }


def _json_object(content: str) -> dict[str, Any] | None:
    candidate = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
    try:
        value = json.loads(candidate)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


__all__ = [
    "Goal",
    "GoalCompletionGate",
    "GoalEvaluator",
    "GoalManager",
    "GoalStatus",
    "GoalStore",
    "InMemoryGoalStore",
    "ModelGoalEvaluator",
]
