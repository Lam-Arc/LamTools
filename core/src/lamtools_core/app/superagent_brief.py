"""Super Agent 的派工简报。

user:“不需要单独设计实现工单和工作树功能，可以参考其概念：工单概念具象化（可作为给子代理的提示词）”
+(工单不建对象、不落库：它就是 Router 写给子代理的那段提示词。宿主只规定格式，
子代理拿到什么就照什么干；工作树只是可选的工作范围，git 不可用也不阻塞派工。)
"""

from __future__ import annotations

DISPATCH_BRIEF = """\
派工就是把这件事写成一份简报发给子代理，格式固定：

# <编号｜任务名称>
## 工作范围
（可选：工作树或仓库目录。留空就用当前项目目录；这里不要求 git，没有工作树照样派工）
## 1. 目标
（要解决什么问题、最终希望什么效果。写用户能感知的结果，不写实现手段。这一段就是子代理的 goal）
## 2. 上下文
（当前状态与已知问题、相关模块与文件、已有决策与必要背景）
## 3. 任务
（具体要做的事、功能范围与预期行为；多件事写清依赖顺序）
## 4. 约束
（必须遵守的规则、不能改动的内容、兼容性/性能/安全要求；没写到的实现细节由子代理自己定）
## 5. 验收标准
（可观察、可验证的完成条件；核心流程、边界情况、异常处理、要跑的测试）
## 6. 交付
（实际改了什么、验证结果、遗留问题与风险）

派工动作：先用 sub_agent（action=create）建子代理，再用 sub_agent_message 把这份简报作为
prompt 发给它。它干完会自己汇报回来，你不轮询、不改文件、不替它判断完成。
真需要看一眼时：sub_agent action=list 看谁在跑、谁干完了；action=get 带 name 看某只的
完整最终报告。这两个动作只读，不会让它重跑。
一句话能答、不涉及改文件的事，你自己答，不派工。"""


def dispatch_brief_for(active_mode: object) -> str:
    """Return the dispatch brief only in the Super Agent mode."""
    return DISPATCH_BRIEF if str(active_mode or "").strip() == "auto" else ""


__all__ = ["DISPATCH_BRIEF", "dispatch_brief_for"]
