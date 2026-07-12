# Core Agent Workbench 前端职责审计

日期：2026-07-10

审计身份：LamTools 架构审计子 agent，只读分析；未修改产品代码。本文是指定报告产物。

## 产品经理整理

真实目标：核实 `members/writer/frontend/src/views/CoreWorkbenchView.vue` 及其直接引用的 Writer appServer 模块里，哪些职责仍由 Writer 页面或 Writer 适配层承担，但按 Core-first 规则应属于通用 Agent Workbench 的基础交互、状态或投影。

验收标准：

- 每项给出精确文件/行号。
- 标明 Core 是否已有同款能力。
- 给出最小下沉方式、迁移风险、优先级。
- 明确排除 Writer 项目/会话业务、AGENTS.md、右栏 Git/review/checkpoint、Writer 专属渲染。

当前工作树状态提示：本审计基于当前未提交工作树。`core/ui/src/appServer/*`、`core/ui/src/composer/*`、`core/ui/src/composables/*` 等 Core UI 基础能力已经存在，Writer 前端也已经在大量调用这些能力；因此结论不是“Writer 完全自研”，而是“Writer 页面仍承担通用组合控制器职责”。

## 范围与排除

纳入：

- `members/writer/frontend/src/views/CoreWorkbenchView.vue`
- 该 view 直接引用的 Writer appServer 模块：
  - `members/writer/frontend/src/appServer/client.ts`
  - `members/writer/frontend/src/appServer/protocol.ts`
  - `members/writer/frontend/src/appServer/selectors.ts`
  - `members/writer/frontend/src/appServer/snapshot.ts`
  - `members/writer/frontend/src/appServer/store.ts`

排除：

- Writer 项目/会话业务：项目分组、项目创建/删除、会话标题、工作目录、路由 query 同步等。
- AGENTS.md 编辑。
- 右栏 Git / review / checkpoint / branch / commit review。
- Writer 专属渲染：`MarkdownRenderer`、assistant label、Writer 文案、Writer 业务空态。
- 后端 appServer 协议实现，本报告只从前端使用面判断。

## 总结判断

Writer appServer 前端模块基本已经是 Core 的薄适配：

- `members/writer/frontend/src/appServer/client.ts:1-24` 只包装 Writer token 路径和 WebSocket 路径，实际 client 来自 Core。
- `members/writer/frontend/src/appServer/protocol.ts:1-36` 复用 Core 协议类型，仅保留 Writer 协议版本常量。
- `members/writer/frontend/src/appServer/selectors.ts:1-7`、`members/writer/frontend/src/appServer/snapshot.ts:1` 直接 re-export Core selector/snapshot。
- `members/writer/frontend/src/appServer/store.ts:11-27` 用 Core runtime controller 创建 Writer store；`members/writer/frontend/src/appServer/store.ts:46-104` 的 connect、turn、queue、command、steer、interrupt、approval 都是转调。

主要剩余问题在 `CoreWorkbenchView.vue`：它仍是事实上的完整 Agent Workbench 应用层，负责连接确保、send/stop/queue/command/approval、消息投影刷新、队列编辑、滚动跟随、模型/思考状态、运行过程展开等通用控制器职责。Core 已有底层 helper、组件和 action，但缺一个稳定的组合接口让 Writer 只提供 member overlay。

## Core 已有同款能力底座

