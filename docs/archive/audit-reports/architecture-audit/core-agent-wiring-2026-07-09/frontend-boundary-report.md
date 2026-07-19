# Core Agent Workbench 前端接缝审计

日期：2026-07-09
范围：Core UI App Server/Workbench 基础能力与 Writer 前端装配层
边界：只读审计；本次未改功能代码。

## 结论

Core UI 已经具备多数基础 Agent App 能力的底座：App Server 连接/初始化、快照接收、断线重连、`turn/start`、`turn/interrupt`、队列增删改、命令目录/执行、审批回复、通用消息投影、队列投影、模型/思考/shallow 控件和基础 composer 能力都已在 `core/ui` 中存在。

但 Core UI 还没有形成一个“完整 Agent Workbench 应用层”接口。Writer 仍在 `CoreWorkbenchView.vue` 中承担大量通用 Workbench 编排：运行中提交转队列、空输入 stop、有输入 send、命令 palette 到执行、队列编辑/引导、审批回复提交态、附件与输入 item 合成、模型选择持久化、自动展开运行过程、滚动跟随、连接确保等。这些不全是 Writer 业务语义，至少一部分应继续下沉到 Core，Writer 只传项目、会话、文案、业务右栏、Writer 专属操作。

当前展示链路已经比历史状态更接近目标：Writer appServer 的 client/protocol/snapshot/selectors 基本只是 Core 的薄适配，实际投影主要走 Core。但展示组合链路仍有差异：Core demo 展示的是基础运行面，Writer 展示的是完整产品面；差异中项目/会话/AGENTS.md/diff/资源统计合理，通用 composer/queue/command/approval 编排不合理。

## 证据

### Core UI 已具备的基础能力

- 连接/初始化/事件接收：
  - `core/ui/src/appServer/client.ts:46-74` 负责 WebSocket 连接、`initialize`、`initialized`。
  - `core/ui/src/appServer/client.ts:119-149` 区分 JSON-RPC response、服务端 request、`thread/snapshot` 通知和普通 event。

- 连接状态、断线重连、resume：
  - `core/ui/src/appServer/store.ts:11-24` 定义通用运行状态。
  - `core/ui/src/appServer/store.ts:70-100` 打开连接并用 `last_seen_seq` resume。
  - `core/ui/src/appServer/store.ts:119-136` 提供指数退避重连。

- send/stop/queue/operation 基础调用：
  - `core/ui/src/appServer/store.ts:157-173` 发起 turn。
  - `core/ui/src/appServer/store.ts:175-203` 创建、更新、删除 queued input。
  - `core/ui/src/appServer/store.ts:205-224` 拉取和执行 command。
  - `core/ui/src/appServer/store.ts:226-258` 支持 steer、interrupt、approval respond。

- timeline/projection：
  - `core/ui/src/appServer/selectors.ts` 已把 core runtime snapshot 投影为 chat、queue、approval、status。
  - `core/ui/src/appServer/workbenchProjection.ts:23-55` 输出 Core Workbench 消息，包含 attachment part 和 shallow pending。
  - `core/ui/src/appServer/workbenchProjection.ts:99-112` 输出队列和最新活跃 turn。
  - `core/ui/src/appServer/messageParts.ts` 负责工具、reasoning、approval、compaction、status 等 part 类型映射。

- 基础 UI 控件：
  - `core/ui/src/components/WorkspaceShell.vue:91-110` 支持通用 send/stop action slot。
  - `core/ui/src/components/ComposerBar.vue:23-32` 独立 composer 也支持 send/stop。
  - `core/ui/src/components/CoreExecutionControls.vue:4-39` 提供模型、思考模式、shallow 入口。
  - `core/ui/src/components/CoreQueuedInputTray.vue:1-22` 提供队列编辑、保存、删除、引导事件。
  - `core/ui/src/components/RuntimePanel.vue:15-33` 提供事件与步骤展示。

- 模型/思考/shallow：
  - `core/ui/src/composer/execution.ts:1-33` 定义通用模式和 payload。
  - `core/ui/src/composer/execution.ts:136-162` 根据模型/供应商能力生成思考选项和请求字段。
  - `core/ui/src/index.ts:49-57`、`core/ui/src/index.ts:133-174` 已把相关组件、helper、App Server 能力导出。

- Core demo 已能跑基础 App Server 体验：
  - `core/ui/src/demo/App.vue:169-183` 直接装配 Core App Server client/controller。
  - `core/ui/src/demo/App.vue:237-256` 支持 send/stop、模型、思考、shallow payload。

### Writer 已经下沉或薄适配的部分

