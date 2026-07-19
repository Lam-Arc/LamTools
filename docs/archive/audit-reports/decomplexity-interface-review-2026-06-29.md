# LamTools 去复杂化审查：从入口 Interface 反推深模块

日期：2026-06-29

维护标注（2026-06-30）：本文提出的 Phase 3 第一刀已落地。Writer 前端产品主线不再保留事件 reducer fallback，`appServer/reducer.ts` 已删除；当前剩余 Interface 问题集中在 Workbench 操作入口、Operation Catalog、GUI control owner 和 CLI 分层。

本轮不是重复 `agent-code-inventory-2026-06-29.md` 的功能底图，也不是继续拆大文件。这里换一个角度：从用户可触达的 CLI、GUI、HTTP、实时状态入口反推内部 Interface 是否过浅。

判断标准：

- 一个能力如果在 CLI、GUI、HTTP、前端 store、后端 reducer 中各自命名和解释一次，就是浅 Interface。
- 一个 Module 删除后如果只是少了一层转发，它是债务；删除后复杂度会扩散到多个调用点，才说明它有深度。
- 一个 Seam 只有一个 Adapter 时，优先怀疑它是假抽象；有生产 Adapter 和测试 Adapter，或者 Writer/Artist 两个成员都真正复用，才是稳定 Seam。

参考成熟产品方向：

- OpenAI Codex CLI 把普通执行、继续会话、诊断、实验能力分层，不把 debug/tool/plugin 类入口和日常任务入口混在同一层。
- Claude Code CLI 区分交互会话、一次性任务、继续最近会话、恢复指定会话；入口少，但语义明确。
- OpenAI/Claude 的共同点不是命令名，而是“一个操作有一个主入口，内部实现可以复杂，但外部语义不漂移”。

## 总结判断

当前 LamTools 的复杂度主要不是“模块还不够多”，而是四个地方把同一件事反复解释：

1. **操作入口重复**：Writer 有 `run/resume/chat/quick/message send`，Artist 是位置参数式 CLI，GUI 又各自接产品动作。
2. **消息与任务混名**：Core UI 的 `createMessage` 被 Artist 拿来启动 `artist-turn`，Writer 则在页面里绕到 app-server `turn/start`。
3. **状态投影重复已收敛第一刀**：Writer 后端权威 snapshot 已成为前端主线，前端 reducer fallback 已删除；后续继续收敛 transcript/app snapshot 边界。
4. **可见控件缺 owner**：共享 `SessionSidebar` 能发 `rename-session`，但当前 Writer/Artist 工作台没有完整持久化接线，属于“看得见但不可靠”的入口。

最小化目标不是“把每个大文件拆小”，而是把这些入口收敛成少数深 Module：

```text
Operation Catalog
  -> CLI adapter
  -> GUI command/action adapter
  -> member backend adapter
  -> canonical snapshot/selectors
```

用户只需要理解操作，代码只需要在一个地方登记操作，前端只读权威状态。

## 代码证据

| 现象 | 源码证据 | 复杂度来源 | 判定 |
|---|---|---|---|
| Core 工作台把发送定义成 `createMessage` | `core/ui/src/composables/useCoreWorkbenchController.ts` | Interface 名称是“写消息”，实际成员需要的是“启动/继续任务” | 债务 |
| Artist 用 `createMessage` 接 `artist-turn` | `members/artist/frontend/src/views/CoreWorkbenchView.vue` | 调用者必须知道这个 message 不是普通消息，而是任务触发 | 债务 |
| Writer 页面同时拿 Core messages 和 app-server turn | `members/writer/frontend/src/views/CoreWorkbenchView.vue`、`members/writer/frontend/src/appServer/store.ts` | 页面承担了“什么时候写消息、什么时候启动 turn、什么时候排队”的业务语义 | 存疑 |
| Writer CLI 普通入口和开发入口同层 | `members/writer/backend/writer_cli/__main__.py` | `agent/tool/debug/message/step` 与 `run/resume/watch` 并列，普通用户与开发诊断混在一起 | 债务 |
| Artist CLI 是位置参数解析 | `members/artist/backend/app/cli.py` | `image/copy/rename/session/prompt` 共享一个 args 列表，help 中还出现未稳定的 `ct` | 债务 |
| Artist `/generate` 已委托到 `/artist-turn` | `members/artist/backend/app/routers/session.py`、`members/artist/backend/app/services/generate_service.py` | 兼容入口存在价值，但不能再作为主文档入口 | 存疑 |
| Writer 前端已改 snapshot-only | `members/writer/frontend/src/appServer/store.ts`、`members/writer/frontend/src/appServer/snapshot.ts`、`members/writer/frontend/src/appServer/selectors.ts` | 前端不再解释事件，只 hydrate 后端 snapshot | 已处理 |
| Sidebar rename 没有稳定 owner | `core/ui/src/components/SessionSidebar.vue`、两个 member 的 `CoreWorkbenchView.vue` | 控件可见，但持久化语义不完整 | 债务 |
| SettingsView 承担配置目录、表单、预设、路由 | `members/writer/frontend/src/views/SettingsView.vue` | 配置页是浅组合体，Provider/Model/Agent/Tool 混在一个页面文件 | 存疑 |

