# Claude Code & OpenCode 源码调研 — LamImager 学以致用分析报告

> 调研日期：2026-05-14
> 源码版本：Claude Code 2.4.3 / OpenCode 1.14.50

## 一、调研概览

| 项目 | 技术栈 | 定位 |
|------|--------|------|
| **Claude Code 2.4.3** | TypeScript / Node / Ink (终端UI) / Anthropic SDK | Anthropic 官方 CLI 编程助手 |
| **OpenCode 1.14.50** | TypeScript / Bun / Effect / SolidJS (终端UI) / Vercel AI SDK | 开源 AI 编程助手 |
| **LamImager** | Python 3.14+ / FastAPI / Vue3 / LangGraph | AI 图像生成管理器 |

两个项目虽然面向编程助手场景，但其架构模式（工具系统、消息模型、上下文管理、权限控制、流式处理等）对 LamImager 有大量可借鉴之处。

---

## 二、LamImager 当前架构痛点

基于对 LamImager 代码的深入分析，当前存在以下核心问题：

| 痛点 | 严重度 | 现状 |
|------|--------|------|
| **三套 Agent 执行逻辑并存** | 🔴 严重 | `agent_service.py` (legacy) / `graph_llm.py+graph_tools.py` (sidebar graph) / `generate_service.py` (agent mode graph)，工具执行逻辑大量复制 |
| **generate_service.py 巨型文件** | 🔴 严重 | 1230行，混合6种职责（普通生成/Agent生成/计划执行/搜索增强/Vision fallback/上下文构建） |
| **消息模型扁平** | 🟡 中等 | `messages` 表把所有内容塞进 `content` 文本 + `metadata` JSON，无法细粒度追踪工具调用状态、推理过程 |
| **AgentState 弱类型** | 🟡 中等 | 40个可选字段的 `TypedDict(total=False)`，节点间通过字典键隐式传递，无编译期检查 |
| **TaskManager 职责过载** | 🟡 中等 | 同时承担任务状态/SSE广播/Checkpoint/Graph存储/取消信号/并发信号量 |
| **缺少上下文压缩** | 🟡 中等 | 长会话 token 膨胀，仅靠 `PlanningContextManager` 6000 token 硬上限截断 |
| **工具执行无权限控制** | 🟡 中等 | LLM 可无限调用 `generate_image` 等有实际成本的工具 |
| **SSE 事件格式不统一** | 🟢 轻微 | snapshot 事件裸 `data:` 行，Agent 事件完整 `event:+id:+data:` 格式 |
| **Provider 解析逻辑重复** | 🟢 轻微 | `resolve_provider_vendor()` 在6+处调用，模式完全相同 |
| **缺少测试** | 🔴 严重 | 整个项目无自动化测试 |

---

## 三、Claude Code 核心架构分析

### 3.1 工具系统架构

**关键文件**：`src/Tool.ts`、`src/tools.ts`

**核心设计**：

- **泛型工具接口** `Tool<Input, Output, P>`：约30个方法，包括 `call()`、`description()`、`inputSchema`、`checkPermissions()`、`validateInput()` 等
- **能力声明**：每个工具通过 `isReadOnly()`、`isDestructive()`、`isConcurrencySafe()`、`shouldDefer`、`alwaysLoad` 声明自身特性
- **Fail-closed 默认值**：`buildTool()` 工厂函数的 `TOOL_DEFAULTS` 默认 `isConcurrencySafe=false`、`isReadOnly=false`、`isDestructive=false`，安全优先
- **工具池组装**：`assembleToolPool()` 合并内置工具 + MCP 工具，内置工具作为连续前缀保持 prompt cache 稳定性
- **延迟加载**：`shouldDefer` 标记的工具（如搜索类）延迟加载 schema，优化 prompt cache；`alwaysLoad` 标记的工具始终加载
- **权限上下文**：`ToolPermissionContext` 包含 `alwaysAllowRules`、`alwaysDenyRules`、`alwaysAskRules`，工具通过 `checkPermissions()` 自行判断

**工具数量**：40+ 内置工具，条件注册（通过 `feature()` 门控和 `process.env.USER_TYPE`）

### 3.2 Agent/Task 系统

**关键文件**：`src/Task.ts`、`src/tasks.ts`

**核心设计**：

- **TaskType 判别联合**：`local_bash | local_agent | remote_agent | in_process_teammate | local_workflow | monitor_mcp | dream`
- **Task 接口**：`{ name, type, kill(taskId, setAppState) }` — 多态 kill
- **TaskStateBase**：`{ id, type, status, description, toolUseId, startTime, endTime, outputFile, outputOffset, notified }`
- **ID 生成**：`generateTaskId()` = prefix + 8位随机小写字母数字
- **终端状态检测**：`isTerminalTaskStatus()` 判断 completed/failed/killed

### 3.3 Query Engine & 上下文管理

**关键文件**：`src/QueryEngine.ts`、`src/context.ts`、`src/query/`

**核心设计**：

- **QueryEngine** 类拥有查询生命周期和会话状态
- **QueryEngineConfig**：约30个字段（cwd, tools, commands, mcpClients, agents, canUseTool, customSystemPrompt, maxTurns, maxBudgetUsd 等）
- **submitMessage()**：AsyncGenerator，包装 canUseTool 进行拒绝追踪，构建系统提示，处理 memory mechanics prompt
- **上下文构建**：`getSystemContext()` memoized — 包含 git status（截断1000字符）、cache breaker 注入
- **不可变配置快照**：`QueryConfig` 每次 `query()` 调用创建不可变快照

### 3.4 成本追踪 & Token 预算

**关键文件**：`src/cost-tracker.ts`、`src/query/tokenBudget.ts`

**核心设计**：

- **Per-model 使用量追踪**：`ModelUsage` 包含 inputTokens、outputTokens、cacheRead、cacheCreation、webSearchRequests、costUSD
- **会话成本持久化**：`saveCurrentSessionCosts()` / `restoreCostStateForSession()` 通过项目配置存储
- **递归成本处理**：`addToTotalSessionCost()` 递归处理 advisor 使用量
- **90% 完成阈值**：`COMPLETION_THRESHOLD = 0.9`，使用量达预算90%时停止
- **递减收益检测**：连续3次续写且每次 delta < 500 token 时判定为递减收益，主动停止
- **BudgetTracker**：`continuationCount`、`lastDeltaTokens`、`lastGlobalTurnTokens` 追踪续写行为

### 3.5 权限 & Gate 系统

**关键文件**：`src/assistant/gate.ts`

**核心设计**：

- **双层门控**：构建时 `feature('KAIROS')` + 运行时 GrowthBook feature flag
- **ToolPermissionContext**：`alwaysAllowRules` / `alwaysDenyRules` / `alwaysAskRules`
- **工具级权限检查**：每个工具的 `checkPermissions()` 方法

### 3.6 Plan Mode

**关键文件**：`src/utils/plans.ts`、`src/utils/planModeV2.ts`

**核心设计**：

- **Word-slug 计划文件**：`getPlanSlug()` 懒生成 + 重试（MAX_SLUG_RETRIES=10）
- **路径遍历防护**：`getPlansDirectory()` memoized 带路径遍历校验
- **子 Agent 计划文件**：`getPlanFilePath(agentId?)` 支持 `-agent-{agentId}` 后缀
- **V2 Agent 数量**：1-3个（基于订阅等级）
- **PewterLedger 实验**：trim/cut/cap 控制计划文件大小

### 3.7 Hook 系统

**关键文件**：`src/utils/hooks/` 目录

**核心设计**：

- **多源 Hook**：`HookSource = EditableSettingSource | 'policySettings' | 'pluginHook' | 'sessionHook' | 'builtinHook'`
- **优先级排序**：`SOURCES` 数组顺序决定优先级（低索引=高优先级），plugin/builtin 优先级999
- **异步 Hook 注册表**：`AsyncHookRegistry` 全局 Map 追踪，默认15秒超时，`Promise.allSettled` 故障隔离
- **12+ Hook 事件**：PreToolUse、PostToolUse、PostToolUseFailure、PermissionDenied、Notification、UserPromptSubmit、SessionStart、Stop、StopFailure、SubagentStart、SubagentStop、PreCompact、PostCompact
- **Session Hook**：`SessionHooksState` 使用 Map（避免 O(N²) 的 Object.is 检查），`FunctionHook` 支持内存回调

### 3.8 Memory/上下文系统

**关键文件**：`src/memdir/` 目录

**核心设计**：

- **MEMORY.md 入口文件**：MAX_ENTRYPOINT_LINES=200、MAX_ENTRYPOINT_BYTES=25KB，自动截断并附加 WARNING
- **四类记忆**：user（用户偏好）/ feedback（反馈）/ project（项目知识）/ reference（参考资料）
- **陈旧度检测**：`memoryAge.ts` 基于 mtime 判断记忆是否过时
- **递归扫描**：`memoryScan.ts` 递归扫描 + frontmatter 解析，200文件上限
- **每日日志模式**（KAIROS）：append-only 日期命名日志，夜间蒸馏到 MEMORY.md

### 3.9 Skill 系统

**关键文件**：`src/skills/` 目录

**核心设计**：

- **多源加载**：managed / user / project / additional / legacy 目录
- **Frontmatter 解析**：`parseSkillFrontmatterFields()` 提取 displayName、description、allowedTools、whenToUse、model、hooks 等
- **条件激活**：`paths` frontmatter 使用 `ignore` 库（gitignore 风格匹配），当工作文件匹配时自动激活
- **动态发现**：`discoverSkillDirsForPaths()` 从文件路径向上查找到 cwd
- **去重**：通过 `realpath` 解析符号链接去重，first-wins 排序
- **MCP Skill**：`fetchMcpSkillsForClient()` 发现 `skill://` MCP 资源

### 3.10 Proactive 主动模式

**关键文件**：`src/proactive/` 目录

**核心设计**：

- **状态机**：inactive → active → paused → inactive
- **Tick 机制**：每30秒注入 `<tick>HH:MM:SS</tick>` 提示，让 LLM 自主决定是否行动
- **Runaway 防护**：`contextBlocked` 标志防止 tick→error→tick 无限循环
- **Listener 模式**：`Set<() => void>` + `subscribeToProactiveChanges()`

### 3.11 流式传输

**关键文件**：`src/utils/stream.ts`

**核心设计**：

- **Stream\<T\> 类**：实现 AsyncIterator，单消费者队列
- **Promise 阻塞读取**：`enqueue(value)`、`done()`、`error()`
- **一次性迭代守卫**：`started` 标志防止多次迭代

### 3.12 状态管理

**关键文件**：`src/state/` 目录

**核心设计**：

- **泛型 Store**：`createStore<T>()` + `Object.is` 跳过不变更新
- **React 集成**：`useSyncExternalStore` + selector 模式
- **AppState**：50+ 字段，`DeepImmutable` 包装确保不可变

---

## 四、OpenCode 核心架构分析

### 4.1 项目结构

**技术栈**：TypeScript / Bun / Effect 生态 / SolidJS (终端UI) / Vercel AI SDK / Drizzle ORM (SQLite)

**Monorepo 结构**：

```
packages/
├── opencode/     — 主应用（CLI + TUI + 后端逻辑）
├── llm/          — 独立的 LLM 路由层（Protocol/Route/Transport）
└── core/         — 共享核心库（@opencode-ai/core）
```

### 4.2 Agent/LLM 集成

**关键文件**：`src/agent/agent.ts`、`src/session/llm.ts`、`src/session/prompt.ts`

**核心设计**：

- **Agent 即权限配置**：每个 Agent 本质上是一组权限规则 + 提示模板 + 模型配置
- **Agent.Info 结构**：name、mode（primary/subagent/all）、permission（Ruleset）、prompt、model、temperature、steps（最大步骤数）
- **内置 Agent**：build（默认）、plan（禁止编辑）、explore（只读）、scout（文档研究）、compaction（无工具）、title/summary（隐藏）
- **Doom Loop 检测**：连续3次相同工具+相同参数时触发权限询问
- **LLM 调用流程**：`LLM.Service.stream()` → Vercel AI SDK `streamText()` → Effect Stream

### 4.3 Part 消息模型

**关键文件**：`src/session/message-v2.ts`

**核心设计**：

- **消息与 Part 分离**：消息只存元数据，实际内容通过 Part 数组承载
- **13 种 Part 类型**：TextPart、ToolPart（状态机 pending→running→completed/error）、ReasoningPart、SubtaskPart、FilePart、CompactionPart、StepStartPart/StepFinishPart、SnapshotPart、PatchPart、AgentPart、RetryPart
- **ToolPart 状态机**：pending（raw 输入流）→ running（解析后输入）→ completed（输出、附件、耗时）或 error
- **增量更新**：`updatePartDelta()` 只发送增量文本
- **压缩过滤**：`filterCompacted()` 重排消息顺序，摘要放在 tail 之前

### 4.4 上下文压缩

**关键文件**：`src/session/compaction.ts`

**核心设计**：

- **Head/Tail 分割**：`select()` 将消息分为 head（需要压缩）和 tail（保留原文，默认2轮）
- **保留预算**：`preserve_recent_tokens = min(8000, max(2000, usable × 0.25))`
- **增量摘要**：基于上一轮摘要 + 新增内容生成7段式结构化摘要（Goal/Constraints/Progress/Decisions/Next Steps/Critical Context/Relevant Files）
- **渐进式修剪**：`prune()` 从后向前遍历工具输出，保留最近 40K token（PRUNE_PROTECT），旧输出标记 compacted
- **溢出检测**：`isOverflow()` 当 token 超过可用上下文窗口时自动触发
- **自动继续**：压缩完成后注入合成用户消息让 LLM 无缝继续

### 4.5 权限模型

**关键文件**：`src/permission/` 目录

**核心设计**：

- **三态动作**：`allow`（允许）/ `deny`（拒绝）/ `ask`（询问用户），默认 `ask`
- **最后匹配优先**（last-match-wins）：`evaluate()` 扁平化规则集，`findLast` 查找最后匹配规则
- **通配符匹配**：`Wildcard.match()` 支持 `*` 和 `?`，路径分隔符统一为 `/`
- **权限请求流程**：`ask()` → 遍历 pattern → 评估规则 → deny 立即拒绝 / allow 直接通过 / ask 挂起等待
- **用户响应**：`once`（仅本次）/ `always`（永久允许并写入 approved 规则集）/ `reject`（拒绝所有待审请求）
- **工具禁用**：`disabled()` 检查 `pattern=*` 且 `action=deny` 的规则