- 连接、重连、resume、turn/queue/command/approval 操作：`core/ui/src/appServer/store.ts:11-24`、`core/ui/src/appServer/store.ts:70-100`、`core/ui/src/appServer/store.ts:119-136`、`core/ui/src/appServer/store.ts:157-258`。
- Workbench 投影：`core/ui/src/appServer/selectors.ts:46-116`、`core/ui/src/appServer/workbenchProjection.ts:23-55`、`core/ui/src/appServer/workbenchProjection.ts:99-168`。
- Composer action：`core/ui/src/appServer/workbenchActions.ts:49-90`、`core/ui/src/appServer/workbenchActions.ts:92-178`。
- 队列 UI：`core/ui/src/components/CoreQueuedInputTray.vue:1-23`、`core/ui/src/components/CoreQueuedInputTray.vue:30-82`。
- 模型/思考控制：`core/ui/src/components/CoreExecutionControls.vue:1-43`、`core/ui/src/composer/execution.ts:1-57`、`core/ui/src/composer/execution.ts:128-210`。
- Slash command 解析与 input item 合成：`core/ui/src/composer/inputItems.ts:9-50`、`core/ui/src/composables/useComposerCommandPalette.ts:11-53`。
- 自动跟随滚动：`core/ui/src/composables/useCoreAutoFollowScroll.ts:19-25`、`core/ui/src/composables/useCoreAutoFollowScroll.ts:35-77`。
- Core UI 对外导出：`core/ui/src/index.ts:95-157`、`core/ui/src/index.ts:159-192`。

## 下沉候选清单

