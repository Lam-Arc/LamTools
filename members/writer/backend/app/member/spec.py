from __future__ import annotations

from lamtools_core.app import CoreAgentSpec


WRITER_SYSTEM_INSTRUCTIONS = (
    "You are LamWriter, a professional software engineer. "
    "You work inside a project workspace. "
    "Write clean, production-quality code. "
    "When creating or modifying files, use write_file or edit_file. "
    "After writing files, verify them by reading them back. "
    "When you complete a task, provide a concise summary of what was done."
)


def build_writer_agent_spec(*, default_model: str = "") -> CoreAgentSpec:
    return CoreAgentSpec(
        id="writer-agent",
        member_id="writer",
        name="Writer",
        instructions=WRITER_SYSTEM_INSTRUCTIONS,
        default_model=default_model,
        metadata={
            "capability_profile": "code-generation",
        },
    )


__all__ = ["build_writer_agent_spec", "WRITER_SYSTEM_INSTRUCTIONS"]