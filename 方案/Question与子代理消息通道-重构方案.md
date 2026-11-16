# Question 与子代理消息通道重构方案

> 定稿依据：本次设计讨论的全部裁决。代码尚未改动，本文件是实施与验收的唯一口径。
> 原则：**Question 控制信息收集与会话恢复，不控制用户的输入权；Approval 才控制执行许可。两者不共用阻塞机制。**

## 一、现状与目标的差异

| 项 | 现状 | 目标 |
|---|---|---|
| Question 的工具形态 | 挂起 tool call，答案以 tool result 回注 | 工具立即闭合；答案是一条标准 user message |
| 等待机制 | 与审批共用等待门（`pending_approval` + `loop_state="wait"`） | 提问用 `paused`，审批保留等待门 |
| 输入栏 | 有任何待处理项就接管输入栏（`LamToolsApp.vue` 的 `composerTakenOver`） | 只有审批接管；提问只改 placeholder |
| 卡片展示 | 决策池出池即消失 | 提问卡常驻消息流，按位置渲染 |
| 子代理提问 | 直接弹卡给用户，答案路由到子会话 | 父代理即用户，问答走信箱消息 |
| 唤醒链路 | 订阅 `sub_agent_events`，只认 `member_finished` / `member_failed` | 订阅 `sub_agent_mailbox`，凡带唤醒标签即唤醒 |

## 二、已裁决事项

| # | 事项 | 结论 | 说明 |
|---|---|---|---|
| 1 | 等待语义 | **paused** | 对外可见；父代理不被成员提问传染 |
| 2 | 答案载体 | **标准 user message** | 不引入新载荷；落点由会话状态决定 |
| 3 | 组与题的身份 | **一组一 interaction** | 组状态与题状态同挂一行 |
| 4 | 确认方式 | **组内一并 confirm** | 无逐题提交中间态 |
| 5 | 暂停条件 | **含必答才 paused** | 全非必答不暂停、不阻塞 |
| 6 | 卡片 | **常驻、按位置渲染、不自然消失** | 展示权威回到消息流 |
| 7 | `done` | **关闭标记，非硬终态** | 关闭后仍可通过卡片追加回答 |
| 8 | 追加回答 | **改写题级状态为 `answered`** | 同时保留关闭时的题级快照 |
| 9 | 超时自动跳过 | **删除** | 前端与后端两处都删 |
| 10 | 子代理 | **父代理即用户** | 子代理的提问不面向用户界面 |
| 11 | 唤醒载体 | **信箱消息 + 唤醒标签** | 完成/失败/message/question 全部带标签 |
| 12 | 唤醒频率 | **不设机制上限** | 在工具描述中提示不要刷进度消息 |
| 13 | 未获答复兜底 | **同一提问最多唤醒 2 次** | 之后自动回“未获答复，按合理默认继续” |

## 三、Question 数据模型

`core/src/lamtools_core/tool/default_toolbox.py` 的 `question` 工具 schema 扩展为：

| 字段 | 含义 |
|---|---|
| `id` | 题级稳定标识（组内唯一） |
| `title` | 问题内容 |
| `description` | 可选补充说明 |
| `type` | `single` / `multiple` / `text` |
| `required` | 是否必答 |
| `options` | `{label, description}` 集合 |
| `placeholder` | 输入提示文字 |

- `type=text` 时忽略 `options`；`options` 缺失时退化为纯文本题。
- `single` 最多选一项；`multiple` 可多选；两者都提供自由文本胶囊。
- 兼容旧调用：仍接受 `question` / `header` / `options` / `multiSelect`，按语义映射到新字段。
- 校验复用 `core/src/lamtools_core/plugin_system/question_access.py` 的规则（1–10 题、题目与选项去重、自定义文本覆盖选项）。

## 四、主线生命周期

### 4.1 调用与闭合

1. Agent 调用 `question`，提交一个或多个结构化问题。
2. 工具**立即闭合**，tool result 只写“问题已展示给用户，等待其在后续消息中回应”。
3. 若组内**存在必答题**：本轮不再继续，回合以 `paused` 收束。
4. 若组内**全部为非必答**：本轮正常继续，卡片留在消息流中等待用户顺手回答。

### 4.2 答案的落点

答案就是一条普通用户消息，由会话状态决定表现：

| 会话状态 | 现有行为 | 对提问而言 |
|---|---|---|
| `running` | steering / 排队 | 运行中插话，顺带答问 |
| `paused` | `turn/resume` 的 `carry_text` / `carry_input` → `guidance_source` | 同一回合继续 |
| 空闲 / 已结束 | `turn/start` | 新回合首条消息 |

不新增回答专用 RPC。UI 提交与用户直接打字产出**同一种东西**：一条标准消息。

### 4.3 组与题的状态

题级：`pending` → `answered` / `skipped`；组被普通消息关闭时未处理的题记 `done`。

- `answered`：用户确认，且有回答内容。
- `skipped`：用户显式跳过，或提交时省略的非必答。
- `done`：组被普通消息关闭时仍未处理的题。

