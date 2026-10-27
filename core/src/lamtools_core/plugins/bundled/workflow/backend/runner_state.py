"""Active workflow run records and process-wide coordination locks."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from lamtools_core.event.run_item import RunItemEvent
from .models import WorkflowDef, WorkflowNodeState
from .runner_context import WorkflowExecutionContext


_PROCESS_SIGNAL_LOCKS: dict[tuple[str, str, str], asyncio.Lock] = {}


_PROCESS_SIGNAL_LOCK_USERS: dict[tuple[str, str, str], int] = {}


_PROCESS_RUN_LOCKS: dict[tuple[str, str, str], asyncio.Lock] = {}


_PROCESS_RUN_LOCK_USERS: dict[tuple[str, str, str], int] = {}


@dataclass
class _ActiveWorkflowRun:
    """Mutable snapshot used to turn an external task cancel into a result."""

    workflow: WorkflowDef
    order: list[str]
    node_states: dict[str, WorkflowNodeState]
    values: dict[str, Any]
    inputs: dict[str, Any] = field(default_factory=dict)
    current_node_id: str = ""
    steps_taken: int = 0
    execution_context: WorkflowExecutionContext | None = None


def _claim_request_fingerprint(identity: Mapping[str, Any]) -> str:
    """Hash claim identity so durable coordination never stores resume secrets."""
    canonical = json.dumps(
        dict(identity), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _coordination_store_key(event_store: Any, snapshot_store: Any) -> str:
    parts: list[str] = []
    for store in (event_store, snapshot_store):
        if store is None:
            continue
        candidate = getattr(store, "directory", None) or getattr(store, "path", None)
        if candidate is not None:
            try:
                parts.append(str(Path(candidate).expanduser().resolve()))
            except OSError:
                parts.append(str(candidate))
        else:
            parts.append(f"object:{id(store)}")
    return "|".join(parts) or "unconfigured"


WorkflowEventCallback = Callable[[RunItemEvent], Awaitable[None] | None]
