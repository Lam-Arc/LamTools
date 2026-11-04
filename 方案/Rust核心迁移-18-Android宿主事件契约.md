# Rust 核心迁移 18：Android 宿主事件契约

日期：2026-11-04
分支：`sunday/m16-projection`（worktree `.worktrees/m16`）

## 为什么先写这份文件

前 17 轮的工作方式是「改 Rust → 构建 APK（十几分钟）→ 装模拟器 → 点界面 → 看截图 → 猜哪里不对」。
这套流程把模拟器当成了测试预言机：业务逻辑对不对，要靠人眼看一张 1080×2400 的截图判断。
结果是每一步都要付构建代价，而且判断依赖我读图的能力，不是依赖一个可重跑的判据。

这一轮改成契约驱动：

1. 先把「现有 Sunday 已经约定的行为」从**已经在跑的代码**里逐条读出来，写成契约。
2. 契约里有争议的每一条，都在下文标注它取自哪个文件的哪一段，不靠印象。
3. 契约落成一份机器可读的样本（`core/android-host/contract/android-host.v1.json`），
   Rust 侧和界面侧**读同一个文件**：Rust 必须产出它，界面必须能渲染它。
4. 实现只对契约负责。模拟器只回答 Android 特有问题（WebView、IPC、权限、SAF、生命周期），
   不再承担「投影对不对」这种纯业务判断。

判据从「截图里看着像对」变成「两份断言都绿」，并且跑一次是秒级，不是十几分钟。

## 一、契约的两个锚点

投影层夹在两个已经存在的契约之间，它自己不该发明第三种方言。

**上游锚点：日志事件。** Rust 核心写进 `journal_events` 的事实，
经 `core/android-host/src-tauri/src/core_service.rs::translate` 变成 `turn/accepted`、
`item/tool_prepared`、`item/approval_request` 这类方法名。这是宿主的输入词汇。

**下游锚点：`core/runItem` 通知。** 共享界面只认这个：
`core/ui/src/appServer/store.ts:1132` 的 `applyCoreRunItemEvent` 读 `payload.kind` 分派，
`store.ts:1135` 起逐字段取 `item_id` / `turn_id` / `status` / `event_id` / `artifacts` / `usage`。
这是宿主的输出契约，**也是本文档唯一要保证的东西**。

下游锚点的字段语义取自桌面核：
`core/src/lamtools_core/event/run_item.py`（`RunItemEvent.to_dict` 定义哪些字段必出现、哪些空则省略）、
`core/src/lamtools_core/event/runtime_projection.py`（每种事实翻译成哪种 `kind`、`status`、`item_id`）、
`core/src/lamtools_core/app/event_store.py`（信封形状与 `seq=0` 的处理）。

## 二、信封契约

每条通知是一个 JSON 对象：

| 字段 | 必出现 | 规则 |
| --- | --- | --- |
| `method` | 是 | 恒为 `"core/runItem"` |
| `thread_id` | 是 | 来自日志事件的线程，不能被投影改写 |
| `event_id` | 是 | 稳定的、由日志位置派生的身份；同一事实重放必须得到同一个值 |
| `payload` | 是 | 见第三节，即 `RunItemEvent.to_dict()` 的结果 |
| `seq` | 条件 | 日志有真实序号时出现；`seq == 0`（无持久锚点的临时事件）必须**省略**，不能写 0。理由见 `event_store.py::AppEventEnvelope.to_dict`：客户端会把 0 当成真实排序锚点，把条目排到所有真实事件之前 |
| `created_at` | 是 | ISO-8601 UTC 字符串，**不得为空串**。空串会让 `store.ts:1614` 把空串当作合法时间写进回合，界面显示 Invalid Date |

### 已确认的偏离（本轮要改）

当前 `projection.rs:456` 起构造的信封里：

- `"created_at": ""` —— 违反上表。空串比缺字段更糟：`typeof '' === 'string'` 成立，界面会把它当时间收下。
- `payload.created_at_ms: 0` —— 1970 年，同样是「看起来有值其实是假值」。
- 信封不携带 `turn_id` / `item_id` / `parent_item_id`。界面目前回退到 `payload.payload` 里同名字段，
  所以没坏，但契约要求没有回退也成立。

## 三、`payload` 契约（`RunItemEvent.to_dict()`）

必出现：`kind`、`thread_id`、`event_id`、`status`、`payload`、`created_at_ms`。
空则省略：`run_id`、`turn_id`、`item_id`、`parent_item_id`、`seq`、`artifacts`、`usage`、`source`、`metadata`。

**`kind` 取值域**（12 个，`run_item.py:RunItemKind`）：
`message`、`thinking`、`tool_call`、`tool_result`、`approval_request`、`approval_response`、
`artifact`、`verification`、`handoff`、`usage`、`error`、`status`。

**`status` 取值域**（7 个，`run_item.py:RunItemStatus`）：
`queued`、`running`、`waiting`、`completed`、`failed`、`cancelled`、`skipped`。