- `members/writer/frontend/src/appServer/client.ts` 只包装 token 路径和 WebSocket 路径，实际 client 来自 Core。
- `members/writer/frontend/src/appServer/protocol.ts` 复用 Core 协议类型，仅保留 Writer 协议版本常量。
- `members/writer/frontend/src/appServer/snapshot.ts`、`selectors.ts` 直接 re-export Core hydrate/selectors。
- `members/writer/frontend/src/appServer/store.ts:11-27` 用 Core runtime controller 创建 Writer store。
- `members/writer/frontend/src/appServer/store.ts:64-104` 的 turn、queue、command、steer、interrupt、approval action 都是转调 Core controller。
- `members/writer/frontend/src/views/CoreWorkbenchView.vue:459-480` 已用 Core 投影生成消息和队列，再映射为 Writer 队列类型。

## 缺口清单

1. Core 仍缺“完整 App Workbench 组合层”
   - Core 有协议、store、projection、控件，但没有一个统一 composable/view 把连接、消息、队列、命令、审批、send/stop 策略和执行控件组成稳定接口。
   - 结果是 Writer 必须在单个 view 中继续写通用编排。

2. Writer 仍承担通用 composer 行为
   - `members/writer/frontend/src/views/CoreWorkbenchView.vue:1130-1168` 负责校验附件、识别 standalone command、运行中转 queue、空闲时 start turn。
   - `members/writer/frontend/src/views/CoreWorkbenchView.vue:1224-1230` 负责连接后 start turn 和 thinking payload。
   - 这些更像 Agent App 通用策略，Writer 只应提供 work root、附件限制、默认文案等 overlay。

3. Writer 仍承担通用 command palette 到 operation 的编排
   - `members/writer/frontend/src/views/CoreWorkbenchView.vue:274-303` 规范化 command catalog。
   - `members/writer/frontend/src/views/CoreWorkbenchView.vue:1015-1054` 处理插入 token、执行 command、错误提示。
   - Core 已有 `useComposerCommandPalette`、syntax/input item helper 和 command operation，但缺少更高层 glue。

4. Writer 仍承担通用 queued input 交互
   - `members/writer/frontend/src/views/CoreWorkbenchView.vue:1752-1818` 负责删除、编辑、保存、作为 guidance 发送、确保连接。
   - Core 有队列托盘和 App Server queue/steer 能力，但组合逻辑还在 Writer。

5. Writer 仍承担通用 approval 提交状态
   - `members/writer/frontend/src/views/CoreWorkbenchView.vue:1178-1197` 处理 waiting request、提交态、失败回滚。
   - Core 投影已暴露 waitingRequest，但缺少通用 respond workflow。

6. 模型选择入口已在 Core，但“选择模型如何落到产品路由”仍混在 Writer view
   - `members/writer/frontend/src/views/CoreWorkbenchView.vue:90-179` 使用 Core helper 生成模型/思考 payload。
   - `members/writer/frontend/src/views/CoreWorkbenchView.vue:126-147` 把选择写入 `lamwriter.modelRouting`，这是 Writer overlay 合理，但最好由 Core 暴露选择事件/状态，Writer 只实现保存 adapter。

7. Core demo 没覆盖完整基础 Agent App
   - `core/ui/src/demo/App.vue` 展示连接、send/stop、模型/思考和 runtime panel，但没有装配 queued input tray、command palette、approval respond、附件输入等完整基础链路。

## Writer 中合理保留的 member overlay

- 项目/会话分组、项目创建、项目删除、项目目录选择：
  - `members/writer/frontend/src/views/CoreWorkbenchView.vue:613-683`
  - `members/writer/frontend/src/views/CoreWorkbenchView.vue:2333-2405`

- Writer 文案、标题、空态、会话标题编辑：
  - `members/writer/frontend/src/views/CoreWorkbenchView.vue:2407-2427`
  - `members/writer/frontend/src/views/CoreWorkbenchView.vue:2437-2440`

- Writer 渲染特化：Markdown 内容、assistant label：
  - `members/writer/frontend/src/views/CoreWorkbenchView.vue:2443-2464`

- Writer 业务右栏：资源统计、diff 文件、checkpoint、agent branch、commit review 等：
  - `members/writer/frontend/src/views/CoreWorkbenchView.vue:2558-2645`
  - 相关数据读取来自 `members/writer/frontend/src/api/index.ts` 的 session/project/change/checkpoint/branch/review operations。

- AGENTS.md 编辑：
  - `members/writer/frontend/src/views/CoreWorkbenchView.vue:2648-2660`

- Writer 配置与路由保存：
  - `members/writer/frontend/src/views/CoreWorkbenchView.vue:126-147`
  - 这属于产品默认模型策略，不应强行变成 Core 业务。

- Writer 附件能力中的产品限制：
  - 附件 UI 可通用，但“当前模型是否允许图片”“运行中是否允许带附件队列”等策略可以由 Core 提供默认，Writer 保留产品级限制或能力 adapter。

## 展示链路差异判断