组级：`created → streaming → pending(paused) → completed`。

### 4.4 关闭与追加

- 消息落库是**唯一**的组关闭事件；那一刻定格题级状态，并保存一份“关闭时题级快照”。
- 关闭后卡片仍可作答：追加回答**改写**题级状态为 `answered`，同时新增一条组内补充记录并发送一条标准消息；组状态不变。
- 关闭快照与当前状态并存，保证“正确记载”与“可改写”不冲突。
- 历史组不可重复提交同一批答案。

## 五、卡片与输入栏

- 存在待处理提问时，**不接管输入栏**，只把 placeholder 改为「有提问待处理」；审批仍按原行为变形为审批卡。
- 一组问题渲染为一个 Question Group，各题独立内容、选项、输入胶囊与操作；组级一个「提交并继续」。
- 必答未填不允许提交（前端禁用 + 明确提示缺失项）；非必答未填不阻塞提交，提交时记为 `skipped`。
- 必答不被硬阻塞：用户始终可以直接在输入栏发一条普通消息结束整组（最高优先级），未处理题转 `done`。
- 已确认但未提交的回答，随该条消息一并携带（按 `Q<id> <title>：<回答>` 拼入正文）。
- 结束后卡片保留在原位置，显示最终状态与追加历史，不再提供重复提交入口。

## 六、子代理消息通道

### 6.1 模型

对子代理来说，**父代理就是用户**：它的 `question` 是对父代理的提问，不进入用户界面。父代理答得出就答；答不出，自然调用自己的 `question` 去问用户。

### 6.2 表改造

`sub_agent_mailbox`（`core/src/lamtools_core/sub_agent_supervisor.py:419`）新增：

| 列 | 用途 |
|---|---|
| `tags TEXT NOT NULL DEFAULT ''` | 语义标签：`question` / `message` / `finished` / `failed` |
| `wake INTEGER NOT NULL DEFAULT 0` | 是否唤醒父代理 |
| `wake_count INTEGER NOT NULL DEFAULT 0` | 已唤醒次数，用于未获答复兜底 |

索引：`(parent_thread_id, direction, delivered_at, wake)`。

### 6.3 写入路径

| 来源 | direction | tags | wake |
|---|---|---|---|
| 子代理 `question` | `child_to_parent` | `question` | 1 |
| 子代理 `message` | `child_to_parent` | `message` | 1 |
| 成员完成 | `child_to_parent` | `finished` | 1 |
| 成员失败 | `child_to_parent` | `failed` | 1 |
| 父代理回复 / 指导 | `parent_to_child` | `reply` | 0 |

### 6.4 唤醒链路

1. `list_threads_with_pending_member_wakes` 改为查询信箱：`direction='child_to_parent' AND delivered_at IS NULL AND wake=1`。
2. `_deliver_member_event_live` 的判定从“事件名在白名单”改为“`wake=1`”，父回合存活时即时注入 guidance。
3. 跨回合唤醒仍由 `core/src/lamtools_core/app/memory_resume_supervisor.py` 的 `_wake_member_threads` 驱动，输入改为“未投递消息包”，按标签拼装。
4. **claim 语义**：`mark_mailbox_delivered` 只在回合真正启动后标 `delivered_at`，保持“启动失败则下次重试”的既有防丢特性。
5. **合并**：沿用 `MEMBER_WAKE_COALESCE_SECONDS` 窗口，一次唤醒投递该父线程全部未投递唤醒消息。
6. **未获答复兜底**：投递时 `wake_count += 1`；父代理回合结束仍无对应 `parent_to_child` 回复时，若 `wake_count < 2` 则重新置为未投递并唤醒，达到 2 次后自动写入一条“未获答复，按合理默认继续”给子代理，避免永久悬空。

### 6.5 迁移边界

| 边界 | 处理 |
|---|---|
| `sub_agent_events` 存量未投递行 | 升级时一次性转为信箱消息（`wake=1`，`message_key` 由 `event_key` 映射），避免重启前的完成事件丢失 |
| 去重键语义不同 | `event_key` → `message_key` 映射必须保证一一对应，否则同一完成会投递两次 |
| 子代理 `message` 由“不唤醒”变“唤醒” | 属预期行为变更，需同步更新既有测试与注释 |
| `member_paused` 旧语义 | 旧语义是“问人类，不唤醒”；新语义是“问父代理，要唤醒”，相关注释与测试一并改写 |

## 七、变更清单

**删除**
- `core/ui/src/composables/useCoreAskAutoContinue.ts`（前端 5 分钟自动跳过）
- `core/src/lamtools_core/app/memory_resume_supervisor.py` 的 `_auto_continue_questions` 与 `_due_question_request_id`（后端自动跳过）
- 子代理提问直接弹用户卡的路径（`core/src/lamtools_core/app/default_agent.py` 的 `child_question` 分支）

**新增**
- Question Group 组件与组级提交（`core/ui/src/components/`）
- 信箱唤醒查询与 `wake` / `tags` / `wake_count` 列
- 组/题状态持久化（复用 `CoreTurnInteraction` 一行）

