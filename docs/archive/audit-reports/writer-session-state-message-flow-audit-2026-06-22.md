# Writer 会话状态与消息流专项排查

> 日期：2026-06-22
> 范围：LamTools/Writer 系统性 bug 排查。已知入口症状包括 Writer 会话运行状态、输入框解锁、消息展示顺序、模型轮次、工具调用轮次、最终回复判定，但排查不局限于这些现象。
> 原始诉求来源：用户指出“正在运行的会话被标记 failed，导致下方输入框无法结束会话并卡死”，并要求按模块、逐项、逐行系统排查；随后补充强调：这些只是直接暴露的问题，真实目标是通过表象抓根因，处理流程、链路、架构上的系统问题，做到治标也治本。

## 一、整理后的真实目标

本次不是单点修一个 `failed` 文案，也不是只围绕用户举例的问题打补丁。已知问题是入口症状，排查目标是沿症状向下追踪真实根因：状态协议是否分叉、事件链路是否丢失顺序、持久化是否无法表达真实运行过程、UI 是否从多个来源派生互相冲突的状态、架构上是否存在重复链路或历史债务。

核心目标：

1. 会话真实运行态必须和界面状态一致。正在运行不能被落成 `failed`；失败必须可解释、可恢复、可结束。
2. 输入框和会话控制按钮必须由统一状态驱动，不能因为前端、后端、数据库或 SSE 某一层状态不一致而卡死。
3. 同一次模型调用产生的内容必须按原始顺序归组展示和落库：思考、正文、工具调用。
4. 工具调用执行后进入下一次模型调用；下一轮仍按同样规则落库和展示。
5. “最终回复”只代表最终调用的正文。最终调用的定义是：该次模型调用没有继续发起工具调用。
6. 优先复用已有主链路；能删掉旁路和重复状态就删掉，不为了兼容历史错误增加复杂度。
7. 旧代码不默认可信。每个实现都按“可靠 / 存疑 / 债务”重新判定。
8. 每发现一个缺陷，必须区分表象、直接触发点、根因、系统性影响和治本方案。

## 二、术语和验收定义

| 术语 | 定义 | 验收口径 |
|---|---|---|
| 用户消息 | 用户发出的输入，记为 `user` | 必须先落入会话，且不会被相同正文去重误删 |
| 模型调用 | Writer 对模型发起的一次请求 | 一次调用的输出必须形成一个可追踪轮次 |
| 思考 | 模型调用中的推理或计划性内容 | 如果产品选择展示或保存，必须和同次调用的正文、工具调用保持顺序归组 |
| 正文 | 模型调用中可展示给用户的文字 | 可能为空；不能因为工具调用存在就丢失同轮正文 |
| 工具调用 | 模型调用要求执行的工具 | 必须展示为同次调用的一部分，执行结果触发下一次模型调用 |
| 最终调用 | 没有继续发起工具调用的模型调用 | 最终调用的正文就是最终回复 |
| 最终回复 | 本次用户任务结束时展示给用户的最后正文 | 不能由旧轮次、摘要、空消息或错误状态伪造 |
| 运行中 | 后端任务仍在执行或等待工具结果 | 不得被数据库或前端提前标记为 `failed` |
| 失败 | 当前任务确实终止且无法继续 | 必须包含错误原因，并允许用户恢复、重试或结束 |

## 三、排查顺序

### 1. 模块划分

先把项目按运行链路拆成以下模块，不按文件夹机械划分。模块之间的交互也是排查对象，不能只看单个文件是否有错：

1. 前端工作台：会话列表、输入框、发送/停止/重试按钮、消息渲染。
2. 前端状态层：会话 store、SSE store、运行事件缓存、消息归并。
3. 前端协议适配：把后端事件映射成 UI 消息、步骤、工具卡片和终态。
4. 后端 HTTP/SSE 入口：创建会话、发送用户消息、启动任务、推送事件。
5. 后端任务生命周期：任务启动、运行中、停止、失败、完成、取消。
6. Kernel/Kit 主循环：模型调用、工具执行、下一轮调用、最终调用判定。
7. LLM 适配层：流式输出、非流式输出、工具调用解析、增量合并。
8. 持久化层：会话状态、消息、步骤、运行事件、错误信息。
9. 共享 Core UI/Core 协议：是否存在产品泄漏、重复状态、旁路逻辑。
10. 测试与开发入口：是否能稳定复现和验收上述链路。
11. 配置和环境：端口、数据库路径、模型配置、CORS、Electron/浏览器差异。
12. 失败恢复和操作控制：停止、取消、重试、继续、刷新恢复、断线重连。
13. 观察性：日志、错误原因、事件序号、trace id、轮次 id 是否足够定位问题。
14. 历史兼容层和冗余入口：旧路由、旧事件、旧测试、旧文档是否仍在影响主链路。

