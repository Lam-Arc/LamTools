# Core UI 流式性能优化（UI 卡顿调查与修复计划）

> 状态：快速见效包已完成（2026-08-07）；结构包已完成（2026-08-07）；part 级 v-memo 隔离已完成（2026-08-07）。
> 发送/进会话延迟优化包已完成（2026-08-07，见文末）。
> 本文档是 Core UI 卡顿问题的唯一权威记录，任何后续会话先读这里。

## 背景

用户反馈 Core 界面"一卡一卡"——动画和流式输出都时不时一顿一顿。经全链路排查（前端 store → 投影 → ChatThread → MarkdownRenderer → 滚动 → 后端事件发射），根因是：**每个流式 tick 前端都做全量工作，主线程每帧被塞爆**，动画（spinner / v-beam 流光）与文字一起卡顿。动画本身不贵，是被饿死。

## 数据链路（每 tick）

后端模型每吐一个 chunk（`runtime.reply_delta`，无节流）→ 逐事件投影成 `core/runItem`（`core/src/lamtools_core/event/runtime_projection.py:276`，128 字符节流只作用于 content 全量更新，delta 事件照样逐 chunk 下发）→ WebSocket → 前端 rAF 批量 apply（`core/ui/src/appServer/store.ts:161`）→ 快照整体替换 → 级联全量重渲。

## 根因清单（8 项，按影响排序）

1. **全量消息投影重建**：`useCoreWorkbenchProjectionController.ts:45` 每个快照变化都重跑 `selectCoreWorkbenchMessages`（`appServer/workbenchProjection.ts:23`），重建全部消息和 part（O(items) 排序合并、sub-agent 树、`isProtocolEnvelopeText` 对每条消息做 JSON.parse 尝试）。
2. **ChatThread 巨型组件无 per-message 边界**（`components/ChatThread.vue`，5237 行）：`messages` 数组整体替换 → 整棵树重渲，`groupParts`/`compactGroups`/`processSummary`/`timelineParts`/`diffDisplayLines` 等 O(全部 part) 的函数对每条历史消息每帧全部重跑（ChatThread.vue:3240-3394）。
3. **ChatThread.vue:1606 watcher**：每帧把所有 part 拼成一个大字符串 `id:status|id:status|…`（O(全部 part)），回调里对每个 running part 又做 `new Set([...])` 复制。
4. **MarkdownRenderer 流式渲染每帧全量**（`components/MarkdownRenderer.vue:221`）：`renderStreaming` 多轮正则 + `DOMPurify.sanitize` 全文 + `v-html` 整体 innerHTML 替换（成本随内容长度线性增长，还会打断文本选区）。
5. **每帧强制回流**：`demo/App.vue:2072` `watch(messages, {deep:true})` → `scrollToBottom` 双次写 `scrollTop`（`composables/useCoreAutoFollowScroll.ts:83-85`）+ `syncThreadResizeObserver` + ResizeObserver 回调再次 scrollToBottom——一帧内多次强制布局。
6. **每帧 HTTP 请求**：`demo/App.vue:2086` `watch([activeSessionId, messages, latestStatus])` → `refreshGoal` 每帧发 `listGoals` 请求（有 generation guard 但请求照样发出）。
7. **快照不可变拷贝 O(items×events)**（`appServer/store.ts:377`）：每帧 N 个事件逐个 spread 拷贝全部 items + `seen_event_ids`（2000 条 slice）+ `deltas` 数组只增不减。
8. **后端每 chunk 都做投影转换**（`core/src/lamtools_core/app/default_agent.py:362` live_callback → `core_events_to_run_items`），模型快时 20-100+ events/s。

次要：`item/started`/`turn/accepted` 不走 rAF 批处理直接替换 state；`typingMessageIds` 只 add 永不 delete（App.vue:2081）。

## 快速见效包（已完成 2026-08-07）

> 验收标准：用户视角零可感知回退；渲染帧节奏不变（仍每帧一次），只削减帧内冗余工作。

| # | 改动 | 文件 | 用户可见影响 |
|---|------|------|------------|
| 1 | rAF 帧内先按 item_id 合并 delta 事件再 apply（`coalesceRunItemEvents`） | `appServer/store.ts` | 无（渲染结果同为帧末最新内容；deltas 粒度无 UI 消费） |
| 5 | 滚动合并为一帧一次；`scrollToBottom` 单次写 + 帧后仅 scrollHeight 变化时校正 | `composables/useCoreAutoFollowScroll.ts`、`demo/App.vue` | 无（最迟 1 帧跟随到位；force 保持立即） |
| 6 | `refreshGoal` 节流 2s（非防抖）+ `force` 参数；turn 结束 / 会话切换 force 刷新 | `composables/useCoreGoals.ts`、`demo/App.vue` | 趋近于零（长流式中 goal 每 2s 刷新一次；turn 结束立即） |
| 7 | ChatThread:1606 watcher getter 只收集 live 消息 parts | `components/ChatThread.vue` | 无（回调本就只处理 live 消息） |

