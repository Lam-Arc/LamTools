"""Small member-facing contracts.

Members provide domain material. Core owns the runner, tools, events, and
snapshot shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from lamtools_core.tool import ToolSpec


@dataclass(frozen=True)
class PromptFragment:
    name: str
    content: str
    priority: int = 100
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationPolicy:
    """Member completion policy consumed by the shared runtime Kit.

    ``required`` establishes the minimum runtime invariant: a task cannot
    complete without a successful, non-empty tool observation. Members may
    narrow eligible tools or categories and tune attempts through metadata;
    semantic claim checks remain member-owned workflows.
    """

    name: str = "default"
    required: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemberLabels:
    display_name: str
    labels: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class MemberKit(Protocol):
    id: str
    display_name: str

    def prompt_fragments(self) -> list[PromptFragment]: ...
    def tool_specs(self) -> list[ToolSpec]: ...
    def verification_policy(self) -> VerificationPolicy: ...
    def labels(self) -> MemberLabels: ...


@dataclass
class StaticMemberKit:
    id: str
    display_name: str
    prompts: list[PromptFragment] = field(default_factory=list)
    tools: list[ToolSpec] = field(default_factory=list)
    verification: VerificationPolicy = field(default_factory=VerificationPolicy)
    member_labels: MemberLabels | None = None

    def prompt_fragments(self) -> list[PromptFragment]:
        return sorted(self.prompts, key=lambda item: item.priority)

    def tool_specs(self) -> list[ToolSpec]:
        return list(self.tools)

    def verification_policy(self) -> VerificationPolicy:
        return self.verification

    def labels(self) -> MemberLabels:
        return self.member_labels or MemberLabels(display_name=self.display_name)


__all__ = [
    "MemberKit",
    "MemberLabels",
    "PromptFragment",
    "StaticMemberKit",
    "VerificationPolicy",
]
