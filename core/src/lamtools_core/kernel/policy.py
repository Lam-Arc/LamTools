"""Loop policy: generic runtime strategy knobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LoopPolicy:
    """Generic runtime policy. Business policy stays in Kit.

    Do NOT put member-specific generation, workspace, branch, or product
    policy fields here.
    """

    model_timeout_seconds: float = 360.0
    model_retries: int = 100
    model_stream_idle_timeout_seconds: float | None = 120.0
    tool_timeout_seconds: float | None = None
    emit_debug_events: bool = False
    # History compaction safety net (OpenAI-style pre-sampling compaction).
    # When set, Kernel trims history to the most recent N messages before
    # build_context, preserving assistant→tool_result pairs. Kit may do
    # smarter compaction in build_context; this is the kernel-level floor.
    max_history_messages: int | None = None
    # Token-based context compaction. When context_window_tokens is set, the
    # Kernel estimates the full model request before sampling. If the estimate
    # reaches compact_trigger_ratio of the window, it structurally summarizes
    # the current request's compressible context while preserving the stable
    # system prefix and newest user context. compact_limit_ratio is a hard
    # post-compaction upper bound for the estimated request, not a best-effort
    # target. This is an estimate for runtime safety, not billing.
    context_window_tokens: int | None = None
    compact_trigger_ratio: float = 0.8
    compact_limit_ratio: float = 0.6
    compact_trigger_tokens: int | None = None
    compact_limit_tokens: int | None = None
    # Tool execution parallelism (OpenAI Codex defaults to sequential for
    # shell-safety; Agents SDK defaults to parallel with optional cap).
    # parallel_tool_calls=False (default) executes tools strictly in order.
    # parallel_tool_calls=True executes concurrently, capped by
    # max_concurrent_tools (None = unbounded). Results are still written
    # back to history in original tool_calls order.
    parallel_tool_calls: bool = False
    max_concurrent_tools: int | None = None
    parallel_tool_names: tuple[str, ...] = ()
    # Last-resort stop for an exact repeated failed tool call/result without a
    # total step budget. The Kernel does not try to enumerate or semantically
    # classify every possible failure; model-visible diagnosis handles that.
    max_identical_tool_results: int | None = 4
    identical_tool_result_window: int = 12
    # Periodic evidence-convergence checkpoint for long tool-only streaks.
    # This does not classify tool semantics or stop the run; it only requires
    # a concise visible progress note before more tools are allowed.
    max_tool_only_rounds_without_progress: int | None = 8
    # Step persistence (OpenAI Rollout-style): when True, Kernel appends a
    # step summary to state.metadata["kernel_steps"] after each iteration.
    # This enables post-run audit and debugging. Full resume/fork requires
    # Kit to also persist history (Kernel does not auto-persist history).
    persist_steps: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "LoopPolicy",
]
