# 16 ChatThread 与状态层 审计报告

> 审计日期：2026-08-13 ｜ 范围：`core/ui/src/components/ChatThread.vue` + `core/ui/src/appServer/*`（store.ts / selectors.ts / workbenchProjection.ts / workbenchActions.ts / client.ts / protocol.ts / messageParts.ts / snapshot.ts / index.ts），并交叉核对外围接线（demo/App.vue、useCoreWorkbenchProjectionController.ts、useCoreLiveComposerController.ts）与后端发射语义（runtime_projection.py / kernel/loop.py）。全程只读。
> 前置阅读：docs/core-ui-streaming-perf.md（已知设计：rAF 帧内合并、投影缓存、v-memo 每消息化、快照边界策略、transient delta 不落库——本报告不重复列为问题）。

## 1. 概况

ChatThread.vue 在"消息视图组件化"重构后已是薄壳（模板 46 行 + 全局 CSS），核心逻辑全部下沉到 appServer 状态层与 MessageView.vue。状态层整体设计质量高：**快照 hydrate 跳过判定**（receivedEventIds + 内容指纹）是防 56MB 快照洪泛重渲的关键机制；**投影两级缓存**（part 级 source 引用判定 + 消息级指纹）严格遵循 AGENTS.md:20 的"新消息对象"不可变约定；**帧内 delta 合并** + 50ms setTimeout 兜底双保险；usage 合并正确处理 cumulative 计数器。审计未发现 S1 级缺陷，但发现 1 个 S2（重连/首连期间事件丢弃 + 快照跳过判定无法自愈，导致当前 turn 内容永久缺块）、3 个 S3、11 个 S4。

## 2. 问题清单

### S2

- **[S2] 首个快照落地前到达的流式事件被静默丢弃，且 hydrate 跳过判定无法自愈，turn 内容永久缺块**
  - 位置：`core/ui/src/appServer/store.ts:205`（frame 回调 `if (!runtime.state) return`）、`store.ts:186-188`（enqueueEvent 先记 id 再丢事件）、`store.ts:685-702`（shouldHydrateSnapshot 不比较 core.items 内容）
  - 问题：`enqueueEvent` 先把事件 id 写入 `receivedEventIds`（186-188 行），再把 core/runItem 事件推入 pendingEvents；帧回调执行时若 `runtime.state` 仍为 null（首连或 disconnect() 后重连、`thread/resume` 响应尚未返回——大线程上 resume 响应可达数百 ms），`pendingEvents.splice(0)` 后直接 return（205 行），**事件永久丢失**。而恰在此时段到达的往往是另一个窗口正在流式的 **transient delta**（kernel/loop.py F1 后 delta 不落库、不在快照中），因此：
    1. 丢失的 chunk 不在 resume 快照里，无法由首次 hydrate 补回；
    2. 后续 delta 继续 append 到截断的 content 上，该 turn 的消息内容缺开头一段；
    3. turn 结束边界快照到达时，`shouldHydrateSnapshot` 只比较 seen_event_ids（全部已见，因为所有 persisted 事件都实时到达过）、requests/queue/顶层 items/status——**不比较 `core.items` 的内容**（snapshotItemsChanged 只比顶层 items 的 status/content，store.ts:753-767），判定跳过 hydrate → **缺块内容持续到下一个 turn 或手动刷新**。
  - 影响：多窗口并存 / 断线重连 / 应用启动时恰逢他人 turn 在流式——该 turn 的流式正文缺块且不自愈，用户看到"内容被截断"的错误输出。不触发白屏，但属于状态错乱（增量路径与规范快照路径永久不一致）。
  - 修复建议：a) 帧回调在 `!runtime.state` 时不丢弃事件，改为挂起（保留 pendingEvents 或设 droppedEvents 标志），首个快照落地后再回放；b) `shouldHydrateSnapshot` 增加 core.items 内容指纹比较（如逐 item 比 content/status 引用或值），使事件派生状态与规范快照状态一旦分歧即强制 hydrate。

### S3

- **[S3] 合并批次的去重是"全有或全无"——批内任一 id 已见则整批丢弃，未见事件被误杀**
  - 位置：`core/ui/src/appServer/store.ts:488-489`
  - 问题：`applyCoreRunItemEvent` 用 `coalescedEventIds.some((id) => seenEventSet.has(id))` 做去重，命中即 `return snapshot` 整批丢弃。后端 E1 会把 20ms 窗口内同 (thread,item,kind) 的 delta 合并为一条 WS 消息（`_coalesced_event_ids` 记录全部 id），重连重放事件与实时事件可能落入同一合并批次：重放的 persisted 事件 id 在客户端 2000 窗口内已见（曾实时收到），而批内新增的实时 delta id 未见——整批被丢，未见 delta 永久丢失（transient 不入快照）。
  - 影响：重连窗口期间偶发丢一个 delta chunk；触发条件苛刻（重连 + 合并窗口恰好跨已见/未见边界），但语义上"未见事件被已见事件连带丢弃"是明确的正确性缺陷。
  - 修复建议：改为按 id 过滤——仅丢弃 `coalescedEventIds` 中已见的 id，保留未见 id 继续应用（或拆批后只应用未见子集）。

