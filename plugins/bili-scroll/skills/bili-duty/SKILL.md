---
name: bili-duty
description: 刷B站值班的兼容技能入口；规则与工具以 bili-scroll 为准。
---

# bili-duty 兼容入口

user:“对比原版，能力应当只增不减”+(旧技能名称保留，转向当前完整章程)。

运行一轮使用 `bili_run`，后端按 `bili-scroll:duty` 启动子代理。完整流程见同包 `../bili-scroll/SKILL.md` 及 `prompts/duty.md`，轮次配置由宿主注入。

当前值班轮只开放 `mcp`。通过 `mcp` 的查询和 `action=run` 执行 `mcp__bilibili__bili_search`、`bili_subtitle`、`duty_report_append` 等当前工具；不使用旧版 brief/search/dedup 命令别名，也不使用 `run_command`。投递、评论和回复必须满足当前配置及执行闸。
