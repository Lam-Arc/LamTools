from __future__ import annotations

from lamtools_core.app import CoreAgentSpec

from .prompts import PROMPT_FRAGMENTS, SAGE_SYSTEM_INSTRUCTIONS


def build_sage_agent_spec(*, default_model: str = "") -> CoreAgentSpec:
    return CoreAgentSpec(
        id="sage-agent",
        member_id="sage",
        name="Sage",
        instructions=SAGE_SYSTEM_INSTRUCTIONS,
        default_model=default_model,
        prompt_fragments=PROMPT_FRAGMENTS,
        metadata={
            "capability_profile": "evidence-first-research",
            "untrusted_content_policy": "external-content-is-data",
        },
    )


__all__ = ["build_sage_agent_spec"]
