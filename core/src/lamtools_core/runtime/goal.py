"""Durable goal lifecycle: a model-controlled gate against stopping early.

The agent itself decides when a goal is done (archived), blocked, or
dropped; nothing here calls a model to judge completion.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, runtime_checkable
import uuid


GoalStatus = Literal["active", "blocked", "archived"]
_TERMINAL_STATUSES: frozenset[GoalStatus] = frozenset({"archived"})
_ALLOWED_TRANSITIONS: dict[GoalStatus, frozenset[GoalStatus]] = {
    "active": frozenset({"blocked", "archived"}),
    "blocked": frozenset({"active", "archived"}),
    "archived": frozenset(),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Goal:
    id: str
    thread_id: str
    objective: str
    completion_criteria: tuple[str, ...] = ()
    status: GoalStatus = "active"
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
        # user:“边界情况”+(一个会话同时只能有一个在跑的目标，否则续跑指向谁就说不清了；
        # 重复创建直接报错，让模型先把旧的收口，而不是留下一个永远没人管的目标)。
        live = [
            goal
            for goal in await self.store.list(thread_id=clean_thread)
            if goal.status != "archived"
        ]
        if live:
            raise ValueError(
                "A goal is already in progress in this thread: "
                f"{live[0].id}. Complete, block, or cancel it first."
            )
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
            completed_at=now if next_status == "archived" else current.completed_at,
        )
        return await self.store.replace(updated, expected_revision=current.revision)


__all__ = [
    "Goal",
    "GoalManager",
    "GoalStatus",
    "GoalStore",
    "InMemoryGoalStore",
]
