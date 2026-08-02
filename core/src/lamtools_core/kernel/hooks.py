"""Standard hook node names for member runtime loops.

Both Writer and Artist have the same fixed-node lifecycle:
- before_model: prepare context and inject information
- after_model: parse model output, apply observations
- after_tool: process tool results, record observations
- verify: check if output meets quality standards
- writeback: persist state, artifacts, and memory

These constants ensure both members use the same vocabulary
for the same lifecycle positions. Each member decides what
happens at each node; the node names themselves are shared.

For the full HookProtocol with typed HookResult, merge rules,
error handling, and permission boundaries, see hook_protocol.py.
For the HookSet base class with no-op defaults, see hook_set.py.
"""

from __future__ import annotations


HOOK_BEFORE_MODEL = "before_model"
HOOK_AFTER_MODEL = "after_model"
HOOK_AFTER_TOOL = "after_tool"
HOOK_VERIFY = "verify"
HOOK_WRITEBACK = "writeback"

ALL_HOOK_NODES = [HOOK_BEFORE_MODEL, HOOK_AFTER_MODEL, HOOK_AFTER_TOOL, HOOK_VERIFY, HOOK_WRITEBACK]

STANDARD_HOOK_NODES = {
    HOOK_BEFORE_MODEL: "Prepare context before calling the model. Inject runtime state, vision, progress, drift detection.",
    HOOK_AFTER_MODEL: "Parse model output, apply task cards, identity contracts, observations.",
    HOOK_AFTER_TOOL: "Process tool results. Create artifacts, record observations, apply reviews.",
    HOOK_VERIFY: "Check if output meets quality standards. Visual review, completion verification.",
    HOOK_WRITEBACK: "Persist state, artifacts, memory. Update lineage, save to store.",
}


__all__ = [
    "HOOK_BEFORE_MODEL",
    "HOOK_AFTER_MODEL",
    "HOOK_AFTER_TOOL",
    "HOOK_VERIFY",
    "HOOK_WRITEBACK",
    "ALL_HOOK_NODES",
    "STANDARD_HOOK_NODES",
]