### 验证

- 静态：`npm run typecheck` ✅ / `npm run test:contract` ✅（相关文件单独跑全部通过）/ `npm run build` ⚠️（ChatThread.vue:1016 报错，经对照实验确认是「样式精进」分支用户 WIP 的既有类型错误，与快速见效包无关——HEAD 版 ChatThread + 快速包其他文件组合构建零错误）
- 相关测试（单独跑，规避 jsdom 多文件串扰）：
  - `core-app-server-store.test.ts`（delta 合并）✅ 7/7
  - `core-workbench-scroll.test.ts`（滚动）✅ 5/5
  - `core-workbench-projection-controller.test.ts` ✅ 11/11
  - `core-live-turn-controller.test.ts` ✅ 3/3
  - `chat-thread-rollback.test.ts` ✅ 4/4
  - 既有失败（非本包引入，已对照实验确认）：`chat-thread-process.test.ts` 18 failed（无本包改动时同样失败）、`core-app-server-workbench-projection.test.ts` 1 failed（HEAD store.ts 时同样失败）、`session-sidebar`/`slot-contract`/`package-boundary-contract` 9 failed（HEAD 基线同样失败）
- 动态体验 checklist（人工验收，待完成）：
  1. 长文本流式平滑、无跳跃感；思考流与工具参数流正常
  2. spinner / beam 流光 / 呼吸动画流畅
  3. 流式中自动跟随滚动不抖动；手动上翻不被拉回；"回到最新"立即可用
  4. goal strip 最长 2s 内反映变化，turn 结束立即更新
  5. 全程无 WS 重连/事件丢失
  6. 长会话（几十条消息）下流式仍流畅
  7. 流式中文本可选中/复制不受影响
- 量化：DevTools Performance 录制（流式 10s），记录长任务（>50ms）数量作为基线（**待填**）

## 结构包（进行中）

> 依赖：**#2 与 #3 一起做**（#3 保证稳定引用，#2 保证重渲范围隔离）；#4 建议在观察前两包效果后再定。

### 阶段 1 — #3 投影增量（已完成 2026-08-07）

- `workbenchProjection.ts`：新增两级缓存（`createCoreWorkbenchProjectionCache`）——part 级（按 `snapshot.core.items[itemId]` + requestState + submitting 布尔判定）与消息级（按 content/parts 引用等指纹判定），未变化消息/part 的对象引用完全稳定
- `useCoreWorkbenchProjectionController.ts`：syncProjection 传缓存，线程切换时 `clear()`
- `store.ts` 无需改动（用底层引用比较，不依赖 changedItemIds）
- 新增 `tests/core-workbench-projection-cache.test.ts`（6 个引用稳定性契约测试，全绿）
- 微基准：60 消息线程投影 0.315ms → 0.134ms（2.35×）

### 阶段 2 — #2 MessageView 组件化（已完成 2026-08-07）

- `ChatThread.vue`（原 5237 行）瘦身为薄壳：v-for + 插槽转发；消息渲染整体迁入新组件 `MessageView.vue`（单消息组件，自递归处理 sub-line）
- 模板零变换搬移（prop 名保持 `msg`）；`<style>` 全局 CSS 留在 ChatThread（测试契约 + 零视觉回归）；内部 UI 状态（展开/折叠/decision draft/copy 反馈）全部下放到 MessageView 实例（状态变更只重渲对应消息）
- **关键机制**：`v-memo="[msg, assistantLabel, processExpandedIds, typingMessageIds, messageActions]"` + 命名事件处理器（内联箭头会让所有消息随父渲染重渲——slots/事件每次父渲染重建引用）。v-memo 依赖 = 消息渲染的全部外部输入；当前消费方（demo/CoreSubAgentDialog）不提供命名插槽，无 stale 风险
- 新增 `tests/chat-thread-messageview-isolation.test.ts`（3 个隔离契约测试：只重渲变化消息 / 同数组零重渲 / message-product 路由，全绿）
- 附带收益：`vue-tsc -b` 与 `npm run build` 恢复全绿（此前被「样式精进」WIP 的 ChatThread:1016 类型错误挡住）
- 回归验证：chat-thread-process 55 测试与基线逐项一致（18 红为 WIP 既有）；chat-thread-rollback 4/4、demo/scroll/projection 相关 32/32 全绿
- 适配：`chat-thread-process.test.ts` 的模板源码契约测试改读 `MessageView.vue`（一行路径）

### 阶段 3 — #4 Markdown 流式瘦身（已完成 2026-08-07）

