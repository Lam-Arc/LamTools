from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentCall:
    name: str
    task: str
    mode: str = "auto"
    clean: bool = False
    options: dict[str, Any] = field(default_factory=dict)
    parent_agent_id: str | None = None
    depth: int = 0