领域外取值一律视为违约，不得靠界面兜底。

### 3.1 用户消息（`turn/accepted`）

- `kind = message`，`status = completed`
- `payload.type = "userMessage"`
- `payload.content` **必须是分片数组**：`[{"type":"text","text":<原话>}]`。
  契约出处 `selectors.ts:854` 注释：「userMessage content is an array of typed input parts」，
  且 `runtime_projection.py:464` 的 guidance 分支就是按这个形状写的。
  当前宿主发的是裸字符串（`projection.rs:196`），属于偏离：界面能容忍（`inputToText` 两种都收），
  但生产方不该依赖读方的宽容。
- `item_id`：有 `client_message_id` 时用 `{thread}:user:{client_message_id}`，否则 `{thread}:user:{seq}`。
  用客户端 id 是为了让重发/重连后同一句话仍是同一个条目，而不是第二句话。

### 3.2 助手文本（`turn/model_completed`）

- `kind = message`，`status = completed`，`payload.type = "agentMessage"`
- **空文本不产生事件**（`runtime_projection.py:271` 的同一条规则：没有文本就没有消息）
- `payload.content` 是字符串（与用户消息相反；`runtime_projection.py:653` 对 agentMessage 就是写 `content` 字符串）
- `item_id` 按轮次区分：`{thread}:{turn}:assistant:{round}`。两轮回复合并成一个条目会丢内容。

### 3.3 工具调用（`item/tool_prepared` → `item/tool_dispatched`）

- `kind = tool_call`，`payload.type = "dynamicToolCall"`
- `payload.tool_name` 必填；取不到时按 `runtime_projection.py:1014` 用 `invalid_tool_call`，
  不要留空串，空工具名在界面上会渲染成没有标题的一行
- `payload.arguments` 携带原始参数对象
- `status`：审批未过 → `waiting`；已派发执行 → `running`
- `item_id = {thread}:{turn}:{tool_call_id}:tool`，**一次工具调用从审批到执行到结果共用这一个 id**
  （`runtime_projection.py:1104`）。共用是必需的：审批卡批准后要更新用户正在看的那一行，
  换 id 就会在旁边多出一行。

### 3.4 工具结果（工具成功/失败）

- `kind = tool_result`，`payload.type = "dynamicToolCall"`
- 必带：`tool_name`、`delta`（结果摘要文本）、`tool_result`（完整结果正文）、`replace: true`、
  `status`（`completed` / `failed`）、`error`（字符串或 `null`）
- `replace: true` 的含义见 `runtime_projection.py:343`：终态文本替换累积的增量，而不是再追加一遍
- `item_id` 与 3.3 相同

### 3.5 审批请求（`item/approval_request`）

- `kind = approval_request`，`status = waiting`，`payload.type = "serverRequest"`
- 必带：`request_id`、`kind`（默认 `"approval"`）、`message`、`tool_name`、`options`
- `options` 至少两项，每项 `{id, label, description, response}`；
  内容与桌面核 `APPROVAL_OPTIONS` 逐字一致（`runtime_projection.py:20`），
  这样手机和桌面显示的按钮文字、回传的 response 不会各说一套
- `metadata.request_id` **与** `metadata.waitingRequest.request_id` 都要给：
  界面有两个读取点（`coreDecisionRequestId` 与 `coreDecisionSelectionPlan`），
  少一个就会「点得动但请求发不出去」，或者退化成把审批当普通消息发出去
- `item_id` 与 3.3 相同（审批卡挂在工具那一行上）

### 3.6 审批终结（`item/approval_resolved`）

- `kind = approval_response`（lifecycle 为 `appearing`/`processing` 时是 `interaction_update`）
- `payload.state` 与 `payload.lifecycle` 都是 `ending`；`payload.status = "resolved"`
- `payload.action` 是用户的选择；`payload.interaction_id` 是这次交互的身份
- **`turn_id` 必须显式为 `""`**：界面把 `approval_response` 当作「延续它指名的那个回合」，
  指向已结束的回合会让界面把回合重新置为运行中，发送按钮卡回 Stop。
  契约出处 `app/live/interactions.py`，实现见 `projection.rs:308` 的注释

### 3.7 文件产物（artifact）

产物的位置是**条目顶层** `payload.artifacts`，不是 `payload.payload.artifacts`。
`store.ts:1360` 明确写：「Tool results carry artifacts on the runItem event TOP level
（RunItemEvent serializes artifacts outside payload — see run_item.py to_dict）」。
当前宿主把产物塞进 `body`（`projection.rs:352`），只是靠 `store.ts:1370` 的兼容分支兜住，属于偏离。

每个产物必带：`artifact_id`、`thread_id`、`turn_id`、`item_id`、`kind`、`name`、`path`、`uri`、
`metadata.description`。`artifact_id` 必须可推导且稳定（`runtime_projection.py:1219`）：
同一份产物在实时流和恢复重放里必须是同一个 id，否则界面会显示两份。