## 高收益去复杂化方案

### 1. 建 Operation Catalog：所有外部能力登记一次

当前问题：

- CLI 文档、GUI 文档、后端路由、前端按钮各自列能力。
- 新增入口时没有测试能发现“文档有但代码没有”或“控件有但保存不了”。

建议 Interface：

```json
{
  "id": "writer.turn.start",
  "member": "writer",
  "visibility": "public",
  "category": "turn",
  "cli": "writer run <task...>",
  "gui": "Workbench composer",
  "backend": "app-server turn/start",
  "status": "stable",
  "aliases": ["writer quick"],
  "deprecated": []
}
```

落地路径：

1. 新增 `core/operations/catalog.schema.json`、`core/operations/writer.json`、`core/operations/artist.json`、`core/operations/core.json`。
2. 先只记录公开能力，不急着驱动代码生成。
3. 加一个轻量检查：公开能力必须至少有 CLI 或 GUI 入口，GUI 可见操作必须有 owner。
4. 后续再让 CLI/GUI 文档从 catalog 校验或生成。

删除收益：

- 旧文档表、重复入口清单、手写 GUI/CLI 对照可以逐步删除。
- `writer agent/tool/debug/message/step` 可统一降到 `writer dev ...`，普通入口减少。

判定：可靠。它不是新业务抽象，而是把已经存在的入口事实集中管理。

### 2. 把 Core Workbench Interface 从 `createMessage` 改成 Turn 操作

当前问题：

- `createMessage(sessionId, content, role)` 看似通用，但 Writer/Artist 真实业务都不是“只写一条消息”。
- Artist 直接把 `createMessage` 适配到 `artist-turn`；Writer 页面绕开 controller 调 app-server `turn/start`。

建议 Interface：

```ts
interface MemberWorkbenchAdapter {
  listSessions(): Promise<Session[]>
  createSession(input?: CreateSessionInput): Promise<Session>
  renameSession(sessionId: string, title: string): Promise<Session>
  deleteSession(sessionId: string): Promise<void>
  listMessages(sessionId: string): Promise<Message[]>
  startTurn(sessionId: string, input: TurnInput): Promise<TurnResult>
  resumeTurn(sessionId: string, input: TurnInput): Promise<TurnResult>
  stopTurn(sessionId: string): Promise<void>
  respondDecision(requestId: string, decision: DecisionInput): Promise<void>
}
```

落地路径：

1. 保留 `getMessages/listEvents` 作为只读能力。
2. 新增 `startTurn`，让 Writer 适配 app-server `turn/start`，Artist 适配 `/artist-turn`。
3. `createMessage` 降级为内部消息持久化方法，不出现在 Workbench 外部 Interface。
4. 两个 member 的 Workbench submit 逻辑都只调用 adapter。

删除收益：

- 删除 Artist “message 即任务”的语义伪装。
- Writer 页面可以少知道 app-server 方法名，减少页面业务分支。

判定：P0 债务处理。这个比继续拆 `CoreWorkbenchView.vue` 更根本。

### 3. Writer 前端只吃后端 snapshot，删除事件 reducer 主线

