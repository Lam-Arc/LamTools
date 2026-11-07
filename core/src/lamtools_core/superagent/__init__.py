"""Super-agent 能力（Source / Policy / Eval / Ticket / Assignment / Worktree / Outbox）。"""

from __future__ import annotations

from .effects import EffectAdapter, EffectOutbox
from .github import GithubCliAdapter, GithubError, PublishAdapter, PublishTarget
from .models import (
    Assignment,
    Decision,
    Effect,
    Mandate,
    SourceActor,
    SourceEvent,
    Ticket,
    TicketStage,
)
from .policy import PolicyConfig, PolicyGate, PolicyVerdict
from .prompt import REPORT_CONTRACT, build_ticket_prompt
from .service import (
    DefaultEvalEngine,
    EvalEngine,
    ExecutionPlan,
    HandleResult,
    SuperagentService,
)
from .store import (
    ConcurrentUpdate,
    InMemorySuperagentStore,
    RecordExists,
    SqlAlchemySuperagentStore,
    SuperagentStore,
)
from .worktree import WorktreeError, WorktreeManager

__all__ = [
    "Assignment",
    "ConcurrentUpdate",
    "Decision",
    "DefaultEvalEngine",
    "Effect",
    "EffectAdapter",
    "EffectOutbox",
    "EvalEngine",
    "ExecutionPlan",
    "GithubCliAdapter",
    "GithubError",
    "PublishAdapter",
    "PublishTarget",
    "HandleResult",
    "REPORT_CONTRACT",
    "build_ticket_prompt",
    "InMemorySuperagentStore",
    "Mandate",
    "PolicyConfig",
    "PolicyGate",
    "PolicyVerdict",
    "RecordExists",
    "SourceActor",
    "SourceEvent",
    "SqlAlchemySuperagentStore",
    "SuperagentService",
    "SuperagentStore",
    "Ticket",
    "TicketStage",
    "WorktreeError",
    "WorktreeManager",
]