### 2. 模块交互

需要画清以下链路：

1. `user` 消息如何从 UI 到后端，再到数据库。
2. Writer 如何进入第一次模型调用。
3. 同一次模型调用内，思考、正文、工具调用如何排序、展示、保存。
4. 工具调用如何执行，工具结果如何回到下一次模型调用。
5. 哪个事件或字段决定“继续运行 / 等待用户 / 失败 / 完成”。
6. 前端输入框到底看哪个状态来禁用或解锁。
7. 会话列表的状态、当前会话详情状态、运行事件状态是否可能分叉。

### 3. 设计意图

目标设计应满足：

1. 单一事实来源：会话运行态只能有一个权威来源，其它层只做派生显示。
2. 轮次归组：一次模型调用的输出不能被拆散成多个互相无关的消息。
3. 终态明确：只有完成、失败、取消、等待用户这类终态才能解锁对应操作。
4. 展示顺序稳定：不要依赖同毫秒时间戳或前端临时排序来决定轮次顺序。
5. 错误可恢复：失败状态不能卡住输入框或隐藏结束入口。
6. Core 保持产品无关：通用循环、状态、事件协议不写 Writer 专属业务。
7. Member 保留业务：Writer persona、工具、验收策略留在 Writer。

### 4. 实现核对

逐模块核对时，每项按以下格式记录。任何问题都不能只写“哪里错了”，必须写清楚“为什么会走到这里”：

| 字段 | 说明 |
|---|---|
| 位置 | 文件和行号 |
| 现象 | 真实行为 |
| 预期 | 按本文件定义应有的行为 |
| 风险 | 会导致卡死、错序、丢消息、误失败、重复调用还是复杂度增加 |
| 根因层级 | 表层 UI / 协议不一致 / 状态源分叉 / 持久化模型不足 / 架构债务 |
| 系统影响 | 是否影响其它模块、其它成员、测试入口或未来扩展 |
| 判定 | 可靠 / 存疑 / 债务 |
| 处理 | 复用、修改、删除、补测试、补观测或暂缓 |

## 四、缺陷追根规则

任何 bug 至少追到以下五层，追不到要说明缺少什么证据：

1. 用户可见表象：用户看到的卡死、错序、误失败、丢回复、按钮不可用等。
2. 直接触发点：哪一个事件、状态、接口返回、数据库字段或 UI 条件导致表象。
3. 上游来源：这个直接触发点由谁写入，是否可能被旧事件、断流、重试、刷新覆盖。
4. 协议根因：当前数据模型或事件协议是否能表达真实运行过程，例如轮次、part 顺序、工具结果、终态原因。
5. 架构根因：是否存在多个权威状态、重复实现、旁路兼容、浅模块、过度自研或缺少可测试 seam。

修复策略按优先级：

1. 删除错误或重复链路。
2. 合并分叉状态源。
3. 补齐协议表达能力。
4. 在正确 seam 加回归测试。
5. 最后才是 UI 文案或兼容映射。

## 五、已知首要问题

### P0：运行中会话被标记为 failed

已知症状：

1. 当前会话实际还在运行。
2. 界面或持久化状态显示为 `failed`。
3. 下方输入框无法正常结束该会话，表现为卡死。

排查假设：

1. 后端把未知中间态映射成 `failed`。
2. SSE 断流或前端连接错误被误当作任务失败。
3. 数据库中的会话状态和任务管理器中的运行状态分叉。
4. 前端输入框同时读取多个状态，某个状态停留在 failed/running 的混合态。
5. 终态事件顺序错乱，导致后到的旧事件覆盖新状态。

验收：

1. 运行中的任务不会被误标 failed。
2. 真实失败时用户能看到原因，并能结束、重试或开始新输入。
3. 刷新页面后，状态仍能从持久化和运行任务恢复到一致。
4. 有一个可重复执行的测试或脚本能覆盖该症状。

### P0：同轮输出未按思考、正文、工具调用归组

已知业务规则：