## 四、不该发生的事

- 拿不到 `request_id` 的审批请求：不产出卡片，并且必须留下可诊断的日志，
  绝不能用空 id 产一张点不动的卡
- 未知的日志事件：不带渲染含义就不产出（`projection.rs` 的 `return None` 路径），
  这是 `EventKind` 追加式扩展的前提
- 静默降级：任何「字段缺失就用默认值凑一个看起来正常的对象」的处理都要在契约里写明，
  没写明的默认值就是在掩盖上游缺字段

## 五、判据

同一份 `core/android-host/contract/android-host.v1.json` 被两侧读取：

- `core/android-host/src-tauri/src/projection.rs` 的契约测试：喂入日志信封，逐条比对契约要求的字段；
- `core/ui/tests/android-host-event-contract.test.ts`：把同一份期望值喂进真实的
  `applyCoreAppEvent` + `selectCoreWorkbenchMessages`，断言用户这句话、助手这句话、
  审批卡的两个选项和请求身份、文件卡片都在结果里出现。

任一侧改坏契约，对应测试立刻红。模拟器不再参与这个判断。

## 六、写契约时定下的三轮裁决

这三条都不是「顺手改的」，是样本先红、再改实现。

**1. 工具参数必须叫 `arguments`。** 宿主原来发 `tool_args`。界面三处读取点
（`messageParts.ts:140`、`selectors.ts:570`、`workbenchProjection.ts:453`）都先看 `item.arguments`，
只有 `MessageView.vue:3818` 把它当兜底别名。也就是说参数在手机上是「有值但没人读」。
现在两个名字都发：`arguments` 是契约，`tool_args` 是兼容。

**2. 一次工具调用从头到尾只有一个行 id，且由 `item/tool_prepared` 定下来。**
原来每个事件用自己那一条的 `turn_id` 重新算 id。审批答复按契约必须带空的 `turn_id`（不让它复活回合），
于是就算出另一个 id：答复落在没人看的新行上，用户刚点过的卡还挂在那里可点。
现在准备阶段把行 id 存进 `Projector.calls`，后续派发、答复、结果都复用它。
契约 3.6 里的「`turn_id` 为空」和「行 id 不变」现在同时成立。

**3. 产物 id 要可读且稳定。** 原来是 `{thread}:{turn}:{item_id}:{path}`，同一份文件在恢复重放里能生成两个不同 id
（界面就显示两张卡）。现在 `{item_id}:artifact:{path}`，并且样本里逐字写死。

## 七、本轮据契约改变的行为

| 位置 | 改前 | 改后 | 为什么 |
| --- | --- | --- | --- |
| 信封 `created_at` | `""` | ISO-8601 UTC | 空串是合法字符串，界面会收下并显示成无效日期 |
| 条目 `created_at_ms` | `0` | 真实毫秒 | 0 是 1970 年，看着有值其实是假值 |
| 信封 `seq` | 恒写 | `seq=0` 时省略 | 0 会被当成真实排序锚点，条目排到所有事件之前 |
| 信封 `turn_id` / `item_id` | 无 | 与 `payload` 同名同值 | 界面不必依赖回退读取 |
| 用户消息 `content` | 裸字符串 | `[{"type":"text","text":…}]` | 契约形状是分片数组；读方宽容不等于生产方可以不合规 |
| 工具参数键 | `tool_args` | `arguments`（保留别名） | 界面读的是 `arguments` |
| 产物位置 | `payload.payload.artifacts` | 条目顶层 `artifacts` | `run_item.py::to_dict` 就在顶层；放在 payload 里靠兼容分支才显示 |
| 工具结果键 | `content` / `is_error` | 另补 `delta` / `tool_result` / `replace` / `status` / `error` | 桌面核用这套名字，两套并存谁都不用猜来源 |

## 八、已知缺口

- **重放事件的时间不是事发时间。** `journal_events.created_at` 一直在库里，
  但 `sunday_store::history_page` 只读 5 列，没把它带出来。所以恢复一段历史时，
  每条事件的时间是「投影发生的时刻」。排序不受影响（排序靠 `seq`），
  受影响的是旧消息显示的时间。要修得给读路径加一列，并让 `BridgeEvent` 多带一个时间字段
  （21 处构造点），这一轮没做，先记在这里，不写进代码注释当承诺。
- 契约目前只覆盖投影边界，不覆盖 SAF 授权、附件上传、进程中途死亡后的重放策略；那些等各自落地时再写各自的契约。

## 九、这一轮怎么判断做完了

两条命令，秒级：

```
cargo test --lib projection            # 15 项，含 3 项契约测试
npx vitest run tests/android-host-event-contract.test.ts   # 10 项
```

模拟器留到「Android 特有行为」再上场：WebView 能不能加载、IPC 能不能通、权限弹窗、SAF、后台被杀。
业务逻辑对不对，不再问模拟器。
