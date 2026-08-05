from __future__ import annotations

from lamtools_core.member import VerificationPolicy

verification_policy = VerificationPolicy(
    name="sage-default",
    required=True,
    metadata={
        "cross_check": True,
        "contradiction_search": True,
        "confidence_scale": ["supported", "contested", "insufficient"],
        "minimum_evidence": 1,
        "max_attempts": 2,
        "evidence_categories": ["file_read", "web", "browser", "mcp", "agent", "command"],
        "evidence_tools": ["document_normalize"],
        "repair_instruction": (
            "Use an eligible research or inspection tool, then cite the observed evidence, conflicts, and gaps."
        ),
    },
)