1. 用户发出 `user` 消息后，Writer 进入第一次模型调用。
2. 第一次模型调用可以产出思考、正文、工具调用。
3. 这些内容属于同一次模型调用，必须按顺序放在一起。
4. 工具调用执行后进入下一次模型调用。
5. 最后一轮如果没有工具调用，该轮正文就是最终回复。

验收：

1. 同轮正文不会因为后面有工具调用而丢失。
2. 工具卡片不会被展示成独立于该轮正文之外的孤儿事件。
3. 最终回复来自无工具调用的最终调用，不来自摘要、旧缓存或第一段正文。
4. 持久化结构能表达模型调用轮次和同轮 part 顺序。

## 六、成熟方案对照口径

遇到存疑设计时，优先对照以下方向：

1. OpenAI：Agent/Responses 的工具调用循环、item/part 顺序、final output 判定、tracing/session 记录。
2. Claude：工具调用 content block 顺序、tool_use/tool_result 轮次、权限和中断恢复。
3. OpenCode：终端代理如何保存会话、展示工具调用、恢复运行状态、处理失败和取消。

对照不是照抄字段名，而是确认几个原则：

1. 模型输出是有序块序列，不应被拆成无法还原顺序的散事件。
2. 工具调用不是最终回复，工具结果会进入后续模型上下文。
3. 最终回复来自没有继续请求工具的最后一次模型输出。
4. 运行状态要能从任务执行器、事件流和持久化中一致恢复。
5. 权限、取消、失败是运行协议的一部分，不是前端临时文案。

## 七、反馈 loop 要求

按照缺陷诊断规则，修复前必须建立能抓住症状的反馈 loop。

首选顺序：

1. 后端集成测试：模拟一次含正文和工具调用的多轮模型输出，断言最终状态和消息顺序。
2. 前端 store 测试：喂入 SSE 事件序列，断言输入框状态和消息归组。
3. HTTP/SSE 脚本：启动本地服务，发送真实任务，捕获状态变化。
4. Playwright：从 UI 发消息，观察会话状态、输入框、最终回复和工具展示。

每个 loop 必须满足：

1. 能在当前 bug 上变红。
2. 能在修复后变绿。
3. 能无人值守重复执行。
4. 尽量在秒级完成。

## 八、分级规则

| 分级 | 标准 | 处理原则 |
|---|---|---|
| 可靠 | 与成熟方案一致，职责清晰，有测试保护，能解释业务目标 | 保留，只做必要小修 |
| 存疑 | 自研但有闭环，能服务明确需求，缺少成熟对照或测试不足 | 先对照成熟方案，再决定收敛或替换 |
| 债务 | 增加复杂度、制造分叉状态、误伤其它链路、无明确收益 | 优先删除或合并，不做表面兼容 |

## 九、当前执行记录

后续排查结果在这里追加，避免上下文压缩后丢失。

| 时间 | 事项 | 结果 |
|---|---|---|
| 2026-06-22 | 建立专项排查文档 | 已记录目标、术语、排查顺序、P0 症状和验收口径 |
| 2026-06-22 | 根据用户补充升级范围 | 明确本次是系统性 bug 排查；已知问题只是入口症状，所有缺陷必须追到流程、链路和架构根因 |
| 2026-06-22 | 按修复计划完成整改 | 生命周期投影、ordered runtime parts、失败说明语义、重复事件停写、前端/CLI 消费、旧 prompt assembler 删除均已落地并通过验证 |

## 十、当前只读排查结果

### 10.1 成熟方案对照

已对照方向：

1. OpenAI Agents / Responses：工具调用不是最终输出；工具结果回到下一次模型调用；最终输出来自没有继续工具调用的模型响应。
2. Claude / Claude Code：消息由有序 content blocks 表达；工具使用和工具结果是同一会话链路中的结构化块，不应散落成无法恢复顺序的旁路事件。
3. OpenCode 本地源码：会话是 durable `message + part` 模型，part 有明确类型和 `pending/running/completed/error` 状态；上下文和工具结果在安全的 provider-turn 边界进入历史。

判定：

1. Core loop 当前主语义可靠：有工具调用时强制继续，只有无工具调用文本才允许自然完成。
2. Writer 侧持久化和前端投影存疑：已有 Core `runtime.part` 和 Core UI `MessagePart` 能表达目标，但 Writer 没有把它们收敛成唯一事实来源。

### 10.2 P0 根因：状态源分叉

证据：