**修改**
- `core/src/lamtools_core/tool/default_toolbox.py`：question schema、终结型工具语义、不接管输入栏的元数据
- `core/src/lamtools_core/kernel/loop.py`：question 不再进等待门；含必答时以 `paused` 收束
- `core/src/lamtools_core/app/live/approvals.py`、`app/approval_resolution.py`：只服务审批
- `core/src/lamtools_core/app/live/turn_pause.py`、`app/live/recovery.py`：paused 关卡与重启关卡对提问组豁免
- `core/src/lamtools_core/sub_agent_supervisor.py`：信箱列、唤醒查询、实时注入判定、claim
- `core/src/lamtools_core/app/memory_resume_supervisor.py`：唤醒输入改为消息包
- `core/ui/src/app/LamToolsApp.vue`：`composerTakenOver` 只认审批
- `core/ui/src/appServer/pendingDecisions.ts`：提问不再由决策池驱动展示

## 八、验收标准

1. 一次调用可包含多道单选、多选、文本题，全部渲染在同一组内。
2. 有提问待处理时，输入栏仍可直接输入并发送；placeholder 显示「有提问待处理」。
3. 含必答题的组：回合进入 `paused`；提交后只产生**一次**恢复。
4. 全非必答的组：回合**不**暂停，正常运行至结束。
5. 必答未填无法提交；显式 Skip 始终可用；非必答未填不阻塞。
6. 普通消息可在任何时候结束整组：未处理题转 `done`，已确认答案随消息携带，不丢失。
7. 提交或关闭后卡片仍留在原位置，显示状态与追加历史，且不可重复提交同一批答案。
8. 关闭后通过卡片追加回答，题级状态改写为 `answered`，同时发送一条标准消息。
9. 重启、重连、切换会话后所有组与题状态完整，且不会重复注入答案。
10. Approval 的输入栏变形与阻塞逻辑与改造前完全一致。
11. 子代理提问不进入用户界面；父代理通过信箱收到并回答；回答能唤醒子代理。
12. 子代理完成、失败、message、question 均能唤醒父代理；未获答复两次后自动放行并留痕。

## 九、实施顺序

1. **信箱唤醒链路**（独立、可先行）：加列 → 改查询 → 改实时注入 → 改 claim → 迁移存量 → 兜底计数。
2. **question schema 与校验**：字段扩展、兼容旧调用。
3. **输入栏与卡片解耦**：`composerTakenOver` 只认审批；placeholder；Question Group 组件。
4. **普通消息关闭组**：消息落库时收束组与题，携带已确认答案。
5. **内核不再挂起 question**：含必答 → `paused` 收束；全非必答 → 继续。
6. **删除两处超时自动跳过**，收敛相关测试。

每一步先写验收测试再实现；只跑本次新增的相关测试。

## 十、实施进度

已落地并通过测试（79 项）：

- 信箱唤醒链路：`tags`/`wake`/`wake_count` 三列与就地迁移、唤醒查询改信箱、启动后 claim、存量事件一次性迁移、未答复兜底。
- 成员完成/失败与子代理 `message` 均写唤醒消息；父回合只注入信箱，事件表降级为审计。
- question 数据模型：`id/title/description/type/required/options/placeholder` 与旧字段兼容、载荷校验。
- 内核：question 工具立即闭合、含必答以 `paused` 收束、全非必答继续执行。
- 新用户消息关闭仍打开的提问组（记为 `done`，保留关闭原因与时间）。
- 前端：提问不再接管输入栏，只把占位文字改为「有提问待处理」；审批仍变形输入栏。
- 删除前端与后端两处「提问 5 分钟自动跳过」。

第二轮补充：

- 子代理 `question` 改道父代理：成员提问写一条 `question` 唤醒消息并暂停自己，父代理用 `sub_agent_message` 回答；用户界面不出现成员提问。
- `sub_agent_message` 与成员 `message` 的工具描述补充「每次发送都会唤醒对方」。
- 用户消息可携带 `question_answers`，关闭组时把对应题级状态改写为 `answered`（后端能力已就绪）。
- 提问组投影为只读过程行（`runtime.question_group`），问题文本出现在时间线，回答走输入栏。

第三轮补充：

- Question Group 组件：同一组内渲染多题，单选/多选/纯文本，必答题未填时提交按钮禁用；组级一次「提交并继续」。
- 提交走标准消息：组件把答案拼成 `Q<n> <题目>：<回答>` 并作为一条普通用户消息发出，不经过审批通道。
- 组关闭后卡片保留，可「追加回答」；后端按同样的行格式把答案回填到题级状态。
- 投影把提问组识别为独立分片（`questionGroup`），不再落到审批卡分支。

仍未完成：

- 子代理问答的端到端验证（信箱与兜底已就位，尚未起真实子代理跑一遍）。
- 提问组在时间线里的位置目前跟随过程行，若需要独立气泡要再调投影 kind。
- 前端类型检查里仍有 27 个与本改造无关的既有错误（Ping 编辑器、demo、design-system 等）。
