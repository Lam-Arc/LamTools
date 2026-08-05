from __future__ import annotations

from lamtools_core.member import MemberLabels, StaticMemberKit

from .prompts import PROMPT_FRAGMENTS
from .tools import TOOL_SPECS
from .verification import verification_policy

kit = StaticMemberKit(
    id="sage",
    display_name="Sage",
    prompts=PROMPT_FRAGMENTS,
    tools=TOOL_SPECS,
    verification=verification_policy,
    member_labels=MemberLabels(
        display_name="Sage",
        labels={
            "composer_placeholder": "提出要搜集、核验或持续关注的问题…",
            "assistant_label": "Sage",
            "arrange_label": "长期安排",
        },
    ),
)
