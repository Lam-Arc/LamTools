"""Writer runtime lifecycle hooks and fixed-node definitions.

Writer's five fixed lifecycle positions correspond to the core HOOK_*
constants. Each position has specific responsibilities:

- before_model: Prepare context before calling the LLM
- after_model: Parse LLM output, detect drift, apply observations
- after_tool: Execute actions, check permissions, handle failures
- verify: Run completion verification, check deliverables
- writeback: Persist state, memory, git context, artifacts

This module provides declarative descriptions and constants.
Real hook logic is in hook_set.py; runtime loop is in
core_kernel_adapter.py using CoreLoopKernel.
"""

from __future__ import annotations

from lamtools_core.kernel.hooks import (
    ALL_HOOK_NODES,
    HOOK_AFTER_MODEL,
    HOOK_AFTER_TOOL,
    HOOK_BEFORE_MODEL,
    HOOK_VERIFY,
    HOOK_WRITEBACK,
    STANDARD_HOOK_NODES,
)


WRITER_HOOK_DESCRIPTIONS: dict[str, str] = {
    HOOK_BEFORE_MODEL: (
        "Inject project rules, plan progress, recent failures, memory context, "
        "git context, and context compression. Detect drift (exploration overload, "
        "production gap, read-heavy). Build prompt via PromptAssembler."
    ),
    HOOK_AFTER_MODEL: (
        "Parse LLM response into WriterTurn. Apply guardrail check. "
        "Emit thought/reply events. Detect drift and build nudge if needed. "
        "Apply observations from tool results."
    ),
    HOOK_AFTER_TOOL: (
        "Execute actions with permission check. Track results in WriterPart. "
        "Handle failures with recovery instructions. Enforce forced action types. "
        "Apply loop breaker (repeated calls, consecutive reads, consecutive tools). "
        "Classify tool observations for next turn."
    ),
    HOOK_VERIFY: (
        "Run CompletionVerifier for non-LLM verification. Check deliverables exist "
        "and are not stubs. Verify acceptance criteria. Handle repair cycles. "
        "Emit verification lifecycle events."
    ),
    HOOK_WRITEBACK: (
        "Run self-review. Write to session memory. Write to MEM module (cross-session). "
        "Save state to WriterStateStore. Record git checkpoint. Update artifact registry. "
        "Record user corrections for cross-session learning."
    ),
}


WRITER_LOOP_POSITIONS = {
    "plan": "Planning phase — produce or confirm a TaskPlan",
    "execute": "Implementation phase — execute actions toward plan",
    "verify": "Verification phase — run CompletionVerifier before done",
    "idle": "Task complete or failed — runtime stopped",
}


WRITER_WORKFLOW_PHASES = {
    "ideation": "Initial brainstorming and exploration",
    "outlining": "Structure and outline creation",
    "drafting": "Main content generation",
    "revising": "Review and refinement",
    "polishing": "Final polish and cleanup",
}


def writer_hook_description(node: str) -> str | None:
    """Get the Writer-specific description for a hook node."""
    return WRITER_HOOK_DESCRIPTIONS.get(node)


def validate_writer_hooks_cover_core() -> bool:
    """Verify Writer hooks cover all core hook nodes."""
    return set(WRITER_HOOK_DESCRIPTIONS.keys()) == set(ALL_HOOK_NODES)


__all__ = [
    "WRITER_HOOK_DESCRIPTIONS",
    "WRITER_LOOP_POSITIONS",
    "WRITER_WORKFLOW_PHASES",
    "writer_hook_description",
    "validate_writer_hooks_cover_core",
    "HOOK_BEFORE_MODEL",
    "HOOK_AFTER_MODEL",
    "HOOK_AFTER_TOOL",
    "HOOK_VERIFY",
    "HOOK_WRITEBACK",
    "ALL_HOOK_NODES",
    "STANDARD_HOOK_NODES",
]
