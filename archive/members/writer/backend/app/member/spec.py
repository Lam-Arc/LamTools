from __future__ import annotations

from lamtools_core.app import CoreAgentSpec


WRITER_SYSTEM_INSTRUCTIONS = (
    "你是 LamWriter，一名专业软件工程师。"
    "在项目工作区内工作。"
    "编写清晰、生产级别的代码。"
    "创建或修改文件时使用 write_file 或 edit_file。"
    "写入文件后通过回读进行验证。"
    "任务完成后提供简洁的完成摘要。"
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