- **streaming 模式跳过 DOMPurify.sanitize**：流式管线所有用户输入先经 escapeHtml，唯一非转义注入是 katex 输出（katex 自带输入转义，含 parse-error 兜底）。DOMPurify 每帧全量清洗整个增长中的内容是最大的单帧热路径之一。完成态渲染（`streaming=false`）仍保留 sanitize。
- **escapeHtml 4 次顺序 replace → 单 pass 字符映射**（`[&<>"]` 一次扫描，字节级等价——2000 随机样本等价性验证通过）
- **normalizeMarkdownLineBreaks 单 pass 优化放弃**：等价性测试证明 `" \n "` 重叠空白无法被不重叠的 replace 单 pass 正确处理，保留顺序 4 pass 原实现（防回归价值：等价性测试在实施前就抓到了该差异）
- 验证：markdown-renderer-style / markdown-renderer-links 4/4 绿；typecheck / `vue-tsc -b` / `npm run build` 全绿

### 阶段 4 — Markdown 增量分段渲染（已完成 2026-08-07）

**背景**：阶段 3 后实测发现 streaming 每帧 `renderStreaming` + `v-html` 全量 innerHTML 替换仍随内容长度线性暴涨（jsdom 基准：4KB→14.9ms、16KB→39ms、48KB→107ms/帧，远超 16ms 帧预算）——长文本流式"一顿一顿"的最终根源。

**实现**（`MarkdownRenderer.vue`）：
- streaming 模式改用增量 DOM：内容只在尾部增长 + 空行分隔的段边界永不回溯变化 → 已闭合段跨 tick 保留其 DOM 节点（对象级复用），仅重建尾部"开放段"
- 段切分 = `normalizeMarkdownLineBreaks` + `split(/\n{2,}/)`（与参考 `renderStreaming` 完全同源）；每段 HTML 用 `renderStreamingBlock`，解析后按序 append（DOM 结构与旧 v-html 逐字节同构）
- `streamedSegments` 组件实例级（`<script setup>` 顶层自动实例级）；streaming→false 切换时清理（DOM 交还 v-html 分支）；链接点击事件同时绑定两个 root
- streaming 的 `renderedHtml` 分支返回 ''（不再全量渲染）

**验证**：
- `tests/markdown-streaming-incremental.test.ts`：逐 tick DOM == 参考渲染器（块 tag + textContent 判据）+ 已闭合段节点跨 tick 复用 + streaming 结束清理，3/3 绿
- 随机等价性：10×60KB 随机 markdown 流（累计数百万字符、随机 tick 增量）textContent + 块结构逐段一致（innerHTML 字节对比在 jsdom 下对 katex 嵌套/未闭合标签有序列化假阳性，已用可靠判据替代）
- 性能：**每帧成本从随内容线性增长变为平坦**（jsdom：8KB→1.34ms、40KB→1.19ms、96KB→1.64ms/300 字符 tick；96KB 时比 v-html 全量降低约 100 倍），真实浏览器下远低于帧预算
- 附带收益：文本选区不再被每帧 innerHTML 全量替换破坏

### 阶段 4 补丁 — v-memo 每消息化（2026-08-07，新消息瞬间卡顿根因）

- **现象**：用户反馈"新消息出现 / 流式输出瞬间卡顿"
- **根因**：ChatThread 的 `v-memo` 缓存键含 `processExpandedIds`（Set **引用**）。新消息到达时该 Set 内容变化 → 新建 Set → 引用变 → **所有历史消息的 v-memo 缓存同时失效 → 整线重渲一次**
- **修复**：v-memo 键改为**每消息布尔** `processExpandedIds.has(msg.id)` / `typingMessageIds.has(msg.id)`——新消息只挂载自身，历史消息 hits cache 不重渲；只有展开状态真正变化的那条消息才重渲
- 新增测试"新消息到达时不重渲历史消息"（`chat-thread-messageview-isolation.test.ts` 4/4）

### 阶段 4 补丁二 — part 级 v-memo 隔离（2026-08-07，直击 runtime-core 自我时间）