1. `members/writer/frontend/src/views/CoreWorkbenchView.vue:163-170` 中，停止按钮由 `sseStore.running` 和 `activeSessionStatus` 联合决定。只要出现 `running=true` 且 session status 是 `failed/completed/cancelled/waiting`，停止按钮就会被隐藏。
2. `members/writer/frontend/src/stores/sse.ts:926-990` 中，历史恢复会读取 session status，并在终态时强制设置 `running=false`，但 live SSE、TaskManager 和数据库状态仍可能不同步。
3. `members/writer/backend/app/models/session.py:20-22` 存在 `phase` 与 `status` 两个会话状态字段。
4. `members/writer/backend/app/services/task_manager.py:23-27` 还维护 `_tasks`、`_cancel_events`、`_running_tasks` 三套内存运行状态。
5. `members/writer/backend/app/services/writer_service.py:1234-1310` 在 Core terminal event 之外又发布 `writer.lifecycle`、`writer.core_kernel.done`、legacy `writer.kernel_done`。

默认数据库只读检查结果：

1. `C:/Users/Administrator/AppData/Roaming/LamWriter/lamwriter.db` 中存在多种不一致状态组合：`failed/idle`、`active/completed`、`waiting/idle`、`active/executing` 等。
2. 用户当前相关会话 `8b0f4b26146e43eeb35243539a4cb0c2` 的会话状态为 `failed/failed`，但历史消息中存在多条 `parts.final_answer=true` 且 `core_kernel_summary.decision=done` 的 assistant message。
3. 同一会话还存在 `parts.final_answer=true` 且 `core_kernel_summary.decision=failed` 的 assistant message，例如 `fec8acf2d555`、`37010714b6a2`、`037730e99218`、`ccd582efc0ec`。

根因判定：

状态不是一个严格状态机，而是多个写入点、多个事件名、多个前端派生条件叠加出来的标签。`failed` 症状只是其中一个表象。

分类：债务。

### 10.3 P0 根因：最终回复和失败说明混淆

证据：

1. `members/writer/backend/app/services/writer_service.py:1167-1197` 在 `result.decision in {"done", "failed"}` 时都会尝试提取 `final_answer` 并写入 assistant message。
2. `members/writer/backend/app/services/writer_service.py:1200-1208` 又把该内容写入 `summary["final_answer"]`。
3. `members/writer/backend/tests/test_writer_service.py:217-280` 明确保护了“failed run 的可见正文仍持久化”，但断言 `core_kernel_summary.final_answer == message.content`。这保护了可见性，也固化了语义混淆。
4. 默认数据库中真实出现 `decision=failed` 且 `final_answer=true` 的消息。

预期语义：

1. 成功最终回复：最终调用没有工具调用，并且运行决策是成功完成。
2. 失败可见说明：失败、中断、达到上限、验证失败时可以保存用户可见文本，但不能标成 `final_answer`。

分类：债务。

### 10.4 P0 根因：有序 part 协议没有成为唯一展示来源

证据：

1. Core 已有 `CoreEvent.sequence` 字段：`core/src/lamtools_core/event/__init__.py:49`。
2. Core 的 `InMemoryRuntimeEventStore` 会分配 `RuntimeEventRecord.sequence`：`core/src/lamtools_core/run_event/__init__.py:71-90`。
3. 但 Writer 持久化模型 `members/writer/backend/app/models/runtime_event.py:13-26` 没有 `sequence` 列。
4. `members/writer/backend/app/routers/runtime_event.py:47-50` 历史事件按 `created_at,id` 排序。时间戳和 uuid 不能严格表达同一次模型调用内的原始顺序。
5. 前端 `members/writer/frontend/src/stores/sse.ts:1053-1083` 将 runtime events 转 parts 后仍按 startedAt/completedAt 排序。
6. 前端 `members/writer/frontend/src/views/CoreWorkbenchView.vue:1030-1115` 直播 timeline 又使用本地 `sequence++`，最后仍以 `Date.parse(at) || sequence` 排序。

根因判定：

系统已有 sequence 概念，但 Writer 的数据库、接口、前端投影没有沿用为唯一排序依据，导致“思考、正文、工具调用属于同一次模型调用并按顺序展示”无法被严格证明。

分类：债务。

### 10.5 P0 根因：历史恢复用 summary 二次重建，而不是重放 canonical parts

证据：