### 4.6 工具定义框架

**关键文件**：`src/tool/tool.ts`、`src/tool/registry.ts`

**核心设计**：

- **Def 接口**：id、description、parameters（Effect Schema）、execute(args, ctx)、formatValidationError
- **Context 接口**：sessionID、messageID、agent、abort、callID、messages、metadata()、ask()
- **ExecuteResult**：title、metadata、output、attachments
- **Schema-first**：所有工具参数使用 Effect Schema 定义，编译一次后缓存解码器
- **自动截断**：`Truncate.Service` 自动截断过长输出，防止上下文溢出
- **MCP 工具转换**：`convertMcpTool()` 转为 AI SDK `dynamicTool`，命名格式 `sanitize(clientName) + "_" + sanitize(toolName)`

### 4.7 流式事件处理器

**关键文件**：`src/session/processor.ts`

**核心设计**：

- **ProcessorContext**：toolcalls 映射、shouldBreak、snapshot、blocked、needsCompaction、currentText、reasoningMap
- **事件处理**：基于 `value.type` 的 switch 分发（text-start/delta/end、tool-call/result/error、start-step/finish-step 等）
- **Doom Loop 检测**：检查最近3个 Part 是否都是同一工具的相同输入调用
- **流处理管道**：`Stream.tap(handleEvent) → Stream.takeUntil(needsCompaction) → Effect.retry → Effect.catch → Effect.ensuring(cleanup)`
- **清理逻辑**：完成未关闭的 Part，等待活跃工具调用（250ms 超时），未完成标记为 error

### 4.8 配置系统

**关键文件**：`src/config/config.ts`

**核心设计**：

- **9层配置叠加**（优先级从低到高）：内置默认 → 全局配置 → 远程配置 → 项目配置 → .opencode 目录 → 环境变量 → 账号配置 → MDM 管理 → 命令行标志
- **深度合并**：`remeda.mergeDeep`，instructions 数组去重合并
- **变量替换**：`ConfigVariable.substitute()` 支持环境变量引用
- **JSONC 支持**：读写时保留注释
- **缓存与失效**：全局配置无限期缓存，`invalidate()` 手动触发重载

### 4.9 Effect 服务模式

**核心设计**：

- **Context.Service + Tag**：`@opencode/ServiceName` 全局唯一标识
- **Layer 依赖注入**：`Layer.effect(Service, Effect.gen(...))` + `Layer.provide()` 组合
- **InstanceState**：`InstanceState.make()` 按项目目录隔离状态，`ScopedCache<string, A>` 以目录为 key
- **SyncEvent 事件溯源**：版本化事件类型 + Projector 投影函数 + 序列号幂等重放
- **Bus 发布/订阅**：`BusEvent.define()` 类型安全事件 + 双层 PubSub + GlobalBus 跨项目广播

---

## 五、可借鉴模式详解（按优先级排序）

### P0：Part 消息模型（来自 OpenCode）

**问题**：LamImager 的 `messages` 表用 `content: str` + `metadata_: str(JSON)` 存储一切，前端需要解析 `metadata.type` 来判断如何渲染，无法细粒度追踪工具调用生命周期。

**OpenCode 方案**：消息由多个 Part 组成，每条消息是一个 Part 容器：

```
Message = { id, role, model, tokens, cost, ... } + [Part, Part, Part, ...]
```

| Part 类型 | 用途 | LamImager 对应场景 |
|-----------|------|-------------------|
| `TextPart` | 文本内容 | 用户输入、LLM 文本回复 |
| `ToolPart` | 工具调用（pending→running→completed/error） | `web_search`、`generate_image` 调用 |
| `ImagePart` (新增) | 图片结果 | 生成的图片 URL + 参数 |
| `ReasoningPart` | 推理过程 | planner_node 的思考链 |
| `StepPart` | 步骤边界 | executor 的每步执行 |
| `CheckpointPart` | 检查点 | checkpoint 中断/恢复 |

**LamImager 适配方案**：

```python
class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str
    synthetic: bool = False

class ToolPart(BaseModel):
    type: Literal["tool"] = "tool"
    call_id: str
    tool_name: str
    state: Literal["pending", "running", "completed", "error"]
    input_: dict | None = None
    output: str | None = None
    error: str | None = None

class ImagePart(BaseModel):
    type: Literal["image"] = "image"
    urls: list[str]
    parameters: dict | None = None

Part = Annotated[Union[TextPart, ToolPart, ImagePart, ...], Discriminator("type")]
```

**收益**：
- 前端 `AgentStreamCard` 可直接按 Part 类型渲染，不再解析 `metadata.type`
- 工具调用有 `pending→running→completed` 状态机，前端可展示"正在执行"
- 每个 Part 独立更新（delta），减少数据库写入
- 为上下文压缩（prune 旧工具输出）奠定基础

---

### P0：流式事件处理器 / Processor（来自 OpenCode）

**问题**：LamImager 的 `TaskManager.publish()` 直接广播 `LamEvent`，没有 Part 级别的生命周期管理；取消任务时没有优雅清理未完成的工具调用。

**OpenCode 方案**：`Processor` 是一个状态机式流处理器，逐事件驱动 Part 生命周期：

```
LLM Stream → Processor.handleEvent()
    ├── text-start → 创建 TextPart
    ├── text-delta → 追加文本（增量更新）
    ├── text-end → 完成 TextPart
    ├── tool-call → 创建 ToolPart(running) + doom loop 检测
    ├── tool-result → 更新 ToolPart(completed)
    ├── tool-error → 更新 ToolPart(error)
    ├── start-step / finish-step → 步骤边界
    └── error → 异常处理
```

**关键特性**：
- **Doom Loop 检测**：连续3次相同工具+相同参数时触发权限询问
- **优雅清理**：`finally` 块完成未关闭的 Part，将未完成工具标记为 error
- **增量更新**：`updatePartDelta()` 只发送 delta，减少 DB 写入

**LamImager 适配方案**：

```python
class SessionProcessor:
    async def process(self, stream: AsyncGenerator[LamEvent, None]) -> None:
        try:
            async for event in stream:
                await self._handle_event(event)
                if self._ctx.needs_compaction:
                    break
        except RetryableError:
            async for event in self._retry_stream():
                await self._handle_event(event)
        finally:
            await self._cleanup()

    async def _cleanup(self) -> None:
        for call_id, entry in self._ctx.active_tool_calls.items():
            if entry.state == "running":
                entry.state = "error"
                entry.error = "Tool execution aborted"
                await self._session.update_part(entry.part_id, entry)
```

**收益**：
- SSE 事件有统一的 Part 生命周期，前端可精确渲染进度
- Doom loop 检测防止 LLM 无限循环调用同一工具
- 取消任务时优雅清理，不会留下"悬挂"的工具调用

---

### P1：上下文压缩 / Compaction（来自 OpenCode）

**问题**：LamImager 的 agent 模式在多轮迭代/辐射策略中，上下文迅速膨胀。当前仅靠 `PlanningContextManager` 的 6000 token 硬上限截断，丢失早期关键决策。

**OpenCode 方案**：三阶段压缩策略：

1. **Head/Tail 分割**：将消息分为 head（需要压缩的旧消息）和 tail（保留原文的近期消息，默认2轮）
2. **增量摘要**：基于上一轮摘要 + 新增内容生成结构化摘要（Goal/Progress/Decisions/Next Steps/Critical Context）
3. **渐进式修剪**：从后向前遍历工具输出，保留最近 40K token，旧输出标记为 `compacted` 并清空内容

**LamImager 适配方案**：

```python
class CompactionService:
    async def compact(self, session_id: str) -> None:
        messages = await self._get_messages(session_id)
        head, tail = self._select(messages, tail_turns=2, preserve_tokens=6000)

        summary = await self._generate_summary(head, previous_summary=...)

        await self._save_compaction(session_id, summary=summary, tail_start_id=tail[0].id)
        await self._prune_old_tool_outputs(session_id, protect_tokens=40000)
```

**收益**：
- 长会话不再 token 爆炸，结构化摘要保留关键决策
- 旧工具输出（搜索结果、图片URL列表）自动清理
- 增量摘要比简单截断更高效

---

### P1：权限模型 / Permission（来自 OpenCode + Claude Code）

**问题**：LamImager 的 agent 工具（`web_search`、`generate_image` 等）无权限检查，LLM 可以无限调用有实际成本的工具。

**OpenCode 方案**：三态权限 + 规则评估：

```
Action = allow | deny | ask
Rule = { permission, pattern, action }
```

- **最后匹配优先**（last-match-wins），类似 CSS 优先级
- **通配符匹配**：`generate_image:*` 匹配所有图片生成
- **用户响应**：`once`（仅本次）/ `always`（永久允许）/ `reject`（拒绝）

**Claude Code 方案**：工具声明式权限：

```typescript
// 每个工具声明自己的权限需求
isReadOnly(): boolean       // 只读工具不需要权限
isDestructive(): boolean    // 破坏性工具需要确认
checkPermissions(): Promise  // 自定义权限检查
```

**LamImager 适配方案**（结合两者）：

```python
class PermissionAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"

class PermissionRule(BaseModel):
    permission: str   # 工具名，支持通配符 "generate_image:*"
    pattern: str      # 参数模式，如 "*" 或 "count>1"
    action: PermissionAction

# 工具声明式权限
class GenerateImageTool(Tool):
    is_destructive = True  # 有成本
    cost_per_call = True   # 每次调用有费用

    async def check_permissions(self, args, ctx) -> PermissionCheck:
        if args.get("count", 1) > 4:
            return PermissionCheck(action=PermissionAction.ASK, reason="批量生成超过4张")
        return PermissionCheck(action=PermissionAction.ALLOW)
```

**收益**：
- `generate_image` 等有成本的工具可在执行前让用户确认
- 多 Agent 角色权限隔离（compaction agent 只读，build agent 可生成）
- 规则可持久化，用户选择"always"后不再重复询问

---

### P1：工具定义框架（来自 OpenCode + Claude Code）

**问题**：LamImager 的工具 `execute(**kwargs)` 接收透传参数，运行时注入 `db`、`api_key` 等依赖，调用方硬编码注入逻辑；工具无法声明自己需要什么依赖。

**OpenCode 方案**：声明式工具定义 + Context 注入：

```typescript
interface Def {
  id: string
  description: string
  parameters: Schema           // Effect Schema，运行时校验
  execute(args, ctx: Context): Effect<ExecuteResult>
}

interface Context {
  sessionID, messageID, agent, abort, callID, messages
  metadata(val): Effect       // 更新工具调用元数据
  ask(req): Effect            // 请求权限
}
```

**Claude Code 方案**：更丰富的工具能力声明：

```typescript
interface Tool {
  shouldDefer: boolean    // 延迟加载 schema（优化 prompt cache）
  alwaysLoad: boolean     // 始终加载（即使被延迟策略跳过）
  isConcurrencySafe: boolean  // 可并行执行
  maxResultSizeChars: number  // 输出截断阈值
  strict: boolean            // 严格参数校验
}
```

**LamImager 适配方案**：

```python
class ToolContext(BaseModel):
    session_id: str
    message_id: str
    db: AsyncSession  # 依赖注入，不再 **kwargs
    agent: str | None = None
    call_id: str | None = None

    async def metadata(self, title: str | None = None, **kwargs) -> None: ...
    async def ask_permission(self, permission: str, patterns: list[str]) -> None: ...

class ToolResult(BaseModel):
    title: str
    output: str
    metadata: dict[str, Any] = {}
    attachments: list[str] = []  # 图片 URL 等

class ToolDef(ABC):
    id: str
    description: str
    parameters: type[BaseModel]  # Pydantic model 作为 schema
    is_destructive: bool = False
    is_readonly: bool = False
    max_result_chars: int = 50000

    @abstractmethod
    async def execute(self, args: BaseModel, ctx: ToolContext) -> ToolResult: ...

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.id,
                "description": self.description,
                "parameters": self.parameters.model_json_schema(),
            }
        }
```

**收益**：
- 工具声明式依赖（`parameters: type[BaseModel]`），不再 `**kwargs` 透传
- 统一的 `ToolContext` 注入，消除6处重复的 provider 解析逻辑
- `is_destructive` / `is_readonly` 为权限系统提供基础
- `max_result_chars` 自动截断过长输出

---

### P2：Agent 定义模型（来自 OpenCode）

**问题**：LamImager 的 sidebar assistant 和 agent mode 使用同一套工具，没有角色区分；用户无法自定义 agent 行为。

**OpenCode 方案**：Agent = 权限规则集 + 提示模板 + 模型配置：

```typescript
interface AgentInfo {
  name: string
  mode: "primary" | "subagent" | "all"
  permission: Permission.Ruleset
  prompt?: string
  model?: { modelID, providerID }
  temperature?: number
  steps?: number  // 最大步骤数限制
}
```

内置 Agent 角色分明：`build`（默认，全权限）、`plan`（禁止编辑工具）、`explore`（只读）、`compaction`（无工具）。

**LamImager 适配方案**：

```python
class AgentMode(str, Enum):
    PRIMARY = "primary"
    SUBAGENT = "subagent"

class AgentDef(BaseModel):
    name: str
    mode: AgentMode
    description: str | None = None
    prompt: str | None = None
    model_override: dict | None = None
    allowed_tools: list[str] | None = None  # None = 全部
    max_steps: int | None = None
    permission: list[PermissionRule] = []

BUILTIN_AGENTS = {
    "build": AgentDef(name="build", mode=AgentMode.PRIMARY, allowed_tools=None),
    "explore": AgentDef(name="explore", mode=AgentMode.SUBAGENT,
                        allowed_tools=["web_search", "image_search"],
                        max_steps=5),
    "compaction": AgentDef(name="compaction", mode=AgentMode.PRIMARY,
                           allowed_tools=[], hidden=True),
}
```

**收益**：
- 不同 Agent 角色有不同工具权限和步骤限制
- 用户可通过配置文件自定义 Agent 行为
- `max_steps` 防止无限循环

---

### P2：Token 预算与成本追踪（来自 Claude Code）

**问题**：LamImager 的 `PlanningContextManager` 用 6000 token 硬上限，没有递减收益检测；成本追踪分散在各处。