- **背景**：WebView2 Performance 实测大会话流式卡顿的主成本是 `runtime-core.esm-bundler.js` 自我时间（171ms / 总 262ms）——数千个 tool 卡在 live 消息内，每个 delta 都会重新 patch 该消息的**全部 parts**（外层消息级 v-memo 因 `msg` 引用变化而失效，导致整条消息重渲）
- **修复**：`MessageView.vue` 内部 5 处 part 循环（行 90/296/428/882/958，`[group.part]` 与 `group.parts`）从 `<template v-for>` 改为**元素级 `<div v-for :key>` + `v-memo="partMemo(part, live)"` + `.part-wrap { display:contents }`**（模板约束：v-memo 必须元素级 v-for 且带 key）
- **`partMemo` 依赖**（`MessageView.vue:1544`）：`part` 引用（#3 投影保证未变化 parts 引用稳定）+ `isPartExpanded`（autoExpandedPartIds）+ `toolExpandedIds` / `toolWrapIds` / `subLineProcessCollapsedIds` / `decisionGuideDrafts[part.id]`——全部状态键齐全；group 展开走外层 `v-if`（`isGroupExpanded`），不受 v-memo 影响
- **live 参数按分支语义**：timeline/live 块 `true`，history 块 `false`（`togglePartExpand(part, false)` 对应块）
- 验证：typecheck / `vue-tsc -b` / `npm run build` 全绿；isolation/rollback/scroll/store 全绿（chat-thread-process 18 红为既有基线）；新增基准测试 `tests/messageview-update-bench.test.ts`（300-part live 消息每 tick 仅变 text part、复用 tool part 引用——模拟真实流式）：**2.0ms → 1.8ms/tick（jsdom）**；WebView2 下收益主要在跳过 300+ tool 卡的 runtime-core patch 自我时间
- 改法提醒：5 处循环改完必须用 div 配对/typecheck 双重验证闭合（本次 428/882/958 的闭合 `</template>` 曾漏改导致 1255+ 报 `Property 'group' does not exist` 作用域错乱）

## 相关文件索引（更新）

| # | 改动 | 工作量 | 风险 | 收益 |
|---|------|--------|------|------|
| 2 | ~~抽 `MessageView` 子组件~~ 已完成 | 已完成 | 已完成 | 最高（历史消息不再每帧重算） |
| 3 | ~~投影增量更新~~ 已完成 | 已完成 | 已完成 | 高 |
| 4 | ~~Markdown 流式瘦身~~ 已完成（跳 sanitize + escapeHtml 单 pass）；**增量分段渲染已完成**（P7 每帧成本 O(tail)） | 已完成 | 已完成 | 最高（长流式从线性卡顿到平坦） |

## 相关文件索引

- 前端事件入口与批处理：`core/ui/src/appServer/store.ts`
- 消息投影：`core/ui/src/appServer/workbenchProjection.ts`、`selectors.ts`、`messageParts.ts`
- 聊天渲染：`core/ui/src/components/ChatThread.vue`、`MarkdownRenderer.vue`
- 滚动跟随：`core/ui/src/composables/useCoreAutoFollowScroll.ts`、`core/ui/src/directives/autoFollowScroll.ts`
- 主界面接线：`core/ui/src/demo/App.vue`
- 后端 delta 发射：`core/src/lamtools_core/kernel/loop.py`（`_stream_model`，`_STREAM_TEXT_PROGRESS_CHARS=128` 仅限 content 全量）、`core/src/lamtools_core/event/runtime_projection.py:276`（reply_delta 逐 chunk 投影）
- 后端事件持久化/发布：`core/src/lamtools_core/app/default_agent.py:362`（live_callback）、`app/live_hub.py`、`app/live_router.py`

## 发送/进会话延迟优化包（已完成 2026-08-07）

> 症状：发一条指令迟迟发不出去（卡住）；进入已有大会话需 5-6 秒。
> 根因（实测证据）：线程 `2b34c636…` 膨胀到 53MB snapshot / 18530 事件 / 2802 items；
> `data/core.db` 6.08GB、checkpoint blobs 24.1GB（其中 **7/16 + 7/22 两天的 42650 个文件占 99.5% 字节**，
> 系旧"全落盘"策略遗留——当前代码已是懒加载，checkpoint.py:523 注释确认）。

| # | 改动 | 文件 | 效果 |
|---|------|------|------|
| 2a | `append_batch` 增 `return_state`，turn/start 写锁内第二次 `persistence.load` 改为复用内存投影（+`reconcile_status` 保等价） | `app/persistence_host.py`、`app/live_operations.py:557-578` | 写锁内省掉一次 53MB 级 DB 读取+解析 |
| 2b | 前端 `request()` 加超时（默认 30s；resume/turn/start 60s），超时 reject 并清理 pending | `ui/src/appServer/client.ts`、`store.ts` | "卡死"变为可见错误，不再无限挂起 |
| 5a | 投影窗口化：`selectCoreWorkbenchMessagesWindow` 只构建最近 N=150 条消息（`tailWindow`），控制器维护窗口 + `loadMoreHistory()`，App.vue 顶部"加载更早消息"按钮（滚动锚定） | `ui/src/appServer/workbenchProjection.ts`、`useCoreWorkbenchProjectionController.ts`、`demo/App.vue` | 进大会话 DOM 渲染从全量（2802 items）降为窗口内；流式/缓存语义不变 |
| 4a | `backup_file` 跳过 >200MB 文件（`MAX_BACKUP_FILE_BYTES`）；每会话主链仅保留最近 6 节点自动剪枝（`MAX_CHECKPOINTS_PER_SESSION`，`_prune_mainline`），回滚后旧未来/被放弃分支被清理（"切回去发新消息后回不去"） | `checkpoint.py` | 防 911MB 级大文件版本再次堆积；时间线节点数与 blob 不再无限增长 |
| 数据 | 全清 checkpoint 体系（615 checkpoint / 214 manifest / 44104 blob / 6 restore）+ blob 目录 + `VACUUM` | 运维操作 | 释放磁盘 ~24.1GB + DB 6.08GB→490MB；**回滚功能整体失效**（manifest 累积引用机制下部分清会导致脏引用，故全清）；当前工作区文件不受影响 |