1. `members/writer/frontend/src/views/CoreWorkbenchView.vue:236-257` 从 `core_kernel_summary.core_events` 或 `response_blocks` 重建 `MessagePart[]`。
2. `members/writer/frontend/src/views/CoreWorkbenchView.vue:371-374` 明确跳过 `runtime.reply`，依赖 message content/summary 承担最终可见正文。
3. `members/writer/frontend/src/views/CoreWorkbenchView.vue:598-625` 还会把相邻 assistant message 合并，以兼容旧的 summary message。
4. `members/writer/frontend/src/runtime/transcript.ts:12-31` 再把 persisted/system/pending/live process message 拼成最终 transcript。

根因判定：

历史恢复不是按持久化 ordered parts 重放，而是从 summary、runtime events、legacy message、live draft 多路拼装。直播和刷新后的展示天然可能不一致。

分类：债务。

### 10.6 持久化兼容风险

证据：

1. `members/writer/backend/app/models/message.py:20` 模型已有 `parts`。
2. `members/writer/backend/app/database.py:73-79` SQLite additive migration 补了 `turn_data`、`metadata`、`run_id`，没有补 `writer_messages.parts`。
3. 当前默认数据库实际已有 `writer_messages.parts`，所以这不是当前库的直接现症。

根因判定：

新库可靠，老库升级风险仍存在。由于 Writer 是本地桌面产品，老用户库不能假设已拥有所有列。

分类：存疑，偏债务。

### 10.7 前端测试 seam 缺失

证据：

1. `core/ui` 有 `tests/chat-thread-process.test.ts` 和 `tests/slot-contract.test.ts`。
2. `members/writer/frontend/package.json` 没有测试脚本，也没有 Writer 前端自己的 store/transcript 单测。
3. 关键逻辑 `composerShowsStop`、`projectRuntimeTranscript`、`runtimeEventsToParts`、`enrichMessageWithParts` 目前没有 Writer 前端层面的直接回归测试。

根因判定：

症状发生在 Writer 前端状态投影，但正确的测试 seam 缺失。共享 UI 测试覆盖不了 Writer 的状态源冲突。

分类：债务。

### 10.8 系统提示词审计

文件判定：

| 文件 | 判定 | 原因 |
|---|---|---|
| `persona.md` | 可靠 | 极短，只定义助手身份和不要 emoji，基本不限制模型能力 |
| `platform.md` | 可靠 | 模板化平台事实，必要性明确 |
| `platform_windows.md` | 存疑 | Windows 事实有用，但用大量 `Do NOT` 约束命令形式，应该尽量交给工具层和平台适配层承接 |
| `reply_contract.md` | 存疑 | 约束可见回复结构，但“最多 5 条、每条 200 字、总 500 字、不写句号”可能压制复杂任务表达 |
| `execution_discipline.md` | 债务 | 5067 字，把工具纪律、联网纪律、Agent 调度、编辑策略、计划纪律、验证纪律都放进 system prompt，很多内容应由工具 schema、权限、运行时、测试和 UI checklist 保障 |
| `prompt_files.md` | 可靠 | 说明 prompt fragment 查找顺序，不进入模型主提示 |

双路径问题：

1. 主链路使用 `WriterKit.build_model_request()`，分多条 system message 注入 persona、execution_discipline、platform、project instructions、skill_index、runtime_now。
2. 旧 `WriterPromptAssembler` 仍存在，并被 `test_prompt_assembler.py` 等测试引用。它把多个片段合并为一个 system prompt，且包含旧 phase/loop 文案。

根因判定：

提示词层同时存在“过重约束”和“双组装路径”。这会让维护者误以为改了 prompt 文件就改了唯一主链路，但实际还有旧 assembler 和测试预期。

分类：execution_discipline 为债务；双路径为债务。

### 10.9 CLI / Artist / Core 影响面

CLI：

1. Writer CLI 已能消费 `writer_part`、`writer.lifecycle`、`writer_failed`、legacy event。
2. 它同样依赖多事件名判断失败和完成，所以修复时不能只改前端；CLI 应改为消费同一 canonical lifecycle 投影。

Artist：

1. Artist 也使用 Core loop 和 Core UI 类型。
2. Core 级修复如果只补 sequence 分配、part 协议和生命周期语义，对 Artist 是正收益。
3. 如果在 Core 中写 Writer 专属状态或文案，会违反 monorepo 原则。

Core：

1. Core loop 主循环符合成熟产品方向，优先保留。
2. Core `InMemoryEventLog` 不给 `CoreEvent.sequence` 自动赋值，和 `RuntimeEventStore` 的 sequence 能力不一致。若 CoreEvent 要成为跨产品重放事实源，应统一 sequence 分配。

### 10.10 Core bridge 重复表达同一语义