- **[S3] ChatThread v-memo 将 checkpointTurnIds（Set）整体作为缓存键——每次 checkpoint 变化整线重渲**
  - 位置：`core/ui/src/components/ChatThread.vue:12`（v-memo 依赖 `checkpointTurnIds`）、`core/ui/src/demo/App.vue:1481`（`computed(() => new Set(Object.keys(checkpointsByTurnId.value)))`）
  - 问题：v-memo 第 8 项是 Set **引用**。App.vue:1498 每次 checkpoint 刷新都会整体替换 `checkpointsByTurnId.value` → computed 重算 → 新建 Set → 引用变化 → **全部消息的 v-memo 缓存同时失效，整线重渲一次**。这与 perf 文档"阶段 4 补丁"对 `processExpandedIds`/`typingMessageIds` 的处理（改为每消息布尔 `has(msg.id)`）正是同一类坑，checkpointTurnIds 漏网——回退/分叉/编辑操作（MessageView 的 hasTurnCheckpoint 依赖它）在大会话上触发 ~O(窗口) 重渲。
  - 影响：每次 checkpoint 操作后 150 条窗口消息整线重渲（大线程上毫秒~百毫秒级卡顿）；频率低但模式与既有修复相悖。
  - 修复建议：v-memo 改 `checkpointTurnIds.has(msg.id)` 布尔；或把 computed 改为缓存稳定 Set（仅在内容变化时新建）。

- **[S3] typingMessageIds 只 add 永不 delete，且原地突变不触发响应式**
  - 位置：`core/ui/src/demo/App.vue:2439`（`typingMessageIds.value.add(msg.id)`，无任何 delete 路径）、`App.vue:1157`（ref 定义）、消费点 `components/MessageView.vue:43`（`typingMessageIds?.has(msg.id)` 驱动 TypewriterText）
  - 问题：Set 在 watch(messages, {deep:true}) 内原地 add：a) 集合随会话内用户消息数无界增长（内存泄漏，长会话可达数千条目）；b) 原地突变不触发 ref 响应式，MessageView 的 typing 指示只能"搭便车"在其他重渲时更新；c) 永不删除意味着 typewriter 效果状态残留。perf 文档已列为遗留（"typingMessageIds 只 add 永不 delete"），本次审计确认仍在。
  - 影响：内存随会话增长 + 打字指示器状态语义错误（低可见性）。
  - 修复建议：turn 结束/消息渲染完成后 delete；改用 `typingMessageIds.value = new Set(...)` 提交新引用（遵守 commitMsg 约定）。

### S4

- **[S4] `normalizeDeliveryRecord` 是恒等函数，workspace_delivery 归一化整段失效（死代码）**
  - 位置：`core/ui/src/appServer/selectors.ts:563-566`（`return value` 恒等返回）、`selectors.ts:526-561`（normalizeMetadataDelivery 依赖其"可能改写"来判断——恒等后所有分支恒为 false，函数整体退化为 `return value`）
  - 问题：`normalizeDeliveryRecord` 对任意输入返回原值，`normalizeDeliveryRecord(x) !== x` 恒 false，normalizeMetadataDelivery 的 workspace_delivery / workspaceDelivery / diagnostics 三处归一化全部不会执行；疑似重构半成品（对比 `normalizeLegacyDeliveryFields` 的 target_tokens→limit_tokens 是真实生效的）。
  - 影响：无行为 bug（退化为透传），但死代码误导维护者；若未来确有 delivery 字段重命名需求，此处静默失效。
  - 修复建议：删除恒等函数与失效分支，或补全真正的归一化实现。

- **[S4] `isFinalAssistantContentItem` 与 `lastAgentMessageItemIdForTurn` 为死代码**
  - 位置：`core/ui/src/appServer/selectors.ts:431-455`
  - 问题：全仓库 grep 无任何调用方（仅定义）。且其实现 O(n) 逐项扫描，若未来被在热路径引用会引入 O(n²)。
  - 修复建议：删除，或落地其注释所暗示的"最终助手消息"语义并加测试。

- **[S4] `CORE_APP_SERVER_PROTOCOL_VERSION` 导出但从未使用（无版本协商/校验）**
  - 位置：`core/ui/src/appServer/protocol.ts:1`、`index.ts:13`（导出）、`protocol.ts:5`（CoreAppEvent.protocol_version 字段）
  - 问题：常量与字段定义齐全，但 client.ts 既不发送也不校验 protocol_version——前后端协议演进无护栏，字段名/事件形状不兼容时前端静默错乱。
  - 修复建议：initialize 参数携带版本；handleMessage 对不匹配版本告警或拒绝。