**Claude Code 方案**：
- **90% 完成阈值**：使用量达预算90%时停止
- **递减收益检测**：连续3次续写且每次 delta < 500 token 时判定为递减收益，主动停止
- **Per-model 成本追踪**：`ModelUsage` 精确记录 input/output/cache_read/cache_creation/web_search 各类 token

**LamImager 适配方案**：

```python
class BudgetTracker:
    completion_threshold: float = 0.9
    diminishing_threshold: int = 500
    max_continuations: int = 3

    def check_budget(self, used: int, budget: int, continuation_count: int, last_delta: int) -> bool:
        if used >= budget * self.completion_threshold:
            return False  # 停止
        if continuation_count >= self.max_continuations and last_delta < self.diminishing_threshold:
            return False  # 递减收益，停止
        return True
```

**收益**：
- Agent 模式不再因 token 膨胀而失控
- 递减收益检测避免 LLM 在接近完成时浪费 token
- 精确的 per-model 成本追踪

---

### P2：Hook 系统（来自 Claude Code）

**问题**：LamImager 没有可扩展的事件钩子机制，所有行为变更都需要改代码。

**Claude Code 方案**：多源 Hook 配置 + 异步执行：

| Hook 事件 | 触发时机 | LamImager 对应场景 |
|-----------|---------|-------------------|
| `PreToolUse` | 工具执行前 | 图片生成前确认/拦截 |
| `PostToolUse` | 工具执行后 | 生成后自动下载/通知 |
| `UserPromptSubmit` | 用户提交 prompt 时 | 自动应用 skill/rule |
| `SessionStart` | 会话开始 | 加载上下文/恢复状态 |
| `Stop` | Agent 停止时 | 生成摘要/保存计划 |

**LamImager 适配方案**：

```python
class HookEvent(str, Enum):
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    SESSION_START = "session_start"
    AGENT_STOP = "agent_stop"

class HookConfig(BaseModel):
    event: HookEvent
    command: str | None = None      # Shell 命令
    callback: Callable | None = None  # Python 回调
    matcher: str | None = None       # 工具名匹配
    timeout: int = 15

class HookRegistry:
    async def run_hooks(self, event: HookEvent, context: dict) -> None:
        for hook in self._get_hooks(event):
            if hook.matcher and not fnmatch.fnmatch(context.get("tool", ""), hook.matcher):
                continue
            if hook.callback:
                await asyncio.wait_for(hook.callback(context), timeout=hook.timeout)
            elif hook.command:
                await self._run_command(hook.command, context, hook.timeout)
```

**收益**：
- 用户可在不修改代码的情况下扩展行为（如生成后自动下载）
- 工具执行前/后可插入自定义逻辑
- 为插件系统奠定基础

---

### P2：Skill 动态发现与条件激活（来自 Claude Code）

**问题**：LamImager 的 Skills 是静态的数据库记录，没有基于上下文的动态激活。

**Claude Code 方案**：
- **多源加载**：managed / user / project / additional / legacy 目录
- **Frontmatter 解析**：`whenToUse`、`allowedTools`、`paths`（条件激活）
- **条件激活**：`paths` 字段使用 gitignore 风格匹配，当工作文件匹配时自动激活
- **动态发现**：`discoverSkillDirsForPaths()` 从文件路径向上查找到 cwd

**LamImager 适配方案**：

```python
class SkillDef(BaseModel):
    name: str
    description: str
    when_to_use: str | None = None
    allowed_tools: list[str] | None = None
    strategy_hint: str | None = None
    prompt_bias: str | None = None
    activate_on: list[str] | None = None  # 条件：关键词匹配

class SkillDiscovery:
    async def discover_for_prompt(self, prompt: str) -> list[SkillDef]:
        all_skills = await self._load_all()
        active = []
        for skill in all_skills:
            if skill.activate_on:
                if any(kw in prompt for kw in skill.activate_on):
                    active.append(skill)
            else:
                active.append(skill)
        return active
```

**收益**：
- Skill 可基于用户输入自动激活，不需要手动选择
- `when_to_use` 让 planner_node 更智能地决定是否应用 skill
- 多源加载支持项目级/用户级 skill

---

### P3：Proactive 主动模式（来自 Claude Code）

**问题**：LamImager 的 Agent 只在用户主动触发时运行，没有"后台观察+主动建议"能力。

**Claude Code 方案**：
- **状态机**：inactive → active → paused → inactive
- **Tick 机制**：每30秒注入 `<tick>HH:MM:SS</tick>` 提示，让 LLM 自主决定是否行动
- **Runaway 防护**：`contextBlocked` 标志防止 tick→error→tick 无限循环

**LamImager 适配场景**：
- 生成完成后主动建议优化方向
- 长时间空闲后提醒用户继续未完成的任务
- 检测到新参考图时主动建议重新生成

---

### P3：Memory 持久记忆（来自 Claude Code）

**问题**：LamImager 的 Assistant 对话记忆仅存 localStorage，跨会话丢失；Agent 模式无跨会话记忆。

**Claude Code 方案**：
- **MEMORY.md 入口文件**：200行/25KB 上限，自动截断
- **四类记忆**：user（用户偏好）/ feedback（反馈）/ project（项目知识）/ reference（参考资料）
- **陈旧度检测**：基于 mtime 判断记忆是否过时
- **每日日志**：长会话的 append-only 日志，夜间蒸馏到 MEMORY.md

**LamImager 适配方案**：

```python
class MemoryService:
    async def load_memory(self, session_id: str) -> str:
        memory_dir = Path("data") / "memory" / session_id
        entrypoint = memory_dir / "MEMORY.md"
        if entrypoint.exists():
            content = entrypoint.read_text()
            return self._truncate(content, max_lines=200, max_bytes=25000)
        return ""

    async def save_memory(self, session_id: str, category: str, content: str) -> None:
        memory_dir = Path("data") / "memory" / session_id
        memory_dir.mkdir(parents=True, exist_ok=True)
        (memory_dir / f"{category}.md").write_text(content)
```

**收益**：
- Assistant 对话跨会话保留用户偏好
- Agent 模式可记住之前的决策和约束
- 为 Phase 3 的 preference/scoring 系统奠定基础

---

### P3：配置分层（来自 OpenCode）

**问题**：LamImager 的 `app_settings` 表是扁平的键值对，没有分层概念；配置变更需重启。

**OpenCode 方案**：9层配置叠加 + 深度合并 + 变量替换 + 热重载

**LamImager 适配方案**（简化版）：

```python
class ConfigLayer(Enum):
    DEFAULT = 0        # 代码内默认值
    GLOBAL = 1         # ~/.lamimager/config.json
    PROJECT = 2        # .lamimager/config.json
    DATABASE = 3       # app_settings 表
    ENV = 4            # 环境变量覆盖

class ConfigService:
    async def get(self, key: str) -> Any:
        for layer in reversed(ConfigLayer):
            value = await self._load_layer(layer, key)
            if value is not None:
                return value
        return None
```

**收益**：
- 支持环境变量注入 API key（`${LAMIMAGER_OPENAI_KEY}`）
- 项目级配置覆盖全局默认值
- 配置热重载无需重启

---

## 六、实施路线图

```
Phase 1 (基础骨架)
├── Part 消息模型 — 重构 messages 表，引入 parts 子表
├── 流式事件处理器 — 统一 SSE 事件生命周期
└── 工具定义框架 — ToolDef + ToolContext + 声明式权限

Phase 2 (核心能力)
├── 权限模型 — 三态权限 + 规则评估
├── Agent 定义模型 — 角色区分 + 步骤限制
├── 上下文压缩 — Head/Tail 分割 + 增量摘要
└── Token 预算 — 90%阈值 + 递减收益检测

Phase 3 (增强体验)
├── Hook 系统 — 可扩展事件钩子
├── Skill 动态发现 — 条件激活 + 多源加载
├── Memory 持久记忆 — 跨会话记忆
└── 配置分层 — 多层配置 + 热重载

Phase 4 (高级特性)
├── Proactive 主动模式 — Tick 驱动自主行动
├── Doom Loop 检测 — 防止 LLM 无限循环
└── 插件系统 — 基于 Hook 的扩展机制
```

---

## 七、核心洞察

1. **Part 消息模型是骨架**：OpenCode 的所有功能（压缩、权限、工具、Agent）都建立在 Part 消息模型之上。LamImager 应先实现 Part 模型，再逐步添加其他功能。

2. **Agent = 权限 + 提示 + 模型**：OpenCode 的 Agent 本质上是权限规则集 + 提示模板 + 模型配置，而非独立执行逻辑。LamImager 当前的三套 Agent 执行逻辑应统一为一个引擎，通过 AgentDef 配置区分角色。

3. **工具声明式能力**：Claude Code 的 `isReadOnly/isDestructive/shouldDefer/alwaysLoad` 让工具系统能自动做出权限和调度决策，而不需要每个调用点手动判断。

4. **增量优于全量**：OpenCode 的增量摘要、增量 Part 更新、delta 流式传输，都体现了"只发送变化量"的理念，对 LamImager 的 SSE 性能有直接帮助。

5. **递减收益检测**：Claude Code 的 `checkTokenBudget()` 在 LLM 连续续写但产出递减时主动停止，这个模式对 LamImager 的 iterative/radiate 策略特别有价值——当迭代改进不再显著时自动终止。

6. **Fail-closed 默认值**：Claude Code 的 `buildTool()` 工厂默认 `isConcurrencySafe=false`、`isReadOnly=false`、`isDestructive=false`，安全优先。LamImager 的工具系统也应采用同样的保守默认值策略。

7. **最后匹配优先**：OpenCode 的权限规则评估使用 `findLast`（最后匹配优先），这比"首次匹配优先"更灵活，允许后续规则覆盖前面的，类似 CSS 优先级模型。

8. **Effect 模式的 Python 等价物**：OpenCode 大量使用 Effect 的 Layer/Service/Stream 模式。在 Python/FastAPI 中，等价物是：依赖注入（FastAPI `Depends`）+ Pydantic Schema + async generator + asyncio.Event。不需要引入 Effect 本身，但可以借鉴其"声明式依赖 + 运行时解析"的理念。

9. **模型即 Agent，代码即 Harness**：learn-claude-code 的核心哲学——"The model IS the agent. Code just runs the loop."。LamImager 的 LangGraph 图不应试图用代码实现智能，而应构建好 Harness（工具、知识、观察、行动接口、权限），让 LLM 自行推理决策。当前的 `decision_node` 用硬编码分数阈值做决策，违背了这个哲学——应该让 LLM 自己判断。

10. **渐进式复杂度**：learn-claude-code 展示了从 Level 0（1个工具）到 Level 5（团队+自治+隔离）的渐进路径。LamImager 当前的 8 节点图直接跳到了较高复杂度，缺少中间层的验证。建议先确保 2 节点 sidebar 循环（Level 1）稳定，再逐步叠加 planner/critic/decision 等高级节点。

---

## 八、learn-claude-code 教学项目分析

> 源码路径：`docs/learning files/learn-claude-code-main/`
> 项目定位：Claude Code 架构的 Python 教学实现，从零到一逐步构建 Agent 系统

### 8.1 项目概览

learn-claude-code 是一个用 Python 实现的 Claude Code 架构教学项目，包含 12 个渐进式课程（s01-s12），每个课程都是**自包含可运行**的 Python 脚本。项目还包含配套文档（中/英/日三语）、Skill 模板和参考代码。

**核心哲学**：

> "The model IS the agent. Code just runs the loop."
> 模型本身就是 Agent，代码只是运行循环的 Harness。
> Harness = Tools + Knowledge + Observation + Action Interfaces + Permissions

### 8.2 渐进式架构演进

| 章节 | 核心机制 | 解决的问题 | 累积工具数 | 关键类/函数 |
|------|----------|-----------|-----------|------------|
| s01 | Agent Loop | 模型碰不到真实世界 | 1 (bash) | `agent_loop()` |
| s02 | Tool Dispatch | 单一工具不够用，加工具不改循环 | 4 | `TOOL_HANDLERS` dict, `safe_path()` |
| s03 | TodoWrite | 多步任务丢失进度 | 5 | `TodoManager`, nag reminder |
| s04 | Subagent | 上下文臃肿 | 5+task | `run_subagent()`, 30轮安全限制 |
| s05 | Skill Loading | 知识全塞系统提示太浪费 | 5+load_skill | `SkillLoader`, 两层注入 |
| s06 | Context Compact | 上下文窗口有限 | 5+compact | `micro_compact()`, `auto_compact()` |
| s07 | Task System (DAG) | 扁平清单无依赖、不持久 | 8 | `TaskManager`, `blockedBy`, `_clear_dependency()` |
| s08 | Background Tasks | 慢操作阻塞循环 | 6+bg | `BackgroundManager`, 通知队列 |
| s09 | Agent Teams | 单 Agent 干不完 | 9 | `MessageBus` (JSONL), `TeammateManager` |
| s10 | Team Protocols | 缺少结构化协调 | 12 | request_id 关联, FSM (pending→approved/rejected) |
| s11 | Autonomous Agents | 领导手动分配扩展不了 | 14 | IDLE 轮询, `claim_task()`, 身份重注入 |
| s12 | Worktree Isolation | 并行执行文件冲突 | 14+wt | `WorktreeManager`, `EventBus` (JSONL) |

### 8.3 关键模式详解与 LamImager 映射

#### 8.3.1 Agent Loop — 最小可行循环

**核心代码**：

```python
def agent_loop(messages: list):
    while True:
        response = client.messages.create(model=MODEL, system=SYSTEM, messages=messages, tools=TOOLS, max_tokens=8000)
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = []
        for block in response.content:
            if block.type == "tool_use":
                output = run_bash(block.input["command"])
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})
```

**LamImager 映射**：
- LamImager 的 sidebar 2 节点图（`agent_node` + `tools_node`）就是这个循环的 LangGraph 实现
- `stop_reason != "tool_use"` 对应 LangGraph 的条件边路由
- `AgentState` TypedDict 是 `messages` 列表的结构化升级
- **差异**：agent mode 的 8 节点图不是简单的 tool_use 循环，而是 intent→skill→context→planner→prompt_builder→executor→critic→decision 的流水线

#### 8.3.2 Tool Dispatch Map — 开闭原则

**核心代码**：

```python
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
}

handler = TOOL_HANDLERS.get(block.name)
output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
```