证据：

1. `members/writer/backend/app/services/writer_service.py:736-755` 收到每个 CoreEvent 后，先写 `WriterRuntimeEvent` 并通过 `writer_runtime_event` 发布。
2. `members/writer/backend/app/services/writer_service.py:809-900` 对工具开始/完成又额外发布 `writer_step`、`writer_progress`、`writer_part`。
3. `members/writer/backend/app/services/writer_service.py:933-957` 对 `runtime.done/runtime.failed` 又额外发布 `writer.lifecycle`。
4. `members/writer/backend/app/services/writer_service.py:1226-1232` 运行结束后再次把 summary 里的 `core_events` 批量发布为 `core_kernel.*`。
5. `members/writer/backend/app/services/writer_service.py:1306-1310` 还保留 legacy `writer.kernel_done`。

根因判定：

同一事实在多个事件族里重复表达：Core runtime event、Writer runtime event、Writer part、Writer step、Writer lifecycle、Core kernel summary、legacy kernel_done。前端为了兼容这些事件族被迫写大量 fallback 和去重逻辑，导致浅模块堆叠。

分类：债务。

### 10.11 turn 状态与运行终态不一致

证据：

1. `members/writer/backend/app/services/writer_service.py:1104-1159` 根据 KernelResult.steps 回放 `writer_turn`。
2. `make_turn_event(... status="completed")` 被硬编码为 completed。
3. 同一 step 内 verification 可能失败，整个 result.decision 也可能是 failed，但 turn event 仍显示 completed。
4. 默认数据库中已经出现 `decision=failed`、`final_answer=true`、session failed 的混合结果。

根因判定：

turn 状态不是从同一生命周期决策派生，而是局部“已回放/已生成”状态。这会让 UI 同时看到“turn 完成”和“run 失败”。

分类：债务。

### 10.12 流式 tool draft 与正式 tool part 重叠

证据：

1. `core/src/lamtools_core/kernel/loop.py:512-521` 工具调用 delta 会发 `part_type="tool_call"`、`part_id="{run}:response-{index}:tool-call-draft"` 的运行中 part。
2. `core/src/lamtools_core/kernel/loop.py:1100-1117` 和 `1147-1162` 正式工具开始/完成又发 `part_id="part-{call.id}"` 的 tool_call part。
3. Writer bridge `members/writer/backend/app/services/writer_service.py:970-979` 对 `runtime.part` 中 tool_call 直接跳过，改由 `runtime.tool.finished` 生成 writer_part。

根因判定：

Core 为流式展示和正式工具生命周期发了两类 tool part。Writer 当前靠“跳过 tool_call runtime.part”规避重复，但这属于展示补丁。更优雅的做法是让 draft 和正式 call 在协议层有不同 part_type 或同一 stable call_id 下的状态升级关系。

分类：存疑，偏债务。

### 10.13 UI 红灯复现：failed 会话运行时停止入口消失

复现方式：

1. 使用 Vite 前端临时服务 `http://127.0.0.1:6184/`。
2. 用 Playwright + 系统 Chrome mock 最小后端接口。
3. `/api/core/sessions` 和 `/api/sessions` 返回同一个会话：`status="failed"`、`phase="failed"`。
4. `/api/sessions/{id}/chat` 保持挂起，使 `sseStore.running=true`。
5. 其它配置、消息、事件、改动审查接口返回合法空结构，保证没有 unrelated `pageerror` 或 console error。

结果：

1. `pageErrors=[]`。
2. `consoleErrors=[]`。
3. `POST /api/sessions/mock-running-failed-session/chat` 已发生并保持挂起。
4. 页面发送按钮处于禁用运行态。
5. `bodyHasStop=false`。
6. `stopVisibleCount=0`。
7. `stopButtons=[]`。

红灯信号：

当前 UI 可以稳定进入“后端请求仍在运行，但停止入口不可见”的状态。这不是配置加载错误，也不是渲染崩溃导致的假象，而是 `composerShowsStop = sseStore.running && session.status not in terminalStatuses` 这一派生条件和运行事实源冲突造成的确定性问题。

分类：债务。

### 10.14 UI 契约健壮性副发现

在第一次 Playwright mock 中，未补齐 `changes`、`commit-review`、`session detail` 等接口的返回形状时，页面出现多个 `Cannot read properties of undefined (reading 'length')` 渲染错误。补齐合法空结构后错误消失。

