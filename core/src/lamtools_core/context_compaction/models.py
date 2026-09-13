"""Data contracts for context compaction.

This module deliberately contains no planning, model calls, persistence, or
token-fitting logic.  The implementation modules depend on these small
contracts so the public compaction API remains stable while the pipeline is
split into focused components.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from lamtools_core.context_compaction_budget import SummaryTokenBudget
from lamtools_core.llm import ChatMessage, LLMClient
from lamtools_core.llm.policy import RetryPolicy
from lamtools_core.llm.retry import ModelRetrySink


COMPACTION_PREFIX = "[Compacted Context]"

COMPACTION_PROMPT = (
    "Compact for continuation.\n\n"
    f"Output format: the first line must be exactly {COMPACTION_PREFIX}.\n\n"
    "Required sections:\n"
    "1. Current Objective And Done Criteria\n"
    "2. Active User Instructions\n"
    "3. External Action Authorization\n"
    "4. Confirmed Facts And Decisions\n"
    "5. Current Execution State\n"
    "6. Verification Evidence\n"
    "7. Open Issues, Risks, And Hypotheses\n"
    "8. Rejected Or Superseded Directions\n"
    "9. Next Actions\n\n"
    "Rules:\n"
    "- Never invent state, permission, completion.\n"
    "- Preserve user requirements, corrections, and done criteria. The latest explicit user instruction wins; "
    "quote prohibitions and permissions.\n"
    "- Separate outcomes from external authorization; facts/evidence/done/not-done from plans/hypotheses. Put rejections in section 8.\n"
    "- Keep artifacts, results, errors, and approvals; order actions.\n"
    "- Use the user's language; keep headings.\n"
    "\n"
    "Output requirements:\n"
    "- Output ONLY the numbered sections above, in order, with their exact headings.\n"
    "- No preamble, no commentary, no markdown code fences, and no closing remarks.\n"
    "- Every section must be present; write \"None\" when a section has nothing to record."
)


_COMPACTION_SUMMARY_FIELDS = (
    "goals",
    "active_user_instructions",
    "external_action_authorization",
    "confirmed_facts_and_decisions",
    "current_execution_state",
    "verification_evidence",
    "open_issues_risks_and_hypotheses",
    "rejected_or_superseded_directions",
    "next_actions",
)
_COMPACTION_SUMMARY_TITLES = (
    "1. Current Objective And Done Criteria",
    "2. Active User Instructions",
    "3. External Action Authorization",
    "4. Confirmed Facts And Decisions",
    "5. Current Execution State",
    "6. Verification Evidence",
    "7. Open Issues, Risks, And Hypotheses",
    "8. Rejected Or Superseded Directions",
    "9. Next Actions",
)
_LEGACY_SUMMARY_TITLES = (
    "1. Current Goal",
    "2. User History, Instructions, And Decisions",
    "3. Completed Work",
    "4. Key Decisions And Constraints",
    "5. Files, APIs, Commands, And Results",
    "6. Open Issues Or Risks",
    "7. Next Best Actions",
    "8. Rejected Or Superseded Directions",
    "9. Next Actions",
)


@dataclass(slots=True)
class CompactionSummary:
    """Canonical internal representation of the nine-part summary contract."""

    goals: str = ""
    active_user_instructions: str = ""
    external_action_authorization: str = ""
    confirmed_facts_and_decisions: str = ""
    current_execution_state: str = ""
    verification_evidence: str = ""
    open_issues_risks_and_hypotheses: str = ""
    rejected_or_superseded_directions: str = ""
    next_actions: str = ""

    def render(self) -> str:
        """Render the canonical external text format, including its prefix."""
        sections = []
        for title, field_name in zip(_COMPACTION_SUMMARY_TITLES, _COMPACTION_SUMMARY_FIELDS):
            content = str(getattr(self, field_name) or "").strip() or "- None."
            sections.append(f"{title}\n{content}")
        return f"{COMPACTION_PREFIX}\n\n" + "\n\n".join(sections)


class ContextCompactionError(RuntimeError):
    """Raised when model-backed context compaction cannot produce a summary."""


class CompactionBudgetExceeded(ContextCompactionError):
    """Raised when required context cannot fit the compaction target."""

    def __init__(
        self,
        message: str,
        *,
        estimated_tokens: int = 0,
        target_tokens: int = 0,
    ) -> None:
        super().__init__(message)
        self.estimated_tokens = estimated_tokens
        self.target_tokens = target_tokens


CompactionDeltaSink = Callable[[str], Awaitable[None] | None]
CompactionEventSink = Callable[[dict[str, Any]], Awaitable[None] | None]
CompactionTokenEstimator = Callable[[list[ChatMessage]], int]


@dataclass(frozen=True, slots=True)
class CompactionOptions:
    """Per-invocation controls shared by automatic and manual compaction."""

    force: bool = False
    target_tokens: int | None = None
    compact_all: bool = False

    def __post_init__(self) -> None:
        if self.target_tokens is not None:
            if isinstance(self.target_tokens, bool) or self.target_tokens <= 0:
                raise ValueError("target_tokens must be positive when provided")


@dataclass(frozen=True)
class ContextCompactionRequest:
    """Input for the single Core context compaction interface."""

    trigger: str
    messages: list[ChatMessage]
    llm_client: LLMClient | None = None
    model: str = ""
    timeout: float | None = None
    limit_tokens: int = 4096
    input_limit_tokens: int = 0
    existing_summary: str = ""
    on_delta: CompactionDeltaSink | None = None
    on_event: CompactionEventSink | None = None
    preserve_latest_user: bool = True
    estimate_tokens: CompactionTokenEstimator | None = None
    estimate_exact_tokens: CompactionTokenEstimator | None = None
    summary_budget: SummaryTokenBudget | None = None
    model_retries: int = 1
    model_timeout_seconds: float | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    on_model_retry: ModelRetrySink | None = None
    options: CompactionOptions = field(default_factory=CompactionOptions)


@dataclass(frozen=True)
class ContextCompactionResult:
    """Output from context compaction, including replacement and display data."""

    status: str
    trigger: str
    summary: str = ""
    summary_message: ChatMessage | None = None
    prefix_messages: list[ChatMessage] = field(default_factory=list)
    compacted_messages: list[ChatMessage] = field(default_factory=list)
    retained_messages: list[ChatMessage] = field(default_factory=list)
    replacement_messages: list[ChatMessage] = field(default_factory=list)
    before_tokens: int = 0
    after_tokens: int = 0
    limit_tokens: int = 0
    segment_count: int = 0
    display_payload: dict[str, Any] = field(default_factory=dict)

    @property
    def compacted_count(self) -> int:
        return len(self.compacted_messages)

    @property
    def retained_count(self) -> int:
        return len(self.retained_messages)


@dataclass(slots=True)
class CompactionPlan:
    """Planner output separating prefix, summarized span, and recent tail."""

    system_prefix: list[ChatMessage]
    messages_to_summarize: list[ChatMessage]
    recent_messages: list[ChatMessage]

    @property
    def prefix_messages(self) -> list[ChatMessage]:
        """Compatibility name used by the pre-package controller."""
        return self.system_prefix

    @property
    def compacted_messages(self) -> list[ChatMessage]:
        """Compatibility name used by the pre-package controller."""
        return self.messages_to_summarize

    @property
    def retained_messages(self) -> list[ChatMessage]:
        """Compatibility name used by the pre-package controller."""
        return self.recent_messages


@dataclass(slots=True)
class CompactionFitInput:
    """Inputs to the bounded replacement-message fitter."""

    system_prefix: list[ChatMessage]
    summary_message: ChatMessage
    recent_messages: list[ChatMessage]
    target_tokens: int


@dataclass(slots=True)
class CompactionFitResult:
    """A replacement that the exact estimator proved fits its target."""

    messages: list[ChatMessage]
    estimated_tokens: int
    attempts: int
    strategy: str


__all__ = [
    "COMPACTION_PREFIX",
    "COMPACTION_PROMPT",
    "CompactionBudgetExceeded",
    "CompactionDeltaSink",
    "CompactionEventSink",
    "CompactionFitInput",
    "CompactionFitResult",
    "CompactionOptions",
    "CompactionPlan",
    "CompactionSummary",
    "CompactionTokenEstimator",
    "ContextCompactionError",
    "ContextCompactionRequest",
    "ContextCompactionResult",
]
