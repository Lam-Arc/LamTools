"""Core Loop Kernel: shared main loop skeleton.

This module provides the CoreLoopKernel and supporting types for
building product runtimes. Kernel owns the loop structure; Kit owns
the business logic.

Key types:
- LoopDecision: continue / wait / done / failed
- LoopPhase: idle / plan / execute / verify
- KernelTurn: Kit-parsed model output
- VerificationResult: Kit verification outcome (with repair tracking)
- KernelStep: Record of one loop iteration
- KernelResult: Output of an entire kernel run
- LoopPolicy: Generic runtime policy knobs (retry count, timeouts)
- RetryPolicy: Transport-level retry backoff strategy (from llm.policy)
- RuntimeKit: Protocol for business capability injection
- CoreLoopKernel: The main loop orchestrator
- KernelError: Base error for kernel operations
"""

from .display import (
    CoreDisplayEvent,
    CoreDisplayFormatter,
    DisplayKind,
    core_event_to_display,
)
from .errors import (
    KernelError,
    ModelCallError,
    RateLimitError,
    StateSaveError,
    TokenOverflowError,
)
from .kit import RuntimeKit
from .loop import CoreLoopKernel
from .policy import LoopPolicy
from .state import KernelResult, KernelStep, KernelTurn, LoopDecision, LoopPhase, VerificationResult
from .tracing import InMemoryTracer, NoopTracer, TraceSpan, Tracer
from lamtools_core.llm.policy import BackoffStrategy, RetryPolicy

__all__ = [
    # State types
    "LoopDecision",
    "LoopPhase",
    "KernelTurn",
    "VerificationResult",
    "KernelStep",
    "KernelResult",
    # Policy
    "LoopPolicy",
    "RetryPolicy",
    "BackoffStrategy",
    # Protocol
    "RuntimeKit",
    # Kernel
    "CoreLoopKernel",
    # Display
    "CoreDisplayEvent",
    "CoreDisplayFormatter",
    "DisplayKind",
    "core_event_to_display",
    # Tracing
    "Tracer",
    "TraceSpan",
    "NoopTracer",
    "InMemoryTracer",
    # Errors
    "KernelError",
    "ModelCallError",
    "TokenOverflowError",
    "RateLimitError",
    "StateSaveError",
]