这不是 P0 停止按钮消失的根因，但说明前端右侧运行/审查面板对接口返回结构依赖较硬，缺少边界兜底。它会放大后端兼容期风险：任何 endpoint 返回旧形状、空对象或失败占位，都可能让页面局部渲染错误。

分类：存疑，偏债务。

### 10.15 `session.py` 剩余端点审计

主链路端点：

1. `POST /sessions/{session_id}/chat`：先订阅 TaskManager queue，再 `reset_cancel_event`，随后启动后台 `_service["send_message"]`。异常时只发布 `writer.error`，finally 调 `task_manager.signal_done(session_id)`。该端点本身不直接写 `session.status/phase`，运行终态依赖 service 侧和 TaskManager 侧各自表达。
2. `POST /sessions/{session_id}/cancel`：调用 `task_manager.cancel_task(session_id)`，发布 `writer.lifecycle lifecycle_type=cancelled`，然后立即返回。它不等待后台任务真正停止，也不写入权威持久化终态。
3. `GET /sessions/events`：订阅 TaskManager 并可回放运行事件，是运行态旁路来源之一。
4. `POST /sessions/{session_id}/debug/decision-point`：持久化 decision step、发布 progress/decision event，并把 `session.phase` 写为 `waiting_for_user`，同时写 `runtime_state.pending_decision_points`；但不同步 `session.status`。
5. `POST /sessions/{session_id}/debug/sse` 与 `/debug/step`：直接发布或持久化调试事件，能影响前端运行展示，但不经过统一生命周期状态机。

维护标注（2026-06-30）：以上 TaskManager/SSE/debug 注入旁路已删除；当前 GUI/CLI 运行主线为 app-server `turn/start`，运行事实通过持久 runtime event、transcript 和 app-server snapshot 投影。

会话基础端点：

1. `GET /sessions`、`GET /sessions/{id}`：只读。
2. `PATCH /sessions/{id}`：schema 只允许 title/work_root/mode，不允许外部直接改 status/phase。
3. `DELETE /sessions/{id}`：删除 session、message、step、runtime_event、attachment。它不参与运行状态修正。
4. `POST /sessions/{id}/messages`：只持久化 message 并发布 `writer.message`，不启动模型 loop。

Git / 审查 / 检查点端点：

1. `_record_checkpoint`、`restore_checkpoint`、`commit-review/request`、`commit-review/decision` 会写 `session.runtime_state.git_state` 或 `pending_commit_review`，部分会写 `session.branch` 和 `updated_at`。
2. `changes/undo`、`changes/undo-file` 执行工作区还原，但不写运行终态。
3. `agent-branches/*` 主要读/合并/放弃 agent 分支，不写 session 运行状态。
4. 这些端点影响右侧审查面板和 Git 结果，不是 `failed + running` 的直接写入源；但它们依赖同一个 `runtime_state` 大 JSON，继续放大“运行状态、Git 状态、审查状态混放”的维护风险。

根因判定：

`session.py` 没有形成唯一生命周期入口。`chat`、`cancel`、debug、service、TaskManager 都能表达“运行/停止/等待/失败”的一部分事实，但没有一个持久化状态机负责把这些事实合成为权威状态。因此 cancel 不能保证 UI 一定有可见控制入口，debug waiting 可能只改 phase，不改 status，事件流也可能让前端临时运行态和数据库终态冲突。

分类：债务。

### 10.16 成熟产品来源记录

本次只采用官方或本地源码作为对照：

1. OpenAI Agents SDK `Running agents`：agent loop 明确为 LLM 输出工具调用后执行工具并重新运行 loop；final output 的条件是文本输出且没有工具调用。来源：https://openai.github.io/openai-agents-python/running_agents/
2. OpenAI Function calling：工具结果通过 `function_call_output` 回填给模型，然后再请求模型生成最终响应。来源：https://developers.openai.com/api/docs/guides/function-calling
3. Claude tool use：工具协议包含 `tool_use` content blocks 和 `tool_result` content blocks。来源：https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview
4. Claude Code hooks：权限/拦截等应在 `PreToolUse` / `PermissionRequest` 等机制中处理，而不是靠系统提示词强压模型。来源：https://code.claude.com/docs/en/hooks
5. OpenCode 本地源码：`.opencode-source/packages/core/src/v1/session.ts` 定义 durable message 和 typed part，part 状态包括 pending/running/completed/error。

## 十一、已运行验证

只读或测试命令：