**LamImager 映射**：
- LamImager 的 `backend/app/tools/` 已实现类似模式，但注册逻辑硬编码在 `graph_tools.py`
- `safe_path()` 的路径沙箱直接对应 LamImager 的 SSRF 防护和路径遍历防护
- **改进**：引入声明式 dispatch map，新工具只需加 handler + 加 schema

#### 8.3.3 TodoWrite — 进度追踪与 Nag Reminder

**核心代码**：

```python
class TodoManager:
    def update(self, items: list) -> str:
        validated, in_progress_count = [], 0
        for item in items:
            status = item.get("status", "pending")
            if status == "in_progress":
                in_progress_count += 1
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress")
        self.items = validated
        return self.render()

# Nag reminder — 3轮不更新就注入提醒
if rounds_since_todo >= 3 and messages:
    last["content"].insert(0, {"type": "text", "text": "<reminder>Update your todos.</reminder>"})
```

**LamImager 映射**：
- `ExecutionPlan`（planner_node 生成）是 TodoWrite 的 LLM 驱动版
- **差异**：LamImager 的 plan 是 LLM 一次性生成的，Claude Code 的 todo 是模型在执行中动态更新的
- **可借鉴**：nag reminder 机制可用于 agent mode——executor 长时间不更新进度时注入提醒
- **可借鉴**：单焦点约束（同一时间只有一个 in_progress）与 `max_concurrent` 理念一致

#### 8.3.4 Subagent — 上下文隔离

**核心代码**：

```python
def run_subagent(prompt: str) -> str:
    sub_messages = [{"role": "user", "content": prompt}]  # 全新上下文
    for _ in range(30):  # 安全限制
        response = client.messages.create(model=MODEL, system=SUBAGENT_SYSTEM,
                                          messages=sub_messages, tools=CHILD_TOOLS, max_tokens=8000)
        sub_messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            break
        # execute tools, append results...
    return "".join(b.text for b in response.content if hasattr(b, "text"))  # 只返回摘要
```

**LamImager 映射**：
- `execute_multi_independent()` 的 `asyncio.gather` 并行执行与 Subagent 隔离思路一致
- **关键差异**：LamImager 的并行是代码驱动的，不需要独立 LLM 循环
- **可借鉴**：如果未来支持复杂并行任务（搜索+优化+生成），Subagent 模式可隔离各分支的 LLM 上下文
- **可借鉴**：摘要返回模式——`critic_node` 只输出 `CriticOutput`（评分+问题），不返回完整视觉分析

#### 8.3.5 Skill Loading — 两层知识注入 ⭐

**核心代码**：

```python
class SkillLoader:
    def get_descriptions(self) -> str:
        # Layer 1: 系统提示中只放名称和描述（~100 token/skill）
        lines = []
        for name, skill in self.skills.items():
            lines.append(f"  - {name}: {skill['meta'].get('description', '')}")
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        # Layer 2: 按需加载完整内容（~2000 token/skill）
        return f"<skill name=\"{name}\">\n{self.skills[name]['body']}\n</skill>"

# 系统提示只包含描述
SYSTEM = f"""You are a coding agent.
Skills available:
{SKILL_LOADER.get_descriptions()}"""

# load_skill 工具按需返回完整内容
TOOL_HANDLERS["load_skill"] = lambda **kw: SKILL_LOADER.get_content(kw["name"])
```

**LamImager 映射**：
- LamImager 当前是**全量注入**模式——所有激活 Skill 内容直接注入 planner_node 和 prompt_builder_node
- 10 个 Skill 每个 ~2000 token = 20,000 token，大部分与当前任务无关
- **直接可借鉴**：两层注入可大幅减少 token 消耗
- **实现建议**：
  1. `capability_prompts.py` 中只列出 Skill 名称和简短描述
  2. 新增 `load_skill` 工具，让 LLM 按需加载完整 Skill 内容
  3. Skill 的 `strategy_hint/planning_bias/constraints/prompt_bias` 仍在 planner_node 阶段按需注入
- **与现有架构的契合**：`skill_node` 已在 graph 中作为独立节点，改造为按需加载非常自然

#### 8.3.6 Context Compact — 三层压缩 ⭐

**核心代码**：

```python
# Layer 1: micro_compact — 每轮静默执行，保留最近3个 tool result
def micro_compact(messages: list) -> list:
    tool_results = [(i, j, part) for i, msg in enumerate(messages)
                    for j, part in enumerate(msg.get("content", []))
                    if isinstance(part, dict) and part.get("type") == "tool_result"]
    if len(tool_results) <= KEEP_RECENT:
        return messages
    for _, _, part in tool_results[:-KEEP_RECENT]:
        if len(part.get("content", "")) > 100:
            part["content"] = f"[Previous: used {tool_name}]"
    return messages

# Layer 2: auto_compact — token 超阈值时 LLM 摘要
def auto_compact(messages: list) -> list:
    transcript_path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(transcript_path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    response = client.messages.create(model=MODEL,
        messages=[{"role": "user", "content": "Summarize this conversation..." + json.dumps(messages)[:80000]}],
        max_tokens=2000)
    return [{"role": "user", "content": f"[Compressed]\n\n{response.content[0].text}"}]

# Layer 3: manual compact — 模型显式调用 compact 工具
```

**LamImager 映射**：
- `PlanningContextManager` 只做**预防性截断**（6000 token 硬上限），不是**智能压缩**
- **直接可借鉴**：
  1. **micro_compact**：agent mode 多步执行中，旧的 tool result（web_search 结果等）3轮后替换为占位符
  2. **auto_compact**：sidebar assistant 对话过长时用 LLM 摘要替代完整历史
  3. **transcript 持久化**：完整对话保存到 `data/transcripts/`，支持事后回溯
- **与现有架构的契合**：`context_enrichment_node` 已在做上下文优化，加入 micro_compact 非常自然
- **关键差异**：图片生成结果（URL 列表）不能简单替换为占位符，后续步骤可能需要引用。需要更精细的压缩策略——保留 URL 但移除 base64 数据

#### 8.3.7 Task System — 持久化任务图 ⭐

**核心代码**：

```python
class TaskManager:
    def create(self, subject, description=""):
        task = {"id": self._next_id, "subject": subject,
                "status": "pending", "blockedBy": [], "owner": ""}
        self._save(task)  # JSON 文件持久化到 .tasks/

    def _clear_dependency(self, completed_id):
        for f in self.dir.glob("task_*.json"):
            task = json.loads(f.read_text())
            if completed_id in task.get("blockedBy", []):
                task["blockedBy"].remove(completed_id)
                self._save(task)
```

**LamImager 映射**：
- `ExecutionPlan` 已有步骤列表，但缺少**依赖关系**和**磁盘持久化**
- **直接可借鉴**：
  1. **依赖图**：iterative 策略步骤天然有序，parallel 策略可能有更复杂依赖。`blockedBy` 让 planner 表达更精细的执行约束
  2. **磁盘持久化**：当前 ExecutionPlan 只在内存中（AgentState），agent 中断则计划丢失。持久化到 `data/tasks/` 可支持断点续执行
  3. **与 checkpoint 结合**：checkpoint 恢复时从任务图读取当前步骤状态

#### 8.3.8 Background Tasks — 异步执行 + 通知注入

**核心代码**：

```python
class BackgroundManager:
    def run(self, command: str) -> str:
        task_id = str(uuid.uuid4())[:8]
        thread = threading.Thread(target=self._execute, args=(task_id, command), daemon=True)
        thread.start()
        return f"Background task {task_id} started"

# 主循环中每轮排空通知
notifs = BG.drain_notifications()
if notifs:
    messages.append({"role": "user",
        "content": f"<background-results>\n{notif_text}\n</background-results>"})
```

**LamImager 映射**：
- LamImager 已有 `asyncio.gather` 并行执行，但这是代码驱动的并行，不是 LLM 驱动的异步
- **可借鉴**：后台生成 + LLM 继续规划——executor_node 开始生成图片时（10-30秒），LLM 可继续规划下一步
- **关键差异**：LamImager 是 async/await 架构，后台任务应用 `asyncio.create_task()` 而非 `threading.Thread`
- **与现有架构的契合**：`LamEvent` 广播可与通知队列结合——后台任务完成时发布 `task_progress` 事件

#### 8.3.9 Agent Teams — JSONL 邮箱多 Agent 协作

**核心代码**：

```python
class MessageBus:
    def send(self, sender, to, content, msg_type="message", extra=None):
        msg = {"type": msg_type, "from": sender, "content": content, "timestamp": time.time()}
        with open(self.dir / f"{to}.jsonl", "a") as f:
            f.write(json.dumps(msg) + "\n")

    def read_inbox(self, name):
        path = self.dir / f"{name}.jsonl"
        msgs = [json.loads(l) for l in path.read_text().strip().splitlines() if l]
        path.write_text("")  # drain-on-read
        return json.dumps(msgs, indent=2)
```

**LamImager 映射**：
- LamImager 当前是单 Agent 架构，不需要多 Agent 协作
- **潜在场景**：LamTools 生态协作（Imager 调用 Coder 生成代码、调用 Sage 做分析）
- **JSONL 邮箱模式**：与 SSE 事件流互补——SSE 是 push 模式，JSONL 邮箱是 pull 模式
- **可借鉴**：如果未来支持多 session 间 Agent 协作，MessageBus 的 drain-on-read 模式可用于跨 session 通信

#### 8.3.10 Team Protocols — request_id 关联的协议握手

**核心代码**：

```python
shutdown_requests = {}

def handle_shutdown_request(teammate: str) -> str:
    req_id = str(uuid.uuid4())[:8]
    shutdown_requests[req_id] = {"target": teammate, "status": "pending"}
    BUS.send("lead", teammate, "Please shut down gracefully.",
             "shutdown_request", {"request_id": req_id})
    return f"Shutdown request {req_id} sent (status: pending)"
```

**LamImager 映射**：
- **checkpoint 机制**与关机协议高度相似：`checkpoint_required` = `shutdown_request`，用户 approve/reject = 队友 approve/reject
- **可借鉴**：request_id 关联——如果未来支持多个并行 checkpoint，需要 request_id 配对
- **可借鉴**：计划审批协议——critic 评分在 warn 区间时触发协议，让用户决定继续/重试/重新规划
- **与现有架构的契合**：`decision_node` 已在做 approve/warn/retry 决策，但这是代码驱动的（分数阈值），不是协议驱动的（请求-响应握手）

#### 8.3.11 Autonomous Agents — 自组织 + 身份重注入 ⭐

**核心代码**：

```python
# IDLE 轮询：每5秒检查收件箱和任务看板
def _idle_poll(self, name, messages):
    for _ in range(IDLE_TIMEOUT // POLL_INTERVAL):  # 60s / 5s = 12
        time.sleep(POLL_INTERVAL)
        inbox = BUS.read_inbox(name)
        if inbox:
            return True
        unclaimed = scan_unclaimed_tasks()
        if unclaimed:
            claim_task(unclaimed[0]["id"], name)
            return True
    return False  # timeout -> shutdown

# 身份重注入：压缩后防止 Agent 忘记自己是谁
if len(messages) <= 3:
    messages.insert(0, {"role": "user",
        "content": f"<identity>You are '{name}', role: {role}. Continue your work.</identity>"})
    messages.insert(1, {"role": "assistant", "content": f"I am {name}. Continuing."})
```

**LamImager 映射**：
- **身份重注入**是最直接可借鉴的模式：agent mode 长时间运行后（特别是经过 context compact），LLM 可能忘记当前任务目标和约束。在 `AgentState` 中维护 `identity` 字段，压缩后自动重注入
- **自动认领**可用于批量任务场景：planner 生成多个子任务，每个子任务被独立 executor 实例认领
- **IDLE 轮询**与 SSE 事件流互补：SSE 是前端监听后端事件，IDLE 轮询是后端 Agent 主动检查任务状态

#### 8.3.12 Worktree Isolation — 控制面与执行面分离

**核心代码**：

```python
class WorktreeManager:
    def bind_worktree(self, task_id, worktree):
        task = self._load(task_id)
        task["worktree"] = worktree
        if task["status"] == "pending":
            task["status"] = "in_progress"
        self._save(task)

class EventBus:
    def emit(self, event_type, data):
        with open(self.path, "a") as f:
            f.write(json.dumps({"type": event_type, "data": data, "ts": time.time()}) + "\n")
```

**LamImager 映射**：
- LamImager 不需要 git worktree 隔离（不涉及代码文件并行修改），但**隔离思想**可映射到：
  1. **Session 隔离**：每个 session 已有独立消息历史和生成结果
  2. **生成结果隔离**：radiate 策略的 anchor grid 和 per-item expansion 可在独立临时目录中处理
  3. **任务-结果绑定**：引入任务图后，每个步骤结果通过 `task_id` 绑定
- **事件流模式**直接对应 `LamEvent` 广播：s12 的 `events.jsonl` 是持久化事件日志，LamImager 的 `EventLog` ring buffer 是内存事件流。可结合两者——事件先写入内存（实时推送），再持久化到磁盘（事后回溯）
- **崩溃恢复**是 LamImager 弱项：服务重启时正在执行的 agent 任务会丢失。借鉴 s12 的磁盘持久化模式，可将 `AgentState` 和 `ExecutionPlan` 持久化到 `data/agent_state/`

### 8.4 Skill 模板与参考代码

#### Agent Philosophy（agent-philosophy.md）

核心观点：
- **"The model IS the agent. Code just runs the loop."**
- Harness = Tools + Knowledge + Observation + Action Interfaces + Permissions
- 车辆隐喻：模型是司机，Harness 是车辆
- "You are not writing intelligence. You are building the world intelligence inhabits."

**LamImager 启示**：LamImager 的 `decision_node` 用硬编码分数阈值（≥7 pass / 5-7 warn / 3-5 retry_prompt / <3 retry_step）做决策，这违背了"模型即 Agent"的哲学——应该让 LLM 自己判断生成质量，而不是用代码规则硬性路由。

#### Minimal Agent（minimal-agent.py）

~80 行最小可行 Agent，3 个工具（bash, read_file, write_file），`agent(prompt, history)` 函数。

**LamImager 启示**：LamImager 的 sidebar assistant 图（2 节点循环）就是这个最小 Agent 的 LangGraph 版本。保持核心循环简单，复杂度通过工具和节点叠加。

#### Subagent Pattern（subagent-pattern.py）