- **[S4] kind='status' 的 runItem 事件被 early-return，payload 永不并入 item**
  - 位置：`core/ui/src/appServer/store.ts:493-509`（`if (kind === 'status')` 仅更新 turns/status 后返回）
  - 问题：后端 runtime_projection.py 对 no_progress 等场景发出 `kind="status"` 且 `item_id=tool_item_id`（复用 tool item，payload 带 `content=message`）——前端早退导致该 payload 不合并进 item，流式路径不显示 no_progress 提示，快照路径才有。事件路径与快照路径行为不一致。
  - 影响：no_progress 提示在流式中缺失（低频、低可见）。
  - 修复建议：status 分支在早退前把 `runPayload`（type/content）合并进 `items[itemId]`。

- **[S4] client.ts handleMessage 的 JSON.parse 无 try/catch**
  - 位置：`core/ui/src/appServer/client.ts:133-134`
  - 问题：畸形帧（或二进制帧）抛异常中断当帧处理（其余帧不受影响），无日志、无错误上报。
  - 修复建议：try/catch 包裹 parse，失败时记录 lastError 并跳过。

- **[S4] connect() 中 initialize 失败时 socket 未显式关闭**
  - 位置：`core/ui/src/appServer/client.ts:46-74`
  - 问题：`request('initialize')` reject 后 socket 仍处于 OPEN，事件仍持续流入 onEvent（store 侧 generation 过滤了 onConnectionState，但事件照常 enqueue）；直到下一次 openClient 的 `runtime.client?.close()`（最迟 ~2s）才关闭。期间事件被应用到（可能已切换的）状态上。
  - 修复建议：initialize 失败路径中 `this.socket?.close()`。

- **[S4] receivedEventIds 超过 20 万整体 clear()，导致下一个快照强制全量 hydrate + 去重失效窗口**
  - 位置：`core/ui/src/appServer/store.ts:177-179`
  - 问题：clear 后任意快照的 seen ids 全部"未见"→ shouldHydrateSnapshot 恒真 → 下一次边界快照必然整体替换状态（大线程整线重渲，正是该机制要避免的）；同时重放去重短暂失效（重复事件可能重放，窗口内 usage 计数可能被重复合并——mergeUsageMetrics 对已 sum 的值再 sum）。
  - 影响：>20 万事件/会话的极端大线程上每 20 万事件一次全量重渲 + 去重盲区。
  - 修复建议：改为淘汰最旧一半而非清空，或与 snapshot 的 seen_event_ids 交集裁剪。

- **[S4] 带附件的用户消息每帧重建，绕过投影消息缓存与附件 part 的 v-memo**
  - 位置：`core/ui/src/appServer/selectors.ts:632-651`（inputAttachments 每帧新建数组）、`workbenchProjection.ts:235`（指纹含 `message.attachments` 数组**引用**）、`workbenchProjection.ts:181-189`（附件 part 不经 buildOrGetPart 缓存，每帧新建对象）
  - 问题：attachments 数组每次 selectChatMessages 都新建 → 消息指纹恒失配 → 带附件消息的 message 缓存永不命中（每帧重建消息对象）；附件 part 无 part 级缓存，每帧新对象 → 对应 part 的 v-memo 恒 miss。
  - 影响：仅带附件消息受影响（附件数量少、渲染轻，实际开销小），但违背缓存设计意图。
  - 修复建议：attachments 数组按 item 内容指纹缓存（与 subAgentChildren 同模式），或指纹改用 `message.attachments` 的深层指纹。

- **[S4] selectChatMessages 每帧全量 O(items) 扫描（已知遗留）**
  - 位置：`core/ui/src/appServer/selectors.ts:69-140`、`workbenchProjection.ts:117`（每次快照变化全量重跑）
  - 问题：perf 文档"遗留"节已确认——每 tick 全量重算 mergedItemOrder/子代理树/每条消息 isProtocolEnvelopeText JSON.parse 尝试；2802 item 线程每 tick 5-20ms。快照频率下降后影响缩小，但流式每帧仍全量执行。
  - 修复建议：投影窗口化后进一步改为"增量 select"（按 changedItemIds 或脏标记），或至少把 isProtocolEnvelopeText 的 JSON.parse 缓存化。

- **[S4] item.deltas 数组只增不减且 UI 无任何消费**
  - 位置：`core/ui/src/appServer/store.ts:551-553`（`item.deltas = [...(existing.deltas ?? []), delta]`）
  - 问题：每帧 delta 追加进数组；全仓库 grep 确认组件层无 `.deltas` 消费（coreItemToAppItem 仅透传）。超长回合下该数组与 content 重复占用内存且无界。
  - 修复建议：确认协议是否需要；若仅历史兼容，可裁剪（如只保留最近 N 条）或去掉。