当前状态：

- 2026-06-30 已删除前端事件 reducer 和 `usesAuthoritativeSnapshots` 迁移旗标。
- `store.ts` 只应用后端返回或推送的 snapshot，`snapshot.ts` 只补齐默认字段。
- 这一步已解决前端重复解释事件的问题；后续重点是所有 mutating RPC 持续返回 snapshot，并用 schema/contract 防漂移。

建议 Interface：

```text
WebSocket event/response
  -> if snapshot exists: hydrate(snapshot)
  -> if only event exists: request latest snapshot
  -> selectors
  -> UI
```

落地路径：

1. 前端 `applyEvent` 已删除，不再作为产品主线或测试工具。
2. app-server 所有 mutating RPC 必须继续返回 snapshot。
3. WebSocket 收到 snapshot 时直接 hydrate；若未来出现裸事件，只能请求最新 snapshot，不自行 reduce。
4. selector 是唯一 UI 输入：messages、queue、approval、metrics、artifacts。

删除收益：

- `members/writer/frontend/src/appServer/reducer.ts` 已删除。
- waiting request、final reply、queue 状态不再有前后端两套解释。

判定：P0 债务处理。先做这个，再拆 `ChatThread`，否则 UI 会被协议变化反复返工。

### 4. CLI 入口分层：普通入口少，开发入口深

当前问题：

- Writer CLI 的 `agent/tool/debug/message/step` 与日常 `run/resume/watch` 同级。
- Artist CLI 的位置参数把任务、图片、会话、复制、重命名混在一个列表里。

建议用户层入口：

```text
writer run/resume/watch/stop/session/config/health
artist run/resume/watch/stop/image/session/config/health
```

建议开发层入口：

```text
writer dev agent/tool/debug/message/step/app-server
artist dev mock/inspect/runtime
```

落地路径：

1. 先不删除旧命令，增加 deprecation 提示。
2. `writer chat/quick/cancel` 保留 alias，但文档不主推。
3. Artist 改成 subparser；`artist <prompt>` 仅作为 `artist run` 快捷。
4. help 首页只显示公开稳定命令。

删除收益：

- 用户记忆负担下降。
- 文档、验收和自动化脚本的命令语义稳定。

判定：可靠。与成熟 coding CLI 的分层方式一致。

### 5. GUI 可见操作必须有 owner；没有 owner 就隐藏

当前问题：

- `SessionSidebar` 支持 rename emit，但 Writer/Artist 工作台没有完整接线。
- 这种控件会制造“用户以为能操作，实际刷新丢失或无反应”的故障。

建议规则：

```text
visible control -> operation id -> adapter method -> backend persistence -> refresh verification
```

落地路径：

1. 用 Operation Catalog 标记所有 GUI control。
2. `rename-session` 先接线到两个 member 的持久化接口；如果某成员没有接口，就关闭 `allow-rename`。
3. 删除只改 localStorage、不改后端事实的伪管理入口，除非它明确标为“本机界面设置”。

删除收益：

- GUI 入口审查变成可测试规则。
- 减少“看起来有功能”的低质量补丁。

判定：债务，且适合立即处理。

### 6. 配置页变成配置 Module，不再由 SettingsView 持有全部知识

当前问题：

- Writer `SettingsView.vue` 同时处理 Provider、Model、Agent、Tool、Theme、默认值、路由。
- Provider presets 这类静态配置适合下沉到共享 catalog；但只有 Writer/Artist 都复用时，才应该成为 Core UI 的稳定外部 Interface。

建议 Interface：

```text
ProviderCatalog
  listPresets()
  createProviderFromPreset(presetId, options)
  createModelsFromPreset(providerId, presetId)

ModelRoutingConfig
  getRoute(taskType)
  setRoute(taskType, modelId)
```

落地路径：

1. Provider preset 由共享 catalog 维护，SettingsView 只调用方法。
2. Writer/Artist 各自保留产品路由规则，但共享供应商/模型术语。
3. Settings 页面按 domain panels 组合：ProviderPanel、ModelPanel、AgentPanel、ToolPanel、ThemePanel。
4. 外部 Interface 仍是 `/settings`，不要把拆出来的内部 panel 变成新路由。

