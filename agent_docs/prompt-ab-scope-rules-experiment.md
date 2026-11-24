# 三条条件规则的对照实验

日期 2026-11-21。目的：按用户新口径检验三条条件规则是否改善范围完整性、统计一致性、目标相关性。

## 一、评分口径修订

必答项：

| 内容 | 是否必答 |
| --- | --- |
| 动态系统提示词修改链路、触发条件、修改方式 | 是 |
| 核心、控制、插件管理、工作流编辑的静态声明分布 | 是 |
| 仓库根目录 `plugins/` 的 `tools.jsonc` | 是 |
| 内置插件 `tools.jsonc` | 是 |
| 原生柱状图与数据一致性 | 是 |
| 示例插件、Rust 重复声明 | 视口径，非独立必答 |
| 辅助会话、子代理等额外声明 | 仅在所属分类内计入 |
| 29 个核心工具完整名称清单 | 否 |
| Provider 等题外机制 | 否 |

任务外的额外发现不加分也不减分。72 个声明点、67 个去重名只作全量盘点参考，不作质量评分的唯一标答。

## 二、新提示词

保留 Ra 结构，不新增编号原则，只在 First Principles 末尾追加三条条件规则：

```
Conditional Rules
- Scope Integrity: For exhaustive or project-wide tasks, establish the relevant source scope before narrowing searches. A search or partial read does not establish completeness outside its covered scope.
- Evidence Accounting: For inventories, counts, and derived conclusions, keep source categories and counting criteria consistent. Prefer deterministic aggregation and reconcile reported totals with their components.
- Goal Relevance: Prioritize evidence and work that directly contribute to the user's requested outcome. Do not expand scope or output detail solely for additional completeness unrelated to that outcome.
```

工作树与指纹：

| 臂 | 工作树 | 字符 | 提示词指纹 |
| --- | --- | --- | --- |
| Ra 对照 | `.worktrees/prompt-ab-variant` | 14417 | `96e5f30f` |
| 三条规则 | `.worktrees/prompt-ab-scope` | 15060 | `90c6dbc8` |

两棵树只差 643 字符，其余文件一致。实验参数 `--mode work --reasoning-level xhigh --permission-preset full_access`，与旧十二次相同。

## 三、单样本结果

| 臂 | 轮次 | 工具 | 耗时 | 字数 | 范围遗漏 | 动态模块 | 统计一致 | 无关轮 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Ra 对照 | 28 | 54 | 358 秒 | 6339 | 0/6 | 10/10 | 是 | 3/28 = 11% |
| 三条规则 | 42 | 70 | 482 秒 | 4428 | 0/6 | 9/10 | 否 | 6/42 = 14% |

Ra 对照的静态盘点：声明条目 65，去重 63，图表合计 65，与正文一致。外置插件 16 条、内置插件 9 条分项列出。

规则臂的静态盘点：去重后写 64，图表合计 66，用户插件写 18，真值 16。范围覆盖与对照臂相同，但出现新的口径错误。

规则臂多出的 14 轮主要花在：读 `runtime/context_delta.py`、`context_compaction/{planner,fitter,state}.py`、`plugin_system/context.py` 的 prompts 门面、`plugins/*/plugin.json` 的 agent 段。这些属于动态链路的补充证据，不是无关探索。

## 四、三个错误率

按新口径对十二次旧运行重算：

| 编号 | 轮次 | 范围遗漏率 | 动态模块缺 | 统计一致 | 无关轮比例 |
| --- | --- | --- | --- | --- | --- |
| Ox-1 | 26 | 0/6 | 3/10 | 否 | 12% |
| Ox-2 | 29 | 0/6 | 1/10 | 是 | 10% |
| Ox-3 | 31 | 0/6 | 0/10 | 是 | 16% |
| Ox-4 | 45 | 2/6 | 0/10 | 是 | 20% |
| Ra-1 | 32 | 1/6 | 1/10 | 是 | 12% |
| Ra-2 | 25 | 0/6 | 1/10 | 是 | 8% |
| Ra-3 | 45 | 0/6 | 3/10 | 否 | 13% |
| Ra-4 | 47 | 0/6 | 1/10 | 是 | 9% |
| Rb-1 | 34 | 1/6 | 0/10 | 是 | 9% |
| Rb-2 | 28 | 1/6 | 2/10 | 否 | 14% |
| Rc-1 | 45 | 0/6 | 1/10 | 是 | 7% |
| Rc-2 | 33 | 0/6 | 2/10 | 无图 | 12% |
| Ra 对照 | 28 | 0/6 | 0/10 | 是 | 11% |
| 三条规则 | 42 | 0/6 | 1/10 | 否 | 14% |

统计不一致的三组旧运行：Ox-1 图表 61 与正文 65、Ra-3 图表 69 与正文 61、Rb-2 图表 48 与正文 40。

范围遗漏集中在仓库根 `plugins/` 与示例清单，Ox-4、Ra-1、Rb-1、Rb-2 四组完全没有覆盖根目录插件。

## 五、十二次按新口径重评分

