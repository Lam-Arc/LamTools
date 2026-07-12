# Core Agent Wiring Controller Review

审阅范围仅限本轮 Core-first 前端控制器、公共导出、Writer 接入及 `hub.py` 下沉。未审阅或评价既有脏工作树、产品专属项目/Git/review/AGENTS.md。

## 结论

存在 2 项阻塞问题和 1 项重要问题。公共 barrel/root export 可通过类型检查；`members/writer/backend/app/app_server/hub.py` 仅保留对 Core hub 类型的兼容别名及 Writer 实例，未发现仍在 Writer 内复制 hub 实现的通用重复。

## 阻塞问题

### P1 队列“引导”不是原子操作，竞争窗口会丢失或重复执行待发送内容

- 位置：`core/ui/src/composables/useCoreQueuedInputController.ts:81-89`；Writer 接入见 `members/writer/frontend/src/views/CoreWorkbenchView.vue:361-370`。
- 证据：控制器先发送 `turn/steer`，再单独发送 `queue/delete`。Writer 后端的 steer 路径只追加 `turn/steered`，不消费队列项（`members/writer/backend/app/app_server/operations.py:1702-1711`、`members/writer/backend/app/app_server/queue.py:123-168`）；删除是另一个独立事务（`members/writer/backend/app/app_server/operations.py:2101-2104`）。
- 行为影响：
  - 点击后到服务端处理间本轮结束时，steer 以正常 RPC 结果返回 `guidance_expired`，控制器仍无条件删除该队列项。引导未生效且用户的待发送内容被删除。
  - steer 已成功而 delete 请求失败时，原队列项保留，会在本轮结束后再被派发，造成重复执行。
- 修复建议：将“消费指定队列项并引导指定 turn”定义为一个 Core app-server 操作，入参包含 `queue_item_id`，在同一事务内校验 active turn、追加引导事件并消费队列项；返回明确的 `applied` 状态。控制器改为调用一个 `guideQueuedInput` 协议，不再串联两个 `Promise<void>`。`applied=false` 时必须保留队列项。

### P1 审批通道暂不可用时被错误降级为普通文本，等待中的审批不会被解决

- 位置：`core/ui/src/composables/useCoreApprovalController.ts:20-53`；Writer 接入见 `members/writer/frontend/src/views/CoreWorkbenchView.vue:234-242`。
- 证据：真实审批请求在 `canRespondApproval=false` 时不重连、不报可重试失败，而使用 `guidance` 调用 `submitText`。Writer 的普通提交在会话 `waiting` 时会进入队列，而不会响应审批（`members/writer/frontend/src/views/CoreWorkbenchView.vue:1069-1098`）。Core WebSocket 客户端在 socket 未打开时不能发送请求（`core/ui/src/appServer/client.ts:91-96`）。
- 行为影响：刷新、短暂断线或重连期间点击批准/拒绝，会把文本排队到正在等待审批的会话；审批保持未决，后续队列也无法派发。
- 修复建议：对带 `waitingRequest.request_id` 的决定，控制器必须通过注入的通道保证接口先恢复连接，再执行 `respondApproval`；恢复失败则返回可重试的 `failed`/`deferred`，绝不可调用普通 `submitText`。只有不是审批请求的决定才允许现有文本降级。

## 重要问题

### P2 队列操作没有执行中状态，双击可并发提交两条引导

- 位置：`core/ui/src/composables/useCoreQueuedInputController.ts:74-93`；`core/ui/src/components/CoreQueuedInputTray.vue:53-62`。
- 证据：控制器没有按队列项跟踪处理中状态，托盘的“引导”按钮只依据 `canGuide` 和 `item.status` 禁用。两次快速点击会生成两个不同的 client message id 并各自调用 steer；后端只按 client message id 去重（`members/writer/backend/app/app_server/queue.py:131-168`）。
- 行为影响：同一条待发送内容可被注入正在运行的 turn 两次；与上项的独立删除请求叠加时，结果不可预测。
- 修复建议：上述原子 `guideQueuedInput` 操作以 `queue_item_id` 做服务端幂等键；前端同时公开 `submittingQueueItemIds`，在请求期间禁用该项的编辑、引导和删除按钮。

## 测试缺口

- `core/ui/tests/core-queued-input-controller.test.ts` 只验证成功时的调用顺序。需覆盖：steer 返回“未应用/turn 已结束”时保留队列项；消费失败或网络中断时不产生重复派发；同一 item 的并发引导只有一个服务端操作。
- `core/ui/tests/core-approval-controller.test.ts` 的降级用例使用不存在的 part，未覆盖含 `waitingRequest.request_id` 的真实审批在断线/重连期的行为。需断言它不会调用 `submitText`，重连后会提交 `approval/respond`，重连失败可重试。
- 需增加 Writer 接入级测试，模拟 `waiting` 会话的审批点击与 `turn/steer` 的 active-turn-mismatch，以验证 UI 不会排队错误文本或删除仍应保留的队列项。

## 已执行验证

- `core/ui`: `npm run test:contract`，14 个文件、93 项通过。
- `core/ui`: `npm run typecheck` 通过。
- `members/writer/frontend`: `npm run lint` 通过。
- Writer 后端队列与 app-server 协议测试：100 项通过，含 1 个既有 Windows asyncio transport 警告；现有覆盖未触及上述跨请求竞态。
