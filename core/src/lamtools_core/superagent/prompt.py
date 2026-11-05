"""把一张工单变成一段可执行的指令。

user:“让用户能够直接交付复杂目标，由 Super-agent 自主规划、拆解、委派、执行、监控、
处理异常、恢复任务、验证成果并完成交付”+(指令必须把「怎么做完并证明做完了」讲清楚，
而不是把目标原样丢给模型，否则它只会改两行代码就说完成了)。
"""

from __future__ import annotations

from typing import Any

from .models import Mandate, Ticket

# 交付报告必须回答的四件事。少一件，用户就没法判断这件事到底能不能用。
REPORT_CONTRACT = """\
结束时用下面四段汇报，缺一段视为没做完：
1. 做了什么：改动了哪些文件、各自为什么改。
2. 怎么验证的：实际跑了什么命令、看到什么结果。不许写「应该可以」。
3. 没做到什么：明确列出没完成的部分和原因。没有就写「无」。
4. 用户接下来要做什么：需要人工确认、推送或合并的动作。没有就写「无」。"""


def _bounds(mandate: Mandate) -> str:
    lines = [f"- 只能改动仓库：{mandate.repo_root}"]
    if mandate.allowed_paths:
        lines.append("- 只能改动这些路径：" + "、".join(mandate.allowed_paths))
    else:
        lines.append("- 仓库内所有路径都可以改")
    if mandate.can_push:
        lines.append("- 允许推送分支，但合并到主干仍需人工确认")
    else:
        lines.append("- 不允许推送，也不允许创建 PR；改完留在本地分支即可")
    return "\n".join(lines)


def build_ticket_prompt(
    ticket: Ticket,
    *,
    work_root: str,
    branch: str = "",
    model_id: str = "",
    context: dict[str, Any] | None = None,
) -> str:
    """拼出一次工单执行的完整指令。"""
    goal = (ticket.instructions or "").strip() or "（没有写目标）"
    where = [f"- 工作目录：{work_root}"]
    if branch:
        where.append(f"- 独立分支：{branch}（这是本工单专用工作树，不影响用户当前检出）")
    if ticket.mandate.base_branch:
        where.append(f"- 基线分支：{ticket.mandate.base_branch}")
    if model_id:
        where.append(f"- 本次执行使用的模型：{model_id}")

    extra = ""
    if context:
        rendered = "\n".join(f"- {key}：{value}" for key, value in context.items() if value not in (None, ""))
        if rendered:
            extra = f"\n\n附加上下文：\n{rendered}"

    delegate = (
        "用 sub_agent 工具，参数必须是 action、type、name、model、reasoning_level 五项；"
        f"model 直接用 {model_id}，不要自己编模型名。"
        if model_id
        else "用 sub_agent 工具，参数必须是 action、type、name、model、reasoning_level 五项；"
        "model 填你当前正在使用的模型。"
    )

    return f"""\
你在作为 Super-agent 独立完成一件交付物。用户已经把这件工作交给你，没有人会中途替你判断对错，所以你必须自己把事做完并证明做完了。

目标：
{goal}

工作现场：
{chr(10).join(where)}{extra}

权限边界：
{_bounds(ticket.mandate)}

按这个顺序推进，不要跳步：
1. 先摸清现状：读代码、读配置、读测试，弄清这件事在这个仓库里到底怎么实现。不要凭文件名猜。
2. 写出计划：用 write_checklist 建 3 到 7 步的清单，每步都要有能验证的产出。发现计划错了就改计划，不要硬撑。
3. 拆解与委派：互相独立的子任务交出去，{delegate}你自己负责需要连续上下文的改动。
4. 动手实现：直接改代码。发现是真实缺陷就修掉，不要只写报告。
5. 验证成果：必须跑真实命令来证明，例如跑相关测试、跑一次真实调用、对比输出。单元测试通过不等于功能可用，能跑端到端就跑端到端。
6. 处理异常：命令失败、测试不过、依赖缺失，先判断是自己改错了还是环境缺东西。自己改错的必须修；环境缺东西的写进报告，不要伪造通过。

{REPORT_CONTRACT}

最后一条：不要停下来问我问题。需要我做的决定写进报告的第四段，其余你自己判断并继续。"""


__all__ = ["REPORT_CONTRACT", "build_ticket_prompt"]