```python
AGENT_TYPES = {
    "explore": {"tools": ["bash", "read_file"], "system": "You are a read-only explorer."},
    "code":    {"tools": ["bash", "read_file", "write_file", "edit_file"], "system": "You are a coder."},
    "plan":    {"tools": ["bash", "read_file"], "system": "You are a planner."},
}

def get_tools_for_agent(agent_type: str) -> list:
    allowed = AGENT_TYPES[agent_type]["tools"]
    return [t for t in ALL_TOOLS if t["name"] in allowed]
```

**LamImager 启示**：Agent 类型注册表 + 工具过滤模式可直接用于 LamImager 的 Agent 定义模型。当前 sidebar assistant 和 agent mode 共享同一套工具，没有角色区分。引入 `AGENT_TYPES` 可以让不同 Agent 有不同的工具权限。

#### Tool Templates（tool-templates.py）

标准化的工具定义模板 + `execute_tool()` 分发器 + `safe_path()` 安全函数。

**LamImager 启示**：LamImager 的 `Tool` 基类（`backend/app/tools/base.py`）已有类似结构，但缺少 `safe_path()` 等安全函数的统一抽象。可以借鉴 tool-templates 的标准化模式。

### 8.5 learn-claude-code 与前两个项目的互补关系

| 维度 | Claude Code 2.4.3（源码） | OpenCode 1.14.50（源码） | learn-claude-code（教学） |
|------|--------------------------|-------------------------|------------------------|
| **深度** | 生产级实现，复杂度高 | 生产级实现，Effect 全栈 | 教学级实现，每个模式独立可运行 |
| **语言** | TypeScript | TypeScript | **Python**（与 LamImager 同语言） |
| **可读性** | 中等（大量抽象） | 低（Effect 生态学习曲线陡） | **高**（每个文件 < 200 行） |
| **实用价值** | 架构参考 | 架构参考 | **直接可移植**（Python → FastAPI/async） |
| **独特贡献** | Tool 能力声明、Hook 系统、Memory、Proactive | Part 消息模型、权限模型、配置分层、流式处理器 | **渐进式构建方法、Nag Reminder、两层 Skill 注入、三层压缩、身份重注入** |

**关键洞察**：learn-claude-code 的 Python 实现可以直接移植到 LamImager 的 FastAPI/async 架构中，而不需要像 Claude Code 和 OpenCode 那样做语言转换。特别是：

1. **两层 Skill 注入**（s05）：Python 实现可直接用于 `skill_engine.py` 的改造
2. **三层压缩**（s06）：`micro_compact()` 和 `auto_compact()` 可直接改为 async 版本
3. **任务图持久化**（s07）：JSON 文件持久化模式可直接用于 `data/tasks/`
4. **身份重注入**（s11）：几行代码即可集成到 `context_enrichment_node`
5. **Nag Reminder**（s03）：几行代码即可集成到 agent mode 的循环中

---

## 九、心智模型与生态架构深度分析

> 源文件：`docs/mental-model.md`（PER/CON/MEN/PLAN 四系统）、`docs/lamtools-ecosystem.md`（5 成员生态）
> 分析视角：将 LamTools 的架构设计作为"目标态"，与三个学习项目的"实现模式"交叉验证，识别 LamImager 当前的差距和可落地的改造路径

### 9.1 心智模型（PER/CON/MEN/PLAN）与学习项目的模式映射

LamTools 心智模型定义了四个运行时系统 + 一个外部输入，其核心运转逻辑是：

```
PER(恒定) + CON(实时) → 选择 MEN → 创建 PLAN → 驱动工作 → 状态更新回写 CON
```

这个模型与三个学习项目的模式存在深层的结构对应关系：

#### 9.1.1 PER（Persona）— 对应 Claude Code 的 Agent 定义 + learn-claude-code 的 AGENT_TYPES

| 维度 | LamTools PER | Claude Code | OpenCode | learn-claude-code |
|------|-------------|-------------|----------|-------------------|
| **定义方式** | `persona.md` 文件，设计时锁定 | Agent = prompt template + model config | `agent.ts` = prompt + model + permissions | `AGENT_TYPES` dict = tools + system prompt |
| **不变性** | "永远不变" | 运行时不可修改 | 运行时不可修改 | 运行时不可修改 |
| **作用** | 滤网——锁死 MEN 可选范围 | 约束 LLM 行为边界 | 约束工具权限 + 行为 | 约束可用工具集 |

**LamImager 现状差距**：

- LamImager **没有 PER 层**。sidebar assistant 和 agent mode 共用硬编码的 `AGENT_SYSTEM_PROMPT`（agent_service.py）和各节点的 system prompt（capability_prompts.py）
- 不同 Agent 角色没有独立的人格定义——sidebar assistant 和 agent mode 的 planner 用的是同一套能力提示，只是拼接顺序不同
- **关键缺失**：PER 的"滤网"作用——"Coder 永远不可能选出'话多热情'模式"——在 LamImager 中完全没有实现。`decision_node` 的分数阈值路由是代码硬逻辑，不是 PER 过滤后的 MEN 选择

**改造方向**：

```python
PERSONAS = {
    "imager": PersonaDef(
        name="LamImager/Artist",
        age=19,
        style="激动时话密得像颜料泼出去。安静时在跟构图较劲",
        men_whitelist=["precise_delivery", "creative_exploration", "iterative_refinement"],
        men_blacklist=["verbose_explanation", "casual_chat"],
        tool_whitelist=["generate_image", "load_skill", "plan"],
        tool_blacklist=["web_search"],  # 搜索由 Sage 负责
    ),
    "sidebar_assistant": PersonaDef(
        name="LamImager Assistant",
        style="简洁、专业、直接给结果",
        men_whitelist=["concise_response", "detailed_analysis"],
        men_blacklist=["creative_exploration"],
        tool_whitelist=["web_search", "image_search", "generate_image", "plan"],
    ),
}
```

这与 OpenCode 的 `AgentDef`（prompt + model + permissions）和 learn-claude-code 的 `AGENT_TYPES`（tools + system）是同一模式。LamImager 应引入 `PersonaDef` 作为 PER 层的运行时载体。

#### 9.1.2 CON（Context）— 对应 OpenCode 的 Part 消息模型 + learn-claude-code 的 Context Compact

| 维度 | LamTools CON | OpenCode | learn-claude-code | Claude Code |
|------|-------------|----------|-------------------|-------------|
| **内容** | 任务状态、用户情绪、成员动态、画像数据、Skill 信号、历史 PLAN 库 | Part 消息流（Text/Tool/Image/Reasoning） | messages 列表 + micro_compact + auto_compact | context window + token budget |
| **分层** | Hot CON（进 prompt）+ Cold CON（做索引） | 无显式分层，但 compaction 隐式实现 | 无显式分层，compact 后旧消息被替换 | 无显式分层，但 token budget 隐式截断 |
| **更新机制** | 工作驱动更新，规则提取（JSON 字段搬运，不走 LLM） | 增量 Part 更新 | micro_compact 每轮静默，auto_compact LLM 摘要 | checkTokenBudget 递减收益检测 |

**LamImager 现状差距**：

- `PlanningContextManager` 只做**预防性截断**（6000 token 硬上限），不是**分层管理**
- 没有 Hot/Cold 分层——所有上下文要么全进 prompt，要么全被丢弃
- `AgentState` 的 30+ 字段全部是扁平的，没有"进 prompt 的热层"和"做索引的冷层"区分
- 画像数据（用户偏好）当前完全不存在——`app_settings` 只有技术参数，没有用户审美偏好

**改造方向**：

```python
class ContextManager:
    def __init__(self):
        self.hot = HotCON(max_tokens=6000)   # 进 prompt，不膨胀
        self.cold = ColdCON(storage_path="data/context/")  # 做索引，可膨胀

    def update(self, event: LamEvent):
        # 规则提取，不走 LLM
        if event.event_type == "task_completed":
            self.hot.set_task_status(event.correlation_id, "completed")
            self.cold.append_artifact(event.payload)

    def build_prompt_context(self) -> str:
        # Hot CON 直接拼接
        # Cold CON 按需检索（MEN 或 Butler 触发）
        return self.hot.render()
```

这与 mental-model.md 的 CON 分层设计完全一致，也与 learn-claude-code 的 micro_compact（保留最近 N 轮 = Hot）+ transcript 持久化（完整历史 = Cold）模式对应。

#### 9.1.3 MEN（Mentation）— 对应 Claude Code 的 Plan Mode + learn-claude-code 的 Skill 两层注入

| 维度 | LamTools MEN | Claude Code | OpenCode | learn-claude-code |
|------|-------------|-------------|----------|-------------------|
| **定义** | 思维模式——这一次怎么想、优先什么、避开什么 | Plan Mode V2（策略选择） | Agent prompt template | Skill 的 strategy_hint/planning_bias |
| **选择机制** | PER + CON 决定用哪份 | 用户手动切换 | Agent 定义中固定 | LLM 自行选择加载哪个 Skill |
| **数量** | 每个 PER 下多个 MEN 模板 | 2 种（auto/plan） | 每个 Agent 一个 | 每个 Skill 一个偏转 |

**LamImager 现状差距**：

- LamImager **没有 MEN 层**。当前所有节点的 system prompt 都是固定的——planner 永远用 `build_planner_system_prompt()`，prompt_builder 永远用 `_build_prompt_builder_system()`
- Skill 的 `strategy_hint/planning_bias/constraints/prompt_bias` 是最接近 MEN 的机制，但它只偏转 planner 和 prompt_builder，不改变 Agent 的"思维方式"
- **关键缺失**：mental-model.md 说"同一任务在不同思维模式下出的计划不同——精准交付 vs 留白协作"。LamImager 的 planner 不管什么情境都用同一套规划逻辑

**改造方向**：

```python
MENTATION_TEMPLATES = {
    "precise_delivery": MentationDef(
        name="精准交付",
        priority="验收点加密、不确定时明确询问",
        avoid="过度探索、风格实验",
        planner_bias="步骤明确、每步可验证",
        prompt_bias="精确描述、减少模糊词",
    ),
    "creative_exploration": MentationDef(
        name="创意探索",
        priority="风格多样性、突破常规",
        avoid="过早收敛、重复相似构图",
        planner_bias="多方案并行、允许试错",
        prompt_bias="开放描述、鼓励意外",
    ),
    "iterative_refinement": MentationDef(
        name="迭代精修",
        priority="逐步提升质量、保留优点改缺点",
        avoid="大方向推翻、忽略用户反馈",
        planner_bias="每步基于上步结果改进",
        prompt_bias="保留核心元素、微调细节",
    ),
}

def select_mentation(per: PersonaDef, con: ContextManager) -> MentationDef:
    # PER 滤网：只从 per.men_whitelist 中选
    # CON 选择器：根据当前情境选最合适的
    candidates = [MENTATION_TEMPLATES[m] for m in per.men_whitelist]
    return con.match_best_mentation(candidates)
```

这与 learn-claude-code 的 Skill 两层注入（Layer 1 描述 → Layer 2 按需加载）高度一致——MEN 模板名和描述始终在 system prompt 中（Layer 1），完整 MEN 内容按需加载（Layer 2）。

#### 9.1.4 PLAN（Plan）— 对应 learn-claude-code 的 Task System + Claude Code 的 Plan Mode V2

| 维度 | LamTools PLAN | Claude Code | OpenCode | learn-claude-code |
|------|-------------|-------------|----------|-------------------|
| **创建** | CON + MEN 创建 | Plan Mode V2 生成 | Agent 输出 | planner_node / TodoManager |
| **执行** | 自执行引擎（每个成员内置） | Task 执行 | Session 驱动 | for step in steps 循环 |
| **持久化** | 骨架回写 CON 历史维 | 无持久化 | 无持久化 | JSON 文件持久化 |
| **依赖** | Butler 编排 | 无显式依赖 | 无显式依赖 | blockedBy DAG |
| **自进化** | 完成的 PLAN 骨架回写 CON，下次相似任务匹配复用 | 无 | 无 | 无 |

**LamImager 现状差距**：

- `ExecutionPlan` 有步骤列表，但**没有依赖关系**（`blockedBy`）
- **没有持久化**——ExecutionPlan 只在 AgentState 内存中，agent 中断则计划丢失
- **没有自进化**——完成的 plan 不会回写 CON 供下次复用
- **没有自执行引擎**——当前 executor_node 是代码驱动的策略路由，不是通用的 step-by-step 循环

**改造方向**：

```python
class ExecutionPlanV2:
    steps: list[PlanStep]
    dependencies: dict[str, list[str]]  # step_id → [blocked_by_step_ids]

    def next_ready_steps(self, completed: set[str]) -> list[PlanStep]:
        return [s for s in self.steps
                if s.id not in completed
                and all(d in completed for d in self.dependencies.get(s.id, []))]

    def save(self, path: Path):
        (path / f"plan_{self.id}.json").write_text(self.model_dump_json())

    @classmethod
    def load(cls, path: Path, plan_id: str) -> "ExecutionPlanV2":
        return cls.model_validate_json((path / f"plan_{plan_id}.json").read_text())
```

这与 learn-claude-code 的 `TaskManager`（blockedBy + JSON 持久化）和 mental-model.md 的"PLAN 骨架回写 CON"（自进化）直接对应。

#### 9.1.5 Skill — 对应 learn-claude-code 的两层 Skill 注入 + Claude Code 的 Skill 系统

| 维度 | LamTools Skill | Claude Code | learn-claude-code | LamImager 现状 |
|------|---------------|-------------|-------------------|---------------|
| **定位** | 外部文件，不是运行时层，和用户刚说的一句话同类 | .claude/skills/ 目录，自动发现 | SkillLoader 两层注入 | skill_engine.py 全量注入 |
| **注入方式** | 进入 CON 作为信号源，经过 PER 过滤后影响 MEN | 自动注入 system prompt | Layer 1 描述 + Layer 2 按需加载 | 全量注入 planner + prompt_builder |
| **过滤** | 同一 Skill 在不同 PER 上出不同结果 | 无过滤 | 无过滤 | 无过滤——所有 Skill 统一处理 |
| **生命周期** | 用户提供，加载后注入 CON | 项目级/用户级/会话级 | 运行时加载 | 数据库 CRUD，无生命周期管理 |

**LamImager 现状差距**：