| 优先级 | 职责 | Writer 证据 | Core 是否已有同款能力 | 最小下沉方式 | 迁移风险 |
|---|---|---|---|---|---|
| P0 | Live Workbench 连接与运行控制组合层 | `CoreWorkbenchView.vue:224-225` 判断当前 appServer 是否对应活动 session；`CoreWorkbenchView.vue:304-310` 计算活动状态；`CoreWorkbenchView.vue:704-711` stop 前自行连接并 interrupt；`CoreWorkbenchView.vue:1136-1142` start turn 前自行连接并附加 workRoot/thinking；`CoreWorkbenchView.vue:1725-1729` 通用 ensure connected；`CoreWorkbenchView.vue:2061-2085` session 切换时断开、重连、加载 command | 部分已有。Core 有 runtime state/controller、resume、start/interrupt，但缺“绑定 active thread 的 Workbench controller” | 在 Core UI 增加 `useCoreLiveWorkbenchController`：输入 runtime adapter、activeThreadId、apiBase、workRoot provider、turn options provider；输出 `activeStatus`、`ensureConnected`、`startTurn`、`stopTurn`、`connectActiveThread`、`disconnect`。Writer 只传路径、workRoot、thinking payload、错误文案 | 中。涉及连接生命周期、session 切换、重连和命令加载时序；需用 Core UI contract + Writer frontend store test 覆盖 |
| P0 | Queued input controller | `CoreWorkbenchView.vue:206` 本地转换 queued inputs；`CoreWorkbenchView.vue:327-329` 自行判断能否 guide；`CoreWorkbenchView.vue:437-455` 把 Core queue 映射回 WriterQueuedInput；`CoreWorkbenchView.vue:1664-1723` 自行实现删除、编辑、保存、guide 到活跃 turn；`CoreWorkbenchView.vue:2388-2398` Core tray 事件仍回到 Writer handler | 已有大部分。Core 有 queue projection、tray UI、queue update/delete、steerTurn、selectLatestActiveTurnId | 在 Core UI 增加 `useCoreQueuedInputController`：直接消费 `CoreQueuedInput[]`，管理 `editingId/draft/canGuide`，封装 edit/save/delete/guide。Writer 不再映射到 `WriterQueuedInput`，只传 store adapter | 低到中。主要风险是 guide 时先保存再 steer/delete 的顺序和失败回滚 |
| P1 | Composer 提交状态机 | `CoreWorkbenchView.vue:911-918` 空输入 stop / 普通 submit；`CoreWorkbenchView.vue:1035-1098` 校验、运行中入队、命令执行、start turn、提交后清空/恢复/清附件；`CoreWorkbenchView.vue:1069-1085` 已调用 Core action 但前后状态仍在 Writer 编排 | 部分已有。Core 有 `submitCoreComposerTask` 与 `coreComposerSubmissionEffects`，但缺一层统一连接、错误、附件策略、执行后 effect 的 composable | 在 Core UI 增加 `useCoreComposerSubmitController`：封装 send/stop、queue/start/command 分流、effect 应用、错误状态；Writer 只提供附件限制、ensure session、workRoot、具体 command side effect | 中。附件策略和自动建 session 属 Writer overlay，不能一并下沉成 Core 业务 |
| P1 | Command catalog 与 command palette 操作编排 | `CoreWorkbenchView.vue:280-294` 拉取 command catalog 并规范化；`CoreWorkbenchView.vue:920-975` 插入 token、执行 action command、失败后 dismiss；`CoreWorkbenchView.vue:978-1020` keyboard handling；`CoreWorkbenchView.vue:2410-2427` palette 与 syntax overlay 装配 | 部分已有。Core 有 `useComposerCommandPalette`、`buildCoreComposerHighlightSegments`、`buildCoreComposerInputItems`、`normalizeCoreCommandCatalogItem`、`executeCommand` | 在 Core UI 增加 `useCoreCommandComposerController` 或并入 composer controller：负责 catalog load、active slash replace、keyboard move/select/dismiss、standalone command 执行。Writer 只处理 `fork` 这类 member command result | 中。`fork` command 会创建/选择 Writer session，必须保留产品回调 |
| P1 | Approval respond workflow | `CoreWorkbenchView.vue:219` 维护提交中的 approval request ids；`CoreWorkbenchView.vue:426-433` 投影消息时注入提交态；`CoreWorkbenchView.vue:1100-1126` 解析 decision、乐观提交态、失败回滚、fallback 文本提交；`CoreWorkbenchView.vue:1128-1134` 在消息里查 part | 部分已有。Core 有 `coreDecisionSelectionPlan`、`respondApproval`、`selectCoreWorkbenchMessages` 的 submitting ids 参数，但缺完整 workflow 状态机 | 在 Core UI 增加 `useCoreApprovalController`：输入 messages、activeThreadId、respondApproval、submitText；输出 `submittingRequestIds` 和 `handleDecisionSelect`。Writer 只传 submitText adapter | 中。要保证 waitingRequest 失败回滚和 fallback 文本路径不变 |
| P1 | 消息投影、过程展开与状态同步的组合时机 | `CoreWorkbenchView.vue:385-408` 维护 processExpandedIds 并自动展开活动过程；`CoreWorkbenchView.vue:426-435` 组合 system messages + Core projection；`CoreWorkbenchView.vue:462-473` 监听 snapshot/status 重建消息、同步状态、展开过程；`CoreWorkbenchView.vue:2061-2063` session 切换清空过程展开；`CoreWorkbenchView.vue:2147-2164` 结束后自动折叠并触发业务 refresh | 部分已有。Core 有 `selectCoreWorkbenchMessages`、`nextCoreProcessExpandedIds`、`normalizeCoreSessionStatus`，但 watch 时机仍在 Writer | 在 Core UI 增加 `useCoreWorkbenchProjectionController`：消费 snapshot/status/submitting ids，输出 messages/processExpandedIds/toggle/sync hooks；暴露 `onTurnFinished` 回调给 Writer 刷新右栏 | 低到中。主要风险是运行结束折叠时机和 Writer 右栏 refresh 触发 |
| P2 | 自动跟随滚动与 ResizeObserver 装配 | `CoreWorkbenchView.vue:217-220` 建立 scroll controller；`CoreWorkbenchView.vue:475-529` 自行 ResizeObserver、消息变化滚底、用户消息平滑滚底、unmount 清理；`CoreWorkbenchView.vue:2341-2345` shell 主区域绑定 scroll/wheel | 部分已有。Core 有 auto-follow scroll composable，但 ResizeObserver 和 watch 装配仍在 Writer | 扩展 `useCoreAutoFollowScroll` 或新增 `useCoreThreadAutoFollow`：封装 observer、message source、latest user id、mount/unmount；Writer 只传滚动容器 ref | 低。主要是滚动体验回归，需用现有 Core scroll contract 加浏览器截图/交互验证 |
| P2 | 模型、thinking、shallow 的状态与持久化控制 | `CoreWorkbenchView.vue:81-186` 选择默认模型、provider、thinking options、本地 storage、payload；`CoreWorkbenchView.vue:133-153` 选择模型后写 `lamwriter.modelRouting`；`CoreWorkbenchView.vue:2441-2452` Core 控件事件仍回到 Writer | 部分已有。Core 有控件、选项、payload、storage helper；Writer 的 `lamwriter.modelRouting` 属产品 overlay | 在 Core UI 增加 `useCoreExecutionControlsController`：管理选中值、storage、option normalization、payload；提供 `onModelSelected` adapter。Writer adapter 只写 `lamwriter.modelRouting` 并刷新 config | 中。不能把 Writer 默认路由策略误下沉；只下沉控制状态和 payload 生成 |
| P2 | Writer appServer Pinia store 的浅包装 | `members/writer/frontend/src/appServer/store.ts:29-105` 基本逐项包装 Core runtime controller action；`client.ts:1-24`、`selectors.ts:1-7`、`snapshot.ts:1`、`protocol.ts:1-36` 已经是薄适配 | 已有。Core runtime controller 已覆盖这些 action；缺的是 Pinia store factory 或成员 adapter 工厂 | 可在 Core UI 提供 `createCoreAppServerPiniaStore` 或普通 factory，让 Writer 只提供 token path、ws path、clientInfo、protocol alias | 低。收益主要是删除浅代码；风险是 TypeScript 泛型和 Pinia this 绑定 |

