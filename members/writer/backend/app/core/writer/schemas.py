from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# --- Action Types (8 MVP tools + meta actions) ---

WriterActionType = Literal[
    "read_file",
    "write_file",
    "edit_file",
    "run_command",
    "search_content",
    "search_files",
    "load_skill",
    "web_search",
    "git_status",
    "git_diff",
    "list_dir",
    "web_fetch",
    "run_tests",
    "inspect_project",
    "browser_check",
    "write_checklist",
    "update_checklist",
    "verify_design",
    "sub_agent",
    "mcp_tool",
]


# --- Runtime Phases ---

WriterPhase = Literal[
    "idle",
    "exploring",
    "planning",
    "executing",
    "verifying",
    "reviewing",
    "waiting",
    "teaching",
    "discussing",
    "brainstorming",
    "completed",
    "failed",
    "error",
]

# Loop positions: conditional cycle replacing linear phase chain
# Each position has entry/exit conditions driven by task complexity
WriterLoopPosition = Literal["plan", "execute", "verify", "idle"]

# Task complexity levels — set by _assess_task_complexity
TaskComplexity = Literal["simple", "moderate", "complex"]

# Planning depth — replaces boolean enforce_planning with 3 levels
PlanningDepth = Literal["none", "light", "full"]

WriterInteractionMode = Literal["EXECUTE"]
"""Writer interaction mode — unified single-mode agent (OpenAI-style)."""


# --- Part Types ---

WriterPartType = Literal[
    "text",
    "tool_call",
    "tool_result",
    "file_diff",
    "test_result",
    "build_output",
    "command_output",
    "plan",
    "todo_update",
    "error",
]


# --- Part Status ---

WriterPartStatus = Literal[
    "pending",
    "running",
    "completed",
    "error",
]



# --- Workflow Phases ---

WriterWorkflowPhase = Literal[
    "none",
    "ideation",
    "outlining",
    "drafting",
    "revising",
    "polishing",
]

# --- Output Types ---

WriterOutputType = Literal[
    "text",
    "reply",
    "email",
    "document",
    "code",
    "report",
    "outline",
]


# --- Runtime Status ---

WriterStatus = Literal[
    "running",
    "paused",
    "done",
    "error",
]


# --- Permission Tiers ---

PermissionTier = Literal[
    "auto_allow",
    "ask_user",
    "hard_block",
]


# --- Core Models ---


class WriterAction(BaseModel):
    """A single action the Writer wants to take."""
    action_type: WriterActionType
    description: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    permission_tier: PermissionTier = "ask_user"
    approved: bool | None = None  # None = not yet decided


class WriterPart(BaseModel):
    """A part of a Writer message — text, tool call, tool result, etc."""
    part_type: WriterPartType
    status: WriterPartStatus = "pending"
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    # For tool calls
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    # For tool results
    tool_result: str | None = None
    tool_error: str | None = None
    # Timing
    started_at: datetime | None = None
    completed_at: datetime | None = None


class WriterTurn(BaseModel):
    """A complete turn from the Writer — one LLM response with actions."""
    text: str = ""
    reply: list[str] = Field(default_factory=list)
    actions: list[WriterAction] = Field(default_factory=list)
    parts: list[WriterPart] = Field(default_factory=list)
    phase: WriterPhase = "idle"
    mode: WriterInteractionMode = "EXECUTE"
    is_complete: bool = False  # True = Writer is done, break the while loop
    needs_user_input: bool = False  # True = Writer wants user input before continuing
    next_phase: WriterPhase | None = None
    output_type: WriterOutputType = "text"
    output_meta: dict[str, Any] = Field(default_factory=dict)