- 当前 Skill 是**全量注入**——所有激活 Skill 的 `strategy_hint/planning_bias/constraints/prompt_bias` 全部注入 planner 和 prompt_builder
- 没有 PER 过滤——"同一份 Skill 在 Coder 身上出极简代码，在 Imager 身上出留白构图"这个设计完全没实现
- 没有 Layer 1/Layer 2 分层——10 个 Skill 每个 ~2000 token = 20,000 token 全部消耗

**改造方向**：结合 mental-model.md 的"Skill 进入 CON 作为信号源，经过 PER 过滤后影响 MEN"和 learn-claude-code 的两层注入：

```python
class SkillInjector:
    def get_layer1(self, per: PersonaDef) -> str:
        # Layer 1: 只放名称和描述（~100 token/skill）
        # 经过 PER 过滤——只列出与当前角色相关的 Skill
        relevant = [s for s in self.skills if per.is_skill_relevant(s)]
        return "\n".join(f"  - {s.name}: {s.description}" for s in relevant)

    def get_layer2(self, skill_name: str, per: PersonaDef) -> str:
        # Layer 2: 按需加载完整内容，经过 PER 过滤
        skill = self.skills[skill_name]
        filtered = per.filter_skill_content(skill)  # Coder 过滤掉视觉相关内容
        return f"<skill name=\"{skill_name}\">\n{filtered}\n</skill>"
```

### 9.2 Prompt 组装线 — 与 LamImager 现状的逐层对比

mental-model.md 定义了严格的 Prompt 组装顺序：

```
PER → Skill → MEN → CON(任务) → CON(画像) → 历史PLAN → System Prompt
对话历史 + 用户输入 + 成员动态 → Messages
```

**LamImager 当前各节点的 Prompt 组装现状**：

| 节点 | 当前组装方式 | 缺失层 |
|------|------------|--------|
| **sidebar agent_node** | 硬编码 `AGENT_SYSTEM_PROMPT` | PER、Skill、MEN、CON(画像)、历史PLAN |
| **intent_node** | `INTENT_NODE_SYSTEM_PROMPT` + 策略机制 + 图像约束 | PER、Skill、MEN、CON(画像)、历史PLAN |
| **planner_node** | `build_planner_system_prompt()` = 基础 + 策略白名单 + skill_constraints + 图像尺寸 + 模型能力 | PER、MEN、CON(画像)、历史PLAN |
| **prompt_builder_node** | `_build_prompt_builder_system()` = 基础 + PROMPT_BUILDER_GUIDE + skill_bias + IMAGE_PROVIDER_CAPABILITIES | PER、MEN、CON(画像)、历史PLAN |
| **critic_node** | `CRITIC_SYSTEM_PROMPT` + 6 维度评估 | PER、MEN、CON(画像) |
| **decision_node** | 纯代码逻辑，无 LLM 调用 | 全部（但 decision_node 本就不该用 LLM） |

**关键发现**：

1. **PER 层完全缺失**——所有节点都没有人格底色注入。sidebar assistant 和 agent mode 的 planner 用的是同一套能力提示，没有角色区分
2. **MEN 层完全缺失**——所有节点的 system prompt 都是固定的，没有根据情境动态切换思维模式
3. **CON(画像) 完全缺失**——没有用户偏好数据，更没有"只有高权重进 prompt"的过滤机制
4. **历史PLAN 完全缺失**——完成的 plan 不会回写，下次相似任务无法复用
5. **Skill 注入位置不对**——当前 Skill 直接注入 planner 和 prompt_builder，但 mental-model.md 规定 Skill 应进入 CON，经过 PER 过滤后影响 MEN，而非直接注入节点

**组装线改造方案**：

```python
class PromptAssembler:
    def assemble_system(self, per: PersonaDef, con: ContextManager,
                        men: MentationDef, skills: list[SkillDef]) -> str:
        sections = []

        # 第一段：PER（永不冲刷）
        sections.append(f"# Identity\n{per.render()}")

        # 第二段：Skill（active 时注入，经 PER 过滤）
        skill_layer1 = self.skill_injector.get_layer1(per)
        if skill_layer1:
            sections.append(f"# Available Skills\n{skill_layer1}")

        # 第三段：MEN（运行时抽换）
        sections.append(f"# Current Mode\n{men.render()}")

        # 第四段：CON(任务)（每轮刷新）
        sections.append(f"# Current Context\n{con.hot.render_task()}")

        # 第五段：CON(画像)（只有高权重进）
        profile = con.hot.render_profile(min_weight=0.5)
        if profile:
            sections.append(f"# User Preferences\n{profile}")

        # 第六段：历史PLAN（只进匹配的骨架）
        matched_plans = con.cold.match_historical_plans(con.hot.task_signature)
        if matched_plans:
            sections.append(f"# Similar Past Plans\n{matched_plans}")

        return "\n\n".join(sections)
```

### 9.3 生态架构 — 与学习项目的交叉验证

#### 9.3.1 Butler 评价与干预机制 — 对应 Claude Code 的 Hook 系统 + learn-claude-code 的 Team Protocols

| 维度 | LamTools Butler 干预 | Claude Code Hooks | learn-claude-code Protocols |
|------|---------------------|-------------------|---------------------------|
| **触发方式** | 节点触发（计划内置）+ 需求触发（异常响应）+ 召唤触发（用户主动） | 7 种 hook source + 优先级排序 | request_id 关联的协议握手 |
| **评价三档** | 通过 / 需修改 / 推翻 | allow / deny / ask | approved / rejected / pending |
| **粒度调节** | 步骤级 / 阶段级 / 产物级，根据用户画像自动调节 | 无粒度调节 | 无粒度调节 |

**LamImager 现状映射**：

- **checkpoint 机制**是 Butler 节点触发的简化版——`executor_node` 的 `interrupt()` 对应"步骤级验收"
- **critic + decision** 是 Butler 评价的代码化版——但只有"通过/需修改"两档，没有"推翻（重规划）"
- **缺少需求触发**——当方向偏离时没有自动检测和介入机制
- **缺少召唤触发**——用户无法在执行中途叫停并重新确认方向

**改造方向**：将 checkpoint 从 executor_node 的硬编码 `interrupt()` 升级为可配置的干预点：

```python
class InterventionConfig:
    node_triggers: list[NodeTrigger]  # 计划内置的验收点
    demand_triggers: list[DemandTrigger]  # 异常检测规则
    summon_enabled: bool = True  # 用户随时可召唤

    def should_intervene(self, state: AgentState) -> bool:
        # 节点触发：检查当前步骤是否在验收点列表中
        if self._check_node_trigger(state):
            return True
        # 需求触发：检测方向偏离、依赖断裂、意图误解
        if self._check_demand_trigger(state):
            return True
        return False
```

#### 9.3.2 共享上下文总线 — 对应 learn-claude-code 的 MessageBus + Claude Code 的 Event 系统

| 维度 | LamTools 上下文总线 | learn-claude-code MessageBus | Claude Code Events | LamImager LamEvent |
|------|-------------------|---------------------------|-------------------|-------------------|
| **架构** | 事件流 + 结构化存储双层 | JSONL 邮箱（drain-on-read） | 内存事件 | 内存 ring buffer |
| **持久化** | WAL → 入库，重启重放 | JSONL 文件 | 无持久化 | 无持久化 |
| **文档状态** | writing/complete/stale/aborted | 无 | 无 | 无 |
| **事件分类** | 进度事件（仅用户可见）+ 完成事件（入总线） | 无分类 | 无分类 | task_progress + task_completed + task_started |

**LamImager 现状映射**：

- `LamEvent` + `EventLog` ring buffer 是事件流的简化版——只有内存层，没有持久化层
- **缺少文档状态字段**——当前生成的图片 URL 直接写入 assistant message，没有 writing→complete 的状态转换
- **缺少事件分类**——`task_progress` 和 `task_completed` 都广播给前端，但没有区分"仅用户可见"和"入 LLM 上下文总线"
- **缺少结构化存储层**——没有 Cold CON 的持久化查询能力

**改造方向**：

```python
class ContextBus:
    def __init__(self, data_dir: Path):
        self.event_stream = EventStream()  # 内存层，实时推送
        self.storage = ContextStorage(data_dir)  # 持久化层，可查询
        self.wal = WALFile(data_dir / "wal.jsonl")  # 预写日志

    async def publish(self, event: LamEvent):
        # WAL 先写
        await self.wal.append(event)
        # 进度事件 → 仅 SSE 推送
        if event.event_type == "task_progress":
            await self.event_stream.broadcast(event)
        # 完成事件 → SSE + 入库 + 通知 LLM 消费者
        elif event.event_type == "task_completed":
            await self.event_stream.broadcast(event)
            await self.storage.store(event)
            await self._notify_consumers(event)

    async def recover(self):
        # 重启时重放 WAL
        for event in await self.wal.read_all():
            await self.storage.store(event)
        await self.wal.clear()
```

#### 9.3.3 画像体系 — 对应 Claude Code 的 Memory + learn-claude-code 的 Context Compact

| 维度 | LamTools 画像 | Claude Code Memory | learn-claude-code | LamImager 现状 |
|------|-------------|-------------------|-------------------|---------------|
| **采集** | Mate 采集人本身、Imager 采集审美、Coder 采集编码习惯、Sage 采集知识消费 | MEMORY.md 入口 + 4 类型 | 无显式画像 | 无画像 |
| **权重** | 交叉印证倍增、权重天花板、衰减 | 200 行/25KB 上限 | 无 | 无 |
| **消费** | 全员消费，Butler 精炼 | LLM 读取 MEMORY.md | 无 | 无 |
| **分阶段** | 单成员临时偏好 → 双成员交叉 → 全家桶完整 | 无分阶段 | 无 | 无 |

**LamImager 现状映射**：

- **完全缺失**——没有任何用户画像采集和消费机制
- `app_settings` 只有技术参数（默认模型、图片尺寸、最大并发数），没有审美偏好
- 最接近的是 `context_enrichment_node` 的"最近生成图片自动作为上下文"——但这不是画像，只是短期上下文

**Imager 单成员阶段的改造方向**（参照 mental-model.md 的"单成员画像策略"）：

```python
class ImagerProfile:
    """单成员临时偏好——不进永久画像，标'低置信度'"""

    style_preferences: dict[str, float]  # {"赛博朋克": 0.8, "写实": 0.3}
    color_tendencies: dict[str, float]   # {"暖色调": 0.6, "高饱和": 0.4}
    iteration_patience: float            # 0.0-1.0，1.0 = 反复精修型
    quality_sensitivity: float           # 0.0-1.0，1.0 = 纠结细节型
    size_habits: dict[str, int]          # {"1024x1024": 15, "512x512": 3}

    def update_from_generation(self, result: GenerationResult):
        # 从生成结果中提取偏好信号
        # 单源数据，低置信度，不设权重天花板
        self.style_preferences[result.style] = min(
            self.style_preferences.get(result.style, 0) + 0.1, 1.0
        )

    def render_for_prompt(self, min_weight: float = 0.5) -> str:
        # 只有高权重进 prompt（CON 画像层）
        lines = []
        for style, weight in self.style_preferences.items():
            if weight >= min_weight:
                lines.append(f"用户偏好{style}风格（置信度：{weight:.0%}）")
        return "\n".join(lines) if lines else ""
```

#### 9.3.4 成员间信息桥 — 对应 learn-claude-code 的 Agent Teams + Claude Code 的 Subagent

| 维度 | LamTools 信息桥 | learn-claude-code Teams | Claude Code Subagent | LamImager 现状 |
|------|---------------|----------------------|---------------------|---------------|
| **架构** | 事件流 + 结构化存储双层 | JSONL 邮箱 | 独立 LLM 循环 | 无跨成员通信 |
| **隔离** | 内容转发，人格不转发 | 独立收件箱 | 独立上下文 | 无 |
| **进度可见** | 并行订阅，侧栏实时状态 | drain-on-read | 无 | SSE 事件流（仅前端） |

**LamImager 现状映射**：

- 当前是单 Agent 架构，不需要跨成员通信
- 但 **SSE 事件流**已经是信息桥的雏形——`task_progress` 事件推送给前端，如果增加 LLM 消费者，就是上下文总线
- **关键洞察**：lamtools-ecosystem.md 的"执行层直连，规划层集中"与 learn-claude-code 的 MessageBus drain-on-read 模式互补——Butler 不当中转站，Imager 和 Coder 直接互传产物

**未来改造方向**（Phase 2+ Coder 上线时）：

```python
class MemberBridge:
    """执行层直连——Imager 和 Coder 直接互传产物"""

    async def send_artifact(self, sender: str, recipient: str,
                           artifact: Artifact, status: str = "complete"):
        # 只有 complete 状态的产物才能被其他成员 LLM 读取
        if status == "complete":
            await self.context_bus.publish(LamEvent(
                event_type="task_completed",
                payload={"from": sender, "artifact": artifact, "status": status}
            ))

    async def receive_artifacts(self, member: str) -> list[Artifact]:
        # 从 Cold CON 查询指定成员的已完成产物
        return await self.context_bus.storage.query(
            filter={"recipient": member, "status": "complete"}
        )
```

#### 9.3.5 Mate 转接与上下文继承 — 对应 learn-claude-code 的身份重注入 + Claude Code 的 Memory

| 维度 | LamTools Mate 转接 | learn-claude-code 身份重注入 | Claude Code Memory | LamImager 现状 |
|------|-------------------|---------------------------|-------------------|---------------|
| **核心** | 上下文必须继承，不能让用户重说一遍 | 压缩后重注入身份块 | MEMORY.md 持久化 | 无上下文继承 |
| **实现** | Butler 从总线抽取相关片段组装 | messages.insert(identity block) | 文件读写 | 无 |
| **裁剪** | 裁掉无关对话，保留任务相关的关键信息 | 无裁剪 | 200 行上限 | 无 |

**LamImager 现状映射**：

- sidebar assistant 的"共享上下文"模式（注入最近 10 条 session 消息）是最简单的上下文继承
- 但 **agent mode 没有跨 session 上下文**——每次生成都是全新开始
- **没有裁剪**——共享上下文模式是全量注入最近 10 条，没有"裁掉无关对话"

**改造方向**：结合身份重注入和上下文裁剪：