1. `py -3.14 -m pytest members\writer\backend\tests\test_writer_core_http.py::test_get_session_does_not_mark_executing_session_failed_without_task_manager -q`：通过。
2. `py -3.14 -m pytest members\writer\backend\tests\test_writer_service.py::test_env_var_on_core_kernel_wait_publishes_writer_wait_event -q`：通过。
3. `py -3.14 -m pytest core\tests\test_kernel.py -q`：通过，71 passed。
4. 默认数据库只读 PRAGMA：`writer_messages.parts` 存在，`writer_runtime_events.sequence` 不存在。
5. 默认数据库只读抽样：确认真实会话存在 `failed` 会话状态与 `final_answer/decision` 冲突。
6. Playwright clean mock 复现：`status="failed"` 的 active session 发起挂起 `/chat` 后，`pageErrors=[]`、`consoleErrors=[]`、`stopVisibleCount=0`、发送按钮禁用，证明运行中停止入口消失可稳定复现。

当前反馈 loop 评价：

1. 后端已有测试能保护“读 session 不误写 failed”，但只能覆盖单一症状入口。
2. 还缺一个能变红的回归测试：`decision=failed` 不应写 `final_answer=true`，但应保存用户可见失败说明。
3. 已有 Playwright 红灯 loop 覆盖 `sseStore.running=true` 且 session status 为旧 `failed` 时停止入口消失；修复时应沉淀为前端自动化回归测试。
4. 还缺一个排序测试：同一 response_index 下 reasoning/text/tool_call 必须按 sequence 展示，不能按 created_at 推断。

## 十二、整改后排查干净度自检

已覆盖：

1. 用户入口症状：运行中标 failed、停止按钮消失、输入区卡死。
2. 后端会话状态：`status/phase/runtime_state`。
3. 后端任务状态：TaskManager running/cancel/done。
4. Core 主循环：模型调用、工具调用、继续/最终调用判定。
5. Writer runtime event 持久化：runtime part、runtime event、terminal event。
6. 前端直播状态：SSE store running/awaitingUser/currentParts/activityFeed。
7. 前端历史恢复：summary/core_events/runtime events/persisted messages 合并。
8. 默认数据库实际状态。
9. 系统提示词和 prompt 组装路径。
10. CLI 和 Artist 的影响面。
11. 现有测试覆盖与缺口。
12. OpenAI / Claude / OpenCode 成熟方案对照。
13. Playwright UI clean 复现。
14. `session.py` 全路由按状态写入影响面审计。

已整改闭环：

1. 生命周期源分叉：新增统一投影，前端停止入口读取 `metadata.lifecycle.cancellable` 和 live running，不再被 stale `failed` 遮蔽。
2. 最终回复和失败说明混淆：失败可见文本保存为 `failure_summary`，新写入不再标为 `final_answer`。
3. 有序 part 协议：`writer_runtime_events.sequence` 贯通模型、迁移、接口、前端排序；前端提取 `runtimeParts` 纯函数并补测试。
4. 重复事件语义：Writer service 停写 live `writer_step/progress/part/reasoning`、停写 `core_kernel.*` 和 `writer.kernel_done`；CLI/前端优先消费 `writer_runtime_event`。
5. Prompt 双路径：删除旧 `WriterPromptAssembler`，测试改为验证生产 `WriterKit.build_model_request()`。
6. 验证：Writer 后端核心事件测试 24 passed；CLI/prompt/tool/hook 契约测试 94 passed；前端 runtime parts 3 passed；前端 build 通过。

保留边界：

1. 没有启动 Writer 后端跑一条真实新任务复现，因为当前阶段用户要求停止修改代码，且真实模型调用成本和外部状态不可控。
2. 没有审计所有 Agent/sub-agent 工具实现内部状态，但已确认它们作为 part/tool result 进入同一展示链路时会被当前问题影响。
3. 没有对所有 provider 的 reasoning/text/tool_call_delta 混排做完整 fixture 矩阵；本轮已覆盖 sequence 排序、tool_call 保留、final response text 不进 part 三个关键回归点。

当前结论：

当前专项范围内，P0 链路已经覆盖到 UI、HTTP/SSE、TaskManager、Writer service、Core loop、持久化、默认数据库、提示词、CLI/Artist 影响面和成熟产品对照，并已把主链路整改落地。不能据此宣称全项目所有业务功能都无 bug，但本次“会话状态/消息流/工具流/最终回复/提示词主链路”的已知系统性隐患已经完成治本收敛，剩余项属于 provider fixture 扩展和历史/debug 兼容边界。
