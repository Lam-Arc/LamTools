from __future__ import annotations

from lamtools_core.member import MemberLabels, StaticMemberKit

from app.core.writer.tool_specs import WRITER_TOOLS
from app.core.writer.core_kernel_adapter import WriterKit

kit = StaticMemberKit(
    id="writer",
    display_name="Writer",
    prompts=[],
    tools=WRITER_TOOLS,
    verification=None,
    member_labels=MemberLabels(
        display_name="Writer",
        labels={
            "composer_placeholder": "描述你想要创建或修改的内容…",
            "assistant_label": "Writer",
            "arrange_label": "长期安排",
        },
    ),
)