```python
def build_handoff_context(source_session: Session, target_role: str) -> str:
    """Mate → Imager 转接时的上下文打包"""
    # Butler 从总线抽取相关片段
    relevant = context_bus.extract_relevant(
        session_id=source_session.id,
        target_role=target_role,
        max_tokens=2000
    )
    # 裁掉无关对话，保留任务相关的关键信息
    # 内容转发，人格不转发——传给 Imager 的是"用户想要什么"，不是"Mate 是怎么聊的"
    return f"<handoff>\n{relevant.render()}\n</handoff>"
```

### 9.4 架构原则验证 — 三个学习项目是否支持 LamTools 的设计原则

LamTools 定义了三条架构原则，我们用三个学习项目的实现来验证其可行性：

#### 原则 1："每个成员必须具备独立处理能力"

| 验证维度 | Claude Code | OpenCode | learn-claude-code | 结论 |
|---------|-------------|----------|-------------------|------|
| 独立 LLM 循环 | ✅ 每个 Task 有独立循环 | ✅ 每个 Agent 有独立 session | ✅ 每个 subagent 有独立 messages | **可行** |
| 独立工具集 | ✅ Task 可配置工具 | ✅ Agent 定义包含权限 | ✅ AGENT_TYPES 过滤工具 | **可行** |
| 独立上下文 | ✅ Task 有独立消息历史 | ✅ Session 隔离 | ✅ subagent 全新上下文 | **可行** |

**LamImager 启示**：当前 agent mode 的 8 节点图是一个**单一 LLM 流水线**，不是独立处理能力。mental-model.md 说"每个成员自带最小自执行引擎"——LamImager 应该让 Imager 的自执行引擎独立于 Butler 的编排。

#### 原则 2："每个成员可独立使用，协作是增值不是强制"

| 验证维度 | Claude Code | OpenCode | learn-claude-code | 结论 |
|---------|-------------|----------|-------------------|------|
| 无 Butler 可运行 | ✅ 无需编排器 | ✅ 无需编排器 | ✅ 单 agent 独立运行 | **可行** |
| 有 Butler 更强 | N/A（无多 Agent） | N/A | s09-s12 展示了协作增值 | **可行** |

**LamImager 启示**：当前 LamImager 就是独立使用的（Phase 1），这符合原则。关键是 Phase 2+ 引入 Butler 时，不能让 Imager 变成"必须依赖 Butler 才能运行"。

#### 原则 3："客观优先，偏好叠加"

| 验证维度 | Claude Code | OpenCode | learn-claude-code | 结论 |
|---------|-------------|----------|-------------------|------|
| 原始数据不篡改 | ✅ tool_result 原样返回 | ✅ Part 数据不可变 | ✅ tool result 原样返回 | **可行** |
| 偏好是外加层 | Memory 是额外注入 | Config 是额外层 | Skill 是额外注入 | **可行** |

**LamImager 启示**：当前 Skill 注入直接修改 planner 的约束和 prompt_builder 的偏置，这**违背了"偏好是外加层"原则**——Skill 应该作为 CON 的信号源，经过 PER 过滤后影响 MEN，而不是直接修改节点行为。

### 9.5 综合差距分析：LamImager → LamTools 目标态

| 层 | LamTools 目标态 | LamImager 现状 | 差距 | 可借鉴来源 |
|----|----------------|---------------|------|-----------|
| **PER** | persona.md 定义，运行时不变 | 无 | 🔴 完全缺失 | OpenCode AgentDef + learn-claude-code AGENT_TYPES |
| **CON Hot** | 当前任务+高权重画像+匹配历史PLAN | PlanningContextManager 6000 token 截断 | 🟡 有基础但缺分层 | learn-claude-code micro_compact + mental-model CON 分层 |
| **CON Cold** | 完整历史+低权重画像+成员动态 | 无 | 🔴 完全缺失 | learn-claude-code transcript 持久化 + lamtools-ecosystem 结构化存储 |
| **MEN** | PER+CON 选择思维模式 | 无 | 🔴 完全缺失 | mental-model MEN 定义 + learn-claude-code Skill 两层注入 |
| **PLAN** | 依赖图+持久化+自进化 | ExecutionPlan 扁平列表+内存 | 🟡 有基础但缺依赖/持久化/自进化 | learn-claude-code TaskManager + mental-model PLAN 回写 |
| **Skill** | 两层注入+PER 过滤 | 全量注入+无过滤 | 🟡 有基础但缺分层和过滤 | learn-claude-code SkillLoader + mental-model Skill 定位 |
| **画像** | 四维采集+交叉印证+权重衰减 | 无 | 🔴 完全缺失 | lamtools-ecosystem 画像体系 + Claude Code Memory |
| **上下文总线** | 事件流+结构化存储+WAL | LamEvent ring buffer | 🟡 有事件层但缺持久化 | lamtools-ecosystem 信息桥 + learn-claude-code MessageBus |
| **干预机制** | 三触发+三档评价 | checkpoint + critic/decision | 🟡 有基础但缺需求触发和召唤触发 | lamtools-ecosystem Butler 干预 + Claude Code Hooks |
| **Prompt 组装** | PER→Skill→MEN→CON(任务)→CON(画像)→历史PLAN | 各节点独立硬编码 | 🔴 完全缺失 | mental-model Prompt 组装线 |

### 9.6 分阶段落地路线

基于差距分析和 LamTools 的 Phase 路线图，建议 LamImager 的改造分三步：

**Phase 1（Imager 单体优化）**— 不引入新成员，但为未来协作铺路：

| 改造项 | 优先级 | 借鉴来源 | 预期收益 |
|--------|--------|---------|---------|
| 引入 PER 层（PersonaDef） | P0 | OpenCode AgentDef | sidebar/agent mode 角色区分 |
| 引入 MEN 层（MentationDef） | P1 | mental-model MEN | 根据情境切换思维模式 |
| Skill 两层注入 + PER 过滤 | P0 | learn-claude-code s05 | 省 ~18,000 token/次 |
| CON Hot/Cold 分层 | P1 | mental-model CON 分层 | 长会话不丢上下文 |
| 统一 Prompt 组装线 | P0 | mental-model Prompt 组装线 | 消除各节点硬编码 |
| ImagerProfile 临时画像 | P2 | lamtools-ecosystem 画像体系 | 记住用户审美偏好 |
| PLAN 持久化 + 依赖图 | P1 | learn-claude-code s07 | 断点续执行 |
| micro_compact | P1 | learn-claude-code s06 | 减少长会话 token 消耗 |
| 身份重注入 | P2 | learn-claude-code s11 | 压缩后不丢失角色 |

**Phase 2（+ Coder）**— 两个成员协作：

| 改造项 | 借鉴来源 |
|--------|---------|
| 上下文总线（事件流+结构化存储） | lamtools-ecosystem 信息桥 |
| 执行层直连 | lamtools-ecosystem 三层架构 |
| 文档状态字段 | lamtools-ecosystem writing/complete/stale/aborted |
| 画像交叉印证 | lamtools-ecosystem 画像权重机制 |

**Phase 3（+ Butler）**— 管家上线：

| 改造项 | 借鉴来源 |
|--------|---------|
| Butler 三触发干预 | lamtools-ecosystem Butler 评价 |
| 上下文打包与裁剪 | lamtools-ecosystem Mate 转接 |
| 画像精炼 | lamtools-ecosystem Butler 精炼方向 |
| PLAN 自进化 | mental-model PLAN 回写 CON |

### 9.7 核心洞察补充

11. **PER 是 LamImager 最缺失的架构层**：三个学习项目都有 Agent 定义机制（Claude Code 的 Agent、OpenCode 的 AgentDef、learn-claude-code 的 AGENT_TYPES），但 LamImager 完全没有。没有 PER，MEN 无法选择，Skill 无法过滤，Prompt 组装线无法分层。PER 是所有其他改造的前提。

12. **mental-model.md 的 Prompt 组装线是 LamImager 最直接的改造蓝图**：当前各节点的 system prompt 是分散硬编码的，没有统一的组装逻辑。mental-model.md 的"PER → Skill → MEN → CON(任务) → CON(画像) → 历史PLAN"六层组装顺序，可以直接实现为 `PromptAssembler` 类，替换现有的 `build_planner_system_prompt()` 和 `_build_prompt_builder_system()` 等分散函数。

13. **CON 分层是解决 token 膨胀的根本方案**：learn-claude-code 的 micro_compact 是战术方案（每轮静默压缩），mental-model.md 的 Hot/Cold CON 分层是战略方案（根本不把冷数据放进 prompt）。两者应结合使用——Hot CON 内部用 micro_compact 控制体积，Cold CON 用结构化存储支持按需检索。

14. **画像体系是 Imager 单成员阶段就可以启动的**：lamtools-ecosystem.md 明确说"单成员画像虽无法交叉印证，但足以提供基础偏好优化"。ImagerProfile 可以从生成历史中提取风格偏好、色调倾向、迭代耐性等维度，作为 CON(画像) 层注入 prompt。这不需要 Butler 或 Mate，现在就可以做。

15. **"模型即 Agent"与 PER/CON/MEN/PLAN 是同一哲学的不同表达**：learn-claude-code 说"The model IS the agent. Code just runs the loop."——代码构建 Harness（工具、知识、观察、行动接口、权限），让 LLM 自行推理。mental-model.md 的 PER/CON/MEN/PLAN 就是 Harness 的结构化定义：PER 定义角色边界，CON 提供情境信息，MEN 提供思维模式选择，PLAN 提供执行框架。代码不实现智能，只构建 LLM 做决策所需的世界。

---

## 十、改造时机与策略分析

> 核心问题：learning-report 识别的改造项，应该放在 P3、P4、还是之后？
> 分析方法：将改造项按"对现有架构的侵入性"和"对 P3/P4 目标的必要性"两个维度分类

### 10.1 现有路线图的阶段定义

先回顾 ROADMAP.md 中各阶段的定位：

| 阶段 | 定位 | 核心交付 | 状态 |
|------|------|---------|------|
| **P1** | 执行内核 | 4 种执行器 + 三入口收敛 + 前端拆分 | ✅ 完成 |
| **P2** | LangGraph 集成 | 8 节点图 + checkpoint + PlanningContext + 计费 | ✅ 完成 |
| **P3** | 高级功能 | 偏好评分 + CriticOutput 标准化 + Mask 精修 + Plan 自动保存与复用 | 📐 设计完成，未实现 |
| **P4** | 架构过渡 | Core SDK 抽取 + 独立包结构 + Imager 迁移 + 代码分层 | 📋 规划中 |

**关键约束**：P4 的目标是"从 Imager 单体中抽取共享基建为 LamTools Core SDK"。这意味着 P4 是一个**架构重组**阶段，不是功能开发阶段。所有需要在 Core SDK 中存在的模块，都必须在 P4 之前或期间完成设计。

### 10.2 改造项分类：按侵入性 × 必要性矩阵

将 learning-report 识别的所有改造项按两个维度分类：

- **侵入性**（横轴）：改造对现有代码的影响范围——低（新增独立模块）、中（修改现有模块接口）、高（重构核心数据流）
- **必要性**（纵轴）：对 P3/P4 目标的支撑程度——P3 必需、P4 必需、P4 之后

```
                    P3 必需                    P4 必需                   P4 之后
                 ┌──────────────────────┬──────────────────────┬──────────────────────┐
  高侵入性       │ Prompt 组装线        │ CON Hot/Cold 分层    │ 上下文总线           │
  (重构核心流)   │ Skill 两层注入       │ PLAN 持久化+依赖图   │ Butler 三触发干预    │
                 │                      │                      │ 执行层直连           │
                 ├──────────────────────┼──────────────────────┼──────────────────────┤
  中侵入性       │ PER 层               │ 上下文总线事件分类   │ 画像交叉印证         │
  (修改模块接口) │ MEN 层               │ 文档状态字段         │ 画像精炼             │
                 │ micro_compact        │                      │ PLAN 自进化          │
                 ├──────────────────────┼──────────────────────┼──────────────────────┤
  低侵入性       │ ImagerProfile 画像   │ 身份重注入           │ Proactive 主动模式   │
  (新增独立模块) │ Nag Reminder         │ Nag Reminder         │ Doom Loop 检测       │
                 │                      │                      │ 桌面宠物             │
                 └──────────────────────┴──────────────────────┴──────────────────────┘
```

### 10.3 核心判断：改造应该在 P3 做，不要等到 P4

**结论：大部分改造应该在 P3 做，P3 应该重新定义范围。**

理由如下：

#### 理由 1：P3 已有的"偏好评分"和"Plan 自动保存"与 learning-report 的改造项高度重合

| P3 原定项 | learning-report 对应改造 | 重合度 |
|----------|------------------------|--------|
| 用户偏好收集与评分系统 | ImagerProfile 临时画像 + CON(画像) 层 | **90%** — P3 的"偏好"就是 CON(画像) 的数据源 |
| Plan 自动保存与复用 | PLAN 持久化 + 依赖图 + 历史PLAN 匹配 | **80%** — P3 的"自动保存"就是 PLAN 持久化，"复用"就是历史PLAN 回写 CON |
| CriticOutput 接口标准化 | decision_node 改造（让 LLM 判断而非硬编码阈值） | **60%** — CriticOutput 已是 P2→P3 桥梁，但 decision 逻辑需要重新审视 |

**结论**：P3 原定的功能与 learning-report 的改造项不是两件事，而是同一件事的不同表述。P3 应该吸收 learning-report 的改造，而不是另起炉灶。

#### 理由 2：P4 是架构重组，不是功能开发——改造必须在 P4 之前完成

P4 的核心任务是"从 Imager 单体中抽取 Core SDK"。如果 P3 没有把 PER/CON/MEN/PLAN/Skill 这些架构层做好，P4 抽取出来的 Core SDK 就是一个空壳——没有 PersonaDef、没有 ContextManager、没有 MentationDef、没有 SkillInjector。

**P4 需要抽取的模块，必须在 P3 中先存在**：

| P4 要抽取的 Core SDK 模块 | P3 需要先实现的 | 如果 P3 不做 |
|--------------------------|---------------|-------------|
| 画像引擎 | ImagerProfile + CON(画像) 层 | P4 抽取的画像引擎没有数据源和消费方 |
| 上下文总线 | CON Hot/Cold 分层 + 事件分类 | P4 抽取的上下文总线没有分层逻辑 |
| LLM 客户端 | Prompt 组装线（统一 PER→Skill→MEN→CON） | P4 抽取的 LLM 客户端没有组装逻辑 |
| 事件总线 | LamEvent 事件分类（进度 vs 完成） | P4 抽取的事件总线没有消费语义 |