- **[S4] 帧回调无异常保护，单事件处理异常导致同帧剩余事件丢失**
  - 位置：`core/ui/src/appServer/store.ts:202-215`
  - 问题：`eventFrameScheduled = false` 与 `splice(0)` 先执行，applyCoreRunItemEvent 循环中任一事件抛异常（如畸形 payload）则异常逸出 rAF，本帧其余事件永久丢失且无日志。
  - 修复建议：循环包 try/catch（或 try/finally），异常事件记 lastError 并跳过。

## 3. 该区 Top 3 问题

1. **[S2] 首个快照前的事件丢弃 + hydrate 跳过判定缺 core.items 比较**——增量事件路径与规范快照路径一旦分歧即永久化（多窗口/重连场景下 turn 内容缺块不自愈）。这是本区唯一触及"状态错乱导致数据缺失"的问题。
2. **[S3] 合并批次全有或全无去重**——"已见 id 连带丢弃未见 id"，是去重逻辑里语义最危险的一条（宁可错杀不可放过），且与后端 E1 合并特性叠加后真实可达。
3. **[S3] checkpointTurnIds 整 Set 进 v-memo**——与已修复的 processExpandedIds 同坑，checkpoint 操作触发整线重渲，说明"Set 进 v-memo"教训尚未形成团队模式（typingMessageIds 的只增不删同理）。

## 4. 亮点

- **快照 hydrate 跳过判定**（store.ts:164-184, 685-767）：receivedEventIds 置于响应式状态之外、guard 在记录前读取、逐项比较 requests/queue/顶层 items/status——设计缜密，注释完整解释"为什么全量 hydrate 会破投影缓存"。
- **投影两级缓存**（workbenchProjection.ts:31-85, 248-287, 375-407）：part 级按 sourceCoreItem/sourceRequest/submitting/subLineItems 四个引用判定、消息级指纹逐成员 === 比较、subAgentChildren 数组引用复用——完整落实 AGENTS.md 的 commitMsg 不可变约定；`nextCoreProcessExpandedIds` 内容稳定时返回同一 Set 引用，是 v-memo 友好的典范。
- **mergeUsageMetrics**（store.ts:794-822）：正确区分 per-call 计数与 cumulative 指标（replace=true 跳过）、sum 后重算 cache_hit_rate、duration 取 max——后端语义还原到位。
- **帧内合并双保险**（store.ts:404-424）：rAF 主拍 + 50ms setTimeout 兜底（fired 标志防双跑），对 rAF 饿死/窗口遮挡场景有真实防护（CDP 实测 2622→112 条消息）。
- **连接生命周期管理**（store.ts:100-135, client.ts:76-84）：generation 递增隔离过期回调、disconnect 全量清理（timer/pendingEvents/client/state）、请求超时（30/60s）与 CoreAppServerClosedError 拒绝 pending——错误路径完整。
- **ChatThread 薄壳化后的 v-memo**（ChatThread.vue:12）：每消息布尔 + 命名事件处理器稳定引用 + 五处 part 级 v-memo 隔离，是性能修复包的正确落地形态。

## 5. 审计范围与方法

- 范围：`core/ui/src/components/ChatThread.vue`（1898 行，含 46 行模板 + 全局 CSS）、`core/ui/src/appServer/` 全部 9 个文件（store.ts 838 / selectors.ts 651 / workbenchProjection.ts 505 / workbenchActions.ts 203 / client.ts 187 / protocol.ts 149 / messageParts.ts / snapshot.ts / index.ts）。
- 交叉核对外围：`demo/App.vue`（runtimeController 接线、checkpointTurnIds/typingMessageIds 生产端、unmount 清理）、`composables/useCoreWorkbenchProjectionController.ts`（投影驱动与缓存生命周期）、`composables/useCoreLiveComposerController.ts`（startTurn 返回布尔封装——已确认无类型错配问题）、`components/MessageView.vue`（v-memo/partMemo/typing 消费点）、后端 `runtime_projection.py` / `kernel/loop.py`（runItem kind 与 transient 语义）。
- 方法：全程只读（Read / grep / git grep）；事件流路径逐帧推演（enqueueEvent→coalesce→apply→hydrate guard）；对照 docs/core-ui-streaming-perf.md 排除已知设计；所有发现均可定位到 file:line。
- 严重度口径：S1=状态错乱导致数据丢失/白屏（无）；S2=状态错乱、增量与快照路径永久分歧（1）；S3=性能/正确性边缘缺陷（3）；S4=死代码/健壮性/内存建议（11）。合计 15 条。