## 不应下沉或暂不纳入的 Writer 职责

- 项目/会话业务：`CoreWorkbenchView.vue:535-704`、`CoreWorkbenchView.vue:718-832`、`CoreWorkbenchView.vue:1160-1224`、`CoreWorkbenchView.vue:2049-2114`。这些涉及 Writer project、session store、work_root、路由、删除策略，属于 member overlay。
- 附件后端操作：`CoreWorkbenchView.vue:838-899`。Core 已有 pending attachment 状态和 input item，但 Writer 的上传、预览、打开 API 是产品能力；只建议把 composer 侧附件校验接口化。
- 右栏资源/Git/review/checkpoint/branch/commit review：`CoreWorkbenchView.vue:1246-2047`、`CoreWorkbenchView.vue:2468-2555`。按本次要求排除。
- Writer 专属渲染：`CoreWorkbenchView.vue:2353-2374` 使用 `MarkdownRenderer` 和 Writer label，合理保留为 slot。
- AGENTS.md：`CoreWorkbenchView.vue:2558-2574`，按本次要求排除。

## 迁移顺序建议

1. 先做 P0 `useCoreQueuedInputController`。它边界最清楚，Core 已有 tray、projection、store 操作，能直接删除 Writer 的 `WriterQueuedInput` 映射和编辑/guide handler。
2. 再做 P0 `useCoreLiveWorkbenchController`。把 connect/ensure/start/stop/session-change 的通用状态机收口，避免后续 composer/command/approval 继续重复连接逻辑。
3. 合并 P1 composer + command。两者共享 textarea/cursor/slash/submit 状态，分开做容易留下新胶水。
4. 再做 P1 approval 与 process projection。它们依赖消息投影和提交态，适合在 live/composer 稳定后收口。
5. 最后处理 P2 scroll、execution controls、Pinia store factory。它们收益明确但不阻塞 Core-first 主线。

## 验证建议

本次未运行测试，避免把只读审计扩大成实现/验证任务。后续真正迁移时建议至少跑：

- `npm run test:contract` in `core/ui`
- `npm test --prefix members/writer/frontend -- appServer/store.test.ts`
- `npm run --prefix members/writer/frontend build`
- 若改动滚动或 ChatThread 装配，补浏览器交互验证：上滚停止跟随、回到底部恢复、用户发送平滑滚底、运行中过程展开/结束折叠。

## 未确定点

- Core UI 当前已有多个新模块处于未提交状态，本文按当前工作树判断；如果这些模块后续被改名或拆分，行号和“Core 已有同款能力”需要复核。
- 未审计 `ChatThread.vue` 内部是否还有可下沉的 Writer 专属显示逻辑；本报告只看 `CoreWorkbenchView.vue` 使用面。
- 未审计后端 appServer 是否已经完全 Core-first；这里只判断前端职责。
- 最终接口命名仅为建议，真正落地时应以现有 Core UI 导出风格为准，避免再造一层浅 adapter。