评分构成：动态链路 40 分，四类静态分布 20 分，根目录插件 15 分，内置清单 15 分，图表一致 10 分。

| 编号 | 动态 | 四类 | 根目录 | 内置 | 图表 | 总分 |
| --- | --- | --- | --- | --- | --- | --- |
| Ox-1 | 28 | 20 | 15 | 15 | 3 | 81 |
| Ox-2 | 36 | 20 | 15 | 15 | 10 | 96 |
| Ox-3 | 40 | 20 | 15 | 15 | 10 | 100 |
| Ox-4 | 40 | 20 | 0 | 15 | 10 | 85 |
| Ra-1 | 40 | 12 | 0 | 15 | 10 | 77 |
| Ra-2 | 36 | 20 | 15 | 15 | 10 | 96 |
| Ra-3 | 28 | 20 | 15 | 15 | 3 | 81 |
| Ra-4 | 40 | 20 | 6 | 15 | 10 | 91 |
| Rb-1 | 40 | 20 | 0 | 15 | 10 | 85 |
| Rb-2 | 32 | 20 | 0 | 15 | 3 | 70 |
| Rc-1 | 36 | 20 | 15 | 15 | 10 | 96 |
| Rc-2 | 32 | 20 | 6 | 15 | 0 | 73 |
| Ra 对照 | 40 | 20 | 15 | 15 | 10 | 100 |
| 三条规则 | 36 | 20 | 15 | 15 | 3 | 89 |

新口径下 Ra-2 从 100 降到 96，原因是动态链路少一条运行时增量。Ox-3 与 Ra 对照同为 100，说明质量上限不是某一版提示词独有。

## 六、结论

1. 三条规则在这一个样本上没有减少范围遗漏，两臂都是 6/6 覆盖。
2. 规则臂轮次增加 50%，工具增加 30%，产物字数反而少 30%。
3. 规则臂出现一处新的统计错误：用户插件 18 条，真值 16 条。
4. 单样本不足以判断规则是否有效，已知同一提示词的轮次极差 19 到 22。

## 七、任务指令前缀实验

以 Ra 提示词为基线，在任务原文开头加一句，提示词侧不动：

```
Make decisions only where judgment is needed. Execute known, deterministic work together. Gather enough evidence to satisfy the user's goal, resolve material uncertainty, and stop.
```

任务文件 `.worktrees/prompt-ab-harness/tasks/prompt-chain-audit-lead.txt`，与原任务只差这一句。两臂同期并行，参数相同。

| 臂 | 轮次 | 工具 | 耗时 | 字数 | 范围遗漏 | 动态模块 | 统计一致 | 无关轮 | 质量分 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Ra 无前缀 第一次 | 28 | 54 | 358 秒 | 6339 | 0/6 | 10/10 | 是 | 11% | 100 |
| Ra 无前缀 第二次 | 56 | 85 | 744 秒 | 6379 | 0/6 | 10/10 | 是 | 21% | 93 |
| Ra 加前缀 | 49 | 70 | 513 秒 | 4332 | 0/6 | 9/10 | 是 | 22% | 96 |

加前缀臂比同期对照少 7 轮、少 15 次工具、少 231 秒，产物字数少三成，质量持平。它的动态链路列了 17 条修改点，含 profiles 降级、study 后端、子代理内核、direct 直调；对照臂列了 14 条，含 checkpoint、tool_freeze、superagent_brief、runtime 的 context 文件注入。两者侧重点不同。

同一提示词同一任务两次运行相差 28 轮，轮次波动两倍。加前缀臂的 49 轮落在 28 到 56 的波动区间内，单样本无法判断前缀是否真的减少轮次。

## 八、Rb 开头加一句清单指令

在 Rb 的 First Principles 标题后加一行 `Write the check_list first.`，其余不动。提示词从 14417 字符变成 14445，指纹 `96e5f30f` 变成 `9d38b9a5`。任务原文不变。

| 臂 | 轮次 | 工具 | 耗时 | 字数 | 范围遗漏 | 动态模块 | 统计一致 | 无关轮 | 质量分 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Rb 第一次 | 34 | 60 | 447 秒 | 5171 | 1/6 | 10/10 | 是 | 9% | 85 |
| Rb 第二次 | 28 | 46 | 353 秒 | 4685 | 1/6 | 8/10 | 否 | 14% | 70 |
| Rb 加清单句 | 53 | 96 | 594 秒 | 5051 | 0/6 | 9/10 | 是 | 8% | 96 |

这句指令没有触发清单工具。整场 96 次工具调用里 `run_command` 93 次、`read_file` 3 次，`write_checklist` 零次，产物也没有清单结构，直接给结论。

质量分 96，范围全覆盖，统计自洽，无关轮 8% 为全部实验最低。代价是轮次 53、工具 96，都是 Rb 谱系里最高的一次。

## 九、待决策



1. 是否给两臂各补一到两个样本，把轮次极差纳入比较。
2. 规则臂的统计错误是否说明 Evidence Accounting 条款写法有问题，还是单纯样本波动。
3. 是否把范围完整性条款改写成强制动作，例如要求先列出待调查来源清单再开始搜索。