验证：后端 214 相关测试通过；前端 typecheck/build 通过、窗口/缓存/控制器/store 24+5 测试通过；
清理后 `core.db` integrity_check=ok，后端 serve 启动 health ok。

注意：**按"保留最近 N 个 checkpoint"的清理策略实测几乎无效**（最新 manifest 累积引用 97.6% 的 blob，孤儿 blob 为 0），
故不再考虑 checkpoint 剪枝类 GC；4a 大文件上限 + 懒加载已从源头防复发。

## 快照洪泛修复包（已完成 2026-08-07）

> 症状：大线程（`2b34c636…`，快照实测 **56.4MB**）上流式输出"一卡一卡"（间歇性、一阵一阵）；
> DevTools Profile 显示单个 ~257ms 长任务中 **239ms 微任务自我时间**（Vue flush 全量重渲）。
> 背景：此前的优化包（rAF 合并/投影缓存/v-memo/Markdown 增量）全部针对逐 chunk 的 `core/runItem` 增量路径——该路径已平滑；
> 本次卡顿的根因在**快照推送路径**，它绕过了所有前端优化。

### 根因链（实测证据）

1. 后端 `live_router.py` `_hub_reader`：**每个非 `core/runItem` 事件**（turn/accepted、queue/*、session/updated、turn/interrupted…）都
   `snapshot_store.load` 全量读 DB（56.4MB）+ 整包 WS 下发
2. outbound 队列（256 条）被 56MB 快照塞满 → `close(1013)` 踢连接 → 前端重连 → `thread/resume` → 又 56MB → 循环
3. RPC 响应后还重复发一条 `thread/snapshot` 通知（同一快照一操作发 2-3 份）
4. 前端收到快照 → `hydrate` 整体替换 state → 投影缓存（**对象引用为键**）全部失配 → 150 条窗口消息 + 数千 part 全量重建 →
   所有 v-memo 失效 → 一次 Vue flush 全量 DOM 重渲 = 录到的 239ms 微任务自我时间
5. 复现证据：run #2 的 215s 回合日志中 WS 反复 accepted→open→closed（3 次/回合中），回合结束 status=ok 后正常关窗

### 改动清单

| # | 改动 | 文件 | 效果 |
|---|------|------|------|
| B1 | `_hub_reader` 每事件快照 → **边界策略**：跳过名单加 `session/updated`；仅 `turn/interrupted`/`turn/steered`/`queue/*` 触发快照且**每连接节流 ≥1s**；其余事件只发事件通知 | `app/live_router.py` | 回合中不再有 56MB 快照洪泛；多窗口经 queue 事件节流同步 |
| B2 | `_send` outbound 满改为**丢弃消息**（warn 日志），不再 `close(1013)`；`CoreAppEventGap`→1013 保留（事件真丢必须重连） | `app/live_router.py` | 瞬时过载不再变成重连风暴 |
| B3 | 去除 RPC 响应后的重复 `thread/snapshot` 通知（响应已内嵌 `result.snapshot`） | `app/live_router.py` | 操作类快照流量减半 |
| F1 | `store.ts` hydrate 增加**跳过判定** `shouldHydrateSnapshot`：incoming 事件 id 全部已收（非响应式 `receivedEventIds` 集合）+ requests/queue/core.status/顶层 items 无变化 → 不替换 state（零重渲）；重连/错过事件/审批决议变化 → 照常 hydrate | `ui/src/appServer/store.ts` | turn 开始/结束、重连（无新事件时）零全量重渲；快照到达不再破投影缓存 |
| F2 | `applyCoreRunItemEvent` 把 tool_result payload 的 artifacts 合并进 core.artifacts（事件路径补齐） | `ui/src/appServer/store.ts` | 收紧快照后 artifact 卡片仍走事件流即时显示 |

### 验证

- 后端：`test_core_live_router.py` **19 passed**（15 原有 + 4 新增：session/updated 后无快照 / queue 边界事件快照+节流 / outbound 满丢弃不 close / RPC 响应后无重复快照通知；turn_start WS 测试改为断言响应内嵌快照）；live 全套（live/live_client/live_client_e2e/live_hub/live_approval/live_recovery/cli_live/http_agent_app/checkpoint_operations）**123 passed, 1 skipped**
- 前端：`core-app-server-store.test.ts` **11 passed**（7 原有 + 4 新增 hydrate 跳过判定；重连测试快照补 seen id 保持原意）；typecheck / `vue-tsc -b` / `npm run build` 全绿
- 既有失败（stash 对照确认非本包引入，与本包改动前完全一致）：`core-app-server-selectors` 2、`core-app-server-workbench-projection` 1（全套件 16 文件失败含 jsdom 串扰噪声，单跑为准）

### 动态体验 checklist（人工验收，待完成）

1. 大线程（2b34c636）流式中 tool/状态事件不再卡顿；turn 开始/结束不卡
2. WS 不再中途断开（回合中无 accepted→closed 循环）；无 "Core App Server socket failed"
3. 审批决议 / 队列操作后 UI 立即更新（这些仍走 RPC 响应快照 + 判定 hydrate）
4. 断网重连恢复后状态一致（resume 快照含未见过事件 → 照常 hydrate）
5. DevTools 录制：回合中无 200ms+ 长任务（边界快照场景下应只有轻量 flush）

### 遗留（后续独立项）

- `selectChatMessages` 每 tick 全量扫描（2802 item 线程每 tick 5-20ms，5-7 趟 O(n) + 每 agentMessage JSON.parse 尝试）——非本次卡顿主因，快照频率降下来后影响已缩小
- 审批 RPC 响应仍内嵌全量快照（罕见路径，保留）
- `App.vue:2092` `watch(messages, {deep:true})` 每 tick 全窗口深遍历——快照减少后触发频率已大降，可后续改为非 deep

## WS 一次性客户端 churn 修复包（2026-08-08 追加）

> 背景：快照洪泛修复后，后端日志仍见回合中大量 `accepted→open→closed`（1005 断开码）循环。
> 加连接身份日志（`initialize client=...`）后发现：**app 同时有 5 个独立客户端**（settings×2 / frontend×1 / core_ui×2），
> 且 `durable/api.ts` 与 `workflow/api.ts` 的 `appServerOperation` **每次 RPC 都新建一条 WS**（connect→RPC→close）。
> goal 条 2s 节流刷新（`refreshGoal`→`listGoals`）在流式中每 2s 开一条连接——215s 回合实测 **47 条连接**。
> 1005 = 客户端 `close()` 无关闭码的正常表现（Chromium 空关闭帧），并非断连故障。

| # | 改动 | 文件 | 效果 |
|---|------|------|------|
| C1 | durable/workflow API 改**模块级持久客户端**（懒创建 + 复用；`onConnectionState` closed/error 时置空，下次调用重连；并发去重 `_appServerConnecting`） | `ui/src/durable/api.ts`、`ui/src/workflow/api.ts` | 回合中连接数 47 → 1；消除 WS 握手 churn |
| C2 | ArrangeManager 的 `appServerUrl(window.location.origin, …)` → `appServerUrl('', …)`（回落 `__LAMTOOLS_API_BASE__`） | `ui/src/components/CoreArrangeManager.vue` | 桌面版 arrange 从「走 vite 代理打已死 5172」改为直连后端（此前桌面版 arrange 功能整体失效 + 无限 proxy error） |
| C3 | 后端连接诊断日志：断开码（INFO，区分 1005 客户端正常关闭 / 1013 服务端踢人）、initialize 客户端身份（INFO）、移除 ending 噪音 | `app/live_router.py` | 本类问题可观测 |

验证：typecheck/build 全绿；`test_core_live_router.py` 19 passed；store/投影/控制器测试全绿；启动后连接数 5+churn → 4 稳定、0 断开。
剩余 proxy error 均来自残留浏览器标签页（无 `__LAMTOOLS_API_BASE__` 走 5173 代理打 5172），与桌面应用无关，关标签页即止。

## CDP 实测验证（2026-08-08，真实性能数据）

> 方法：独立 Edge + `--remote-debugging-port` + CDP Tracing（`devtools.timeline` 类目），
> 驱动真实回合（大线程 2b34c636，56MB 快照），60s trace 覆盖回合开始→流式→结束。
> 关键教训：Tracing 是全浏览器级——残留标签页的渲染进程会混入 trace（其 resume/重连的
> 56MB 解析呈现为 1000ms+ 假长任务），**必须按 client.ts 所在的渲染进程 pid 过滤**。

| 阶段 | 长任务（>50ms） | 说明 |
|------|----------------|------|
| 修复前（用户 Profile） | 单任务 257ms，微任务自我时间 91.9% | 快照洪泛 → hydrate → 全量重渲 |
| 快照洪泛 + churn 修复后 | 回合中段 **0**；边界残留 3 个（turn 开始 1070ms / 2×290ms） | 边界任务实为标签页进程混入 + turn 开始响应快照解析 |
| 全部修复后（含下述两项） | **0**（60s 完整回合，总任务时间 423ms） | 主线程全程在帧预算内 |

### 追加修复（2026-08-08）

| # | 改动 | 文件 | 效果 |
|---|------|------|------|
| D1 | `startTurn` 请求加 `include_snapshot: false`（turn/accepted + item/started 事件已覆盖 UI 状态；响应快照在 56MB 线程上是 ~1s 的 JSON.parse，且发生在 hydrate 跳过判定之前，跳过省不了 parse） | `ui/src/appServer/store.ts` | 回合开始不再解析 56MB |
| D2 | `nextCoreProcessExpandedIds` 只自动展开**含 running part** 的助手消息（此前回合开始把**所有**历史助手消息加入集合 → 全部消息 v-memo 布尔翻转 → 整线重渲 ~1s；回合结束清空集合 → 又一次整线重渲） | `ui/src/appServer/workbenchProjection.ts` | turn 开始/结束的重渲范围从 O(全窗口) 降到 O(当前回合消息)；历史消息保持紧凑组折叠（紧凑组摘要本就是为此设计）；审批卡由 FloatingApprovalCard 兜底 |

验证：typecheck/build 全绿；投影/控制器/store 测试全绿（唯一失败为既有基线 "nests real child run items"）；
CDP 实测 0 长任务（60s 完整回合）。


## 流式输出残留卡顿：消息风暴 → rAF 饿死（2026-08-08 第二阶段）

> 背景：上述修复后用户仍报告「流式输出不流畅」。CDP Tracing 全程解剖（94260–255441 事件/75s 回合），
> 每阶段用 CDP + 页面内 PerformanceObserver(longtask) + 8ms setTimeout 探针双重验证。

### 根因链（实测证据）

1. **后端无节流推送小 chunk**：模型快速输出时突发 **1770 条 WS 消息/0.76s（~2500 条/秒）**，
   75s 回合共 2622 条（118 条/秒均值）。每条消息 24 字节 payload，处理 <1ms，但 2000+ 条任务持续占满主线程。
2. **rAF 被饿死**：整个 trace 里 `FireAnimationFrame` 只触发 **2 次**（60fps 应 ~4500 次），
   页面 75s 仅 18 个 Layout 事件——**前端每帧合并（rAF coalesce）在消息风暴下完全失效**，
   渲染冻结 → 状态突变式跳动（用户感知的「不流畅」）。
3. **长任务 dur/tdur ≈ 7.5:1**：`Receive mojo message`/`TimerFire` 任务墙钟 200–850ms 但线程 CPU 仅 15%——
   主线程被节流/排队。**环境教训：Edge 窗口被遮挡（occluded）时 rAF 冻结、timer 节流到 1s**，
   会把测量污染成假长任务（`--disable-backgrounding-occluded-windows` 可解但会静默破坏 Tracing，
   最终用 OS 级 SetForegroundWindow 解决）。
4. **turn 结束后 14 秒的密集 60ms 任务**：part 自动折叠（1s timer）→ 折叠时整条消息重渲染
   （markdown 重解析 ~50ms）；beam 流光动画每帧写 style（rAF 无限循环）。

### 修复

| # | 改动 | 文件 | 效果 |
|---|------|------|------|
| E1 | **后端 runItem 发送合并缓冲**：同 (thread, item, kind) 的 delta 事件在 20ms 窗口内合并成一条 WS 消息（`_coalesced_event_ids` 记录全部事件 id，前端去重语义不变；非 delta 事件与边界事件先 flush 保证顺序；协议零改动） | `app/live_router.py` + 4 个新测试 | **2622 → ~112 条消息（23x）**；rAF 2 → 19103 次 |
| E2 | 前端合并兜底：`defaultScheduleFrame` 加 **50ms setTimeout 兜底**（rAF 饿死/窗口遮挡时状态仍跟进，`fired` 标志防双跑） | `ui/src/appServer/store.ts` | 双保险 |
| E3 | **beam 流光降频到 20fps**（每 3 帧写一次 style；5.6s 慢扫视觉等效，style 写入/layout 3x 削减） | `ui/src/components/MessageView.vue` | 每帧 style 写入成本 -66% |
| E4 | **MarkdownRenderer 渲染缓存**（按 content 缓存 parse+sanitize 结果 + mermaid blocks；LRU 100 条） | `ui/src/components/MarkdownRenderer.vue` | 折叠/展开重渲染不再重解析 markdown（60ms 长任务消失） |

### 验证（最终状态，75s 完整回合含流式）

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| WS 消息数 | 2622 | ~112 |
| 长任务（>50ms） | 21（峰值 852ms） | **2**（51ms + 281ms，均为流式首条合并消息的一次性成本） |
| 空闲基线长任务 | 0 | 0 |
| rAF / 75s | 2（饿死） | 19103（正常） |
| 主线程最大响应间隙 | 51.8s（冻结） | ~300ms（仅首条消息时刻） |

剩余 281ms 长任务 = 流式首条合并消息的 wall-clock（JSON.parse + 2802 条 items map 复制 + 首次投影+渲染 + 排队），
属每回合一次的启动成本，用户感知为回合开始 ~0.3s 轻微停顿，随后全程帧内流畅。

测试：后端 live 套件 117 passed；前端 typecheck 全绿；store/投影测试全绿（4 个失败为既有基线，
stash 验证与本改动无关）。

## 第三阶段：秒级一跳的真相 = 流式热路径上的快照投影（2026-08-08）

> 背景：WebView2 节流修复后新会话流畅，但 code map 长会话（63MB 快照）仍是「一次几十~上百字、~1.8s 一跳」。
> 采用**假 API 代理（testapi_proxy.py）**劫持所有 provider（OC GO/OC free/讯飞 → 本地透明转发代理，记录每个 chunk
> 的到达时刻 + 字符数），三层日志对齐定位。

### 根因（实测证据，code map 线程）

| 环节 | 实测 | 判定 |
|------|------|------|
| 真 API | 850 chunk/9.6s，逐字符（中位 2 字符），831/850 间隔 <100ms | ✅ 平滑，无罪 |
| 请求体 | 2802 条历史 → 3 messages / 3851 字符（上下文压缩在工作） | ✅ 压缩有效（体积） |
| kernel 流式 | `[perf:emit] transient=False` 每次 **1.7-2.3s** | ❌ 每 128 字符写库事件 |
| 55MB 快照 apply_many | 实测 **621ms**（loads 146 + dumps 241 + UPDATE 234；SQLAlchemy async + savepoint 下 1.7-2.3s） | ❌ 主阻塞 |
| WS 发送 | 34 条/59.6s，间隔中位 **1772ms**，合并消息 chars=128（与 `_STREAM_TEXT_PROGRESS_CHARS=128` 吻合） | 体感 1.8s/跳 |

**机制**：kernel 每 `_STREAM_TEXT_PROGRESS_CHARS=128` 字符发射一次**非 transient** content 事件
→ `_persist_core_event_live` → `append_batch` → `apply_many` 全量投影 55MB 快照 → **事件循环阻塞 1.7-2.3s**
→ 流式暂停 → 合并缓冲积压 67-77 条 delta → 写库完成后一次性 flush（128 字符/跳）。
新会话快照几 KB，apply 毫秒级，故不卡。fork 线程（34MB）明显比 code map（63MB）快——快照大小即阻塞时间。

### 修复（对齐 opencode：流式热路径纯事件，持久化移出热路径）

| # | 改动 | 文件 |
|---|------|------|
| F1 | 每 128 字符的 text/thinking **进度事件改 `transient=True`**（只 publish 实时渲染，不落库；最终态由 turn 结束 persist） | `kernel/loop.py` |
| F2 | `append_batch` 加 `project_snapshot=False`：**turn 期间所有事件只写事件表、不投影快照**（part start/end、status、usage 等低频事件此前每次仍写 1.3-2.3s） | `app/persistence_host.py` |
| F3 | `_persist_core_event_live`（turn 实时路径）传 `project_snapshot=False`；**快照投影统一在 turn 边界**（`_persist_run_items` 保持默认投影） | `app/default_agent.py` |
| F4 | 测量工具 `testapi_proxy.py`（透明转发代理 + chunk 节律日志）保留于 `core/`，可复用于后续对比 | — |

前端无感知：turn 期间靠 runItem 增量事件渲染（已有），快照只在边界推送（已有）；resume 时事件表含最终态。

### 验证（code map 63MB 线程，真 API）

| 指标 | 修复前 | 修复后 | 目标 |
|------|--------|--------|------|
| kernel 流式 | 34.55s（3.9x）→ 17.86s（1.91x） | **9.40s（1.07x）** | ≤ API × 1.2 ✅ |
| WS 发送间隔中位 | 1772ms | **~60-100ms** | ≤ 150ms ✅ |
| 回合总时长 | 59.49s | **27.65s** | — |

方法论沉淀：**假 API 代理劫持 + 三层日志对齐（真 API chunk 节律 ↔ kernel 消费 ↔ WS 发送）**可复用于任何
「流式卡顿在 API 还是自己」的争议；分段计时（emit/persist/publish/chunk-gap）逐层排除。