class WriterSessionState(BaseModel):
    """Persistent state for a Writer session."""
    model_config = {"arbitrary_types_allowed": True}

    session_id: str
    work_root: str = ""
    branch: str | None = None
    phase: WriterPhase = "idle"
    mode: WriterInteractionMode = "EXECUTE"
    workflow_phase: WriterWorkflowPhase = "none"
    workflow_data: dict[str, Any] = Field(default_factory=dict)
    todos: list[dict[str, Any]] = Field(default_factory=list)
    open_loops: list[str] = Field(default_factory=list)
    context_summary: str = ""
    turn_count: int = 0
    error_count: int = 0
    last_action_type: WriterActionType | None = None
    # W2: 强制计划阶段
    task_plan: TaskPlan | None = None  # Structured plan, must be confirmed before execution
    enforce_planning: bool = True  # legacy — use planning_depth instead
    planning_depth: PlanningDepth | None = None  # None means derive from enforce_planning
    task_complexity: TaskComplexity = "simple"
    loop_position: WriterLoopPosition = "execute"  # When True, must go through planning before execution
    # W4: 迷失检测
    turns_without_output: int = 0  # Consecutive turns without write_file/run_command
    total_reads_this_session: int = 0  # Total read operations this session
    total_writes_this_session: int = 0  # Total write operations this session
    last_output_turn: int = 0  # Turn number of last productive output
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    locked_context: dict[str, str] = Field(default_factory=dict)  # W8: Anchored key-value pairs that survive compaction
    pending_decision_points: dict[str, Any] = Field(default_factory=dict)
    decision_history: list[dict[str, Any]] = Field(default_factory=list)
    git_state: dict[str, Any] = Field(default_factory=dict)
    git_history: list[dict[str, Any]] = Field(default_factory=list)
    session_memory: dict[str, Any] = Field(default_factory=dict)
    quality_mode: str = "auto"

    @property
    def effective_planning_depth(self) -> PlanningDepth:
        """Resolve planning_depth: if explicitly set, use it; otherwise derive from enforce_planning."""
        if self.planning_depth is not None:
            return self.planning_depth
        return "full" if self.enforce_planning else "none"

    # --- DB row conversion helpers ---

    @classmethod
    def from_session(cls, session: Any) -> WriterSessionState:
        """Construct WriterSessionState from a WriterSession DB row.

        Fields that map directly to DB columns are read from the row.
        Fields stored in the runtime_state JSON blob are extracted from it.
        """
        runtime_state = session.runtime_state or {}
        task_plan_raw = session.task_plan

        # Deserialize task_plan from dict if present
        task_plan: TaskPlan | None = None
        if task_plan_raw and isinstance(task_plan_raw, dict):
            task_plan = TaskPlan(**task_plan_raw)

        return cls(
            session_id=session.id,
            work_root=session.work_root or "",
            branch=session.branch,
            phase=session.phase or "idle",
            mode=session.mode or "EXECUTE",
            workflow_phase=runtime_state.get("workflow_phase", "none"),
            workflow_data=runtime_state.get("workflow_data", {}),
            todos=session.todos or [],
            open_loops=session.open_loops or [],
            context_summary=session.context_summary or "",
            turn_count=session.turn_count or 0,
            error_count=session.error_count or 0,
            last_action_type=runtime_state.get("last_action_type"),
            task_plan=task_plan,
            enforce_planning=runtime_state.get("enforce_planning", True),
            planning_depth=session.planning_depth,
            task_complexity=session.task_complexity or "simple",
            loop_position=session.loop_position or "execute",
            turns_without_output=runtime_state.get("turns_without_output", 0),
            total_reads_this_session=runtime_state.get("total_reads_this_session", 0),
            total_writes_this_session=runtime_state.get("total_writes_this_session", 0),
            last_output_turn=runtime_state.get("last_output_turn", 0),
            created_at=session.created_at or datetime.now(),
            updated_at=session.updated_at or datetime.now(),
            locked_context=runtime_state.get("locked_context", {}),
            pending_decision_points=runtime_state.get("pending_decision_points", {}),
            decision_history=runtime_state.get("decision_history", []),
            git_state=runtime_state.get("git_state", {}),
            git_history=runtime_state.get("git_history", []),
            session_memory=runtime_state.get("session_memory", {}),
            quality_mode=runtime_state.get("quality_mode", "auto"),
        )

    def to_session_updates(self) -> dict[str, Any]:
        """Return a dict of DB column updates from this state.

        Top-level fields map directly to WriterSession columns.
        Everything else goes into the runtime_state JSON blob.
        """
        return {
            "work_root": self.work_root,
            "branch": self.branch,
            "phase": self.phase,
            "mode": self.mode,
            "todos": self.todos,
            "open_loops": self.open_loops,
            "context_summary": self.context_summary,
            "loop_position": self.loop_position,
            "task_complexity": self.task_complexity,
            "planning_depth": self.planning_depth,
            "turn_count": self.turn_count,
            "error_count": self.error_count,
            "task_plan": self.task_plan.model_dump(mode="json") if self.task_plan else None,
            "runtime_state": self._json_safe(self._runtime_state_dict()),
        }

    def _runtime_state_dict(self) -> dict[str, Any]:
        """Return fields stored in the runtime_state JSON blob.

        These are rarely-queried fields that don't need their own DB columns.
        """
        return {
            "workflow_phase": self.workflow_phase,
            "workflow_data": self.workflow_data,
            "last_action_type": self.last_action_type,
            "enforce_planning": self.enforce_planning,
            "turns_without_output": self.turns_without_output,
            "total_reads_this_session": self.total_reads_this_session,
            "total_writes_this_session": self.total_writes_this_session,
            "last_output_turn": self.last_output_turn,
            "locked_context": self.locked_context,
            "pending_decision_points": self.pending_decision_points,
            "decision_history": self.decision_history,
            "git_state": self.git_state,
            "git_history": self.git_history,
            "session_memory": self.session_memory,
            "quality_mode": self.quality_mode,
        }

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {k: WriterSessionState._json_safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [WriterSessionState._json_safe(v) for v in value]
        if isinstance(value, tuple):
            return [WriterSessionState._json_safe(v) for v in value]
        if hasattr(value, "model_dump"):
            return WriterSessionState._json_safe(value.model_dump(mode="json"))
        return value

    model_config = {"arbitrary_types_allowed": True}


class WriterArtifact(BaseModel):
    """Metadata about a file change or artifact produced by the Writer."""
    artifact_type: Literal["file_create", "file_edit", "file_delete", "command_output", "test_result"]
    path: str
    description: str = ""
    diff: str | None = None
    content_before: str | None = None
    content_after: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WriterToolResult(BaseModel):
    """Result from executing a tool."""
    success: bool
    output: str = ""
    error: str | None = None
    artifacts: list[WriterArtifact] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# --- Task Plan Models (W2: 强制计划阶段) ---


class TaskPlanStep(BaseModel):
    """A single step in a task plan."""
    step_id: str = ""  # Auto-generated
    description: str = ""
    deliverables: list[str] = Field(default_factory=list)  # Files to create
    acceptance_criteria: list[str] = Field(default_factory=list)  # How to verify
    depends_on: list[str] = Field(default_factory=list)  # Step IDs this depends on
    status: Literal["pending", "in_progress", "completed", "failed", "skipped"] = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure_reason: str = ""  # Populated when status="failed"

    def mark_failed(self, reason: str) -> None:
        """Mark this step as failed with a reason."""
        self.status = "failed"
        self.failure_reason = reason
        self.completed_at = datetime.now()

    def mark_completed(self) -> None:
        """Mark this step as completed."""
        self.status = "completed"
        self.completed_at = datetime.now()

    def mark_in_progress(self) -> None:
        """Mark this step as in progress."""
        self.status = "in_progress"
        self.started_at = datetime.now()

    def auto_generate_criteria(self) -> list[str]:
        """W7: Auto-generate acceptance criteria based on deliverables when criteria are empty."""
        if self.acceptance_criteria:
            return self.acceptance_criteria  # Already has criteria

        criteria: list[str] = []
        for deliverable in self.deliverables:
            if deliverable.endswith('.py') or deliverable.endswith('.ts') or deliverable.endswith('.js'):
                criteria.append(f"File {deliverable} exists and contains valid code")
            elif deliverable.endswith('.html') or deliverable.endswith('.vue'):
                criteria.append(f"File {deliverable} exists and contains valid markup")
            elif deliverable.endswith('.md') or deliverable.endswith('.txt'):
                criteria.append(f"File {deliverable} exists and contains content")
            else:
                criteria.append(f"File {deliverable} exists")

        return criteria


class TaskPlan(BaseModel):
    """Structured plan for a Writer task."""
    goal: str = ""
    steps: list[TaskPlanStep] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    user_confirmed: bool = False  # Must be True before execution starts
    created_at: datetime = Field(default_factory=datetime.now)

    @property
    def current_step_index(self) -> int:
        """Return the index of the first in-progress step, or -1."""
        for i, step in enumerate(self.steps):
            if step.status == "in_progress":
                return i
        return -1

    @property
    def failed_count(self) -> int:
        """Count of failed steps. W3: Used by re-planning trigger."""
        return sum(1 for s in self.steps if s.status == "failed")

    def start_first_step(self) -> TaskPlanStep | None:
        """Start the first pending step. Call once when execution begins."""
        for step in self.steps:
            if step.status == "pending":
                step.mark_in_progress()
                return step
        return None

    @property
    def progress_summary(self) -> dict:
        """Structured progress summary for prompt injection and event emission."""
        total = len(self.steps)
        completed = sum(1 for s in self.steps if s.status == "completed")
        failed = sum(1 for s in self.steps if s.status == "failed")
        in_progress = [s for s in self.steps if s.status == "in_progress"]
        next_pending = next((s for s in self.steps if s.status == "pending"), None)
        return {
            "total_steps": total,
            "completed": completed,
            "failed": failed,
            "progress_pct": round(completed / total * 100) if total > 0 else 0,
            "current_step": in_progress[0].description if in_progress else None,
            "next_step": next_pending.description if next_pending else None,
            "failed_steps": [s.description for s in self.steps if s.status == "failed"],
        }

    @property
    def current_step(self) -> TaskPlanStep | None:
        """The step currently in progress."""
        return next((s for s in self.steps if s.status == "in_progress"), None)

    @property
    def next_step(self) -> TaskPlanStep | None:
        """The next pending step."""
        return next((s for s in self.steps if s.status == "pending"), None)

    def advance_step(self) -> TaskPlanStep | None:
        """Mark current step completed, advance to next. Returns new current step or None."""
        current = self.current_step
        if current:
            current.status = "completed"
            current.completed_at = datetime.now()
        nxt = self.next_step
        if nxt:
            nxt.status = "in_progress"
            nxt.started_at = datetime.now()
        return nxt

    def fail_current_step(self, reason: str = "") -> TaskPlanStep | None:
        """Mark current step as failed. Returns the failed step."""
        current = self.current_step
        if current:
            current.status = "failed"
            current.failure_reason = reason
            current.completed_at = datetime.now()
        return current


# --- Rebuild models for forward reference resolution ---
# Required because of `from __future__ import annotations`

WriterAction.model_rebuild()
WriterPart.model_rebuild()
WriterTurn.model_rebuild()
WriterSessionState.model_rebuild()
WriterArtifact.model_rebuild()
WriterToolResult.model_rebuild()
TaskPlanStep.model_rebuild()
TaskPlan.model_rebuild()