#### 理由 3：等到 P4 之后做 = 等到 LamCoder 上线后再做 = 太晚了

ROADMAP.md 明确说"P4 完成后才能启动 LamCoder"。如果改造推迟到 P4 之后：
- LamCoder 上线时没有 PER 层 → Coder 和 Imager 共用同一套硬编码 prompt，无法角色区分
- LamCoder 上线时没有上下文总线 → Coder 和 Imager 无法互传产物
- LamCoder 上线时没有画像交叉印证 → Coder 和 Imager 各自独立画像，无法互相增强

**这些改造是 LamCoder 能否正常工作的前提，不是锦上添花。**

### 10.4 重新定义 P3：吸收 learning-report 的改造

建议将 P3 重新定义为两个子阶段：

#### P3A：架构层搭建（PER/CON/MEN/Skill/Prompt 组装线）

这是最核心的改造——建立 mental-model.md 定义的四个运行时系统，替换现有的硬编码逻辑。

| 改造项 | 改造内容 | 涉及文件 | 侵入性 | 预期收益 |
|--------|---------|---------|--------|---------|
| **PER 层** | 新增 `PersonaDef` + `PERSONAS` 注册表，sidebar/agent mode 各自绑定 Persona | 新增 `core/persona.py`；修改 `graph.py`（绑定 persona）、`graph_llm.py`（读取 persona） | 中 | sidebar/agent mode 角色区分，为未来 Coder/Butler 角色铺路 |
| **Prompt 组装线** | 新增 `PromptAssembler`，按 PER→Skill→MEN→CON(任务)→CON(画像)→历史PLAN 六层组装 | 新增 `core/prompt_assembler.py`；修改 `capability_prompts.py`（降级为片段提供者）、各节点（改用 assembler） | 高 | 消除各节点硬编码，统一组装逻辑 |
| **Skill 两层注入** | `SkillInjector` Layer 1（描述）+ Layer 2（按需加载），经 PER 过滤 | 新增 `core/skill_injector.py`；修改 `skill_node.py`（改用 injector）、`skill_engine.py`（提供 layer1/layer2 接口） | 中 | 省 ~18,000 token/次，同一 Skill 在不同角色出不同结果 |
| **MEN 层** | 新增 `MentationDef` + `MENTATION_TEMPLATES`，PER+CON 选择 | 新增 `core/mentation.py`；修改 `prompt_assembler.py`（注入 MEN 段） | 中 | 根据情境切换思维模式（精准交付/创意探索/迭代精修） |
| **CON Hot/Cold 分层** | `ContextManager` = HotCON（进 prompt）+ ColdCON（做索引） | 新增 `core/context_manager.py`；修改 `planning_context.py`（降级为 HotCON 的计算引擎） | 中 | 长会话不丢上下文，冷数据可检索 |

**P3A 的依赖顺序**：

```
PER ──→ Skill 两层注入（需要 PER 过滤）
  │
  ├──→ MEN 层（需要 PER 滤网）
  │
  └──→ Prompt 组装线（需要 PER + Skill + MEN + CON）
         │
         └──→ CON Hot/Cold 分层（组装线消费 HotCON）
```

**建议实施顺序**：PER → Skill 两层注入 → MEN → Prompt 组装线 → CON 分层

#### P3B：功能增强（画像/PLAN 持久化/压缩/身份重注入）

在 P3A 的架构层之上，叠加具体功能。

| 改造项 | 改造内容 | 依赖 P3A | 涉及文件 | 侵入性 |
|--------|---------|---------|---------|--------|
| **ImagerProfile 画像** | 从生成历史提取风格偏好、色调倾向、迭代耐性，作为 CON(画像) 层 | 需要 CON 分层 + Prompt 组装线 | 新增 `services/profile.py`；修改 `context_manager.py`（画像进 HotCON） | 低 |
| **PLAN 持久化 + 依赖图** | `ExecutionPlanV2` 增加 `blockedBy` + JSON 持久化 + 断点续执行 | 需要 CON 分层（ColdCON 存历史 PLAN） | 修改 `schemas/execution.py`；新增 `services/plan_persistence.py` | 中 |
| **micro_compact** | 每轮静默压缩旧 tool result，保留最近 3 个 | 需要 CON 分层（HotCON 内部压缩） | 修改 `context_manager.py`（HotCON.compact()） | 低 |
| **身份重注入** | 压缩后自动重注入 PER 身份块 | 需要 PER 层 + CON 分层 | 修改 `context_manager.py`（compact 后检查是否需要重注入） | 低 |
| **Nag Reminder** | executor 长时间不更新进度时注入提醒 | 无强依赖 | 修改 `graph.py`（executor_node 循环中检查） | 低 |
| **Plan 自动保存与复用** | P3 原定项——每次生成的 plan 永久保存，支持精确匹配复用 | 需要 PLAN 持久化 | 新增 `core/agent/nodes/plan_saver_node.py`；修改 `graph.py`（添加节点） | 中 |
| **CriticOutput 标准化** | P3 原定项——critic 接口从 P2 的 dataclass 升级为 P3 的结构化输出 | 无强依赖 | 修改 `critic_interface.py`、`critic_node.py`、`decision_node.py` | 低 |
| **Mask 精修** | P3 原定项——图像局部编辑 | 无强依赖 | 新增 `services/mask_refinement.py` | 低 |

**P3B 的依赖顺序**：

```
CON Hot/Cold 分层 ──→ ImagerProfile（画像进 HotCON）
      │
      ├──→ PLAN 持久化（ColdCON 存历史 PLAN）
      │         │
      │         └──→ Plan 自动保存与复用
      │
      ├──→ micro_compact（HotCON 内部压缩）
      │         │
      │         └──→ 身份重注入（compact 后重注入 PER）
      │
      └──→ ImagerProfile + PLAN 持久化 ──→ 历史PLAN 匹配（ColdCON 检索）

独立（无 P3A 依赖）：
  Nag Reminder → CriticOutput 标准化 → Mask 精修
```

### 10.5 P4 应该做什么：架构重组而非功能开发

P3 完成后，LamImager 内部已经有了 PER/CON/MEN/PLAN/Skill 的完整架构层。P4 的任务是从 Imager 中把这些架构层**抽取**为 Core SDK，而不是**开发**新功能。

| P4 任务 | 前提（P3 必须交付） | P4 做什么 |
|--------|-------------------|----------|
| Core SDK 抽取 | `PersonaDef`、`ContextManager`、`MentationDef`、`SkillInjector`、`PromptAssembler` 已在 Imager 中运行 | 将这些类从 `backend/app/core/` 移至 `lamtools-core/` 独立包 |
| 上下文总线 | CON Hot/Cold 分层 + 事件分类已实现 | 将 `ContextBus`（事件流+结构化存储+WAL）从 Imager 移至 Core SDK |
| 画像引擎 | `ImagerProfile` 已实现 | 将画像引擎泛化（从 Imager 专用 → 通用画像接口），移至 Core SDK |
| Imager 迁移 | 上述模块已抽取 | Imager 改为 `import lamtools_core`，删除本地实现 |
| 独立仓库化 | Imager 已基于 Core SDK 运行 | Imager 和 Core SDK 分仓库，CI/CD 独立 |

**P4 不应该做的事**：
- ❌ 在 P4 中开发 PER/CON/MEN 等架构层——这些应该在 P3 中完成
- ❌ 在 P4 中开发新功能——P4 是纯粹的架构重组
- ❌ 在 P4 中修改 Prompt 组装逻辑——P3 已经统一了

### 10.6 P4 之后（LamCoder 上线及后续）

P4 完成后，Core SDK 就绪，可以启动 LamCoder。此时 learning-report 识别的跨成员改造项才有意义：

| 改造项 | 启动时机 | 借鉴来源 |
|--------|---------|---------|
| 上下文总线（事件流+结构化存储+WAL） | LamCoder 启动时 | lamtools-ecosystem 信息桥 |
| 执行层直连 | LamCoder + Imager 并行时 | lamtools-ecosystem 三层架构 |
| 文档状态字段 | LamCoder + Imager 并行时 | lamtools-ecosystem writing/complete/stale/aborted |
| 画像交叉印证 | LamButler 上线时 | lamtools-ecosystem 画像权重机制 |
| Butler 三触发干预 | LamButler 上线时 | lamtools-ecosystem Butler 评价 |
| 上下文打包与裁剪 | LamMate 上线时 | lamtools-ecosystem Mate 转接 |
| 画像精炼 | LamButler 上线时 | lamtools-ecosystem Butler 精炼方向 |
| PLAN 自进化 | LamButler 上线后 | mental-model PLAN 回写 CON |

### 10.7 修订后的完整路线图

```
P3A（架构层搭建）
│
├── 1. PER 层 — PersonaDef + PERSONAS 注册表
│      sidebar_assistant / imager 两个角色
│      新增 core/persona.py
│
├── 2. Skill 两层注入 — SkillInjector Layer1/Layer2 + PER 过滤
│      省 ~18,000 token/次
│      新增 core/skill_injector.py，修改 skill_node.py
│
├── 3. MEN 层 — MentationDef + MENTATION_TEMPLATES
│      精准交付 / 创意探索 / 迭代精修 三种模式
│      新增 core/mentation.py
│
├── 4. Prompt 组装线 — PromptAssembler
│      PER → Skill → MEN → CON(任务) → CON(画像) → 历史PLAN
│      新增 core/prompt_assembler.py，修改各节点
│
└── 5. CON Hot/Cold 分层 — ContextManager
       HotCON（进 prompt）+ ColdCON（做索引）
       新增 core/context_manager.py，修改 planning_context.py

P3B（功能增强）
│
├── 6. ImagerProfile 画像 — 从生成历史提取审美偏好
│      新增 services/profile.py
│
├── 7. PLAN 持久化 + 依赖图 — blockedBy + JSON 持久化
│      修改 schemas/execution.py，新增 services/plan_persistence.py
│
├── 8. micro_compact — 每轮静默压缩旧 tool result
│      修改 context_manager.py
│
├── 9. 身份重注入 — 压缩后重注入 PER 身份块
│      修改 context_manager.py
│
├── 10. Nag Reminder — executor 不更新进度时注入提醒
│       修改 graph.py
│
├── 11. Plan 自动保存与复用 — P3 原定项
│       新增 nodes/plan_saver_node.py
│
├── 12. CriticOutput 标准化 — P3 原定项
│       修改 critic_interface.py, critic_node.py, decision_node.py
│
└── 13. Mask 精修 — P3 原定项
        新增 services/mask_refinement.py

P4（架构重组 — Core SDK 抽取）
│
├── PersonaDef → lamtools-core/persona/
├── ContextManager → lamtools-core/context/
├── MentationDef → lamtools-core/mentation/
├── SkillInjector → lamtools-core/skill/
├── PromptAssembler → lamtools-core/prompt/
├── ImagerProfile → lamtools-core/profile/（泛化为通用画像接口）
├── LamEvent + EventLog → lamtools-core/event/
├── 计费模块 → lamtools-core/billing/
├── LLM 客户端 → lamtools-core/llm/
└── Imager 迁移至 import lamtools_core

P4 之后（生态扩展）
│
├── LamCoder — 基于 Core SDK 独立仓库
│   └── 上下文总线 + 执行层直连 + 文档状态字段
│
├── LamButler — 管家上线
│   └── 三触发干预 + 画像交叉印证 + 画像精炼 + PLAN 自进化
│
├── LamSage — 知识库
│
└── LamMate — 陪伴
    └── 上下文打包与裁剪 + 画像采集
```

### 10.8 风险与注意事项

#### 风险 1：P3A 改动面大，可能引入回归

**缓解**：P3A 的每个改造项都是**新增模块 + 修改现有模块的调用方式**，不改变核心数据流。具体策略：
- `PersonaDef` 是纯新增，现有代码先不读取它（渐进式启用）
- `PromptAssembler` 先与现有 `build_planner_system_prompt()` 并行运行，对比输出一致后再切换
- `SkillInjector` 先只实现 Layer 1（描述注入），Layer 2（按需加载）后续再加

#### 风险 2：P3 范围膨胀，迟迟无法进入 P4

**缓解**：P3A 的 5 个改造项有明确的依赖顺序和交付标准：
- PER：`PersonaDef` 类可实例化 + sidebar/agent mode 绑定不同 persona → 交付
- Skill 两层注入：Layer 1 描述注入生效 + token 消耗下降 → 交付
- MEN：`MentationDef` 类可实例化 + planner 可根据情境切换模式 → 交付
- Prompt 组装线：`PromptAssembler` 替换所有节点的硬编码组装 → 交付
- CON 分层：HotCON/ColdCON 可分别读写 → 交付

P3B 的 8 个改造项中，**Mask 精修是唯一与架构改造无关的功能**，可以独立推进不阻塞其他项。

#### 风险 3：PER/CON/MEN 的设计可能与 Core SDK 的通用化需求冲突

**缓解**：P3A 设计时遵循 mental-model.md 的定义，这些定义本身就是面向 LamTools 全家族的，不是 Imager 专用的。`PersonaDef` 的 `men_whitelist/tool_whitelist` 字段天然支持多角色——Imager 的 persona 和 Coder 的 persona 只是不同的 `PersonaDef` 实例。

#### 风险 4：缺少测试，大改造容易出问题

**缓解**：这是现有问题（整个项目无自动化测试），不是改造引入的新风险。建议在 P3A 开始前，至少为 `PromptAssembler` 和 `SkillInjector` 编写单元测试——这两个是改造的核心，且逻辑相对独立，容易测试。

### 10.9 一句话总结

**改造应该在 P3 做，P3 应该重新定义为 P3A（架构层搭建）+ P3B（功能增强），P4 只做架构重组不做功能开发，P4 之后才是跨成员协作的改造。**

核心逻辑链：
1. P3 原定的"偏好评分"和"Plan 自动保存"与 learning-report 的改造项高度重合 → 不是额外工作，是同一件事
2. P4 要抽取 Core SDK，但 Core SDK 需要先有东西可抽 → P3 必须先把 PER/CON/MEN/Skill/Prompt 组装线做好
3. P4 之后 LamCoder 上线，需要 PER 角色区分和上下文总线 → 这些在 P3 中打好基础，P4 中抽取为共享模块
4. 跨成员协作（Butler 干预、画像交叉印证等）→ LamCoder 上线之后才有意义，不急