删除收益：

- SettingsView 减少大量表单和预设样板。
- Provider/Model 文档和 UI 命名统一。

判定：存疑转可靠。前提是两个成员都复用 catalog，否则不要过早上抽。

### 7. 兼容入口设置删除日期

当前问题：

- `/generate` 已委托到 `/artist-turn`，但如果文档继续宣传它，就会变成第二主线。
- `writer list/new/status/result/messages` 与 `writer session ...` 并存。

建议规则：

| 类型 | 处理 |
|---|---|
| 已有用户可能依赖 | 保留 alias，一版提示期 |
| 仅测试/调试使用 | 移到 `dev` 或测试 helper |
| 没有 owner 的旧入口 | 标 legacy，定删除日期 |
| 文档误导入口 | 立即从普通指南移除 |

删除收益：

- 新人不会继续走旧路径。
- 后续删代码有明确验收口径。

判定：可靠。删除兼容层必须比新增功能更优先。

## 推荐实施顺序

### Phase 0：文档与入口止血

- 保留当前 `docs/cli-guide.md`、`docs/gui-guide.md` 的源码口径。
- `docs/cli-gui-entry-audit-2026-06-29.md` 作为事实审计。
- `docs/cli-gui-entry-optimization-plan-2026-06-29.md` 作为入口优化路线。
- 普通用户文档不再主推 debug/tool/message/step。

验收：

- `writer --help`、`artist --help` 能跑。
- 文档不再指向不存在的 `artist.py`。

### Phase 1：Operation Catalog + GUI owner 检查

- 新增 catalog 三份：core/writer/artist。
- 写检查脚本：公开 operation 必须有入口映射；GUI 入口必须有 owner。
- 先修或隐藏 session rename。

验收：

- Sidebar 可见操作全部能持久化或被隐藏。
- CLI/GUI 指南能从 catalog 校验。

### Phase 2：Workbench Adapter 改造

- 新增 `startTurn/resumeTurn/stopTurn/respondDecision`。
- Artist 不再把 `artist-turn` 塞进 `createMessage`。
- Writer 页面减少 app-server 方法名直连。

验收：

- Writer/Artist 输入框都通过同一 Workbench 操作 Interface。
- `/messages` 明确只做消息读写。

### Phase 3：Writer snapshot-only

- 状态：第一刀已完成，前端产品主线 reducer 已删除。
- app-server mutating RPC 持续返回 snapshot。
- 前端保持 snapshot-only，不恢复 event replay 主线。
- selector 覆盖 queue、approval、final reply、artifacts。

验收：

- live 和刷新后展示一致。
- waiting request、queue、final reply 不再依赖前端 event replay。

### Phase 4：CLI 分层和 alias 退场

- Writer 增 `dev` 组；Artist 改 subparser。
- 普通 help 只显示稳定入口。
- alias 输出 deprecation 提示。

验收：

- `writer run/resume/watch/stop/session/config/health` 是普通主线。
- `artist run/resume/image/session/config/health` 是普通主线。

### Phase 5：Settings deepening

- ProviderCatalog 共享。
- SettingsView 拆 domain panels，但不新增用户路由。
- 配置文档统一“供应商/模型”。

验收：

- Provider preset 只维护一份。
- Writer/Artist 配置入口术语一致。

## 不要做的事

- 不要因为文件大就机械拆文件。拆完调用者还要知道同样多的事实，就是浅拆。
- 不要让 Core 认识 Writer/Artist 业务动作。Core 只知道 operation shape 和 Workbench shape。
- 不要长期保留前后端两套 reducer。兼容可以短期存在，但必须有退场点。
- 不要把 debug 命令藏在普通帮助里。用户入口和开发入口要分层。
- 不要让 GUI 控件先出现、后端语义以后再补。没有 owner 的控件应该先隐藏。

## 最终形态

```text
User intent
  -> Operation Catalog entry
  -> CLI adapter or GUI adapter
  -> MemberWorkbenchAdapter
  -> member backend action
  -> canonical app snapshot
  -> selectors
  -> shared UI render
```

一句话：入口只登记一次，任务只启动一次，状态只解释一次。
