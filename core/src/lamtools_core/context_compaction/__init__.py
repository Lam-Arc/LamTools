"""Public API for the context-compaction pipeline."""

from lamtools_core.context_compaction_budget import (
    SummaryTokenBudget,
    TokenBudget,
    TokenMeasurement,
    measure_for_compaction_trigger,
)
from .models import (
    COMPACTION_PREFIX,
    COMPACTION_PROMPT,
    CompactionBudgetExceeded,
    CompactionDeltaSink,
    CompactionEventSink,
    CompactionFitInput,
    CompactionFitResult,
    CompactionOptions,
    CompactionPlan,
    CompactionSummary,
    CompactionTokenEstimator,
    ContextCompactionError,
    ContextCompactionRequest,
    ContextCompactionResult,
)
from .formatting import (
    format_messages_for_compaction,
    parse_compaction_summary,
    with_compaction_prefix,
)
from .fallback import (
    compress_structured_compaction_summary,
    fallback_structured_compaction_summary,
)
from .planner import (
    CompactionPlanner,
    compaction_segment_input_limit,
    select_context_compaction_layout,
)
from .fitter import CompactionFitter, MAX_FIT_ATTEMPTS, truncate_text_to_tokens
from .summarizer import summarize_context_messages
from .controller import ContextCompactor, compact_context


__all__ = [
    "COMPACTION_PREFIX",
    "COMPACTION_PROMPT",
    "CompactionBudgetExceeded",
    "CompactionFitInput",
    "CompactionFitResult",
    "CompactionFitter",
    "CompactionOptions",
    "CompactionPlan",
    "CompactionPlanner",
    "CompactionSummary",
    "ContextCompactionError",
    "ContextCompactor",
    "ContextCompactionRequest",
    "ContextCompactionResult",
    "MAX_FIT_ATTEMPTS",
    "compact_context",
    "compress_structured_compaction_summary",
    "compaction_segment_input_limit",
    "fallback_structured_compaction_summary",
    "format_messages_for_compaction",
    "parse_compaction_summary",
    "select_context_compaction_layout",
    "summarize_context_messages",
    "truncate_text_to_tokens",
    "with_compaction_prefix",
]
