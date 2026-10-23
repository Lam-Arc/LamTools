"""Turn-control domain: logical turns, runs, interactions and control intents.

The model is import-light on purpose: event projection, runtime ownership and
queue state import the status vocabulary from here, and loading the SQL/store
layer eagerly created an ``event -> turn -> store -> app -> event`` cycle.
Storage, orchestration and the worker are therefore resolved lazily.
"""

from __future__ import annotations

from importlib import import_module

from .model import (
    ACTIVE_TURN_STATUSES,
    BUSY_TURN_STATUSES,
    LIVE_RUNTIME_STATUSES,
    MAIN_SCOPE,
    SESSION_OWNING_STATUSES,
    TERMINAL_ITEM_STATUSES,
    TERMINAL_TURN_STATUSES,
    TURN_TRANSITIONS,
    AgentFact,
    AgentRun,
    ControlIntent,
    Fact,
    Interaction,
    InteractionAnswer,
    InteractionFact,
    InteractionOption,
    ItemFact,
    Run,
    Turn,
    TurnFact,
    agent_run_id_from_scope,
    agent_scope,
    can_transition,
    fact_from_payload,
    is_agent_scope,
    new_id,
    now_ms,
)

_LAZY_EXPORTS = {
    "TurnStore": ".store",
    "new_run_id": ".store",
    "new_turn_id": ".store",
    "TurnCoordinator": ".coordinator",
    "TurnHooks": ".coordinator",
    "TurnWorker": ".worker",
}

__all__ = [
    "ACTIVE_TURN_STATUSES",
    "BUSY_TURN_STATUSES",
    "LIVE_RUNTIME_STATUSES",
    "MAIN_SCOPE",
    "SESSION_OWNING_STATUSES",
    "TERMINAL_ITEM_STATUSES",
    "TERMINAL_TURN_STATUSES",
    "TURN_TRANSITIONS",
    "AgentFact",
    "AgentRun",
    "ControlIntent",
    "Fact",
    "Interaction",
    "InteractionAnswer",
    "InteractionFact",
    "InteractionOption",
    "ItemFact",
    "Run",
    "Turn",
    "TurnFact",
    "TurnHooks",
    "TurnStore",
    "TurnWorker",
    "TurnCoordinator",
    "agent_run_id_from_scope",
    "agent_scope",
    "can_transition",
    "fact_from_payload",
    "is_agent_scope",
    "new_id",
    "new_run_id",
    "new_turn_id",
    "now_ms",
]


def __getattr__(name: str):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value