- 合理差异：
  - Writer 有项目/会话/工作目录/AGENTS.md/diff/资源统计/Markdown 渲染，这些是 member overlay。
  - Writer 使用 token 化 `/api/app-server`，Core demo 使用 `/api/core/app-server`，属于宿主路径差异。
  - Writer 的模型选择会写入 `lamwriter.modelRouting`，这是产品配置策略。

- 不合理或应继续下沉的差异：
  - Core demo 没展示 queue/approval/command palette 完整链路，导致 Writer 是事实上的完整 Workbench 样板。
  - Writer view 自己判断运行中输入进入 queue、空输入触发 stop、standalone command 触发 operation。这些是通用 Agent App 交互。
  - Writer view 自己维护 queued input 编辑/guide 操作，Core 只有托盘事件和底层 operation。
  - Writer view 自己维护 approval submitting 状态，Core 只提供投影和 respond operation。
  - Writer view 自己做滚动跟随、运行过程自动展开，这些对 Artist/未来成员也会重复。

## 建议动作

1. 在 Core UI 增加一个通用 Agent Workbench 组合层。
   - 输入：App Server adapter、session id、work root、模型/供应商源、附件源、command catalog、产品文案。
   - 输出：messages、queuedInputs、composer state、connection state、send/stop/queue/guide/approval/command handlers。
   - Writer 只提供项目/会话/配置/右栏/Markdown slot。

2. 把 Writer 中通用 composer 提交流程下沉。
   - 下沉：standalone command 识别、运行中 queue、空输入 stop、input item 合成、连接确保、错误状态。
   - 保留：附件能力限制、Writer 文案、work root、模型路由保存。

3. 把 queued input controller 下沉。
   - Core 已有 `CoreQueuedInputTray` 和 queue/steer/delete/update operation，应补一个通用控制器承接编辑、保存、删除、guide。

4. 把 approval workflow 下沉。
   - Core 投影已输出 waitingRequest；应补通用提交态、decision 归一化、失败回滚。

5. 让 Core demo 或 contract fixture 覆盖完整基础 Workbench。
   - 不一定要变成产品页面，但要证明 Core 自己能跑：连接、send、stop、queue、guide、command、approval、模型/思考/shallow、runtime panel。

6. 保持 Writer appServer 薄适配，不再新增 Writer-local 协议/投影逻辑。
   - 现在 `members/writer/frontend/src/appServer/*` 的方向正确；后续新增行为优先加到 Core，再由 Writer adapter 配置路径/token/文案。

## UI/协议测试缺口

- Core 缺少 App Server client 的单测覆盖：initialize、服务端 request 回复、`thread/snapshot` 路由目前 Writer client 有类似测试，但 Core client 自身应直接覆盖。
- Core 缺少完整 composer workflow 测试：空输入 stop、有输入 start、运行中 queue、附件 input items、standalone command、approval respond。
- Core 缺少 queued input controller 测试：编辑、保存、删除、guide 到活跃 turn。
- Core 缺少组合层或 demo contract 测试：Core UI 自身完成完整 Agent App 基础链路，而不是依赖 Writer view 证明。
- Writer 缺少“只做 overlay”的回归测试：应验证 Writer view 使用 Core 投影/控件/组合层，不再复制通用 workflow。
- Writer 现有 appServer tests 仍有价值：
  - `members/writer/frontend/tests/appServer/store.test.ts` 覆盖 snapshot authority、structured input、shallow payload、command、queue、reconnect。
  - `members/writer/frontend/tests/appServer/selectors.test.ts` 覆盖 canonical core projection、tool/reasoning/compaction/status/artifacts 等。
  - `members/writer/frontend/tests/appServer/client.test.ts` 覆盖 JSON-RPC pending、server request response、snapshot notification。
- Core 现有 tests 也有基础覆盖：
  - `core/ui/tests/core-app-server-store.test.ts` 覆盖 snapshot authority、structured input/command、reconnect resume。
  - `core/ui/tests/core-app-server-workbench-projection.test.ts` 覆盖 workbench message、attachment、queue、active turn projection。
  - `core/ui/tests/core-composer-execution.test.ts` 覆盖模型选项、思考能力、thinking payload。
  - `core/ui/tests/core-queued-input-tray.test.ts` 覆盖队列托盘组件。

## 没把握的点

- 未启动前端或 App Server 做浏览器级验证；本报告基于源码与现有测试审计。
- 未审计后端 App Server 协议实现，只从前端 client/store/protocol 使用面判断。
- 未审计 `ChatThread.vue` 全量细节，只基于 Core 投影和 Writer 使用方式判断展示接缝。
- 未判断具体下沉后的最终接口形状；这里只确认哪些行为更像 Core 基础能力、哪些保留在 Writer 更合理。
- 未运行测试，避免把审计任务扩大成验证/修复任务。建议后续变更前运行 Core UI 与 Writer frontend 的相关测试矩阵。
