# Core / Member 架构还原设计方案

日期：2026-06-30

关联文档：

- `docs/agent-architecture-north-star-2026-06-30.md`
- `docs/complexity-and-loc-review-2026-06-30.md`
- `docs/writer-complexity-source-analysis-2026-06-30.md`
- `docs/core-member-architecture-refactor-execution-plan-2026-07-01.md`

目标：把 LamTools 还原成 **Core agent 基座 + member 领域特化包**。Writer/Artist 不再拥有独立 runtime、旧事件、旧投影、重复工具实现。最终任何工程师看目录和关键接口时，都能明确判断：

```text
Core = 可直接运行、可改造的 agent 基层
Member = 领域 persona、prompt、工具声明、验收、UI
Product = Core + Member
```

## 1. 设计原则

| 原则 | 说明 | 不接受的形态 |
|---|---|---|
| Core 是唯一运行实现源 | 模型、工具、权限、事件、session、snapshot、artifact、sub-agent、MCP 的基础实现只在 Core | Writer/Artist 各自写 LLM client、tool executor、event bridge、SSE manager |
| Member 是领域包 | member 只提供领域内容、策略和少量 adapter | member 目录里出现 runtime、projection、legacy event system |
| 替换，不叠层 | 每引入一个 Core interface，就迁移调用方并删除旧 Writer 实现 | 新 Core adapter 外面继续套 Writer adapter，再保留旧 fallback |
| 一条运行主线 | CLI/GUI/HTTP 都进入同一 operation/turn path | CLI 和 GUI 走不同 runner，REST 旧入口仍可触发另一条 runtime |
| 一个状态事实源 | UI 只消费 Core snapshot / selectors | transcript、runtime events、SSE、snapshot 同时驱动 UI |
| 测试保护新结构 | 测试验证 Core contract 和 member fixture | 测试继续保护 `core_adapter.py`、TaskManager SSE、old parser key |
| 行数反映主次 | Writer runtime <= 6,000，业务核心 <= 1,500 | 通过移动文件名或隐藏复杂度绕过行数目标 |

## 2. 最终目录形态

### 2.1 Core

```text
core/src/lamtools_core/
  app/
    agent_app.py             # 组合 AgentSpec + MemberKit + services
    operation_catalog.py     # CLI/GUI/HTTP 共用操作目录
  kernel/
    loop.py                  # 对外保持小 interface
    model_caller.py
    tool_runner.py
    approval_gate.py
    context_compactor.py
    event_emitter.py
  llm/
    __init__.py
    adapter.py
    provider_profile.py
    model_capability.py
    stream_normalizer.py
  tool/
    __init__.py
    registry.py
    permission.py
    workspace_toolkit.py
    shell_toolkit.py
    git_toolkit.py
    web_toolkit.py
    mcp_toolkit.py
  prompt/
    __init__.py
    assembler.py
    budget.py
  session/
    store.py
    transcript.py            # 审计协议，不是 UI 事实源
  event/
    run_item.py
    sink.py
  snapshot/
    reducer.py
    store.py
    selectors_contract.py
  artifact/
    __init__.py
  mem/
    __init__.py
  agent/
    sub_agent_runner.py
  mcp/
    registry.py
    client.py
```

说明：

- 目录名是目标形态，不要求一次性机械改名。
- Core 可内部拆小文件，但公开 interface 必须少。
- Core 中不得出现 Writer/Artist 业务名、业务 prompt、产品分支。

### 2.2 Writer

```text
members/writer/
  member.toml
  backend/
    app/
      main.py                # thin app bootstrap
      adapter.py             # product HTTP/DB adapter, thin only
      kit.py                 # WriterKit: 组合 prompt/tool/verification
      prompts/
        persona.md
        execution.md
        reply_contract.md
      tools.py               # Writer 专用工具声明/领域 handler
      verification.py        # Writer 验收策略
      agents/
        architecture.md
      ui_labels.py           # 产品展示文案，不含运行协议
  frontend/
    src/
      Workbench.vue          # product composition only
      Settings.vue           # Writer-specific settings only
      writerLabels.ts
```

Writer 不再保留：

- `services/task_manager.py`
- `core/writer/core_adapter.py`
- `core/writer/events.py` 旧 Writer event family
- `app_server/runtime_bridge.py` 的多层 WriterRuntimeEvent 输入
- `writer_cli/__main__.py` 里的旧 event formatter 和 dev/debug 混层
- `utils/llm_client.py` / `llm_adapter_profiles.py` 里的通用转换
- `tool_executor.py` 里的 workspace/shell/git/web 通用实现
- `frontend/src/runtime/transcript.ts` 作为 UI 主路径

### 2.3 Artist

```text
members/artist/
  member.toml
  backend/
    app/
      main.py
      adapter.py
      kit.py
      prompts/
      visual_context.py
      tools.py
      verification.py
  frontend/
    src/
      Workbench.vue
      Settings.vue
      artistLabels.ts
```

Artist 是第二个验证样例，不是新 runtime。它用于证明 Core 的通用能力确实可复用。

## 3. 核心 Interface 设计

### 3.1 AgentApp

目标：让 Core 可以直接运行一个基础 agent，也可以加载 member。

```python
app = AgentApp(
    spec=AgentSpec(...),
    kit=member_kit,
    model_provider=provider,
    session_store=store,
    event_sink=sink,
)

result = await app.run_turn(TurnInput(...))
```

公开 interface：

| Interface | 责任 |
|---|---|
| `AgentSpec` | agent 名称、instructions、默认模型、工具集合、能力声明 |
| `MemberKit` | 领域注入点：prompt fragments、领域工具、verification、labels |
| `ModelProvider` | LLM 调用入口，内部处理 provider profile、stream、usage、tool calls |
| `ToolRegistry` | 工具目录和执行入口 |
| `SessionStore` | 会话历史、状态、恢复 |
| `EventSink` | canonical run item event 输出 |
| `SnapshotStore` | snapshot reduce/load |

删除测试：

- 如果 Writer 仍需要直接调用 `writer_service.py` 才能跑 turn，失败。
- 如果新 member 需要复制 Writer 的 runtime service，失败。

### 3.2 MemberKit

替代当前过宽的 RuntimeKit。Kernel 可以继续保留内部 `RuntimeKit`，但 member 对外只实现更小的 interface。

```python
class MemberKit(Protocol):
    id: str
    display_name: str

    def prompt_providers(self) -> list[PromptFragmentProvider]: ...
    def tool_providers(self) -> list[ToolProvider]: ...
    def verification_policy(self) -> VerificationPolicy: ...
    def labels(self) -> MemberLabels: ...
```

Core 内部负责：

- build context
- assemble prompt
- build LLM request
- parse tool calls
- run tools
- emit events
- reduce snapshot
- ask approval
- persist state

Member 负责：

- 提供 persona / prompt fragments
- 声明领域工具
- 提供领域验收规则
- 提供产品 labels

当前 Writer 的 `core_kernel_adapter.py` 应拆成：

| 当前职责 | 去向 |
|---|---|
| LLM bridge / stream 转换 | Core `llm` |
| prompt 拼接顺序和预算 | Core `prompt` |
| Writer prompt 内容 | Writer `prompts/` + prompt provider |
| workspace/shell/git/web 工具执行 | Core `tool/*_toolkit.py` |
| Writer 专用工具声明 | Writer `tools.py` |
| runtime event formatting | Core `event` |
| completion verifier adapter | Writer `verification.py` + Core `VerificationResult` |

### 3.3 OperationCatalog

目标：CLI/GUI/HTTP 不再各自维护入口。

```text
operation_catalog
  thread.create
  thread.resume
  turn.start
  turn.cancel
  approval.respond
  queue.create/update/delete
  session.list
  settings.get/update
```

规则：

- GUI 调 operation。
- CLI 调 operation。
- HTTP/WebSocket 只是 transport adapter。
- dev/debug 操作必须在 `dev.*` 命名空间。
- 任何旧 REST message path 都标记 deprecated，然后删除。

### 3.4 Canonical RunItemEvent

目标：替换 CoreEvent / WriterRuntimeEvent / Writer SSE / AppEvent 多层互转。

```text
RunItemEvent
  id
  run_id
  turn_id
  seq
  kind
  item_id
  parent_id
  status
  payload
  artifacts
  usage
  created_at
```

允许的 `kind`：

```text
message
thinking
tool_call
tool_result
approval_request
approval_response
artifact
verification
handoff
usage
error
status
```

禁止：

- `writer_git_snapshot`
- `writer_part_updated`
- Writer SSE payload 内嵌 `core_event`
- runtime event 再转 app event 再转 snapshot 的多层链路

### 3.5 Snapshot

目标：UI 只认 snapshot。

```text
RunItemEvent -> SnapshotReducer -> ThreadSnapshot -> selectors -> UI
```

规则：

- transcript 是审计，不是 UI 事实源。
- snapshot reducer 在 Core，member 可提供 labels 和 domain projection。
- frontend store 只能 hydrate snapshot。
- ChatThread 只渲染 canonical parts。

### 3.6 Toolkits

Core 提供 optional toolkits：

| Toolkit | 能力 |
|---|---|
| WorkspaceToolkit | read/write/edit/search/list/diff |
| ShellToolkit | run command, approval-aware |
| GitToolkit | status/diff/branch/commit/checkpoint metadata |
| WebToolkit | web_search/web_fetch |
| MCPToolkit | register/call MCP tools |
| SubAgentToolkit | delegate to configured sub-agent |

Writer/Artist 只能：

- 选择启用 toolkit。
- 设置权限策略。
- 声明领域工具。
- 定义工具结果如何参与验收。

## 4. 迁移阶段

### Phase 0：冻结旧入口增长

目标：不再增加 Writer 内 runtime 代码。

动作：

1. 标记 `TaskManager` SSE、`core_adapter.py`、`writer_git_*`、旧 REST message path 为 deprecated。
2. 新功能只能接 Core interface，不准接 Writer service 内部。
3. 新测试只能覆盖 Core contract 或 member behavior，不准新增旧事件测试。

验收：

- `rg "writer_git_|writer_part_updated|writer_payload_to_core_event" members/writer/backend/app` 结果只减少不增加。
- `writer_cli` 不再新增旧 event formatter。

### Phase 1：事件和状态收敛

目标：一条事实链。

```text
Core RunItemEvent -> Core SnapshotReducer -> Snapshot -> UI/CLI
```

动作：

1. 在 Core 增加 `RunItemEvent`、`EventSink`、`SnapshotReducer`。
2. Writer `runtime_bridge.py` 改为只接受 Core RunItemEvent。
3. CLI formatter 改为读取 canonical event/snapshot。
4. 删除 `core_adapter.py` 和对应测试。
5. 合并并删除 `writer_git_*`、`writer_part_updated`。

验收：

- `members/writer/backend/app/core/writer/core_adapter.py` 删除。
- `members/writer/backend/app/core/writer/events.py` 不再定义 canonical SSE event types。
- `writer_cli/__main__.py` 不再判断 `writer_git_*` / `writer_part_updated`。

### Phase 2：运行入口收敛

目标：CLI/GUI/HTTP 同源。

动作：

1. Core 增加 `OperationCatalog`。
2. App Server websocket 调 operation。
3. CLI 调 operation。
4. 旧 REST `/sessions/{id}/messages`、Core HTTP compatibility path 迁移为 deprecated adapter。
5. dev/debug 命令移到 `writer dev`。

验收：

- 普通 `writer run/resume/watch/session` 不 import `AgentRuntime`、`ExtendedToolExecutor`。
- `routers/session.py` 不再混放 debug、checkpoint、commit review、message runtime。
- GUI 和 CLI 用同一个 `turn.start` operation。

### Phase 3：LLM/provider 下沉

目标：Writer 不解析 provider payload。

动作：

1. Core `LLMAdapter` 接管 profile、request payload、stream chunk、tool call、usage、thinking。
2. Writer provider/model DB 只作为配置 adapter。
3. 删除 Writer `llm_adapter_profiles.py` 和 `llm_adapters/*.jsonc` 中通用语义。
4. Settings/Workbench 只读 Core model capability。

验收：

- Writer 不再出现 provider-specific response path parser。
- thinking/tool-call/usage 只在 Core LLM 层解释。
- Artist 复用同一 Core LLM adapter。

### Phase 4：工具和权限下沉

目标：Writer 不实现通用工具 runtime。

动作：

1. Core 增加 Workspace/Shell/Git/Web/MCP/SubAgent toolkits。
2. Writer `tools.py` 只声明启用哪些 toolkit 和领域工具。
3. Core `ApprovalGate` 统一权限请求、等待、恢复。
4. Writer command policy 变成策略配置，不再是执行实现。

验收：

- Writer `tool_executor.py` 删除或只剩领域 handler。
- `scope_guard.py` compatibility methods 删除。
- Git status/diff/branch/commit metadata 来自 Core GitToolkit。

### Phase 5：Prompt / Memory / Verification 收敛

目标：WriterKit 变薄。

动作：

1. Core prompt assembler 负责排序、预算、截断。
2. Writer prompt providers 只返回 fragments。
3. Core memory protocol 负责 store/recall/provenance/budget。
4. Core `VerificationResult` 统一验收结果协议。
5. Writer completion verifier 保留领域判定，但输出 Core result。

验收：

- WriterKit 不再手写长 prompt 拼接。
- `completion_verifier.py` 拆成领域规则，通用 result/evidence/repair 协议在 Core。

### Phase 6：UI 瘦身

目标：前端只做产品 UI。

动作：

1. Core UI 提供 snapshot selectors、ChatThread canonical renderer、SessionSidebar、SettingsShell。
2. Writer Workbench 只组合 product-specific slots。
3. SettingsView 拆成 Writer panels，provider/model 能力来自 Core UI/shared data。
4. 删除 `runtime/transcript.ts` UI 主路径。

验收：

- `ChatThread.vue` 不理解 Writer runtime event。
- `CoreWorkbenchView.vue` 只调 operation 和 selectors。
- Writer frontend src <= 2,500 行。

### Phase 7：Artist 作为示例迁移

目标：证明 Core 可复用。

动作：

1. Artist 改成同一 MemberKit。
2. 删除 Artist SSE runtime 和 fallback schema mapper。
3. 图像生成、视觉上下文、视觉验收留在 Artist。
4. Artist 文档改成“如何实现一个 member”的示例。

验收：

- Writer/Artist 都不复制 LLM/tool/session/event runtime。
- scaffold 新 member 可以参考 Writer/Artist 两个薄样例。

## 5. 行数目标

| 范围 | 当前 | 硬上限 |
|---|---:|---:|
| Writer backend runtime | 40,809 | <=3,000 |
| Writer frontend src | 8,022 | <=2,500 |
| Writer prompt/config/入口薄壳 | 约数百 | <=500 |
| Writer runtime 合计 | 48,831 | <=6,000 |
| Writer 专属业务核心 | 混在 40k 内 | <=1,500 |

行数审查脚本必须固定口径：

计入：

- `members/writer/backend/app/**/*.py`
- `members/writer/backend/writer_cli/**/*.py`
- `members/writer/frontend/src/**/*.{ts,vue,css}`
- Writer prompt/config runtime 文本

不计入：

- tests
- docs
- node_modules
- dist/release/target
- package-lock
- 截图/临时产物
- Core 代码

## 6. 测试设计

### 6.1 Core contract tests

必须覆盖：

- `AgentApp.run_turn`
- LLM adapter payload/stream/tool-call/usage/thinking normalization
- ToolRegistry + toolkit execution
- ApprovalGate interrupt/resume
- Prompt assembler ordering/budget/truncation
- RunItemEvent schema
- Snapshot reducer idempotency
- Session store persistence/reload
- Sub-agent runner result/error

### 6.2 Member fixture tests

Writer/Artist 测试只证明：

- member manifest 可加载。
- prompt providers 输出领域 fragments。
- tools 声明合法。
- verification 输出 Core `VerificationResult`。
- UI labels/slots 合法。

### 6.3 Product smoke tests

每个 member 保留最少 smoke：

- 创建会话。
- 发送 turn。
- 工具调用。
- approval。
- refresh snapshot。
- CLI run。
- GUI render。

### 6.4 删除旧测试

同步删除或改写：

- `test_writer_core_adapter.py`
- `test_task_manager.py`
- 保护 `writer_git_*` / `writer_part_updated` 的 CLI tests
- 保护 old `response/thought/phase/mode` parser 的 tests
- Core UI 对旧 transcript/runtime part 的兼容测试

## 7. 风险和处理

| 风险 | 处理 |
|---|---|
| 抽 Core 时把 Writer 业务语义带进去 | Core contract review：不得出现 Writer/Artist 名称、业务 prompt、业务分支 |
| 删除旧 SSE 影响 cancel/running 状态 | 先实现 Core runtime registry，再删 TaskManager |
| snapshot reducer 迁移造成刷新丢消息 | 先建 idempotency contract test，再迁 UI |
| LLM adapter 迁移破坏 provider 差异 | 用 provider fixture 测 stream/tool-call/thinking/usage |
| 工具下沉降低安全性 | Core PermissionGate 默认保守；member 只能配置策略，不能绕过 gate |
| 行数目标导致机械删文件 | 每次删除必须通过“复杂度消失/下沉/领域保留”三分法 |

## 8. 不做事项

这些事情不应作为第一阶段重点：

- 不先大拆 UI。事件和状态未收敛前拆 UI 会返工。
- 不新增一个更大的 Writer facade。facade 只能临时迁移，不能成为新主线。
- 不保留双事件系统做“稳定过渡”。过渡必须短，并有删除验收。
- 不把 Writer 验收策略沉 Core。Core 只放 `VerificationResult` 协议。
- 不把 Artist 当成熟产品源复制。Artist 是第二适配器验证 Core，不是抽象来源。

## 9. 第一批实施切片

建议按以下顺序开工：

1. **Core RunItemEvent + SnapshotReducer contract**
   - 新增 Core event/snapshot 协议。
   - Writer app-server 先适配该协议。
   - 不动 UI 视觉。

2. **删除 Writer SSE -> CoreEvent**
   - 改 `events.py` 不再 enrich `core_event`。
   - 删 `core_adapter.py` 和测试。

3. **替换 TaskManager running/cancel**
   - Core/App runtime registry 接管 running/cancel。
   - App Server snapshot 表达 running/cancel 状态。
   - 删 `TaskManager` SSE 产品链路。

4. **CLI formatter 只读 canonical event**
   - 删除 `writer_git_*` / `writer_part_updated` 旧 formatter。
   - dev/debug 命令移出普通 CLI。

5. **Core LLM adapter 接管 Writer profile**
   - 先迁 OpenAI-compatible 和 xfyun profile。
   - 再删 Writer-local profile parser。

### 9.1 执行记录：2026-06-30 第一切片

已完成：

- Core 新增 `RunItemEvent` 和 snapshot reducer contract，并补充事件序列化、幂等归约、message/tool/approval/artifact/usage 测试。
- Writer app-server `runtime_bridge.py` 主路径改为 `WriterRuntimeEvent -> Core RunItemEvent -> Writer AppEvent`，旧 phase fallback 已删除。
- Writer SSE payload 内嵌 `core_event` 的反向适配已删除；`core_adapter.py` 和 `test_writer_core_adapter.py` 已删除。
- CLI formatter 删除 `writer_git_*` 和 `writer_part_updated` 旧展示分支，普通 CLI 保留 app-server event 主线。

验证：

- `py -3.14 -m pytest core/tests/test_event.py core/tests/test_run_item_snapshot.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_events.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_cli.py`

下一步：

- 用 Core snapshot reducer 替换 Writer app-server reducer 的通用 item/turn/request/artifact 归约，只保留 queue 等 Writer 产品扩展。
- 处理 `TaskManager` SSE 产品链路和 `writer_service.py` 中 runtime/app/transcript 多投影。
- 将 kernel 当前 `CoreEvent` 运行摘要逐步收敛到 `RunItemEvent`。

### 9.2 执行记录：2026-06-30 第二切片

已完成：

- Core 新增 `RuntimeTaskRegistry`，统一管理 active run、cooperative cancel event、按 turn/run 精确查询和强制取消。
- Writer app-server 删除本地 `_APP_SERVER_RUNTIME_TASKS`、`_runtime_task`、`_register_runtime_task`、`_cancel_runtime_task`，启动和中断统一走 Core runtime registry。
- Writer session lifecycle 的 running/cancellable 判断改为读取 Core runtime registry。
- Writer kernel 调用的 cancel event 改为来自 Core runtime registry。
- `TaskManager` 降级为旧 SSE pub/sub，只保留 subscribe/publish/event_stream/signal_done 和 SSE 序列化；running/cancel/task metadata 已移除。

验证：

- `py -3.14 -m pytest core/tests/test_runtime.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_task_manager.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m py_compile core/src/lamtools_core/runtime/__init__.py members/writer/backend/app/app_server/connection.py members/writer/backend/app/services/session_lifecycle.py members/writer/backend/app/services/writer_service.py members/writer/backend/app/services/task_manager.py`

下一步：

- 删除 Writer 旧 SSE transport/publish 链路，让 app-server event/snapshot 成为 GUI 主线。
- 清理 `writer_service.py` 内 runtime event、transcript、app-server event 的重复投影，只保留审计 transcript 和 Core snapshot 主线。
- 将旧 `TaskManager` 测试从保护 SSE 兼容转为证明该链路已删除。

### 9.3 执行记录：2026-06-30 第三切片

已完成：

- 删除 `members/writer/backend/app/services/task_manager.py` 和 `members/writer/backend/tests/test_task_manager.py`。
- Writer service 删除旧 OpenAI-style SSE chunk 生成和 `TaskManager.publish` 发布面；运行事实只保留在 `WriterRuntimeEvent`、transcript 和 app-server projection。
- Writer REST session router 删除无人订阅的旧事件日志写入。
- Writer service 测试不再读取 `_event_log`，改为检查持久 `WriterRuntimeEvent` 阶段。

验证：

- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_cli.py`
- `py -3.14 -m py_compile members/writer/backend/app/services/writer_service.py members/writer/backend/app/routers/session.py`

下一步：

- 清理 `writer_service.py` 内 runtime event、transcript、app-server event 三重投影，优先把通用投影规则沉到 Core snapshot/reducer。
- 删除旧 debug/message/step 注入入口，普通 GUI/CLI 只保留 app-server `turn/start` 主线。
- 继续压缩 Writer service，拆出真正的 Writer 领域 Kit、验收和工具声明。

### 9.4 执行记录：2026-06-30 第四切片

已完成：

- 删除 Writer CLI `debug decision-point`、`message send`、`step send` 三个旧注入命令。
- 删除 Writer REST `/sessions/{id}/debug/decision-point` 和 `/sessions/{id}/debug/step` endpoints 及对应 request schema。
- 更新 CLI/GUI/入口审查/复杂度/历史会话流文档，标注 debug 注入旁路已删除。

验证：

- `py -3.14 -m pytest members/writer/backend/tests/test_writer_cli.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py`
- `py -3.14 -m py_compile members/writer/backend/app/routers/session.py members/writer/backend/writer_cli/__main__.py`

已知非本切片失败：

- `py -3.14 -m pytest members/writer/backend/tests/test_core_http_writer_unit.py members/writer/backend/tests/test_main_core_app_unit.py` 有 2 个旧口径失败：Core session create 当前返回 `idle`，旧测试期望 `active`；health 当前返回额外 `writer_service` 字段，旧测试只允许 `status/app`。

下一步：

- 继续收缩 Writer CLI formatter 的旧 Writer event 分支，只保留 app-server/canonical event。
- 清理 `writer_service.py` 内 runtime event、transcript、app-server event 三重投影。

### 9.5 执行记录：2026-06-30 第五切片

已完成：

- 删除 Writer CLI `quick`、`chat` 两个重复运行别名；`run` 直接创建会话并启动 app-server turn，`resume` 直接向既有会话启动 app-server turn。
- 删除 Writer CLI `agent ...`、`tool ...` 顶层直连后端内部能力的旁路入口。
- 删除 CLI 对旧 `writer_agent_*` 事件族的 formatter 分支和测试。
- 测试新增 `chat/quick/agent/tool` 已删除的反向覆盖，防止旁路入口回流。
- 更新 CLI/GUI/入口审查/复杂度文档，标注普通 Writer CLI 已收敛到 app-server 主线和会话读取入口。

验证：

- `py -3.14 -m py_compile members/writer/backend/writer_cli/__main__.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_cli.py`

下一步：

- 清理 `writer_service.py` 内 runtime event、transcript、app-server event 三重投影。
- 收缩 `events.py` 旧 Writer event helper，让运行事实继续向 Core run item / app-server event 靠拢。

### 9.6 执行记录：2026-06-30 第六切片

已完成：

- Writer CLI formatter 删除 `writer_runtime_event` 和旧 `writer_response/progress/step/decision/lifecycle/part/verification` 事件族分支。
- 删除只服务旧事件格式的 runtime payload/text/detail formatter、旧 `writer_part` formatter、旧 verification formatter、旧 decision prompt helper。
- `_is_done_event`、`_is_failed_event`、`_is_waiting_event`、`_event_request_id` 等运行控制判断只认 app-server event。
- `test_writer_cli.py` 删除旧 Writer event formatter 保护用例，改为覆盖 app-server reply/tool/approval/completed/failed/verbose fallback。

验证：

- `py -3.14 -m py_compile members/writer/backend/writer_cli/__main__.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_cli.py`
- `rg '_format_verification|_prompt_decision|_format_runtime_event|_format_part|_runtime_event|writer_response|writer_progress|writer_step|writer_lifecycle|writer_decision|writer_part|writer_verification|writer_runtime_event' members/writer/backend/writer_cli/__main__.py members/writer/backend/tests/test_writer_cli.py`

下一步：

- 继续清理 `writer_service.py` 内 runtime event、transcript、app-server event 三重投影。
- 继续从旧 session router、旧测试中删除不再作为外部主线的 Writer event helper。

### 9.7 执行记录：2026-06-30 第七切片

已完成：

- 收缩 `members/writer/backend/app/core/writer/events.py`：删除无生产引用的 session/action/turn/part/verification/delegation/progress/decision/lifecycle 包装函数。
- 保留仍被生产代码调用的 helper：`emit_step`、基础 step/progress/response/git constructor、AgentRuntime/ArchitectureAgent 的 thought/workflow/agent step 事件、`git_context` 的 git 事件。
- `test_events.py` 从旧 canonical SSE event family 覆盖改为只保护仍在生产路径使用的 helper。
- `test_progress_tracking.py` 与 `test_wave3_p2.py` 删除旧 event helper 测试；同步修正 `auto_generate_criteria()` 当前每个 deliverable 生成一条验收标准的旧断言。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/events.py members/writer/backend/tests/test_events.py members/writer/backend/tests/test_progress_tracking.py members/writer/backend/tests/test_wave3_p2.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_events.py members/writer/backend/tests/test_progress_tracking.py members/writer/backend/tests/test_wave3_p2.py`
- `rg 'writer_session_created|writer_session_ended|writer_turn_started|writer_turn_completed|writer_action_started|writer_action_completed|writer_part_updated|writer_phase_changed|writer_error\(|writer_waiting_for_approval|writer_action_event|writer_done_event|writer_failed_event|writer_error_event|writer_mode_event|writer_part_event|writer_phase_event|writer_response_event|writer_waiting_for_user_event|writer_decision_required_event|writer_resumed_event|writer_plan_ready_event|writer_progress_event|writer_criteria_verified_event|writer_verification_started_event|writer_verification_completed_event|writer_delegation_event|make_decision_event|make_lifecycle_event|make_reasoning_event|make_part_event|emit_part_event|make_turn_event' members/writer/backend/app members/writer/backend/tests -g '*.py'`

下一步：

- 维护标注：`writer_agent_*` 已在 9.9 删除；后续继续处理 step helper 与 projection。
- 继续清理 `writer_service.py` 内 runtime event、transcript、app-server event 三重投影。

### 9.8 执行记录：2026-06-30 第八切片

已完成：

- 删除未被实例化的 `GitContextManager` 历史壳；当前 Git 产品能力继续由 `WriterGitManager`、session changes/checkpoint 路由和 session state/memory 承担。
- 删除 `writer_git_*` helper 与 `make_git_event`，`events.py` 不再输出 `writer.git` 事件。
- 删除无引用的旧 Writer event schema：`WriterGitEvent`、`WriterDecisionEvent`、`WriterLifecycleEvent`、`WriterPartEvent`、`WriterTurnEvent`。
- `test_events.py` 删除 Git event helper 保护，只保留仍有生产引用的 thought/workflow/agent helper 测试。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/git_context.py members/writer/backend/app/core/writer/events.py members/writer/backend/app/core/writer/schemas.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_events.py members/writer/backend/tests/test_git_context.py members/writer/backend/tests/test_context_specs.py`
- `rg 'GitContextManager|writer_git_|make_git_event|WriterGitEvent|WriterDecisionEvent|WriterLifecycleEvent|WriterPartEvent|WriterTurnEvent|writer\\.git|writer\\.decision|writer\\.lifecycle|writer\\.part|writer\\.turn' members/writer/backend/app members/writer/backend/tests -g '*.py'`

下一步：

- 维护标注：`writer_agent_*` helper 已在 9.9 删除；继续让子 agent 展示事实只走 Core/app-server 主线。
- 继续清理 `writer_service.py` 内 runtime event、transcript、app-server event 三重投影。

### 9.9 执行记录：2026-06-30 第九切片

已完成：

- 删除 `AgentRuntime -> WriterKit -> writer_service` 的 `member_event_callback` 旧桥接通道。
- 删除 `writer_agent_*`、`writer_thought_event`、`writer_workflow_event` helper，`events.py` 只保留仍被生产代码使用的 step helper。
- `ArchitectureAgent` 不再发旧 Writer SSE 形状的过程事件；架构结果继续通过 tool result、handoff metadata、runtime round log 和 Core/app-server 主线暴露。
- 删除旧 `WriterProgressEvent`、`WriterResponseEvent` schema，保留仍被 step helper 使用的 `WriterStepEvent`。
- `test_events.py` 改为只保护仍存在的 step event 构造，`test_agent_runtime.py` 不再把 event callback 当成 AgentRuntime 构造合同。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/events.py members/writer/backend/app/core/writer/schemas.py members/writer/backend/app/core/writer/agent_runtime.py members/writer/backend/app/core/writer/agents/architecture_agent.py members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/services/writer_service.py members/writer/backend/tests/test_agent_runtime.py members/writer/backend/tests/test_events.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_events.py members/writer/backend/tests/test_agent_runtime.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `rg 'writer_agent_|writer_thought_event|writer_workflow_event|member_event_callback|WriterProgressEvent|WriterResponseEvent|make_progress_event|make_response_event|writer\\.progress|writer\\.response' members/writer/backend/app members/writer/backend/tests -g '*.py'`

当前收缩：

- 本切片净删 574 行。
- `events.py` 从 256 行降到 143 行。
- `agent_runtime.py` 降到 932 行。
- `architecture_agent.py` 降到 1,536 行。
- `writer_service.py` 降到 2,016 行。

下一步：

- 继续清理 `writer_service.py` 内 runtime event、transcript、app-server event 三重投影。
- 处理 `emit_step` 的 no-op event callback 形态，判断 WriterStep 是否还应保留为 DB adapter，还是并入 Core run item -> snapshot 投影。

### 9.10 执行记录：2026-06-30 第十切片

已完成：

- 删除 `members/writer/backend/app/core/writer/events.py`，Writer 后端不再保留 `writer.step/progress/response` 旧事件构造器。
- 删除 `WriterStepEvent` schema 和 `test_events.py`，测试不再保护旧 Writer SSE event family。
- 新增 `step_persistence.py`，把当前仍需要的能力收缩为 Writer DB adapter：只负责创建 `WriterStep` 行，不发事件、不接 callback。
- `writer_service.py` 持久化 kernel tool/verification step 时直接调用 `create_writer_step()`，去掉 `_publish_step` no-op callback。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/step_persistence.py members/writer/backend/app/services/writer_service.py members/writer/backend/app/core/writer/schemas.py`
- `rg 'core\\.writer\\.events|from app\\.core\\.writer\\.events|emit_step\\b|make_step_event|WriterStepEvent' members/writer/backend/app members/writer/backend/tests -g '*.py'`
- `rg 'writer\\.(progress|response)|writer\\.step\"' members/writer/backend/app members/writer/backend/tests -g '*.py'`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_agent_runtime.py members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`

当前收缩：

- 本切片净删约 190 行。
- Writer 专属 step 留存形式从“旧 event helper”降级为“DB adapter helper”。

下一步：

- 继续处理 `writer_service.py` 的 transcript、runtime event、app-server projection 三重投影。
- 维护标注：`routers/step.py`、`WriterStep` 表和服务层 step 写入已在 9.11 删除；后续清理前端 step store/API 孤儿定义。

### 9.11 执行记录：2026-07-01 第十一切片

已完成：

- 删除后端 `/api/sessions/{id}/steps*` 路由和 `step_router` 注册。
- 删除 `WriterStep` model、`writer_steps` SQLite additive migrations、session 删除时的 step 清理。
- 删除 `writer_service.py` 中每轮完成后额外写 `WriterStep` 行的逻辑；运行事实继续由 Core result、runtime events、transcript、app-server event/snapshot 承担。
- Writer member manifest 移除 `step` capability 和路由描述。
- 同步 `test_core_http_writer_unit.py` 的 test manifest，避免继续把 step 当作 Writer 能力。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/main.py members/writer/backend/app/database.py members/writer/backend/app/routers/session.py members/writer/backend/app/models/__init__.py members/writer/backend/app/services/writer_service.py`
- `rg 'WriterStep|writer_steps|routers\\.step|step_router|step_persistence|create_writer_step|/steps|steps/summary' members/writer/backend -g '*.py'`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_core_http_writer_unit.py members/writer/backend/tests/test_main_core_app_unit.py -q`

当前收缩：

- 本切片净删约 340 行后端代码。
- 后端已不再有 WriterStep 表/API/持久化链路。

待处理：

- 前端仍有未接入当前视图的 step store/API/type 定义；由于 `CoreWorkbenchView.vue`、`types/index.ts` 当前存在未提交改动，本切片未纳入前端文件，避免混入无关变更。
- 下一步继续清理 `writer_service.py` 三重投影，或在单独前端切片删除 step store/API 孤儿定义。

### 9.12 执行记录：2026-07-01 第十二切片

已完成：

- 删除后端旧 `/api/sessions/{id}/runtime-events` 和 `/api/sessions/{id}/runtime-events/{event_id}` REST 查询入口。
- 删除只保护旧 REST runtime event 查询表面的 `test_runtime_events.py`。
- Writer member manifest 移除 `runtime_event` capability；`/api` 路由说明不再把 runtime event 暴露为外部产品接口。
- 保留 `WriterRuntimeEvent` model、内部持久化、Core HTTP usage 映射和 App Server runtime bridge；当前它仍是 `writer_service.py -> app_server/runtime_bridge.py -> snapshot` 的内部适配事实源，后续再替换为 Core `RunItemEvent` 输入。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/main.py members/writer/backend/app/routers/core_http.py members/writer/backend/app/services/writer_service.py`
- `rg 'routers\\.runtime_event|runtime_event_router|/runtime-events' members/writer/backend -g '*.py'`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_core_http_writer_unit.py members/writer/backend/tests/test_main_core_app_unit.py -q`

当前收缩：

- 本切片删除旧外部 REST 查询表面约 220 行。
- runtime event 从“外部产品能力 + 内部投影适配”降级为“内部过渡 adapter”，避免 GUI/CLI/REST 又形成一条并行查看主线。

待处理：

- 前端 `step.ts` store 和 runtime event API helper 已在 9.13 删除；后续继续清理更深的 old parser key。
- `runtime_bridge.py` 仍应从 `WriterRuntimeEvent` 输入迁移到 Core `RunItemEvent` 输入，最终删除 Writer-local runtime event 投影层。

### 9.13 执行记录：2026-07-01 第十三切片

已完成：

- 删除前端 `stores/step.ts`，不再保留已经没有后端支撑的 step store。
- 删除前端 `/steps`、`/runtime-events` API helper 和对应 `Step` / `RuntimeEvent` 类型。
- 删除未被引用的 `runtime/runtimeParts.ts`。
- `CoreWorkbenchView.vue` 移除会话切换时清空 step store 的遗留调用；该文件已有未提交的 thinking 控制改动，本切片只暂存 step store 删除 hunk。

验证：

- `rg 'useStepStore|stores/step|listSteps|getStepSummary|getStepDetail|retryStep|getRuntimeEvent|listRuntimeEvents|runtime-events|/steps|StepDetail|StepSummary|RuntimeEvent' members/writer/frontend/src -g '*.ts' -g '*.vue'`
- `npm run build`

当前收缩：

- 本切片删除前端旧 step/runtime REST 孤儿表面约 190 行。
- Writer 前端不再引用后端已删除的 `/steps` 和 `/runtime-events` 接口。

### 9.14 执行记录：2026-07-01 第十四切片

已完成：

- `turn_parser.py` 不再把旧模型输出键 `response`、`thought` 映射为 `text`。
- `turn_parser.py` 不再接受旧 `phase_transition`、`mode_transition` 兼容键；模型输出只认当前 `text`、`next_phase`、`mode`。
- `test_turn_parser.py` 从保护旧兼容改为证明旧键被忽略。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/turn_parser.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_turn_parser.py -q`

当前收缩：

- 本切片移除 Writer 模型输出 parser 的一层历史 schema 兼容，减少未来 prompt/测试继续把旧键当成合法接口的风险。

### 9.15 执行记录：2026-07-01 第十五切片

已完成：

- Writer CLI 不再在 verbose 模式下格式化未知旧 Writer event；未知非 app-server 事件现在被忽略。
- `--verbose` 帮助文案从“thoughts / unknown low-level events”改为“additional app-server details”，避免把旧 writer_thought 一类事件继续作为合法展示层。
- `test_writer_cli.py` 改为证明 `writer_thought` 在默认和 verbose 模式下都不显示；需要原始事件时继续使用 `--raw`。

验证：

- `py -3.14 -m py_compile members/writer/backend/writer_cli/__main__.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_cli.py -q`
- `rg 'writer_thought|unknown low-level|Show thoughts' members/writer/backend/app members/writer/backend/writer_cli -g '*.py'`

当前收缩：

- CLI 展示面不再保留旧 Writer event family 的可见兼容出口，只认 app-server/display 主线。

### 9.16 执行记录：2026-07-01 第十六切片

已完成：

- `runtime_bridge.py` 新增 `persist_run_item_events_as_app_events()`，把 Core `RunItemEvent` 作为 app projection 的主持久化入口。
- `persist_runtime_event_as_app_events()` 降级为过渡 adapter：先把 `WriterRuntimeEvent` 转为 `RunItemEvent`，再走 canonical app projection 入口。
- app projection 的增量内容补写逻辑从 `runtime.part` 特判改为适用于任意 `item/started + content` 的通用规则，为后续 `writer_service.py` 直接发 `RunItemEvent` 留出口。
- `test_writer_app_runtime_bridge.py` 增加直接持久化 Core `RunItemEvent` 的覆盖。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime_bridge.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py -q`

当前收缩：

- projection 主入口从 Writer-local runtime event 转向 Core canonical event；WriterRuntimeEvent 仍保留为内部过渡输入，下一步可改 `writer_service.py` 写入/发布 RunItemEvent。

### 9.17 执行记录：2026-07-01 第十七切片

已完成：

- 删除 `app_server/cleanup.py`，不再在 Writer 启动时归档 `legacy_runtime_part_display_event` 或修复旧 final reply 截断数据。
- 删除 `WriterAppEventArchive` 模型、`writer_app_events_archive` SQLite 建表和索引迁移。
- 删除只保护旧启动清理链路的 `test_writer_app_cleanup.py`。
- `init_db()` 只负责建表和当前 schema 的 additive migration，不再执行历史数据修复副作用。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/database.py members/writer/backend/app/models/app_server.py members/writer/backend/app/models/__init__.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_event_ledger.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_main_core_app_unit.py -q`
- `rg 'app_server\\.cleanup|archive_dirty_app_display_events|repair_truncated_final_reply_events|writer_app_events_archive|WriterAppEventArchive' members/writer/backend -g '*.py'`

当前收缩：

- 启动主路不再背历史数据库兼容壳；旧 app event 修复不再是产品运行时的一部分。

### 9.18 执行记录：2026-07-01 第十八切片

已完成：

- `writer_service.py` 的 app projection 持久化调用从 `persist_runtime_event_as_app_events()` 改为 `persist_run_item_events_as_app_events()`。
- 服务层仍保留 `WriterRuntimeEvent` 表作为过渡审计/旧测试事实，但发布到 app snapshot 前先转换为 Core `RunItemEvent` 列表，再走 canonical projection 入口。
- projection 失败隔离测试改为 mock canonical RunItemEvent 持久化入口，避免继续保护旧 WriterRuntimeEvent persist API。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/writer_service.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py -q`
- `rg 'persist_runtime_event_as_app_events' members/writer/backend/app/services/writer_service.py members/writer/backend/tests/test_writer_service.py`

当前收缩：

- App snapshot 的服务层持久化入口已经转向 Core `RunItemEvent`；维护标注（2026-07-01 9.24）：`writer_service.py` 已停止构造/保存 `WriterRuntimeEvent`，剩余债务转移到 bridge adapter、旧表模型和测试输入。

### 9.19 执行记录：2026-07-01 第十九切片

已完成：

- 删除 `runtime_bridge.py` 中的旧直连 helper `runtime_event_to_app_event_inputs()`。
- `test_writer_app_runtime_bridge.py` 改为在测试内显式组合 `runtime_event_to_run_item_events()` + `run_item_events_to_app_event_inputs()`，不再要求生产代码暴露 runtime event -> app event 的直连 API。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime_bridge.py members/writer/backend/tests/test_writer_app_runtime_bridge.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py -q`
- `rg 'runtime_event_to_app_event_inputs' members/writer/backend/app members/writer/backend/tests -g '*.py'`

当前收缩：

- projection API 只保留 Core `RunItemEvent` -> app event 的主入口；runtime event adapter 仍存在，但不再暴露“直接变 app event”的独立生产 helper。

### 9.20 执行记录：2026-07-01 第二十切片

已完成：

- 删除 `runtime_bridge.py` 中的旧 persist API `persist_runtime_event_as_app_events()`。
- runtime bridge 和 approval 测试改用测试 helper：先把 `WriterRuntimeEvent` 转为 Core `RunItemEvent`，再调用 `persist_run_item_events_as_app_events()`。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime_bridge.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py -q`
- `rg 'persist_runtime_event_as_app_events|runtime_event_to_app_event_inputs' members/writer/backend/app members/writer/backend/tests -g '*.py'`

当前收缩：

- 生产 app projection 持久化 API 已只剩 Core `RunItemEvent` 主入口；runtime event 只能先转 canonical event，不能再直接持久化为 app event。

### 9.21 执行记录：2026-07-01 第二十一切片

已完成：

- `/api/core/usage` 和 `/api/core/usage/total` 不再从 `WriterRuntimeEvent` 统计用量。
- Core HTTP usage 兼容面保留空列表/零用量响应，不再把 runtime event 当作 usage fact source。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/routers/core_http.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_core_http_writer_unit.py -q`

当前收缩：

- `core_http.py` 对 `WriterRuntimeEvent` 的生产依赖只剩 `/api/core/sessions/{id}/events`；usage 已从 runtime event 链路中剥离。

### 9.22 执行记录：2026-07-01 第二十二切片

已完成：

- 删除 Writer Core HTTP 兼容面的 `/api/core/sessions/{session_id}/events` 路由。
- `core_http.py` 删除 `WriterRuntimeEvent` import 和 runtime event -> Core event mapper，完全脱离 runtime event 表。
- Writer 前端 `getCoreEvents()` 保留兼容函数但直接返回空数组，不再请求后端旧 events 路由。
- `test_core_http_writer_unit.py` 增加旧 Core events 路由未挂载断言。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/routers/core_http.py members/writer/backend/tests/test_core_http_writer_unit.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_core_http_writer_unit.py -q`
- `npm run build`（`members/writer/frontend`）
- `rg 'WriterRuntimeEvent|runtime_event|/events|CoreEventRaw|mapEvent' members/writer/backend/app/routers/core_http.py members/writer/frontend/src/api/core.ts members/writer/backend/tests/test_core_http_writer_unit.py`

当前收缩：

- Core HTTP 适配层不再是 runtime event 的消费面；runtime event 剩余生产依赖集中在 `writer_service.py`、`runtime_bridge.py` adapter、session 删除清理、Core HTTP 之外的旧测试。

### 9.23 执行记录：2026-07-01 第二十三切片

已完成：

- `runtime_bridge.py` 新增 `runtime_fact_to_run_item_events()`，支持从运行事实字段直接生成 Core `RunItemEvent`。
- `runtime_event_to_run_item_events()` 降级为薄 adapter，只把 `WriterRuntimeEvent` 字段转给 `runtime_fact_to_run_item_events()`。
- `writer_service.py` 的 app projection 发布路径改为调用 `runtime_fact_to_run_item_events()`，不再直接调用 `runtime_event_to_run_item_events()`。
- `WriterRuntimeEvent` 仍作为过渡审计/旧测试事实落库，下一步再删除表和相关测试保护。维护标注（2026-07-01 9.24）：服务层已停止落库，旧表只剩模型/迁移/删除清理与 bridge adapter 测试输入。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime_bridge.py members/writer/backend/app/services/writer_service.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_service.py -q`

当前收缩：

- app projection 从 service 层看已经是“runtime fact fields -> Core RunItemEvent -> app snapshot”，`WriterRuntimeEvent` 不再是 projection API 的必经输入。维护标注（2026-07-01 9.24）：service 已停止审计落库，只剩 adapter 测试和旧表壳。

### 9.24 执行记录：2026-07-01 第二十四切片

已完成：

- `writer_service.py` 删除 `WriterRuntimeEvent` import，不再构造、`db.add()` 或 `flush()` 旧 runtime event row。
- 服务层改用内存 `RuntimeProjectionFact` 承载投影字段，继续生成 Core `RunItemEvent` 并写入 app ledger/snapshot。
- `test_writer_service.py` 不再查询旧 runtime event 表；服务链路测试改为验证 app ledger、thread snapshot、transcript block 和 session terminal state。
- projection 失败隔离仍保留：app projection 写入失败不会让 Core run 失败，transcript 审计事实仍可恢复。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/writer_service.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`

当前收缩：

- Writer 服务层已经退出旧 runtime event 持久化，`WriterRuntimeEvent` 剩余为模型/迁移、session 删除清理、`runtime_bridge.py` 薄 adapter 和旧 bridge 测试输入。
- 下一步应删除 `runtime_bridge.py` 对 `WriterRuntimeEvent` 的类型/import 依赖，把测试改为纯 `runtime_fact_to_run_item_events()` / `RunItemEvent` contract。

### 9.25 执行记录：2026-07-01 第二十五切片

已完成：

- `runtime_bridge.py` 删除 `WriterRuntimeEvent` import 和 `runtime_event_to_run_item_events()` adapter。
- bridge 内部 helper 类型统一为 `_RuntimeFact`，生产入口只保留 `runtime_fact_to_run_item_events()` 和 `persist_run_item_events_as_app_events()`。
- `test_writer_app_runtime_bridge.py` 从 ORM row fixture 改为纯 runtime fact dict fixture。
- `test_writer_app_approvals.py` 同步改用 runtime fact 投影 helper，不再从测试侧构造旧 runtime event。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime_bridge.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py -q`
- `rg 'WriterRuntimeEvent|runtime_event_to_run_item_events|runtime_event\\(|persist_projection_from_runtime_event|_projection_inputs_from_runtime_event' members/writer/backend/app/app_server/runtime_bridge.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py`

当前收缩：

- app projection 主线已经完全脱离 `WriterRuntimeEvent` 类型；旧 runtime event 剩余为数据库模型/export、数据库 additive migration、session 删除清理。
- 下一步可删除 `models/runtime_event.py`、`models.__init__` export、`database.py` 旧列迁移和 `routers/session.py` 删除清理。

### 9.26 执行记录：2026-07-01 第二十六切片

已完成：

- 删除 `members/writer/backend/app/models/runtime_event.py`。
- `models/__init__.py` 移除 `WriterRuntimeEvent` export。
- `database.py` 移除 `writer_runtime_events.sequence` additive migration。
- `routers/session.py` 删除会话清理时对旧 runtime event 表的 delete。
- 当前 `members/writer/backend/app` 和 `members/writer/backend/tests` 已查不到 `WriterRuntimeEvent` / `writer_runtime_events`。

验证：

- `rg 'WriterRuntimeEvent|writer_runtime_events' members/writer/backend/app members/writer/backend/tests -g '*.py'`
- `py -3.14 -m py_compile members/writer/backend/app/database.py members/writer/backend/app/models/__init__.py members/writer/backend/app/routers/session.py members/writer/backend/app/app_server/runtime_bridge.py members/writer/backend/app/services/writer_service.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_core_http_writer_unit.py members/writer/backend/tests/test_main_core_app_unit.py -q`

当前收缩：

- Writer 旧 runtime event 表/模型/adapter 已退出代码库。
- 剩余 runtime event 词汇主要是服务层内部 runtime fact 元数据键、序列命名和 sub-agent recorder 参数名；后续可在不改变行为的前提下改为 canonical run fact / transcript fact 命名。

### 9.27 执行记录：2026-07-01 第二十七切片

已完成：

- `writer_service.py` 内部 `runtime_event` 元数据键、序列变量和锁命名改为 `runtime_fact`。
- `AgentRuntime` / `ArchitectureAgent` 的内部 recorder 参数名从 `runtime_event_recorder` 改为 `runtime_fact_recorder`。
- 当前 `members/writer/backend/app` 已查不到 `runtime_event` 词汇；测试侧仅保留 `test_legacy_runtime_events_endpoint_is_not_mounted` 用于证明旧路由未挂载。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/writer_service.py members/writer/backend/app/core/writer/agent_runtime.py members/writer/backend/app/core/writer/agents/architecture_agent.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py -q`
- `rg 'runtime_event' members/writer/backend/app -g '*.py'`

当前收缩：

- Writer 后端 app 代码层的旧 runtime event 命名已清空，运行事实命名统一为 runtime fact / RunItemEvent / app snapshot。
- 下一步应继续按复杂度目标拆 `writer_service.py` 的 TranscriptSink / AppProjectionSink，而不是恢复任何旧事件壳。

### 9.28 执行记录：2026-07-01 第二十八切片

已完成：

- 新增 `members/writer/backend/app/services/app_projection_sink.py`，集中负责 Core `RunItemEvent` -> app ledger/snapshot 持久化和 hub 发布。
- `writer_service.py` 删除 projection 专用 session factory、`NullPool`、app hub 和 app projection 持久化细节；服务层只调用 `AppProjectionSink.publish()`。
- projection failure 测试改为 mock sink 持久化入口，继续证明 app projection 失败不会导致 Core run 失败。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/app_projection_sink.py members/writer/backend/app/services/writer_service.py members/writer/backend/app/app_server/runtime_bridge.py members/writer/backend/tests/test_writer_service.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py -q`
- `rg 'projection_session_factory|_persist_app_projection|app_server_hub|NullPool|persist_run_item_events_as_app_events' members/writer/backend/app/services/writer_service.py`

当前收缩：

- App projection 已从 `writer_service.py` 中分离为独立 sink；service 剩余主要混杂点是 transcript sync 和 runtime fact 组装。
- 下一步优先拆 `TranscriptSink` 或把 `RuntimeProjectionFact` 组装下沉到更小的 adapter。

### 9.29 执行记录：2026-07-01 第二十九切片

已完成：

- 新增 `members/writer/backend/app/services/runtime_fact_projection.py`。
- `RuntimeProjectionFact`、runtime fact -> Core `RunItemEvent` 转换入口、同一 `runtime.part` 增量增长缓冲从 `writer_service.py` 抽出。
- `writer_service.py` 删除 `pending_runtime_part_index` 和 `_run_items_from_runtime_fact()` 内联逻辑，同一 part 增长后复用首个 fact id 的规则由 `RuntimeFactProjectionBuffer` 负责。
- 新增 `test_runtime_fact_projection.py`，直接保护 part 增长复用 fact id 并更新内容的 contract。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/runtime_fact_projection.py members/writer/backend/app/services/writer_service.py members/writer/backend/tests/test_runtime_fact_projection.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_runtime_fact_projection.py members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py -q`
- `rg 'pending_runtime_part_index|_run_items_from_runtime_fact|runtime_fact_to_run_item_events' members/writer/backend/app/services/writer_service.py members/writer/backend/app/services/runtime_fact_projection.py`

当前收缩：

- runtime fact projection 知识已离开 `writer_service.py`；service 剩余主要职责混杂点是 transcript sync、approval 继续逻辑和 Core run orchestration。
- 下一步优先拆 `TranscriptSink`，把 transcript block 写入规则从 service 中拿走。

### 9.30 执行记录：2026-07-01 第三十切片

已完成：

- 新增 `members/writer/backend/app/services/runtime_fact_helpers.py`。
- `event_model_call_id`、tool call id 规范化、tool args 提取、usage token 解析、visible runtime part content 等纯解析规则从 `writer_service.py` 迁出。
- 新增 `test_runtime_fact_helpers.py`，直接保护 run/response id、tool id、usage、visible content contract。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/runtime_fact_helpers.py members/writer/backend/app/services/writer_service.py members/writer/backend/tests/test_runtime_fact_helpers.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_runtime_fact_helpers.py members/writer/backend/tests/test_runtime_fact_projection.py members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py -q`
- `rg 'def _event_|def _tool_|def _visible_runtime_part_content|def _usage_tokens' members/writer/backend/app/services/writer_service.py`

当前收缩：

- transcript 同步前置的纯解析规则已独立，`writer_service.py` 内剩余是实际 DB 写入流程。
- 下一步可围绕 `TranscriptSink` 迁移 `_sync_transcript_fact()` 和 `_close_running_model_calls()`。

### 9.31 执行记录：2026-07-01 第三十一切片

已完成：

- 新增 `members/writer/backend/app/services/runtime_transcript_sink.py`。
- `_sync_transcript_fact()`、latest model call fallback、usage 写入、running model call 收尾从 `writer_service.py` 迁出为 `RuntimeTranscriptSink`。
- `writer_service.py` 只保留 `transcript_sink.sync_fact()` 和 `transcript_sink.latest_model_call()` 调用，不再内联 runtime fact -> transcript block 的写入分支。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/runtime_transcript_sink.py members/writer/backend/app/services/writer_service.py members/writer/backend/app/services/runtime_fact_helpers.py members/writer/backend/app/services/runtime_fact_projection.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_runtime_fact_helpers.py members/writer/backend/tests/test_runtime_fact_projection.py members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py -q`
- `rg 'def _sync_transcript_fact|def _latest_transcript_model_call|def _apply_usage|def _close_running_model_calls|ensure_model_call|event_model_call_id|tool_call_id_from_payload|visible_runtime_part_content|usage_tokens' members/writer/backend/app/services/writer_service.py`

当前收缩：

- Transcript 写入主规则已离开 `writer_service.py`；service 剩余大块主要是 Core run orchestration、final answer/session terminal 写入和 approval continuation。
- 下一步可继续拆 final answer/session terminal sink，或先审查 `writer_service.py` 当前行数与剩余职责。

### 9.32 执行记录：2026-07-01 第三十二切片

已完成：

- 新增 `members/writer/backend/app/services/runtime_finalization_sink.py`。
- 成功/失败终局判断、final reply block 复用、fallback 交付回复、turn terminal、queued guidance 过期和 assistant message 写入从 `writer_service.py` 迁出为 `RuntimeFinalizationSink`。
- `writer_service.py` 删除终局持久化内联分支和 `_fallback_delivery_answer()`，Core run 结束后只负责编排 `summarize_core_kernel_result()`、调用 finalization sink、记录 metrics/checkpoint/review。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/runtime_finalization_sink.py members/writer/backend/app/services/writer_service.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_runtime_fact_helpers.py members/writer/backend/tests/test_runtime_fact_projection.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py -q`
- `rg '_find_final_reply_block|_fallback_delivery_answer|expire_guidance_for_turn|WriterTranscriptModelCall' members/writer/backend/app/services/writer_service.py`

当前收缩：

- `writer_service.py` 降到 1,374 行；终局持久化规则离开主编排文件。
- Writer 后端运行主线当前已分出 AppProjectionSink、RuntimeFactProjectionBuffer、RuntimeTranscriptSink、RuntimeFinalizationSink；service 剩余大块主要是 Core run orchestration、approval continuation、session/checkpoint/review 编排。
- 下一步优先审查 approval continuation 是否能并入同一运行主线，或抽出 RuntimeRunner 让 service 只保留入口级编排。

### 9.33 执行记录：2026-07-01 第三十三切片

已完成：

- `writer_service.py` 新增 `_mark_session_executing()` 和 `_apply_kernel_summary_to_session()`，普通 send、guidance continuation、approved-tool continuation 共用同一套 session status / phase 收尾规则。
- 删除三处重复的 `decision -> session.status/session.phase` 分支，避免后续 Core decision 语义调整时在多处漏改。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/writer_service.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `rg 'session\.status = "active"|session\.status = "failed" if|if decision == "done"|_mark_session_executing|_apply_kernel_summary_to_session' members/writer/backend/app/services/writer_service.py`

当前收缩：

- `writer_service.py` 降到 1,355 行；重复 session terminal mapping 已收为一个内部规则。
- 下一步仍是 approval continuation：优先把 waiting request resolve、approved tool execution、continuation prompt 组装拆出，或先抽 RuntimeRunner。

### 9.34 执行记录：2026-07-01 第三十四切片

已完成：

- 新增 `members/writer/backend/app/services/runtime_approved_tool.py`。
- 已批准 waiting request 的工具执行、tool_call/tool_result transcript 写入、artifact 记录和 producer 收尾从 `writer_service.py` 迁出。
- `writer_service.py` 在 approve 分支只保留 request 分类、失败/继续决策和 Core continuation 编排，不再内联 `ReadWriteToolExecutor` / `ToolCall` 执行细节。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/runtime_approved_tool.py members/writer/backend/app/services/writer_service.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_approvals.py -q`
- `rg 'ReadWriteToolExecutor|ToolCall|record_artifacts|close_active_producers' members/writer/backend/app/services/writer_service.py members/writer/backend/app/services/runtime_approved_tool.py`

当前收缩：

- `writer_service.py` 降到 1,266 行；approval continuation 中的“批准后工具执行”已成为独立边界。
- 下一步可继续拆 waiting request action normalize / response persistence / continuation prompt，或把 run continuation 抽成 RuntimeRunner。

### 9.35 执行记录：2026-07-01 第三十五切片

已完成：

- 新增 `members/writer/backend/app/services/runtime_waiting_request.py`。
- waiting request 的 action 归一化、guidance 校验、response block 持久化和 Core state pending approval 清理从 `writer_service.py` 迁出。
- `writer_service.py` 的 `respond_waiting_request()` 只保留业务分支：deny、guide continuation、approved tool continuation。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/runtime_waiting_request.py members/writer/backend/app/services/writer_service.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_app_approvals.py -q`
- `rg 'upsert_block|utc_now|pending_approval|pending_waiting_request|Unsupported waiting request decision|Guidance decision requires|resolve_waiting_request_response' members/writer/backend/app/services/writer_service.py members/writer/backend/app/services/runtime_waiting_request.py`

当前收缩：

- `writer_service.py` 降到 1,237 行；waiting request persistence 已成为独立边界。
- 下一步可抽 continuation prompt / RuntimeRunner，或者继续把 session/checkpoint/review 编排分离。

### 9.36 执行记录：2026-07-01 第三十六切片

已完成：

- 新增 `members/writer/backend/app/services/runtime_continuation_prompts.py`。
- guidance continuation 和 approved-tool continuation 的 prompt 文本从 `writer_service.py` 迁出。
- `writer_service.py` 的 waiting request 分支只负责选择 continuation 类型并调用 Core run，不再内联中文 prompt 拼接。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/runtime_continuation_prompts.py members/writer/backend/app/services/writer_service.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_app_approvals.py -q`
- `rg 'json|继续完成同一个用户任务|guidance_continuation_prompt|approved_tool_continuation_prompt' members/writer/backend/app/services/writer_service.py members/writer/backend/app/services/runtime_continuation_prompts.py`

当前收缩：

- `writer_service.py` 降到 1,232 行；waiting request 的执行、持久化、continuation prompt 已拆成独立边界。
- 下一步优先抽 RuntimeRunner 或 session/checkpoint/review 编排，继续让 service 收敛为入口层。

### 9.37 执行记录：2026-07-01 第三十七切片

已完成：

- 新增 `members/writer/backend/app/services/commit_review_service.py`。
- Core 工具结果中的 `request_commit_review` 提取、diff/numstat 收集、untracked file 统计、pending commit review 写入从 `writer_service.py` 迁出。
- `writer_service.py` 在 Core run 后只调用 `commit_review_service.latest_request()` 和 `persist_request()`，不再内联 commit review 的 Git diff 细节。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/commit_review_service.py members/writer/backend/app/services/writer_service.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `rg 'GitCommandResult|_collect_review_changes|_persist_commit_review_request|_latest_commit_review_request|_untracked_stats|pending_commit_review|WriterCommitReviewService|commit_review_service' members/writer/backend/app/services/writer_service.py members/writer/backend/app/services/commit_review_service.py`

当前收缩：

- `writer_service.py` 降到 1,093 行；commit-review 产品编排已离开主 runtime service。
- 下一步优先抽 checkpoint/session orchestration 或 RuntimeRunner。

### 9.38 执行记录：2026-07-01 第三十八切片

已完成：

- 新增 `members/writer/backend/app/services/checkpoint_service.py`。
- Git repo ensure、dirty 检查、checkpoint 写入、session runtime_state/git_state 更新从 `writer_service.py` 迁出。
- `commit_review_service.py` 改为复用 `checkpoint_service.ensure_repo`，避免在主 runtime service 中保留重复 Git repo 初始化逻辑。
- `writer_service.py` 的发送前/运行后自动存档只调用 `checkpoint_service.checkpoint_if_dirty()`。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/checkpoint_service.py members/writer/backend/app/services/commit_review_service.py members/writer/backend/app/services/writer_service.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `rg '_ensure_work_root_repo|_record_git_checkpoint|_checkpoint_if_dirty|checkpoint_service|WriterCheckpointService|_runtime_state_dict|_git_state_dict|git_manager|WriterGitManager' members/writer/backend/app/services/writer_service.py members/writer/backend/app/services/checkpoint_service.py members/writer/backend/app/services/commit_review_service.py`

当前收缩：

- `writer_service.py` 降到 1,039 行；Git checkpoint 产品编排已离开主 runtime service。
- 下一步优先抽 Core run orchestration / RuntimeRunner，让 `writer_service.py` 更接近入口层。

### 9.39 执行记录：2026-07-01 第三十九切片

已完成：

- 新增 `members/writer/backend/app/services/runtime_fact_recorder.py`。
- Core `CoreEvent` -> runtime fact -> transcript sink -> Core `RunItemEvent` -> app snapshot projection 的记录链路从 `writer_service.py` 迁出。
- runtime fact sequence、reply delta 特判、part 增长缓冲、terminal CoreEvent 标记和 payload preview 裁剪由 `RuntimeFactRecorder` 负责。
- `writer_service.py` 只把 `runtime_recorder.record_core_event` 作为 Core loop callback，并在 metrics/terminal fallback 处调用 `runtime_recorder.record()`。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/runtime_fact_recorder.py members/writer/backend/app/services/writer_service.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py -q`
- `rg '_runtime_group_from_core_event|_runtime_summary_from_core_event|_runtime_payload_preview|RUNTIME_VISIBLE_TEXT_CHARS|RUNTIME_SUMMARY_CHARS|RuntimeFactRecorder|runtime_group_from_core_event|record_core_event|runtime_recorder' members/writer/backend/app/services/writer_service.py members/writer/backend/app/services/runtime_fact_recorder.py`

当前收缩：

- `writer_service.py` 降到 855 行；runtime fact / transcript / app projection 记录链路已离开入口服务。
- 下一步可抽 Core run orchestration / RuntimeRunner，或先复核 Writer backend runtime 总量和剩余重复面。

### 9.40 执行记录：2026-07-01 第四十切片

已完成：

- 新增 `members/writer/backend/app/services/runtime_input_context.py`。
- queued guidance 合并、当前 user message 去重、最近 user/assistant history 加载从 `writer_service.py` 迁出。
- `writer_service.py` 的 Core run 入口只接收准备好的 `goal` 和 `history`，不再内联上下文拼接规则。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/runtime_input_context.py members/writer/backend/app/services/writer_service.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py -q`
- `rg 'consume_guidance_for_turn|guidance_items|Load conversation history|raw_user_message.*history|prepare_runtime_input_context|RuntimeInputContext' members/writer/backend/app/services/writer_service.py members/writer/backend/app/services/runtime_input_context.py`

当前收缩：

- `writer_service.py` 降到 816 行；本轮输入上下文准备已成为独立边界。
- 下一步优先抽 Core run orchestration / RuntimeRunner，使 service 只保留会话入口和产品级收尾。

### 9.41 执行记录：2026-07-01 第四十一切片

已完成：

- 新增 `members/writer/backend/app/services/runtime_runner.py`。
- Core run 生命周期从 `writer_service.py` 迁出：启动 runtime recorder、调用 Core kernel、失败记录、finalization、metrics、运行后 checkpoint、commit review request、terminal fallback、prewarm 调度。
- `writer_service.py` 保留 `_run_core_kernel_path()` 薄代理，继续兼容现有 send / waiting-request continuation 调用点。
- runner 通过构造参数注入 `run_core_kernel`、summary、prewarm 和 runtime registry，保持现有测试替换点有效。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/runtime_runner.py members/writer/backend/app/services/runtime_input_context.py members/writer/backend/app/services/writer_service.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `rg 'RuntimeFactRecorder|RuntimeFinalizationSink|runtime_group_from_core_event|prepare_runtime_input_context|runtime_recorder|terminal_fallback|summarize_core_kernel_result|schedule_writer_startup_prewarm' members/writer/backend/app/services/writer_service.py members/writer/backend/app/services/runtime_runner.py`

当前收缩：

- `writer_service.py` 降到 685 行；Core run orchestration 已离开入口服务。
- 下一步继续拆 session/message lifecycle，或把 runner 内的通用 event/snapshot contract 下沉 Core。

### 9.42 执行记录：2026-07-01 第四十二切片

已完成：

- Writer App Server snapshot 新增 `core` 子树，使用 Core `lamtools_core.snapshot.apply_run_item_event()` 生成 canonical runtime snapshot。
- `persist_run_item_events_as_app_events()` 在落库 AppEvent 时附加内部 `_core_run_item_event`，普通 `run_item_event_to_app_event_inputs()` / `run_item_events_to_app_event_inputs()` 仍保持纯 AppEvent 转换，避免污染离线转换接口。
- Writer reducer 消费 `_core_run_item_event` 后同步更新 `snapshot.core`，并阻止该内部字段进入现有 `items`。
- 现有 Writer `items/turns/queue/requests` snapshot 保持不变，为后续 UI/store 切到 canonical snapshot 提供可验证数据源。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime_bridge.py members/writer/backend/app/app_server/reducer.py`
- `py -3.14 -m pytest tests/test_run_item_snapshot.py -q`（工作目录：`core/`）
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_event_ledger.py members/writer/backend/tests/test_writer_app_approvals.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`

当前收缩：

- Writer 已有产品 snapshot 旁边出现由 Core reducer 生成的 canonical runtime snapshot。
- 下一步可以把前端 selectors / ChatThread 的运行态读取逐步切到 `snapshot.core`，或把 App Server event ledger 改成直接存 `RunItemEvent`。

### 9.43 执行记录：2026-07-01 第四十三切片

已完成：

- `load_snapshot()` 对旧形状 `writer_thread_snapshots` 做当前形状归一化，确保返回值始终包含 `core` canonical snapshot 子树。
- 新增旧 snapshot 形状回归测试，证明没有 `_core_run_item_event` 的历史 snapshot 也能被当前读取面稳定消费。
- 该处理只补齐当前 snapshot 结构，不恢复旧 Writer event 族或启动期数据修复链路。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/snapshot.py members/writer/backend/tests/test_writer_app_event_ledger.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_event_ledger.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py -q`

当前收缩：

- `snapshot.core` 成为 App Server 读取面的稳定字段，后续 UI/store 不需要针对新旧 snapshot 形状分支。

### 9.44 执行记录：2026-07-01 第四十四切片

已完成：

- Writer 前端 `WriterAppSnapshot` 类型新增 `core` canonical snapshot 子树。
- `hydrateSnapshot()` 对缺失 `core` 的 snapshot 补默认结构，与后端 `load_snapshot()` 归一化保持一致。
- `selectChatMessages()` 对同一 `item_id` 优先使用 `snapshot.core.items`，再回退外层 Writer AppEvent projection；用户消息、queue、request 状态仍由外层产品 snapshot 提供。
- `selectLatestTurnStatus()` 优先使用非 idle 的 `snapshot.core.status`，让运行态逐步来自 Core SnapshotReducer。
- 新增 selector 测试：外层 item 是旧/截断内容时，渲染使用 canonical core item 的完整内容和 usage metrics。

验证：

- `npm run test -- --test-name-pattern=selectors`（工作目录：`members/writer/frontend`）
- `npx vue-tsc -b --pretty false`（工作目录：`members/writer/frontend`）
- `npm run test`（工作目录：`members/writer/frontend`）

当前收缩：

- 前端运行态展示开始消费 `snapshot.core`，外层 Writer AppEvent projection 从唯一显示事实源降级为产品事件和回退层。
- 下一步可以继续把 ChatThread 运行 part 语义从 Writer 外层 `items` 迁到 canonical core item，或让 App Server ledger 直接保存 RunItemEvent。

### 9.45 执行记录：2026-07-01 第四十五切片

已完成：

- `selectChatMessages()` 的渲染顺序从单一外层 `state.item_order` 改为外层产品 `item_order` + `snapshot.core.item_order` 去重合并。
- canonical runtime item 即使不存在于外层 AppEvent projection 的 `item_order`，也能进入前端消息流。
- 保留外层 `item_order` 在前，继续承载用户消息和产品事件顺序；core order 作为运行事实补充来源。
- 新增 selector 测试覆盖“外层只有用户消息，core 里有 agent message”的过渡形态。

验证：

- `npm run test -- --test-name-pattern=selectors`（工作目录：`members/writer/frontend`）
- `npx vue-tsc -b --pretty false`（工作目录：`members/writer/frontend`）
- `npm run test`（工作目录：`members/writer/frontend`）

当前收缩：

- 前端不再要求 runtime item 必须先被外层 Writer AppEvent projection 写入 `item_order` 才可显示。
- 后续可以继续减少 `runtime_bridge.py` 生成的外层 item projection，保留 AppEvent 只承载产品事件和兼容回放。

### 9.46 执行记录：2026-07-01 第四十六切片

已完成：

- `selectChatMessages()` 的 artifact 归属从单一外层 `state.artifacts` 扩展为外层产品 artifacts + `snapshot.core.artifacts` 去重合并。
- canonical core artifact 即使没有被外层 AppEvent projection 重写，也能挂到对应 process/tool item 上进入前端消息流。
- 去重键优先使用 `artifact_id`，其次使用 `id`，避免过渡期外层 projection 和 core snapshot 同时存在时重复显示。
- 新增 selector 测试覆盖“artifact 只存在于 `snapshot.core.artifacts`”的过渡形态。

验证：

- `npm run test -- --test-name-pattern=selectors`（工作目录：`members/writer/frontend`）
- `npx vue-tsc -b --pretty false`（工作目录：`members/writer/frontend`）
- `npm run test`（工作目录：`members/writer/frontend`）

当前收缩：

- 前端运行事实源继续向 `snapshot.core` 收敛，外层 Writer AppEvent projection 对 runtime artifacts 的必要性降低。
- 下一步可以减少 `runtime_bridge.py` 中为 UI 重建 artifacts/tool result 的外层投影，或把通用 selector 逻辑上移到 Core UI。

### 9.47 执行记录：2026-07-01 第四十七切片

已完成：

- Core `SnapshotReducer` 现在会把任何 `RunItemEvent.artifacts` 写入 canonical `snapshot.artifacts`，不再只有 `kind == artifact` 才进入顶层 artifact 索引。
- Writer `runtime_bridge.py` 删除 `tool_result -> artifact/created` 外层 AppEvent 投影。
- Writer artifact 仍直接写入 `WriterArtifact` 表，保留 `artifact/read` 与 `artifact/open` 产品能力。
- 显式 `artifact` 事件路径暂时保留，避免一次性牵动非工具结果 artifact 的历史入口。
- 回归测试改为验证工具结果 artifact 出现在 `snapshot.core.artifacts`，外层 `snapshot.artifacts` 不再被该路径填充。

验证：

- `py -3.14 -m py_compile core/src/lamtools_core/snapshot/__init__.py members/writer/backend/app/app_server/runtime_bridge.py`
- `py -3.14 -m pytest tests/test_run_item_snapshot.py -q`（工作目录：`core`）
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_artifacts.py -q`

当前收缩：

- 工具结果 artifact 的显示事实源已回到 Core snapshot，Writer 不再用外层 AppEvent 复制一份 `artifact/created` 事件。
- 下一步可以继续处理 `tool_result` 的 `item/delta` / `item/completed` 外层投影，或把显式 `artifact` 事件收敛为 Core artifact 持久化路径。

### 9.48 执行记录：2026-07-01 第四十八切片

已完成：

- Writer `runtime_bridge.py` 删除 `tool_result -> item/delta` 外层文本投影。
- `tool_result -> item/completed` 暂时保留为当前 AppEvent ledger 承载 `_core_run_item_event` 的最小事件，直到 ledger 可直接保存 `RunItemEvent`。
- Core snapshot 继续从 `RunItemEvent.payload.delta` 累积工具结果文本，前端 selector 已验证可从 canonical core item 渲染工具结果 content。
- artifact 与工具结果文本两类运行事实都不再需要外层 Writer projection 复制。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime_bridge.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_event_ledger.py -q`
- `npm run test -- --test-name-pattern=selectors`（工作目录：`members/writer/frontend`）

当前收缩：

- `runtime_bridge.py` 对工具结果只保留当前 ledger 必需的最小 carrier event；UI 事实继续由 `snapshot.core.items` 和 `snapshot.core.artifacts` 提供。
- 下一步的真正删除点是让 App Server ledger 直接保存/回放 `RunItemEvent`，届时 `tool_result -> item/completed` carrier 也可以退出。

### 9.49 执行记录：2026-07-01 第四十九切片

已完成：

- Writer App Server 协议新增 `core/runItem` ledger method，用现有 `writer_app_events` 表直接保存 `RunItemEvent.to_dict()`，不新增表、不新增迁移。
- `reducer.apply_event()` 识别 `core/runItem` 后只更新 `snapshot.core`，不再写外层 Writer `items/item_order/artifacts`。
- `runtime_bridge.py` 将 `tool_result` 从 `item/completed` carrier event 切换为直接 `core/runItem` 持久化。
- `run_item_event_to_app_event_inputs()` 对 `tool_result` 不再生成外层 AppEvent，避免保留一条已经不是主线的转换路径。
- Writer artifact 读/打开能力继续通过 `WriterArtifact` 表保留，显示事实来自 `snapshot.core.items` / `snapshot.core.artifacts`。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/protocol.py members/writer/backend/app/app_server/ledger.py members/writer/backend/app/app_server/reducer.py members/writer/backend/app/app_server/runtime_bridge.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_event_ledger.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `npm run test -- --test-name-pattern=selectors`（工作目录：`members/writer/frontend`）
- `npm run test`（工作目录：`members/writer/frontend`）

当前收缩：

- `tool_result` 已成为第一类直接落地的 Core runtime fact，不再依赖 Writer AppEvent carrier。
- 后续可以按同样模式迁移 `usage`、`tool_call`、`message/thinking`；审批仍需保留产品 request 表和用户交互语义，适合最后处理。

### 9.50 执行记录：2026-07-01 第五十切片

已完成：

- Core `SnapshotReducer` 支持 `usage` 事件的 replace 语义：`payload.replace == true` 时用最终指标替换增量指标，而不是继续累加。
- Writer `runtime_bridge.py` 将 `usage` 从外层 `turn/metrics` AppEvent 投影切换为直接 `core/runItem` 持久化。
- `run_item_event_to_app_event_inputs()` 对 `usage` 不再生成外层 AppEvent。
- 前端 selector 已验证在外层 turn 没有 `runtime_metrics` 时，仍能从 `snapshot.core.turns[turn_id].usage` 渲染过程指标。
- 当前代码中 `turn/metrics` 只剩 reducer 对旧事件的读取兼容，不再是 runtime_bridge 生成路径。

验证：

- `py -3.14 -m pytest tests/test_run_item_snapshot.py -q`（工作目录：`core`）
- `py -3.14 -m py_compile core/src/lamtools_core/snapshot/__init__.py members/writer/backend/app/app_server/runtime_bridge.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_event_ledger.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_event_ledger.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_service.py -q`
- `npm run test -- --test-name-pattern=selectors`（工作目录：`members/writer/frontend`）
- `npm run test`（工作目录：`members/writer/frontend`）

当前收缩：

- `tool_result` 和 `usage` 两类运行事实已直接落 Core ledger / Core snapshot。
- 下一步可以迁移 `tool_call`，让工具开始事件也不再生成外层 `item/started`，前提是确认审批卡和工具展示都能从 `snapshot.core` 或产品 request 表获得所需字段。

### 9.51 执行记录：2026-07-01 第五十一切片

已完成：

- Writer `runtime_bridge.py` 将 `tool_call` 从外层 `item/started` AppEvent 投影切换为直接 `core/runItem` 持久化。
- `run_item_event_to_app_event_inputs()` 对 `tool_call` 不再生成外层 AppEvent。
- 前端 selector 已验证在外层 `items` 为空时，仍能从 `snapshot.core.items` 渲染 canonical tool call。
- 服务层回归已改为验证 `tool_call` / `tool_result` 都以 `core/runItem` 出现在 App Server ledger 中。
- 审批请求仍保留外层 `item/started + item/requestApproval`，因为它还负责产品 request 表和用户交互，不和普通工具开始事件混删。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime_bridge.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_event_ledger.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `npm run test -- --test-name-pattern=selectors`（工作目录：`members/writer/frontend`）
- `npm run test`（工作目录：`members/writer/frontend`）

当前收缩：

- `tool_call`、`tool_result`、`usage` 三类运行事实已直接落 Core ledger / Core snapshot。
- 下一步可以迁移 `message` / `thinking`，这会删除大量 `item/started` / `item/delta` 外层文本投影，但需要先确认增量文本、最终文本和前端滚动行为全部由 `snapshot.core` 承载。

### 9.52 执行记录：2026-07-01 第五十二切片

已完成：

- Writer `runtime_bridge.py` 将 `message` / `thinking` 从外层 `item/started` / `item/delta` / `item/completed` 文本投影切换为直接 `core/runItem` 持久化。
- 文本类 `RunItemEvent.event_id` 改为内容敏感：`runtime.reply_delta` 和 `runtime.part` 会用内容哈希生成稳定事件 id，避免同一 runtime id 的增长内容被 Core snapshot 去重吞掉。
- `run_item_event_to_app_event_inputs()` 对 `message` / `thinking` 不再生成外层 AppEvent。
- 前端 selector 已验证在外层没有 agent/reasoning item 时，仍能从 `snapshot.core.items` 渲染模型回复和思考块。
- 服务层回归已改为从 `snapshot.core.items` 验证 reasoning 分片隔离。
- 删除已无调用的 `_stable_item_started_event_id()`。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime_bridge.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_event_ledger.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `npm run test -- --test-name-pattern=selectors`（工作目录：`members/writer/frontend`）
- `npm run test`（工作目录：`members/writer/frontend`）

当前收缩：

- `message`、`thinking`、`tool_call`、`tool_result`、`usage` 五类运行事实已直接落 Core ledger / Core snapshot。
- `runtime_bridge.py` 剩余主要外层投影是 approval request、turn/status、artifact 显式事件和旧 AppEvent replay 兼容；下一步适合拆分 approval 与 status，避免误伤产品交互。

### 9.53 执行记录：2026-07-01 第五十三切片

已完成：

- Writer `runtime_bridge.py` 将 `status` 从外层 `turn/completed` / `thread/status/changed` AppEvent 投影切换为直接 `core/runItem` 持久化。
- `runtime.done` / `runtime.failed` 仍生成 `RunItemEvent(kind="status")`，但不再生成 Writer 外层完成事件；完成/失败状态由 Core SnapshotReducer 写入 `snapshot.core.status` 与 `snapshot.core.turns[turn_id].status`。
- 服务层回归已从 `turn/completed` 旧事件断言改为验证 `core/runItem` status 事实和 Core snapshot 状态。
- 前端 selector 补充验证：外层 snapshot 仍是 running 时，非 idle 的 `snapshot.core.status` 会接管最新状态。
- 审批请求仍保留外层 `item/started + item/requestApproval`，因为它负责产品 request 表和用户交互，不在本切片混删。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime_bridge.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_event_ledger.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest core/tests/test_run_item_snapshot.py -q`
- `npm run test -- --test-name-pattern=selectors`（工作目录：`members/writer/frontend`）
- `npm run test`（工作目录：`members/writer/frontend`）
- `npx vue-tsc -b --pretty false`（工作目录：`members/writer/frontend`）

当前收缩：

- `message`、`thinking`、`tool_call`、`tool_result`、`usage`、`status` 六类运行事实已直接落 Core ledger / Core snapshot。
- `runtime_bridge.py` 剩余主要外层投影集中在 approval request、artifact 显式事件、error 以及旧 AppEvent replay 兼容；下一步应优先拆 approval 的产品交互副作用和 Core request 状态，避免继续让普通运行事实绕回 Writer 外层 ledger。

### 9.54 执行记录：2026-07-01 第五十四切片

已完成：

- Writer `runtime_bridge.py` 将 `approval_request` 从外层 `item/started + item/requestApproval` 投影切换为直接 `core/runItem` 持久化。
- Approval request 仍创建 `WriterAppRequest` 行，用于 Writer 的用户响应、继续执行和历史等待门；但显示状态和 request fact 已进入 `snapshot.core.requests`。
- `respond_to_approval()` 保留外层 `serverRequest/resolved` 作为用户操作回执，同时在 payload 中携带 Core `approval_response`，让 Core SnapshotReducer 同步关闭 `snapshot.core.requests[request_id]`。
- `appServer/selectors.ts` 的审批卡合并读取 `snapshot.core.requests` 与外层 `requests`，支持 Core-only request 显示。
- 删除 `runtime_bridge.py` 中已无入口的旧 `item/started` 文本增长转换和 `item/requestApproval` request-row 创建分支。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime_bridge.py members/writer/backend/app/app_server/approvals.py members/writer/backend/app/app_server/reducer.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_event_ledger.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `npm run test -- --test-name-pattern=selectors`（工作目录：`members/writer/frontend`）

当前收缩：

- `message`、`thinking`、`tool_call`、`tool_result`、`usage`、`status`、`approval_request` 七类运行事实已直接落 Core ledger / Core snapshot。
- `runtime_bridge.py` 剩余主要外层投影是显式 artifact、error 以及旧 AppEvent replay 兼容；审批响应仍保留外层回执，但 Core request 状态不再依赖外层 request 投影。

### 9.55 执行记录：2026-07-01 第五十五切片

已完成：

- Writer App Server runtime fallback 失败路径不再直接写外层 `error` / `turn/completed`，改为写 Core `RunItemEvent(kind="error")` 与 `RunItemEvent(kind="status")`。
- 用户中断导致的 runtime 取消现在以 `core/runItem` status failed 落入 `snapshot.core.status`，不再生成外层 `turn/completed`。
- 后台异常仍保留错误信息，但错误事实进入 Core reducer；外层只负责发布 ledger envelope。
- 队列分发 `dispatch_next_queue_item()` 的完成态判断改为优先读取 `snapshot.core.status`，避免 runtime terminal status 迁到 Core 后排队任务不继续。
- 新增回归：Core completed status 可以触发 FIFO queue dispatch；中断测试改为验证 `core/runItem` status failed。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/connection.py members/writer/backend/app/app_server/queue.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_queue.py -q`

当前收缩：

- 运行主线的 completion / failure / cancellation 已开始从 App Server 外层 turn event 收敛到 Core status。
- 仍保留外层 `turn/accepted` / `turn/started` / `turn/interrupted` / queue event，因为它们是 Writer App Server 用户输入和队列操作事实，不是 LLM runtime 输出事实。

### 9.56 执行记录：2026-07-01 第五十六切片

已完成：

- Writer `runtime_bridge.py` 将显式 `RunItemEvent(kind="artifact")` 从外层 `artifact/created` 投影切换为直接 `core/runItem` 持久化。
- `RunItemEvent(kind="artifact")` 的 payload-only artifact 也会写入 `WriterArtifact` 表，继续支持 Writer 的 artifact read/open 产品能力。
- 删除 `runtime_bridge.py` 中已无入口的 `artifact/created` carrier 后处理分支。
- 新增回归：显式 artifact 只更新 `snapshot.core.artifacts`，外层 `snapshot.artifacts` 保持为空，同时 `WriterArtifact` 表仍保存路径。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime_bridge.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_artifacts.py -q`

当前收缩：

- `message`、`thinking`、`tool_call`、`tool_result`、`usage`、`status`、`approval_request`、`artifact` 八类运行事实已直接落 Core ledger / Core snapshot。
- `runtime_bridge.py` 剩余主要外层 runtime 投影只剩 `error` carrier 与旧 AppEvent replay 兼容；下一步适合把普通 `error` 也直接切到 `core/runItem`。

### 9.57 执行记录：2026-07-01 第五十七切片

已完成：

- Writer `runtime_bridge.py` 将 `RunItemEvent(kind="error")` 从外层 `error` carrier 切换为直接 `core/runItem` 持久化。
- `persist_run_item_events_as_app_events()` 简化为所有 `RunItemEvent` 统一 append `core/runItem`，只在写入前保留 `WriterArtifact` / `WriterAppRequest` 两类产品副作用。
- 删除旧 `run_item_event_to_app_event_inputs()`、`run_item_events_to_app_event_inputs()`、`_attach_core_run_item_event()` 和 `_persist_run_item_app_event()`，runtime_bridge 不再负责把 Core fact 翻译回 Writer AppEvent carrier。
- 新增回归：显式 error 只更新 `snapshot.core.last_error` / `snapshot.core.items`，外层 `snapshot.last_error` 和 `snapshot.items` 保持为空。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime_bridge.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py -q`

当前收缩：

- `runtime_bridge.py` 已从“Core fact -> Writer AppEvent carrier -> Core reducer”简化为“Core fact -> core/runItem -> Core reducer”。
- 剩余外层 AppEvents 主要是用户输入、队列、审批响应、手动中断等 Writer App Server 产品操作事实；不再承担 LLM runtime 输出事实的主线投影。

### 9.58 执行记录：2026-07-01 第五十八切片

已完成：

- `respond_to_approval()` 不再把 Core `approval_response` 嵌入外层 `serverRequest/resolved` payload 的 `_core_run_item_event`。
- 审批响应现在先写独立 `core/runItem` approval_response，并应用 Core SnapshotReducer；再写外层 `serverRequest/resolved` 作为 Writer App Server 用户操作回执。
- Writer reducer 删除“任意非 Core AppEvent payload 里偷带 `_core_run_item_event` 就更新 `snapshot.core`”的兼容路径。
- 外层 `serverRequest/resolved` payload 不再携带内部 Core 字段；外层 `requests` 只保留产品回执状态，Core request 状态由独立 `core/runItem` 驱动。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/approvals.py members/writer/backend/app/app_server/reducer.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_server_protocol.py -q`

当前收缩：

- `_core_run_item_event` 已退出当前后端 App Server 主线代码；Core 状态只由 `core/runItem` ledger event 驱动。
- 外层 AppEvent 仍保留用户输入、队列、审批响应、手动中断等产品操作事实。

### 9.59 执行记录：2026-07-01 第五十九切片

已完成：

- Writer App Server reducer 删除已无生产写入入口的旧 runtime carrier 归约：`thread/status/changed`、`turn/metrics`、`item/delta`、`artifact/created`。
- 删除 `turn/metrics` 专用指标合并 helper；usage 指标事实已经由 Core `RunItemEvent(kind="usage")` 与 Core SnapshotReducer 负责。
- 快照重建测试从旧 `item/delta` replay 改为 `core/runItem` message replay，验证运行文本只进入 `snapshot.core.items`，不再回写外层 Writer `items`。
- 保留 `turn/accepted`、`turn/started`、`turn/interrupted`、`turn/completed`、`item/requestApproval`、`serverRequest/resolved`、queue 与外层 `error`，因为它们仍属于当前 Writer App Server 产品操作或审批失败回执。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/reducer.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_event_ledger.py members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `rg -n 'thread/status/changed|turn/metrics|artifact/created|item/delta|_merge_runtime_metrics' -- members/writer/backend/app members/writer/backend/tests/test_writer_app_event_ledger.py`

当前收缩：

- App Server reducer 不再为已迁入 Core snapshot 的运行文本、usage、artifact 和 thread runtime status 保留旧投影兼容。
- 外层 Writer snapshot 继续只承载产品操作事实；运行事实继续收敛到 `snapshot.core`。

### 9.60 执行记录：2026-07-01 第六十切片

已完成：

- Writer CLI formatter 直接识别 `core/runItem`，从 canonical run item 显示 message、tool call/result、approval request、artifact、usage、status 和 error。
- CLI 的 waiting / done / failed / request id 判断支持 `core/runItem`，运行完成不再依赖旧外层 `turn/completed` runtime carrier。
- 删除 CLI 对旧 `item/delta` runtime carrier 的显示分支；测试从旧 `item/delta` / runtime `turn/completed` 改为保护 `core/runItem` message/status/tool/approval。
- 保留 turn start、queue、serverRequest resolved 等产品操作事件的 CLI 显示。

验证：

- `py -3.14 -m py_compile members/writer/backend/writer_cli/__main__.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_cli.py -q`
- `rg -n 'item/delta|turn/metrics|thread/status/changed|artifact/created' -- members/writer/backend/writer_cli/__main__.py members/writer/backend/tests/test_writer_cli.py`

当前收缩：

- CLI 运行显示已经与 Core run item 主线对齐，不再保护旧文本 delta carrier。
- 后续重点转向前端 ChatThread / selectors 对 canonical part 的进一步瘦身，以及更上层的 operation catalog 收敛。

### 9.61 执行记录：2026-07-01 第六十一切片

已完成：

- Writer 长上下文 App Server E2E 脚本从观察旧 `item/delta` 改为观察 `core/runItem` 的 `kind == message`。
- WebSocket 捕获字段增加 `run_item_kind`，运行 item 的展示类型从 `payload.payload.type` 读取，兼容 canonical run item envelope。
- 结果字段从 `first_agent_delta_event_ms` / `provider_delta_observed` 改为 `first_agent_message_event_ms` / `provider_message_observed`，测试语义与 Core run item 对齐。

验证：

- `node --check members/writer/frontend/scripts/writer-app-server-long-context-e2e.mjs`
- `rg -n 'item/delta|first_agent_delta_event_ms|provider_delta_observed|thread/status/changed|turn/metrics|artifact/created' members/writer/frontend/scripts/writer-app-server-long-context-e2e.mjs`

当前收缩：

- 活跃长上下文 E2E 不再把旧 AppEvent 文本 delta 当作实时链路验收事实。
- 剩余 `item/delta` 命中主要在历史设计文档和非主线历史说明中。

### 9.62 执行记录：2026-07-01 第六十二切片

已完成：

- Writer App Server 审批继续失败不再写外层 `error` AppEvent，改为写 Core `RunItemEvent(kind="error")` 和 `RunItemEvent(kind="status", status="failed")`。
- Writer reducer 删除外层 `error` 归约分支，错误事实只进入 `snapshot.core.last_error` 和 `snapshot.core.status`。
- Writer CLI 删除外层 `error` AppEvent 显示/失败判断，只保留 `core/runItem` error/status 显示。
- Core SnapshotReducer 增加 error contract 测试，明确 Core error 会记录 failed item、failed turn、failed thread 和 `last_error`。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/connection.py members/writer/backend/app/app_server/reducer.py members/writer/backend/writer_cli/__main__.py`
- `py -3.14 -m pytest core/tests/test_run_item_snapshot.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_cli.py -q`
- `rg -n 'method="error"|method\s*=\s*"error"|method == "error"|"method": "error"|elif method == "error"|\[error\]' members/writer/backend/app/app_server members/writer/backend/writer_cli members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_cli.py`

当前收缩：

- App Server 外层 AppEvent 不再承载错误事实；运行错误、审批继续失败等错误状态统一进入 Core run item / Core snapshot。
- 外层 AppEvent 继续保留用户输入、队列、审批响应等产品操作事实。

### 9.63 执行记录：2026-07-01 第六十三切片

已完成：

- 删除 Writer 后端根目录下仍被 git 跟踪的旧 REST/SSE 验证脚本：`quick_verify.ps1`、`regression_suite.ps1`、`run_all_phases.ps1`、`run_all_phases_v3.ps1`、`test_sse.ps1`。
- 删除这些旧脚本配套的历史截图产物：`screenshot1_initial.png`、`screenshot2_main.png`、`screenshot3_main.png`、`screenshot4_scrolled.png`。
- 保留 `check_app_server.py`，因为它走当前 `AppServerClient` / app-server protocol，不是旧 `/chat` SSE 验证壳。

验证：

- `git ls-files members/writer/backend/quick_verify.ps1 members/writer/backend/regression_suite.ps1 members/writer/backend/run_all_phases.ps1 members/writer/backend/run_all_phases_v3.ps1 members/writer/backend/test_sse.ps1 members/writer/backend/screenshot1_initial.png members/writer/backend/screenshot2_main.png members/writer/backend/screenshot3_main.png members/writer/backend/screenshot4_scrolled.png`
- `rg -n 'quick_verify|regression_suite|run_all_phases|test_sse' --glob '!node_modules/**' --glob '!dist/**' --glob '!release/**' .`

当前收缩：

- 当前仓库不再把旧 `/api/sessions/{id}/chat` SSE 与 `writer_*` 事件采集脚本作为可执行验证入口维护。
- 历史计划和交接文档仍可保留这些名称作为历史记录，但不再是当前验证面。

### 9.64 执行记录：2026-07-01 第六十四切片

已完成：

- Writer CLI 删除外层 `item/started` / `item/completed` 中旧 `agentMessage`、tool call、server request carrier 的显示分支。
- CLI 的运行文本、工具调用、工具结果、审批请求继续只从 `core/runItem` 读取。
- 外层 `item/started` / `item/completed` 在 CLI 中只保留当前生产路径仍会产生的 user message 展示；`serverRequest/resolved` 作为审批响应回执继续保留。

验证：

- `py -3.14 -m py_compile members/writer/backend/writer_cli/__main__.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_cli.py -q`
- `rg -n 'dynamicToolCall|mcpToolCall|commandExecution|fileChange|agentMessage|serverRequest' members/writer/backend/writer_cli/__main__.py members/writer/backend/tests/test_writer_cli.py`

当前收缩：

- CLI 不再保留旧 runtime item carrier 的 tool/agent 展示兼容；产品操作事件和 Core run item 事件的边界更清楚。

### 9.65 执行记录：2026-07-01 第六十五切片

已完成：

- 删除 `item/requestApproval` 旧审批 carrier：Writer App Server hub 不再把它转换成 JSON-RPC server request。
- Writer reducer 删除外层 `item/requestApproval` 归约分支；审批请求事实只由 Core `RunItemEvent(kind="approval_request")` 写入 `snapshot.core.requests`。
- Writer CLI 删除外层 `item/requestApproval` waiting/decision 判断；等待态和 request id 只从 `core/runItem` approval request 读取。
- 队列等待回归从旧 `item/requestApproval` 改为 Core approval request，验证 `snapshot.core.status == waiting` 时不会分发下一条队列。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/connection.py members/writer/backend/app/app_server/reducer.py members/writer/backend/writer_cli/__main__.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_cli.py -q`
- `rg -n 'item/requestApproval' members/writer/backend/app members/writer/backend/tests members/writer/backend/writer_cli`

当前收缩：

- 审批请求事实已经完全退出外层 AppEvent carrier；外层只保留 `serverRequest/resolved` 作为用户操作回执。

### 9.66 执行记录：2026-07-01 第六十六切片

已完成：

- 删除 `turn/completed` 旧 runtime completion carrier：Writer reducer 和 CLI 不再识别外层 `turn/completed`。
- 队列调度和快照重建测试从外层 `turn/completed` 改为 Core `RunItemEvent(kind="status")` completed/failed。
- 晚到 interrupt 回归改为证明 Core failed status 不被外层 `turn/interrupted` 改写。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/reducer.py members/writer/backend/writer_cli/__main__.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_cli.py -q`
- `rg -n 'turn/completed' members/writer/backend/app members/writer/backend/tests members/writer/backend/writer_cli`

当前收缩：

- runtime terminal status 已完全由 Core status run item 承载；外层 turn 事件只保留 accepted/started/steered/interrupted 等用户操作与控制事实。

### 9.67 执行记录：2026-07-01 第六十七切片

已完成：

- 删除 `item/completed` 重复用户消息事件；`accept_turn_start()` 现在只写 `turn/accepted`、`item/started(status=completed)`、`turn/started`。
- Writer reducer 和 CLI 删除外层 `item/completed` 分支。
- turn/start 相关测试更新为 3 条初始 AppEvent，snapshot 序列从 4 收缩为 3。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/queue.py members/writer/backend/app/app_server/reducer.py members/writer/backend/writer_cli/__main__.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_cli.py members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `rg -n 'item/completed' members/writer/backend/app members/writer/backend/tests members/writer/backend/writer_cli`

当前收缩：

- 外层 item 事件只剩当前产品输入事实 `item/started(userMessage)`；运行 item 和完成状态不再通过外层 item carrier 表达。

### 9.68 执行记录：2026-07-01 第六十八切片

已完成：

- Writer 队列层新增统一的有效 turn 状态判断：同一个 turn 若已在 `snapshot.core.turns` 中进入 completed/failed/cancelled/skipped 等非活跃状态，即使外层 `snapshot.turns` 仍停留在 running，也不再视为活跃 turn。
- `turn/steer` 改为使用上述判断；Core 已终止的 turn 收到后续 guidance 时只写 `queue/itemUpdated(status=guidance_expired)`，不再追加 `turn/steered`。
- `turn/interrupt` 改为复用同一活跃 turn 判断；Core 已终止的 turn 收到 interrupt 时返回 idle，不再追加 `turn/interrupted`。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/connection.py members/writer/backend/app/app_server/queue.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_server_protocol.py -q`

当前收缩：

- runtime terminal status 不只用于展示和队列分发，也开始成为控制入口的权威判断来源。
- 外层 turn 事件继续保留用户操作和控制事实，但不能覆盖 Core runtime 的终态。

### 9.69 执行记录：2026-07-01 第六十九切片

已完成：

- 删除 Writer 内未使用的旧 SSE helper 包 `members/writer/backend/app/core/events/__init__.py`。
- 该文件只剩 `sse_event(event, data)` 字典包装函数，当前代码和测试均无引用；实时主线已是 App Server websocket + snapshot，不再需要 Writer 自己保留一套 SSE event helper。

验证：

- `rg -n 'app\\.core\\.events|core\\.events|sse_event\\(' members/writer/backend/app members/writer/backend/tests`
- `py -3.14 -m pytest members/writer/backend/tests/test_main_core_app_unit.py members/writer/backend/tests/test_writer_app_server_protocol.py -q`

当前收缩：

- 旧 Writer SSE 事件语言继续退出 member；后续只保留 App Server 事件和 Core `RunItemEvent` 两类必要事实。

### 9.70 执行记录：2026-07-01 第七十切片

已完成：

- 修正 Writer member manifest 中 `/api/core` 的能力说明，删除已不存在的 `events` 声明。
- 当前 Writer Core HTTP 兼容面只声明 sessions、messages、providers、usage；运行事件事实不再通过 `/api/core/sessions/{id}/events` 对外暴露。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/main.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_main_core_app_unit.py members/writer/backend/tests/test_core_http_writer_unit.py -q`

当前收缩：

- Core HTTP compatibility path 不再误导调用方认为旧 runtime events 仍是成员能力。

### 9.71 执行记录：2026-07-01 第七十一切片

已完成：

- 删除 `writer_service.py` 中旧 `_infer_interaction_mode()` 无操作兼容函数。
- 删除 `send_message()` 中调用该函数并尝试更新 `session.mode` 的死分支；该函数固定返回 `None`，实际不会改变任何运行路径。

验证：

- `rg -n '_infer_interaction_mode|infer_interaction|mode inference|Kept as no-op' members/writer/backend/app members/writer/backend/tests`
- `py -3.14 -m py_compile members/writer/backend/app/services/writer_service.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`

当前收缩：

- Writer 任务入口不再保留旧模式推断壳；运行模式由 session 创建/更新明确写入，任务执行直接进入当前 Core runtime 主线。

### 9.72 执行记录：2026-07-01 第七十二切片

已完成：

- 删除孤儿 `members/writer/backend/app/core/writer/tool_executor.py` 与对应 `test_tool_executor.py`。
- 删除孤儿 `members/writer/backend/app/core/writer/scope_guard.py` 与对应 `test_scope_guard.py`。
- 当前生产工具执行主线只保留 `core_kernel_adapter.py` 内的 `ReadOnlyToolExecutor` / `ReadWriteToolExecutor`，以及 `test_tool_contracts.py`、`test_writer_core_kernel_adapter.py` 对这条主线的测试。

验证：

- `rg -n 'from app\\.core\\.writer\\.tool_executor|from app\\.core\\.writer\\.scope_guard|import app\\.core\\.writer\\.tool_executor|import app\\.core\\.writer\\.scope_guard' members/writer/backend/app members/writer/backend/tests --glob '*.py'`
- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/services/runtime_approved_tool.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`

当前收缩：

- Writer 不再保留一套未接入运行主线的低风险工具执行器。
- `scope_guard.py` 的旧 advisory/compat 层退出；权限和执行策略继续由当前工具主线、Core permission 词汇和 App Server 审批链路承担。

### 9.73 执行记录：2026-07-01 第七十三切片

已完成：

- 删除未接入生产主线的普通 Writer 自审模块 `members/writer/backend/app/core/writer/self_review.py`。
- 删除只保护该孤儿模块的 `test_self_review.py`、`test_plan_review.py`，并从 `test_wave3_p2.py` 移除 W11 plan executability 私有方法测试。
- 保留 Novel 专用自审 `members/writer/backend/app/core/writer/novel/self_review.py`；该路径仍由 Novel service/router 使用，属于领域专用验收策略，不在本切片删除范围。

验证：

- `rg -n 'app\\.core\\.writer\\.self_review|from app\\.core\\.writer\\.self_review|SelfReviewer|review_code_change|review_command_execution' members/writer/backend/app members/writer/backend/tests --glob '*.py'`
- `py -3.14 -m py_compile members/writer/backend/app/core/writer/completion_verifier.py members/writer/backend/app/core/writer/novel/self_review.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_wave3_p2.py members/writer/backend/tests/test_completion_verifier.py members/writer/backend/tests/test_novel_e2e.py -q`

当前收缩：

- Writer 普通任务验收回到 completion verifier / verification specs / failure specs 主线，不再保留一套未被运行链路调用的自审壳。
- Novel 自审继续作为 Writer 领域特化示例保留，符合 member 只保留自身 Kit、prompt、工具、验收和产品 UI 的目标。

### 9.74 执行记录：2026-07-01 第七十四切片

已完成：

- 删除 `members/writer/backend/app/core/writer/artifacts.py`、`design_constraints.py`、`feedback.py`、`session_memory.py`、`transitions.py`、`verification_specs.py`。
- 这些模块在当前生产链路和测试链路中均无入边；其中 `session_memory.py` 的工具输出索引器没有被 `recall_session` 工具或 Core runtime state 使用，当前会话运行状态仍由 `WriterSessionState.session_memory` 中的 Core runtime state 保存。维护标注（2026-07-01 第七十六切片）：旧 Writer 私有 `core/mem/**` 后续也已确认未接入主线并删除，通用 memory 协议回到 Core。
- App Server artifact 主线保留在 `app_server/artifacts.py` 与 `models/app_server.py`；普通任务验收主线保留在 `completion_verifier.py` 与 `failure_specs.py`。

验证：

- `rg -n 'app\\.core\\.writer\\.(artifacts|design_constraints|feedback|session_memory|transitions|verification_specs)|from app\\.core\\.writer\\.(artifacts|design_constraints|feedback|session_memory|transitions|verification_specs)|WriterSessionMemory|TaskDesignConstraints|extract_writer_feedback|apply_transition|VERIFICATION_CRITERIA' members/writer/backend/app members/writer/backend/tests --glob '*.py'`
- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/services/writer_service.py members/writer/backend/app/core/writer/schemas.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_state_store.py -q`

当前收缩：

- Writer `core/writer` 继续回到真实运行主线：Core loop adapter、工具、权限、验收、Git、agent runtime、schema。
- 无调用的旧 phase transition、artifact manager、feedback extractor、verification 常量、design constraint 草稿和 session memory 索引器不再占据 member 结构。

### 9.75 执行记录：2026-07-01 第七十五切片

已完成：

- 删除只被测试触达的旧 Writer helper：`context_specs.py`、`design_prompts.py`、`git_context.py`、`turn_parser.py`。
- 删除只保护这些 helper 的 `test_context_specs.py`、`test_git_context.py`、`test_turn_parser.py`。
- 从 `test_mcp.py` 删除旧 `tool_call_to_action()` 映射测试；MCP 当前仍由 registry/client 与工具执行主线覆盖。
- 从 `test_design_scoring.py` 删除旧四轮设计 prompt 断言；保留仍被 ArchitectureAgent 使用的 `design_scoring.py` 评分测试。

验证：

- `rg -n 'app\\.core\\.writer\\.(context_specs|design_prompts|git_context|turn_parser)|from app\\.core\\.writer\\.(context_specs|design_prompts|git_context|turn_parser)|parse_writer_turn|tool_call_to_action|deterministic_context_summary|git_context_lines|candidates_prompt|decision_prompt' members/writer/backend/app members/writer/backend/tests --glob '*.py'`
- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/agents/architecture_agent.py members/writer/backend/app/core/writer/design_scoring.py members/writer/backend/app/core/mcp/registry.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_mcp.py members/writer/backend/tests/test_design_scoring.py members/writer/backend/tests/test_runtime_feasibility.py members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`

当前收缩：

- Writer 不再保留旧模型 JSON/Markdown 兜底解析器；模型运行事实由 Core tool call / RunItemEvent 主线承担。
- 旧上下文压缩 helper、Git context helper、四轮设计 prompt helper 已退出，避免测试继续为非生产路径提供存在理由。

### 9.76 执行记录：2026-07-01 第七十六切片

已完成：

- 删除 Writer 私有 MEM 包 `members/writer/backend/app/core/mem/**` 与对应 `test_mem.py`。
- 删除 `writer_service.py` 中未使用的 `MEMModule` import 和初始化；该对象只创建、不参与 prompt、tool、recall、writeback 或 runtime state。
- Novel 当前记忆写回保留在 `members/writer/backend/app/core/writer/novel/memory_writeback.py`，通用 memory 协议保留在 Core。

验证：

- `rg -n 'from app\\.core\\.mem|app\\.core\\.mem|MEMModule|WriterAdapter|MEMRecallResult' members/writer/backend/app members/writer/backend/tests --glob '*.py'`
- `py -3.14 -m py_compile members/writer/backend/app/services/writer_service.py members/writer/backend/app/core/writer/novel/memory_writeback.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_novel_e2e.py -q`

当前收缩：

- Writer 不再维护一套未被运行主线调用的私有 memory store/recall/budget/provenance。
- 后续如需长期记忆，应基于 Core memory protocol 接入，而不是在 member 内重建基础 agent 能力。

### 9.77 执行记录：2026-07-01 第七十七切片

已完成：

- 删除旧 `members/writer/backend/app/core/guardrail.py`。
- 删除无调用方的旧 `members/writer/backend/app/schemas/` 包：`__init__.py`、`session.py`、`message.py`。
- 当前 Writer 普通工具权限由 `core/writer/permission.py` 和 Core permission 词汇承担；session/message 请求响应模型在当前 `routers/session.py`、`routers/core_http.py` 内定义。

验证：

- `rg -n 'app\\.schemas|from app\\.schemas|app\\.core\\.guardrail|from app\\.core\\.guardrail|WriterGuardrail' members/writer/backend/app members/writer/backend/tests --glob '*.py'`
- `py -3.14 -m py_compile members/writer/backend/app/routers/session.py members/writer/backend/app/routers/core_http.py members/writer/backend/app/core/writer/permission.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_project_crud.py members/writer/backend/tests/test_core_http_writer_unit.py members/writer/backend/tests/test_permission.py -q`

当前收缩：

- Writer 不再保留一套未使用的旧 guardrail 类和重复 API schema 包。
- 权限、会话、消息模型继续以当前运行主线为准，避免“同名 schema 在两处定义”的误导。

### 9.78 执行记录：2026-07-01 第七十八切片

已完成：

- 删除 Artist 中无生产入边的旧 runtime helper：`core/artist/artifacts.py`、`feedback.py`、`image_context.py`、`normalizer.py`、`tools.py`、`transitions.py`、`visual_review.py`。
- 删除 Artist 旧 prompt/memory stub：`core/prompt_assembler.py`、`core/mem/__init__.py`、`core/mem/adapters/artist.py`。
- 保留当前 Artist 主线：`core/artist/core_kernel_adapter.py`、`tool_specs.py`、`image_prep.py`、`artifact_registry.py`、`contact_sheet.py`、`services/image_context_resolver.py`、`services/visual_workspace.py`、产品 routers/services/UI。

验证：

- `rg -n 'app\\.core\\.artist\\.(artifacts|feedback|image_context|normalizer|tools|transitions|visual_review)|from app\\.core\\.artist\\.(artifacts|feedback|image_context|normalizer|tools|transitions|visual_review)|app\\.core\\.prompt_assembler|from app\\.core\\.prompt_assembler|app\\.core\\.mem|from app\\.core\\.mem|ArtistToolExecutor|PromptAssembler|MEMModule' members/artist/backend/app members/artist/backend/tests --glob '*.py'`
- `py -3.14 -m py_compile members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/services/artist_service.py members/artist/backend/app/services/generate_service.py members/artist/backend/app/main.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py members/artist/backend/tests/test_artist_tool_specs.py members/artist/backend/tests/test_artist_session_lifecycle.py -q`

当前收缩：

- Artist 不再保留旧的并行 tool executor、phase transition、prompt assembler、memory stub、visual review helper。
- Artist 保留的是领域产品能力本身：图像生成、视觉上下文、VLM 验收、谱系/产物、产品 API/UI。

### 9.79 执行记录：2026-07-01 第七十九切片

已完成：

- 删除无生产入边的旧 Artist 产品事件 helper `members/artist/backend/app/core/artist/events.py`。
- 保留仍在使用的 `members/artist/backend/app/core/events/__init__.py`；该模块提供 `LamEvent/EventLog`，当前 TaskManager/SSE 仍依赖它。

验证：

- `rg -n 'app\\.core\\.artist\\.events|from app\\.core\\.artist\\.events|artist_thinking\\(|artist_reasoning_delta\\(|batch_progress\\(|long_task_created\\(' members/artist/backend/app members/artist/backend/tests --glob '*.py'`
- `py -3.14 -m py_compile members/artist/backend/app/services/task_manager.py members/artist/backend/app/services/artist_service.py members/artist/backend/app/services/generate_service.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py members/artist/backend/tests/test_artist_session_lifecycle.py -q`

当前收缩：

- Artist 旧事件 constructor 不再与 Core display / TaskManager SSE 并行存在。
- 后续 Artist 事件收敛应围绕 `CoreDisplayEvent` 与当前 `LamEvent/EventLog` 边界继续，而不是恢复 `core/artist/events.py`。

### 9.80 执行记录：2026-07-01 第八十切片

已完成：

- Core 新增 `lamtools_core.event.runtime_projection`，承接 `runtime.*` 事实到 `RunItemEvent` 的通用映射，包括 message/thinking/tool/approval/artifact/usage/status。
- Writer `runtime_fact_projection.py` 改为从 Core 调用该映射；Writer `app_server/runtime_bridge.py` 删除重复 runtime fact -> run item 翻译器，只保留 Writer 产品侧的 `WriterArtifact` / approval request 持久化副作用。
- Writer runtime bridge 测试改为从 Core contract 导入映射函数，不再保护 Writer 私有映射入口。
- 当前行数口径：`core/src` 7,064 行 / 37 文件；Writer backend+CLI 31,432 行 / 109 文件；Writer frontend 7,881 行 / 23 文件；Writer runtime 合计 39,313 行 / 132 文件。

验证：

- `py -3.14 -m py_compile core/src/lamtools_core/event/runtime_projection.py core/src/lamtools_core/event/__init__.py members/writer/backend/app/app_server/runtime_bridge.py members/writer/backend/app/services/runtime_fact_projection.py`
- `py -3.14 -m pytest core/tests/test_event.py core/tests/test_run_item_snapshot.py core/tests/test_runtime_projection.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_event_ledger.py members/writer/backend/tests/test_writer_cli.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_app_approvals.py -q`

当前收缩：

- `runtime.*` 到 canonical `RunItemEvent` 的规则不再属于 Writer member；后续 Writer/Artist 都应复用 Core 投影 contract。
- Writer `runtime_bridge.py` 从“事件翻译器 + 产品持久化”收缩为“产品持久化适配”，符合 Core 是唯一运行主线、member 只保留薄 adapter 的目标。

### 9.81 执行记录：2026-07-01 第八十一切片

已完成：

- Core `runtime_projection` 新增 `RuntimeProjectionBuffer`，承接 `runtime.part` 增长合并，避免 member 为同一流式 part 自建缓冲器。
- Writer `RuntimeFactRecorder` 改为直接使用 Core `RuntimeProjectionInput` / `RuntimeProjectionBuffer` / `runtime_projection_to_run_item_events`。
- 删除 Writer 私有 `members/writer/backend/app/services/runtime_fact_projection.py` 和只保护该模块的 `test_runtime_fact_projection.py`；原 part-growth 回归迁入 Core `test_runtime_projection.py`。
- 当前行数口径：`core/src` 7,093 行 / 37 文件；Writer backend+CLI 31,365 行 / 108 文件；Writer frontend 7,881 行 / 23 文件；Writer runtime 合计 39,246 行 / 131 文件。

验证：

- `rg -n 'app\\.services\\.runtime_fact_projection|from app\\.services\\.runtime_fact_projection|RuntimeFactProjectionBuffer|RuntimeProjectionFact|run_items_from_runtime_fact' members/writer/backend/app members/writer/backend/tests core/src core/tests --glob '*.py'`
- `py -3.14 -m py_compile core/src/lamtools_core/event/runtime_projection.py core/src/lamtools_core/event/__init__.py members/writer/backend/app/services/runtime_fact_recorder.py members/writer/backend/app/services/runtime_runner.py`
- `py -3.14 -m pytest core/tests/test_runtime_projection.py core/tests/test_event.py core/tests/test_run_item_snapshot.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_app_approvals.py -q`

当前收缩：

- Writer 不再拥有 runtime fact projection 模块；运行事实输入、增长合并和 canonical run item 生成都归 Core。
- Writer 仍保留 transcript sync、app projection sink、artifact/request 产品持久化，这些是当前产品 adapter 边界，后续继续判断哪些能进一步收缩为 Core operation/snapshot store。

### 9.82 执行记录：2026-07-01 第八十二切片

已完成：

- Core `runtime_projection` 新增 `runtime_group_from_event_name()`、`runtime_summary_from_event_name()`、`runtime_payload_preview()` 和默认预览长度常量。
- Writer `RuntimeFactRecorder` 删除本地 runtime event group/summary/payload preview 函数，改为调用 Core contract。
- Writer `runtime_runner.py` 的 terminal fallback group 也改为从 Core runtime projection 读取，避免从 Writer recorder 反向导入通用运行事件分类函数。
- 当前行数口径：`core/src` 7,155 行 / 37 文件；Writer backend+CLI 31,324 行 / 108 文件；Writer frontend 7,881 行 / 23 文件；Writer runtime 合计 39,205 行 / 131 文件。

验证：

- `rg -n 'runtime_group_from_core_event|runtime_summary_from_core_event|def runtime_payload_preview|from app\\.services\\.runtime_fact_recorder import RuntimeFactRecorder,' members/writer/backend/app members/writer/backend/tests core/src core/tests --glob '*.py'`
- `py -3.14 -m py_compile core/src/lamtools_core/event/runtime_projection.py core/src/lamtools_core/event/__init__.py members/writer/backend/app/services/runtime_fact_recorder.py members/writer/backend/app/services/runtime_runner.py`
- `py -3.14 -m pytest core/tests/test_runtime_projection.py core/tests/test_event.py core/tests/test_run_item_snapshot.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py -q`

当前收缩：

- Writer 不再定义 CoreEvent 的运行类别、默认摘要、payload 预览裁剪规则；这些属于 Core runtime projection contract。
- Writer recorder 继续只做产品侧 transcript 同步和投影发布，符合“运行事实归 Core，member 只保留 adapter”的方向。

### 9.83 执行记录：2026-07-01 第八十三切片

已完成：

- 删除 Writer 私有 `members/writer/backend/app/services/runtime_fact_helpers.py` 与对应 `test_runtime_fact_helpers.py`。
- 将 runtime payload helper 下沉到 Core `runtime_projection`：model call id、response index、tool call id/raw id、tool args、usage tokens、visible runtime part content。
- Writer `RuntimeTranscriptSink` 改为从 Core runtime projection 调用这些 helper；它继续保留 Writer transcript 落库职责，但不再拥有 runtime payload 解释规则。
- 当前行数口径：`core/src` 7,261 行 / 37 文件；Writer backend+CLI 31,239 行 / 107 文件；Writer frontend 7,881 行 / 23 文件；Writer runtime 合计 39,120 行 / 130 文件。

验证：

- `rg -n 'app\\.services\\.runtime_fact_helpers|from app\\.services\\.runtime_fact_helpers' members/writer/backend/app members/writer/backend/tests --glob '*.py'`
- `py -3.14 -m py_compile core/src/lamtools_core/event/runtime_projection.py core/src/lamtools_core/event/__init__.py members/writer/backend/app/services/runtime_transcript_sink.py`
- `py -3.14 -m pytest core/tests/test_runtime_projection.py core/tests/test_event.py core/tests/test_run_item_snapshot.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_realtime_transcript_contract.py members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_app_runtime_bridge.py -q`

当前收缩：

- Writer transcript adapter 仍负责审计落库，但 runtime payload 的基础解释规则已退出 Writer。
- Core runtime projection 现在覆盖 canonical run item 映射、part-growth 缓冲、事件摘要、payload preview 和 transcript 所需 runtime payload helper。

### 9.84 执行记录：2026-07-01 第八十四切片

已完成：

- Core 新增 `lamtools_core.kernel.summary`，承接 KernelResult / CoreEvent 的通用摘要能力：event compaction、response block grouping、progress dict、kernel result summary。
- Writer `core_kernel_adapter.py` 删除本地摘要实现，改为从 Core 调用；只临时保留旧名称别名，降低本切片调用面风险。
- Writer `writer_service.py` 直接注入 Core `summarize_kernel_result`，服务层不再从 Writer adapter 获取通用摘要器。
- 纯摘要单测迁入 `core/tests/test_kernel_summary.py`；Writer adapter 测试删除对应重复单测，只保留运行链路与 Writer 装配验证。
- 当前行数口径：`core/src` 7,498 行 / 38 文件；Writer backend+CLI 31,006 行 / 107 文件；Writer frontend 7,881 行 / 23 文件；Writer runtime 合计 38,887 行 / 130 文件。

验证：

- `rg -n 'def compact_core_events_for_summary|def build_response_blocks_for_summary|def writer_core_event_to_progress_dict|def summarize_core_kernel_result|writer_core_event_to_progress_dict|summarize_core_kernel_result' core/src core/tests members/writer/backend/app members/writer/backend/tests --glob '*.py'`
- `py -3.14 -m py_compile core/src/lamtools_core/kernel/summary.py core/src/lamtools_core/kernel/__init__.py members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/services/writer_service.py`
- `py -3.14 -m pytest core/tests/test_kernel_summary.py core/tests/test_runtime_projection.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py::TestRunCommandFailure::test_run_command_background_http_server_requires_current_work_root_probe members/writer/backend/tests/test_writer_core_kernel_adapter.py::TestRunCommandFailure::test_run_command_background_http_server_returns_ok_after_probe -q -vv`

验证备注：

- `members/writer/backend/tests/test_writer_core_kernel_adapter.py members/writer/backend/tests/test_writer_service.py -q` 首次全文件运行出现 2 个后台 HTTP server 探针时序失败，单独复跑失败用例通过；失败点与本切片摘要迁移无关。

当前收缩：

- KernelResult / CoreEvent 的展示摘要不再属于 Writer member；这是 Core agent 基座的一部分。
- Writer adapter 当前只剩旧名称别名作为过渡点，后续应在清调用面后删除 `writer_core_event_to_progress_dict` / `summarize_core_kernel_result` 别名。

### 9.85 执行记录：2026-07-01 第八十五切片

已完成：

- 删除 Writer `core_kernel_adapter.py` 中无调用方的 `writer_core_event_to_progress_dict` / `summarize_core_kernel_result` 兼容别名。
- 删除对应未使用 Core 导入；Writer 代码现在只通过 Core 正式名称使用 kernel summary 能力。
- 当前行数口径：`core/src` 7,498 行 / 38 文件；Writer backend+CLI 30,995 行 / 107 文件；Writer frontend 7,881 行 / 23 文件；Writer runtime 合计 38,876 行 / 130 文件。

验证：

- `rg -n 'writer_core_event_to_progress_dict|summarize_core_kernel_result|core_event_to_progress_dict|summarize_kernel_result' members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app members/writer/backend/tests core/src core/tests --glob '*.py'`
- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/services/writer_service.py`
- `py -3.14 -m pytest core/tests/test_kernel_summary.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py::test_core_kernel_path_produces_observable_metadata -q`

当前收缩：

- Writer 不再暴露旧命名的 kernel summary API；该能力只有 Core contract。
- 这一步很小，但消除了上一切片保留的过渡面，避免后续代码继续从 Writer adapter 反向依赖通用摘要能力。

### 9.86 执行记录：2026-07-01 第八十六切片

已完成：

- 删除 Writer session API 中旧 mode 别名兼容：`CODE` / `CODING` / `DEFAULT` / `EXEC` 不再被映射为 `EXECUTE`。
- 删除对应测试 `test_create_session_normalizes_legacy_code_mode`；当前 session mode 只做空值默认和大小写规范化。
- 当前行数口径：`core/src` 7,498 行 / 38 文件；Writer backend+CLI 30,988 行 / 107 文件；Writer frontend 7,881 行 / 23 文件；Writer runtime 合计 38,869 行 / 130 文件。

验证：

- `rg -n 'legacy_aliases|legacy-code-mode|normalizes_legacy_code_mode|CODE.*EXECUTE|CODING.*EXECUTE|DEFAULT.*EXECUTE|EXEC.*EXECUTE' members/writer/backend/app/routers/session.py members/writer/backend/tests/test_project_crud.py`
- `py -3.14 -m py_compile members/writer/backend/app/routers/session.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_project_crud.py -q`

当前收缩：

- Writer 不再维护旧 mode 名称兼容；会话入口只接受当前产品语义。
- 这类“旧入口名自动纠偏”会隐藏 API 边界，后续应继续删掉其它仅服务历史输入的别名和兜底。

### 9.87 执行记录：2026-07-01 第八十七切片

已完成：

- 删除 Writer App Server `load_snapshot()` 中读取历史 snapshot JSON 时的旧 shape 自动补齐逻辑。
- 删除对应测试 `test_load_snapshot_normalizes_legacy_shape_with_core_snapshot` 和无用导入。
- 当前行数口径：`core/src` 7,498 行 / 38 文件；Writer backend+CLI 30,981 行 / 107 文件；Writer frontend 7,881 行 / 23 文件；Writer runtime 合计 38,862 行 / 130 文件。

验证：

- `rg -n '_ensure_current_snapshot_shape|normalizes_legacy_shape|legacy-snapshot' members/writer/backend/app/app_server/snapshot.py members/writer/backend/tests/test_writer_app_event_ledger.py`
- `py -3.14 -m py_compile members/writer/backend/app/app_server/snapshot.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_event_ledger.py -q`

当前收缩：

- Writer 不再在读取 snapshot 时为历史外层形状补齐 `core`；当前持久化数据必须已经是当前 shape。
- 这一步移除的是旧数据兼容壳，不改变当前事件增量归约和 rebuild 路径。

### 9.88 执行记录：2026-07-01 第八十八切片

目标：

- 将 `9.87` 后续执行从零散清理切换为可审计计划。
- 新增执行计划文档，挂到本设计文档。
- 固定当前基线，避免后续把历史文档扫描结果误当当前代码事实。

已完成：

- 新增 `docs/core-member-architecture-refactor-execution-plan-2026-07-01.md`。
- 执行计划按 12 步拆分：基线冻结、Core contract、Operation 主线、Event/Snapshot 收口、前端去旧投影、LLM/provider 下沉、Tool/Permission 下沉、Prompt/Memory/Verification 收敛、Writer thin member、Artist thin member、Scaffold 更新、最终验收。
- 对照 OpenAI Agents/Responses 与 Claude Code 成熟形态，明确 Core 管运行、工具、权限、状态，Member 只管领域注入。
- 固定当前基线：
  - Writer 旧 `services/task_manager.py` 不存在。
  - Writer 旧 `core/writer/core_adapter.py` 不存在。
  - Writer 私有 `services/runtime_fact_projection.py` 不存在。
  - Writer 私有 `services/runtime_fact_helpers.py` 不存在。
  - Writer 前端 `runtime/transcript.ts` 仍存在。
  - Writer `utils/llm_client.py` / `utils/llm_adapter_profiles.py` 仍存在。
  - Artist `services/task_manager.py` 仍存在。
  - `AgentApp` / `MemberKit` / `OperationCatalog` 目标接口尚未形成。
- 记录当前行数口径：Core `core/src` 38 文件 / 6,354 行；Writer backend+CLI 107 文件 / 27,230 行；Writer frontend 23 文件 / 7,169 行；Writer runtime 合计 130 文件 / 34,399 行。
- 记录当前工作区已有未提交改动，后续执行不得误覆盖。

验证：

- `git status --short`
- `Test-Path .\members\writer\backend\app\services\task_manager.py; Test-Path .\members\writer\backend\app\core\writer\core_adapter.py; Test-Path .\members\writer\backend\app\services\runtime_fact_projection.py; Test-Path .\members\writer\backend\app\services\runtime_fact_helpers.py; Test-Path .\members\writer\frontend\src\runtime\transcript.ts; Test-Path .\members\writer\backend\app\utils\llm_adapter_profiles.py; Test-Path .\members\artist\backend\app\services\task_manager.py`
- `rg -n 'class AgentApp|AgentApp|class MemberKit|MemberKit|OperationCatalog|operation_catalog|turn\.start|approval\.respond' core/src members/writer/backend/app members/artist/backend/app --glob '*.py'`
- `rg -n 'writer_git_|writer_part_updated|writer_payload_to_core_event|WriterRuntimeEvent|TaskManager|runtime_fact_projection|runtime_fact_helpers|llm_adapter_profiles|runtime/transcript|ExtendedToolExecutor' members/writer/backend/app members/writer/backend/writer_cli members/writer/frontend/src members/artist/backend/app core/src --glob '*.py' --glob '*.ts' --glob '*.vue'`

当前收缩：

- 本切片不改业务代码，先把继续执行的目标、顺序、验收口径和记录机制固定下来。
- 后续切片从 `Step 2：Core Contract 最小补齐` 开始，不再优先做无序小清理。

下一步：

- 实施 Core Contract 最小补齐：`AgentSpec`、`MemberKit`、`AgentApp`、`OperationCatalog`。

### 9.89 执行记录：2026-07-01 第八十九切片

目标：

- 完成执行计划 Step 2：Core Contract 最小补齐。
- 先建立最小可测接口，不把 Writer/Artist 业务迁入 Core。

已完成：

- 新增 `core/src/lamtools_core/member/kit.py`：
  - `MemberKit`
  - `PromptFragment`
  - `VerificationPolicy`
  - `MemberLabels`
  - `StaticMemberKit`
- 新增 `core/src/lamtools_core/app/agent_app.py`：
  - `AgentSpec`
  - `TurnInput`
  - `ModelTurnInput`
  - `ModelTurnOutput`
  - `TurnResult`
  - `AgentApp`
- 新增 `core/src/lamtools_core/app/operation_catalog.py`：
  - `OperationCatalog`
  - `OperationRequest`
  - `OperationResult`
- 更新 Core 导出，允许后续 Writer/Artist 从 Core 正式 contract 接入。
- 新增 `core/tests/test_agent_app_contract.py`，覆盖 minimal member turn 和 shared operation 执行。

验证：

- `py -3.14 -m py_compile core/src/lamtools_core/member/kit.py core/src/lamtools_core/app/agent_app.py core/src/lamtools_core/app/operation_catalog.py core/src/lamtools_core/member/__init__.py core/src/lamtools_core/app/__init__.py core/src/lamtools_core/__init__.py`
- `py -3.14 -m pytest core/tests/test_agent_app_contract.py -q`
- `py -3.14 -m pytest core/tests/test_app_factory.py core/tests/test_member_manifest.py core/tests/test_member_registry.py core/tests/test_run_item_snapshot.py -q`
- `rg -n 'Writer|Artist|LamWriter|LamArtist|writer|artist' core/src/lamtools_core --glob '*.py'`

当前收缩：

- Core 已具备最小 `AgentApp + MemberKit + OperationCatalog` 目标接口。
- 这一步只建立 contract 和测试，不迁移产品业务，因此没有触碰 Writer/Artist 运行主线。

下一步：

- 实施 Step 3：Operation 主线接入 Writer。先从 Writer app-server/CLI 当前入口读起，定义 `turn.start`、`turn.cancel`、`approval.respond` 的最小 adapter。

### 9.90 执行记录：2026-07-01 第九十切片

目标：

- 开始执行 Step 3：Operation 主线接入 Writer。
- 先把 Writer app-server 的核心控制入口接到 Core `OperationCatalog`，不改运行逻辑。

已完成：

- Writer app-server connection 引入 Core `OperationCatalog` / `OperationRequest` / `OperationResult`。
- 新增 operation 名称归一化：
  - `turn.start`
  - `turn.cancel`
  - `approval.respond`
- 保留旧 transport alias：
  - `turn/start` -> `turn.start`
  - `turn/interrupt` / `turn.interrupt` -> `turn.cancel`
  - `approval/respond` -> `approval.respond`
- Writer CLI client 改为发送 dot operation：
  - `start_turn()` 发送 `turn.start`
  - `respond_approval()` 发送 `approval.respond`
  - 新增 `cancel_turn()` 发送 `turn.cancel`
- `writer cancel` 改为调用 `cancel_turn()`。
- 增加协议测试，证明 dot operation 会通过 Core catalog 分发到当前 Writer handler。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/connection.py members/writer/backend/writer_cli/app_server_client.py members/writer/backend/writer_cli/__main__.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_cli.py -q`

当前收缩：

- CLI/GUI/HTTP 的核心控制名开始向 `operation` 语义靠拢。
- 本切片仍是兼容式接入：实际 `_turn_start` / `_turn_interrupt` / `_approval_respond` 运行逻辑还在 Writer connection 内。
- 下一步应把 operation handler 从 connection 内部方法抽成 Writer app-server adapter 函数，再逐步迁向 Core operation 主线。

下一步：

- 继续 Step 3：拆出 Writer operation adapter，让 websocket connection 只做 transport，operation handler 承担业务入口。

### 9.91 执行记录：2026-07-01 第九十一切片

目标：

- 继续执行 Step 3：把 Writer operation adapter 从 websocket connection 中拆出。
- 让 connection 更接近 transport 层，operation adapter 承担方法名归一化和 Core catalog 装配。

已完成：

- 新增 `members/writer/backend/app/app_server/operations.py`。
- 将 operation 名称归一化迁出 connection：
  - `operation_name()`
  - `OPERATION_ALIASES`
- 将 Writer operation catalog 装配迁出 connection：
  - `build_writer_operation_catalog()`
  - `turn.start`
  - `turn.cancel`
  - `approval.respond`
- `WriterAppServerConnection` 只保留 `_operation_catalog()` 作为 transport 到 adapter 的薄桥接。
- 增加测试覆盖：
  - slash transport alias 到 dot operation 的归一化。
  - Writer operation catalog 对 RPC handler 的包装。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_cli.py -q`
- `py -3.14 -m pytest core/tests/test_agent_app_contract.py core/tests/test_app_factory.py core/tests/test_member_manifest.py core/tests/test_member_registry.py core/tests/test_run_item_snapshot.py -q`
- `rg -n 'Writer|Artist|LamWriter|LamArtist|writer|artist' core/src/lamtools_core --glob '*.py'`
- `git diff --check`

验证备注：

- Core tests 和 Writer backend tests 需要分开运行；同一条 pytest 命令混跑 `core/tests` 与 `members/writer/backend/tests` 时，当前 pytest 包名收集会出现 `No module named 'tests.test_*'`，属于测试根目录组合方式问题，不是本切片代码失败。

当前收缩：

- Operation 分发边界已从 websocket connection 中独立出来。
- 当前仍未把 `_turn_start` / `_turn_interrupt` / `_approval_respond` 的业务实现迁出 connection；下一步应继续拆这些 handler 的业务入口，降低 connection 文件职责。

下一步：

- 继续 Step 3：优先拆 `turn.cancel` 或 `approval.respond` 这类较小 handler，形成 Writer operation handler 模块的真实业务入口。

### 9.92 执行记录：2026-07-01 第九十二切片

目标：

- 继续执行 Step 3：先拆较小的 `turn.cancel` handler。
- 让 websocket connection 退出取消逻辑，只保留 transport 的发送和 publish。

已完成：

- `members/writer/backend/app/app_server/operations.py` 新增：
  - `WriterOperationOutcome`
  - `handle_turn_cancel_operation()`
- `turn.cancel` 的业务逻辑迁出 `WriterAppServerConnection._turn_interrupt()`：
  - 读取 thread / turn 参数。
  - 读取 snapshot 并判断当前 active turn。
  - 写入 `turn/interrupted` event。
  - 应用 snapshot。
  - 调用 Core runtime task registry 做强制取消。
  - 返回 RPC response 和待 publish event。
- connection 的 `_turn_interrupt()` 现在只调用 operation handler、发送 response、发布事件。
- operation handler 支持注入 `session_factory`，保持现有测试和生产依赖边界。
- 增加无 thread_id 的 operation 单测。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py::test_turn_interrupt_cancels_app_server_runtime_task members/writer/backend/tests/test_writer_app_server_protocol.py::test_turn_interrupt_ignores_core_terminal_turn -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_cli.py -q`
- `py -3.14 -m pytest core/tests/test_agent_app_contract.py core/tests/test_app_factory.py core/tests/test_member_manifest.py core/tests/test_member_registry.py core/tests/test_run_item_snapshot.py -q`
- `git diff --check`

当前收缩：

- `turn.cancel` 已成为独立 Writer operation handler，connection 不再拥有取消业务逻辑。
- 这一步仍保留 `turn/interrupted` 外层 AppEvent，因为当前 snapshot/queue/CLI 仍以该事件表达用户中断；后续 Event/Snapshot 收口阶段再决定是否改为 Core `RunItemEvent` status。

下一步：

- 继续 Step 3：拆 `approval.respond` handler，优先把审批响应和 continuation 调度从 connection 中移出。

### 9.93 执行记录：2026-07-01 第九十三切片

目标：

- 继续执行 Step 3：拆 `approval.respond` handler。
- 让 connection 退出审批响应落库和结果构造，只保留发送、通知和 continuation task 启动。

已完成：

- `members/writer/backend/app/app_server/operations.py` 新增：
  - `ApprovalResolution`
  - `resolve_approval_request()`
  - `handle_approval_respond_operation()`
- `approval.respond` 的核心逻辑迁出 connection：
  - 校验 `request_id` / `decision`。
  - 查询审批请求是否仍 open。
  - 调用现有审批落库逻辑生成 `serverRequest/resolved` 和 Core approval response。
  - 读取 snapshot。
  - 返回 RPC response、notify event 和 continuation 参数。
- JSON-RPC response 形式的审批回执也改为复用 `resolve_approval_request()`。
- 删除 connection 中的 `_resolve_approval()` 和 `_snapshot_for_result()`。
- connection 不再直接导入 `WriterAppRequest` 或 `respond_to_approval`。
- 增加缺少必填字段的 `approval.respond` operation 单测。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_cli.py -q`
- `py -3.14 -m pytest core/tests/test_agent_app_contract.py core/tests/test_app_factory.py core/tests/test_member_manifest.py core/tests/test_member_registry.py core/tests/test_run_item_snapshot.py -q`
- `rg -n "_resolve_approval|_snapshot_for_result|WriterAppRequest|respond_to_approval" members/writer/backend/app/app_server/connection.py members/writer/backend/app/app_server/operations.py`
- `git diff --check`

当前收缩：

- `turn.cancel` 和 `approval.respond` 都已经是独立 Writer operation handler。
- connection 的职责继续向 transport 收缩，但 `turn.start`、queue、artifact、runtime continuation 仍在 connection 内。

下一步：

- 继续 Step 3：拆 `turn.start` 的前半段，即 accept turn / snapshot / response 构造；运行 task 启动可先留在 connection。

### 9.94 执行记录：2026-07-01 第九十四切片

目标：

- 继续执行 Step 3：拆 `turn.start` 的前半段。
- 先迁移 accept turn / snapshot / response 构造，运行 task 生命周期仍留在 connection。

已完成：

- `members/writer/backend/app/app_server/operations.py` 新增 `handle_turn_start_operation()`。
- `turn.start` 的入口逻辑迁出 connection：
  - 校验 `thread_id` / `client_message_id` / `input`。
  - 检查 Writer session 是否存在。
  - 调用 `accept_turn_start()` 写入用户输入和 turn 事件。
  - 读取 snapshot 并构造 RPC response。
  - 生成 `runtime_start` 参数，交由 connection 启动现有 Writer runtime task。
- connection 的 `_turn_start()` 现在只调用 operation handler、发送 response / event notification，并在有 `runtime_start` 时启动 runtime。
- 清理 connection 中已不再使用的 `accept_turn_start` import。
- 增加缺少必填字段的 `turn.start` operation 单测。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py::test_turn_start_passes_existing_app_server_message_and_turn_to_runtime members/writer/backend/tests/test_writer_app_server_protocol.py::test_turn_interrupt_cancels_app_server_runtime_task members/writer/backend/tests/test_writer_app_server_protocol.py::test_turn_start_operation_returns_error_without_required_fields -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_cli.py -q`
- `py -3.14 -m pytest core/tests/test_agent_app_contract.py core/tests/test_app_factory.py core/tests/test_member_manifest.py core/tests/test_member_registry.py core/tests/test_run_item_snapshot.py -q`
- `rg -n "accept_turn_start|handle_turn_start_operation|def _turn_start" members/writer/backend/app/app_server/connection.py members/writer/backend/app/app_server/operations.py`
- `git diff --check`

当前收缩：

- `turn.start` / `turn.cancel` / `approval.respond` 三个核心控制入口都已经通过 Writer operation handler 承担业务入口。
- websocket connection 仍负责 transport、事件通知、runtime task 启动、queue、artifact 和 approval continuation；下一步应继续削减这些职责。

下一步：

- 继续 Step 3：拆 queue create/update/delete 或 artifact read/open 这类不触发 runtime 的 handler，进一步把 connection 压成 transport 层。

### 9.95 执行记录：2026-07-01 第九十五切片

目标：

- 继续执行 Step 3：拆 queue create/update/delete。
- 将不触发 runtime 的队列操作迁到 Writer operation handler，connection 只负责发送 response 和 event notification。

已完成：

- `members/writer/backend/app/app_server/operations.py` 新增：
  - `handle_queue_create_operation()`
  - `handle_queue_update_operation()`
  - `handle_queue_delete_operation()`
- `queue/create` 的业务逻辑迁出 connection：
  - 校验 `thread_id` / `client_message_id` / `input`。
  - 调用 `accept_queue_item()`。
  - 读取 snapshot 并构造 RPC response。
- `queue/update` 的业务逻辑迁出 connection：
  - 校验 `thread_id` / `queue_item_id` / `text`。
  - 调用 `update_queue_item()`。
  - 读取 snapshot 并构造 RPC response。
- `queue/delete` 的业务逻辑迁出 connection：
  - 校验 `thread_id` / `queue_item_id`。
  - 调用 `delete_queue_item()`。
  - 读取 snapshot 并构造 RPC response。
- connection 的 queue handlers 现在只调用 operation handler、发送 response、发送 event notification。
- 增加 queue operation 参数校验单测。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py::test_queue_operations_return_validation_errors members/writer/backend/tests/test_writer_app_queue.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_cli.py -q`
- `py -3.14 -m pytest core/tests/test_agent_app_contract.py core/tests/test_app_factory.py core/tests/test_member_manifest.py core/tests/test_member_registry.py core/tests/test_run_item_snapshot.py -q`
- `rg -n "accept_queue_item|update_queue_item|delete_queue_item|handle_queue_(create|update|delete)_operation|async def _queue_(create|update|delete)" members/writer/backend/app/app_server/connection.py members/writer/backend/app/app_server/operations.py`
- `git diff --check`

当前收缩：

- `turn.start` / `turn.cancel` / `approval.respond` / queue create-update-delete 都已经通过 Writer operation handler 承担业务入口。
- connection 还保留 artifact read/open、turn steer、runtime dispatch/continuation/failure 等职责。

下一步：

- 继续 Step 3：拆 artifact read/open 或 turn.steer；优先选择 artifact read/open，因为它们不触发 runtime。

### 9.96 执行记录：2026-07-01 第九十六切片

目标：

- 继续执行 Step 3：拆 artifact read/open。
- 将不触发 runtime 的 artifact 操作迁到 Writer operation handler，connection 只负责发送 RPC response。

已完成：

- `members/writer/backend/app/app_server/operations.py` 新增：
  - `handle_artifact_read_operation()`
  - `handle_artifact_open_operation()`
- `artifact/read` 的业务逻辑迁出 connection：
  - 校验 `thread_id` / `artifact_id`。
  - 调用 `read_artifact()`。
  - 统一转换 LookupError 为 RPC error。
- `artifact/open` 的业务逻辑迁出 connection：
  - 校验 `thread_id` / `artifact_id`。
  - 调用 `open_artifact()`。
  - 统一转换 LookupError / ValueError / FileNotFoundError 为 RPC error。
- connection 的 artifact handlers 现在只调用 operation handler 并发送 response。
- 增加 artifact operation 参数校验单测。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py::test_artifact_operations_return_validation_errors members/writer/backend/tests/test_writer_app_runtime_bridge.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_cli.py -q`
- `py -3.14 -m pytest core/tests/test_agent_app_contract.py core/tests/test_app_factory.py core/tests/test_member_manifest.py core/tests/test_member_registry.py core/tests/test_run_item_snapshot.py -q`
- `rg -n "open_artifact|read_artifact|handle_artifact_(read|open)_operation|async def _artifact_(read|open)" members/writer/backend/app/app_server/connection.py members/writer/backend/app/app_server/operations.py`
- `git diff --check`

验证备注：

- Windows / Python 3.14 下完整 Writer 相关测试结束时出现一次 asyncio closed pipe 的 unraisable warning，测试结果为通过，未影响断言。

当前收缩：

- `turn.start` / `turn.cancel` / `approval.respond` / queue create-update-delete / artifact read-open 都已经通过 Writer operation handler 承担业务入口。
- connection 还保留 turn.steer、runtime dispatch/continuation/failure、thread read/start/resume、hub/websocket transport 等职责。

下一步：

- 继续 Step 3：拆 `turn.steer` 或 thread read/start/resume；优先拆 `turn.steer`，使 turn 控制族都归 operation handler。

### 9.97 执行记录：2026-07-01 第九十七切片

目标：

- 继续执行 Step 3：拆 `turn.steer`。
- 让 turn 控制族 `turn.start` / `turn.cancel` / `turn.steer` 都归 Writer operation handler。

已完成：

- `members/writer/backend/app/app_server/operations.py` 新增 `handle_turn_steer_operation()`。
- `turn.steer` 的业务逻辑迁出 connection：
  - 校验 `thread_id` / `turn_id` / `client_message_id` / `input`。
  - 调用 `accept_turn_steer()`。
  - 读取 snapshot 并构造 RPC response。
- connection 的 `_turn_steer()` 现在只调用 operation handler、发送 response、发送 event notification。
- connection 不再导入 `accept_turn_steer`。
- 增加缺少必填字段的 `turn.steer` operation 单测。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py::test_turn_steer_operation_returns_error_without_required_fields members/writer/backend/tests/test_writer_app_queue.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_cli.py -q`
- `py -3.14 -m pytest core/tests/test_agent_app_contract.py core/tests/test_app_factory.py core/tests/test_member_manifest.py core/tests/test_member_registry.py core/tests/test_run_item_snapshot.py -q`
- `rg -n "accept_turn_steer|handle_turn_steer_operation|async def _turn_steer" members/writer/backend/app/app_server/connection.py members/writer/backend/app/app_server/operations.py`
- `git diff --check`

验证备注：

- Windows / Python 3.14 下完整 Writer 相关测试结束时出现一次 asyncio closed pipe 的 unraisable warning，测试结果为通过，未影响断言。

当前收缩：

- turn 控制族、approval、queue、artifact 操作都已迁到 Writer operation handler。
- connection 主要剩余职责：thread read/start/resume、runtime task 启动与失败收尾、approval continuation、queue dispatch、hub/websocket transport。

下一步：

- 继续 Step 3：拆 thread read/start/resume，或把 operation catalog 覆盖扩展到这些 thread 操作。

### 9.98 执行记录：2026-07-01 第九十八切片

目标：

- 继续执行 Step 3：拆 thread read/start/resume。
- 将 thread 普通请求入口迁到 Writer operation handler，connection 只保留订阅、发送 response 和 publish。

已完成：

- `members/writer/backend/app/app_server/operations.py` 新增：
  - `handle_thread_start_operation()`
  - `handle_thread_resume_operation()`
  - `handle_thread_read_operation()`
- `thread.start` 的业务逻辑迁出 connection：
  - 校验 `thread_id`。
  - 写入 `thread/started` event。
  - 应用 snapshot。
  - 返回 RPC response 和待 publish event。
- `thread.resume` 的业务逻辑迁出 connection：
  - 校验 `thread_id`。
  - 读取 after-seq events。
  - 读取 snapshot 并构造 RPC response。
- `thread.read` 的业务逻辑迁出 connection：
  - 校验 `thread_id`。
  - 读取 snapshot 并构造 RPC response。
- connection 对 thread handlers 只保留 `_subscribe()`、发送 response 和 publish。
- 测试不再通过 `connection_module.list_events_after` 依赖 connection 的偶然 import，改为直接从 ledger 导入。
- 增加 thread operation 参数校验单测。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py::test_thread_operations_return_validation_errors_without_thread_id members/writer/backend/tests/test_writer_app_server_protocol.py::test_snapshot_rebuild_includes_events_after_five_thousand -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py::test_turn_interrupt_cancels_app_server_runtime_task members/writer/backend/tests/test_writer_app_server_protocol.py::test_turn_interrupt_ignores_core_terminal_turn members/writer/backend/tests/test_writer_app_server_protocol.py::test_approval_continuation_failure_persists_core_error -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_cli.py -q`
- `py -3.14 -m pytest core/tests/test_agent_app_contract.py core/tests/test_app_factory.py core/tests/test_member_manifest.py core/tests/test_member_registry.py core/tests/test_run_item_snapshot.py -q`
- `rg -n "append_event|list_events_after|AppendEventInput|handle_thread_(start|resume|read)_operation|async def _thread_(start|resume|read)" members/writer/backend/app/app_server/connection.py members/writer/backend/app/app_server/operations.py`
- `git diff --check`

验证备注：

- Windows / Python 3.14 下完整 Writer 相关测试结束时出现一次 asyncio closed pipe 的 unraisable warning，测试结果为通过，未影响断言。

当前收缩：

- thread、turn、approval、queue、artifact 的普通 RPC 入口都已经通过 Writer operation handler 承担业务入口。
- connection 主要剩余职责：初始化、websocket/hub transport、runtime task 启动、runtime failure 收尾、queue dispatch、approval continuation。

下一步：

- 继续 Step 3：将 operation catalog 覆盖扩展到 thread / queue / artifact / turn.steer，减少 `_handle_raw()` 中的旧 handler dict。

### 9.99 执行记录：2026-07-01 第九十九切片

目标：

- 继续执行 Step 3：扩展 operation catalog 覆盖。
- 删除 `_handle_raw()` 中的旧 handler dict，让普通 RPC 统一走 Core `OperationCatalog`。

已完成：

- `build_writer_operation_catalog()` 覆盖以下 operation：
  - `thread.read`
  - `thread.resume`
  - `thread.start`
  - `turn.start`
  - `turn.steer`
  - `turn.cancel`
  - `approval.respond`
  - `queue.create`
  - `queue.update`
  - `queue.delete`
  - `artifact.read`
  - `artifact.open`
- 删除 `WriterAppServerConnection._handle_raw()` 中的旧 handler dict。
- unsupported method 现在是在 operation catalog 查不到后直接返回 method-not-found。
- 增加测试确认 catalog 覆盖所有普通 app-server RPC operation。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py::test_writer_operation_catalog_wraps_rpc_handlers members/writer/backend/tests/test_writer_app_server_protocol.py::test_writer_operation_catalog_covers_app_server_rpc_methods members/writer/backend/tests/test_writer_app_server_protocol.py::test_connection_routes_dot_operations_through_core_catalog -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_cli.py -q`
- `py -3.14 -m pytest core/tests/test_agent_app_contract.py core/tests/test_app_factory.py core/tests/test_member_manifest.py core/tests/test_member_registry.py core/tests/test_run_item_snapshot.py -q`
- `rg -n "handler = \{|Unsupported method|build_writer_operation_catalog\(|catalog\.register" members/writer/backend/app/app_server/connection.py members/writer/backend/app/app_server/operations.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `git diff --check`

验证备注：

- Windows / Python 3.14 下完整 Writer 相关测试结束时出现一次 asyncio closed pipe 的 unraisable warning，测试结果为通过，未影响断言。

当前收缩：

- app-server 普通 RPC 已统一通过 operation catalog 分发。
- connection 已明显收缩为 websocket/hub transport、初始化、operation bridge、runtime task 生命周期和少量 continuation/failure helper。

下一步：

- 继续 Step 3 或进入 Step 4 前置：拆 runtime task 启动/失败收尾/queue dispatch/approval continuation 中可独立成 adapter 的部分。

### 9.100 执行记录：2026-07-01 第一百切片

目标：

- 继续执行 Step 3，并为 Step 4 做前置收口。
- 将 Writer app-server connection 中的 runtime task 生命周期、失败收尾、queue dispatch、approval continuation 抽到独立 adapter，connection 保持 transport / subscribe / operation bridge 角色。

已完成：

- 新增 `members/writer/backend/app/app_server/runtime.py`。
- 新增 `WriterRuntimeLifecycle`，集中承载：
  - runtime task 启动和重复启动保护。
  - 调用 Writer runtime 发送消息。
  - runtime cancel / error 后写入 Core run-item 失败事实并 publish。
  - completed turn 后 FIFO dispatch queue item，并自动启动下一轮 runtime。
  - approval response 后继续 waiting request；失败时写入 Core error / status。
- `members/writer/backend/app/app_server/connection.py` 删除 runtime / queue / approval continuation 的大段实现。
- connection 保留 `_start_writer_runtime()`、`_dispatch_next_queue_item()`、`_continue_resolved_approval()` 薄入口，兼容既有测试与调用点，内部委托 `WriterRuntimeLifecycle`。
- 删除 connection 中已无调用的 `_runtime_context()` / `_input_text()` 旧辅助函数。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime.py members/writer/backend/app/app_server/connection.py`
- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py::test_turn_start_passes_existing_app_server_message_and_turn_to_runtime members/writer/backend/tests/test_writer_app_server_protocol.py::test_turn_interrupt_cancels_app_server_runtime_task members/writer/backend/tests/test_writer_app_server_protocol.py::test_client_json_rpc_response_resolves_server_request members/writer/backend/tests/test_writer_app_server_protocol.py::test_approval_continuation_failure_persists_core_error -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_cli.py -q`
- `py -3.14 -m pytest core/tests/test_agent_app_contract.py core/tests/test_app_factory.py core/tests/test_member_manifest.py core/tests/test_member_registry.py core/tests/test_run_item_snapshot.py -q`
- `rg -n "_run_writer_runtime|_finish_runtime_failed|_publish_approval_continuation_error|_find_single_open_waiting_block|WriterRuntimeLifecycle|dispatch_next_queue_item" members/writer/backend/app/app_server/connection.py members/writer/backend/app/app_server/runtime.py`
- `git diff --check`

验证备注：

- Writer 相关完整回归 89 passed。
- Core contract 相关回归 42 passed。
- Windows / Python 3.14 下完整 Writer 相关测试结束时仍出现一次 asyncio closed pipe 的 unraisable warning，测试结果为通过，未影响断言。
- `git diff --check` 通过；PowerShell 输出了既有 CRLF 转换 warning。

当前收缩：

- connection 从普通 RPC 分发、业务操作、运行生命周期混合体，进一步收缩为 websocket/hub transport、初始化、operation bridge 与少量兼容薄入口。
- runtime lifecycle 的状态落库、publish、queue dispatch、approval continuation 形成独立 adapter，后续更容易下沉到 Core app seam 或 Writer MemberKit。

下一步：

- 继续 Step 4：检查 event / snapshot / runtime lifecycle 是否还有 Writer app-server 独占投影链路；优先删除重复投影或把可共用的事实写入路径收敛到 Core contract。

### 9.101 执行记录：2026-07-01 第一百零一切片

目标：

- 继续 Step 4 前置收口：减少 Writer runtime lifecycle 内部对 run-item event / snapshot 的手写持久化路径。
- 对照成熟事件流做法，保持“runtime 事实 -> Core run item -> app snapshot 派生”的单一路径，不新增平行状态链。

已完成：

- `members/writer/backend/app/app_server/runtime.py` 的 runtime failed 和 approval continuation failed 不再手写：
  - `append_run_item_event()`
  - `apply_event_to_snapshot()`
- 改为统一调用 `persist_run_item_events_as_app_events()`。
- runtime lifecycle 仍负责构造失败事实和 publish；落库、artifact/request 副作用、snapshot 应用继续由 runtime bridge 统一承担。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime.py members/writer/backend/app/app_server/runtime_bridge.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py::test_turn_interrupt_cancels_app_server_runtime_task members/writer/backend/tests/test_writer_app_server_protocol.py::test_approval_continuation_failure_persists_core_error members/writer/backend/tests/test_writer_app_runtime_bridge.py::test_runtime_bridge_persists_error_as_core_fact -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_cli.py -q`
- `py -3.14 -m pytest core/tests/test_agent_app_contract.py core/tests/test_app_factory.py core/tests/test_member_manifest.py core/tests/test_member_registry.py core/tests/test_run_item_snapshot.py -q`

验证备注：

- Writer 相关完整回归 89 passed。
- Core contract 相关回归 42 passed。
- Windows / Python 3.14 下完整 Writer 相关测试结束时仍出现一次 asyncio closed pipe 的 unraisable warning，测试结果为通过，未影响断言。

当前收缩：

- runtime lifecycle 不再直接知道 run-item envelope 怎样应用到 snapshot。
- Core run-item 投影写入路径进一步集中到 runtime bridge，后续可以把 bridge interface 下沉为 member adapter。

下一步：

- 继续 Step 4：检查 approval 主流程、queue dispatch、operation handler 中的 `append/apply/load` 是否能收敛为更小的 app-event store interface；优先找重复最多且测试覆盖明确的位置。

### 9.102 执行记录：2026-07-01 第一百零二切片

目标：

- 继续 Step 4：把 Writer app-server 中重复的 `append event -> apply snapshot` 手写链路收敛为小接口。
- 保持事件事实仍是唯一写入源，snapshot 继续作为派生状态。

已完成：

- 新增 `members/writer/backend/app/app_server/event_store.py`。
- 提供三个小接口：
  - `append_event_and_apply_snapshot()`
  - `append_events_and_apply_snapshot()`
  - `append_run_item_event_and_apply_snapshot()`
- 替换重复写法：
  - `queue.py` 的批量事件追加与 snapshot 应用。
  - `runtime_bridge.py` 的 Core run-item 写入与 snapshot 应用。
  - `approvals.py` 的 approval response run-item 写入，以及新的 resolved app event 写入。
  - `operations.py` 中 `thread.start` / `turn.cancel` 的 app event 写入。
- `approvals.py` 中已 resolved 的幂等分支继续只 append resolved app event，不额外 apply snapshot，避免改变既有行为。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/event_store.py members/writer/backend/app/app_server/approvals.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/queue.py members/writer/backend/app/app_server/runtime_bridge.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_event_ledger.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_cli.py -q`
- `py -3.14 -m pytest core/tests/test_agent_app_contract.py core/tests/test_app_factory.py core/tests/test_member_manifest.py core/tests/test_member_registry.py core/tests/test_run_item_snapshot.py -q`

验证备注：

- 本切片覆盖测试 67 passed。
- Writer 相关完整回归 89 passed。
- Core contract 相关回归 42 passed。
- Windows / Python 3.14 下测试仍出现一次 asyncio closed pipe 的 unraisable warning，测试结果为通过，未影响断言。

当前收缩：

- app-server 的 event fact 写入和 snapshot 派生关系更集中，调用方不再重复知道“写入后必须 apply snapshot”的顺序。
- 这一步没有引入新状态模型，只把既有顺序封装成更深的写入接口。

下一步：

- 继续 Step 4：检查 `load_snapshot()` 后立即返回 RPC snapshot 的 handler，判断是否需要形成 read-side helper；如果收益不够，转入前端去旧投影链路扫描。

### 9.103 执行记录：2026-07-01 第一百零三切片

目标：

- 继续 Step 4：收敛 Writer app-server operation handler 中“写事件后立即读 snapshot”的读写顺序。
- 不新增平行状态链，继续保持 event fact 为唯一写入源，snapshot 为派生状态。

已完成：

- `members/writer/backend/app/app_server/event_store.py` 新增 `append_event_and_load_snapshot()`。
- `thread.start` 和 `turn.cancel` 不再手写：
  - append app event。
  - apply snapshot。
  - 再 load snapshot。
- 新增事件存储单测，覆盖 append event 后返回当前 snapshot 的契约。
- 盘点剩余 `load_snapshot()` 调用：
  - 纯读 handler 保持不动。
  - queue / turn / approval 的调用点多数是在已有 helper 完成写入后读取结果，当前不强行抽浅接口。
  - 前端 app-server 路径当前主要消费 snapshot selector，但相关文件存在未提交改动，本切片不触碰前端。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/event_store.py members/writer/backend/app/app_server/operations.py members/writer/backend/tests/test_writer_app_event_ledger.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_event_ledger.py::test_event_store_appends_event_and_returns_current_snapshot members/writer/backend/tests/test_writer_app_server_protocol.py::test_thread_operations_return_validation_errors_without_thread_id members/writer/backend/tests/test_writer_app_server_protocol.py::test_turn_interrupt_cancels_app_server_runtime_task -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_event_ledger.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_cli.py -q`
- `py -3.14 -m pytest core/tests/test_agent_app_contract.py core/tests/test_app_factory.py core/tests/test_member_manifest.py core/tests/test_member_registry.py core/tests/test_run_item_snapshot.py -q`

验证备注：

- Writer/app-server 相关回归 94 passed。
- Core contract 相关回归 42 passed。
- Windows / Python 3.14 下测试仍出现一次 asyncio closed pipe 的 unraisable warning，测试结果为通过，未影响断言。

当前收缩：

- event store 的 interface 覆盖“写事实并返回派生快照”的常见操作，operation handler 更少知道内部顺序。
- 剩余读侧调用不再是明显重复的 append/apply/load 三连，下一步更适合转向前端旧投影链路或更高层 Core store seam。

下一步：

- 进入 Step 5 前置扫描：前端是否仍有绕过 app-server snapshot 的旧投影链路；先只做盘点和可删面识别，避免覆盖当前未提交前端改动。

### 9.104 执行记录：2026-07-01 第一百零四切片

目标：

- 进入 Step 5 前置扫描：确认 Writer 前端是否仍绕过 app-server snapshot 使用旧 messages/events 投影链路。
- 只做证据盘点，不覆盖当前未提交的前端改动。

已完成：

- 扫描 Writer 前端 app-server 主线：
  - `members/writer/frontend/src/appServer/store.ts`
  - `members/writer/frontend/src/appServer/selectors.ts`
  - `members/writer/frontend/src/appServer/snapshot.ts`
  - `members/writer/frontend/src/views/CoreWorkbenchView.vue`
- 确认当前主渲染路径：
  - websocket 收到 `thread/snapshot` 后 hydrate snapshot。
  - `CoreWorkbenchView.vue` 通过 `selectChatMessages(appServerStore.state)` 渲染消息。
  - queue tray 通过 `selectQueueTray(appServerStore.state)` 渲染。
- 确认旧 Core events 路径：
  - `members/writer/frontend/src/api/core.ts#getCoreEvents()` 当前返回空数组。
  - `getCoreMessages()` / `createCoreMessage()` / `getCoreEvents()` 仍作为 `useCoreWorkbenchController` 的 `coreApi` contract 字段传入。
  - `coreMessages` / `events` 在 Writer workbench 当前主渲染里未直接使用。
- 当前不删除前端旧接口的原因：
  - `CoreWorkbenchView.vue` 与 `appServer/store.ts` 已存在未提交改动。
  - `useCoreWorkbenchController` 仍要求通用 CoreWorkbench API shape；直接删除会牵动 `@lamtools/ui` contract，而不是单纯删除 Writer 旧投影。

验证：

- `rg -n "getCoreMessages|getCoreEvents|createCoreMessage|coreMessages|events\\b|useCoreWorkbenchController|selectChatMessages|selectQueueTray|hydrateSnapshot|thread/snapshot|transcriptSnapshot|projectTranscriptSnapshot" members/writer/frontend/src -g "*.ts" -g "*.vue"`
- `rg -n "getCoreMessages|getCoreEvents|createCoreMessage|messages: coreMessages|\\bevents,|coreMessages\\b|events\\.value|coreApi" members/writer/frontend/src/views/CoreWorkbenchView.vue members/writer/frontend/src -g "*.ts" -g "*.vue"`
- `git diff -- members/writer/frontend/src/appServer/store.ts members/writer/frontend/src/views/CoreWorkbenchView.vue --stat`

当前判断：

- Writer GUI 主显示已经基本迁到 app-server snapshot selector。
- 剩余旧 read contract 不是 Writer projection 逻辑本身，而是通用 workbench controller 仍要求 message/event API 字段。
- 下一步如果要删除旧接口，应先在 `@lamtools/ui` / CoreWorkbench controller contract 上提供 thin-session 模式，或让 Writer workbench 不再通过旧 message/event contract 初始化。

下一步：

- Step 5 实施切片应从 UI contract 入手：让 Writer workbench 的主路径只声明 session/provider 能力，消息与事件完全由 app-server snapshot store 提供。
- 在动前端前需先合并或明确保留当前未提交 thinking controls 改动，避免覆盖用户侧工作。

### 9.105 执行记录：2026-07-01 第一百零五切片

目标：

- 继续 Step 5：让 Core UI workbench controller 支持 thin-session 模式。
- Writer workbench 主路径不再声明旧 `getMessages()` / `createMessage()` / `getEvents()` 能力，消息和事件显示继续由 app-server snapshot store 提供。

已完成：

- `core/ui/src/composables/useCoreWorkbenchController.ts`
  - `CoreWorkbenchApi.getMessages` 改为可选。
  - `CoreWorkbenchApi.createMessage` 改为可选。
  - `CoreWorkbenchApi.getEvents` 改为可选。
  - `selectSession()` 在缺少 messages/events 能力时返回空数组，不再要求旧 read contract。
  - `sendMessage()` 在缺少 `createMessage` 时直接返回，避免 thin-session 模式误清空 composer。
- `members/writer/frontend/src/views/CoreWorkbenchView.vue`
  - 删除 Writer workbench 对 `getCoreMessages` / `createCoreMessage` / `getCoreEvents` 的导入。
  - `coreApi` 只声明 session/provider 能力。
  - 不再从 `useCoreWorkbenchController()` 解构 `coreMessages` / `events`。
- `members/artist/frontend/src/lamtools-ui.d.ts`
  - 同步 Core UI 类型声明，保持 Artist 本地声明与 Core contract 一致。

验证：

- `npm.cmd run typecheck`，工作目录 `core/ui`
- `npm.cmd test -- --runInBand`，工作目录 `members/writer/frontend`
- `npm.cmd run build`，工作目录 `members/writer/frontend`
- `rg -n "getCoreMessages|getCoreEvents|createCoreMessage|coreMessages\\b|\\bevents\\b" members/writer/frontend/src/views/CoreWorkbenchView.vue core/ui/src/composables/useCoreWorkbenchController.ts`

验证备注：

- Core UI typecheck 通过。
- Writer frontend app-server tests 20 passed。
- Writer frontend build 通过。
- Vite build 输出 chunk-size warning 和 plugin timing warning，构建成功，未影响本切片。

当前收缩：

- Writer workbench 不再通过旧 messages/events API 声明主显示能力。
- `useCoreWorkbenchController` 从强制 message/event reader 变成 session-first controller，Writer 的消息显示由 app-server snapshot selector 独立承担。
- Artist 和新 member 模板仍可继续传入 messages/events 能力，不破坏现有调用方。

下一步：

- Step 5 继续：删除 Writer frontend `api/core.ts` 中已不再被 Writer workbench 使用的 `getCoreMessages()` / `createCoreMessage()` / `getCoreEvents()`，或先确认是否还有其它入口引用。

### 9.106 执行记录：2026-07-01 第一百零六切片

目标：

- 继续 Step 5：删除 Writer 前端中已经无调用方的旧 Core message/event API helper。
- 保持新成员模板和 Artist 仍可继续使用通用 messages/events 能力。

已完成：

- `members/writer/frontend/src/api/core.ts`
  - 删除 `getCoreMessages()`。
  - 删除 `createCoreMessage()`。
  - 删除 `getCoreEvents()`。
  - 删除不再需要的 `createMessageMapper`、`CoreMessageRawLike`、`CoreMessage`、`CoreRuntimeEvent` 引用。
- 保留 Writer frontend `listCoreSessions()` / `createCoreSession()` / `listCoreProviders()`。
- 不修改 `core/templates/member` 和 Artist 的旧 message/event API：这些仍是通用 controller 的兼容使用方。

验证：

- `rg -n "getCoreMessages|createCoreMessage|getCoreEvents|createMessageMapper|CoreMessageRawLike|CoreRuntimeEvent" members/writer/frontend/src -g "*.ts" -g "*.vue"`
- `npm.cmd test -- --runInBand`，工作目录 `members/writer/frontend`
- `npm.cmd run build`，工作目录 `members/writer/frontend`

验证备注：

- Writer frontend app-server tests 20 passed。
- Writer frontend build 通过。
- `rg` 对 Writer frontend 无匹配，说明旧 helper 和旧 event type 已从 Writer 前端移除。
- Vite build 仍输出 chunk-size warning，构建成功，未影响本切片。

当前收缩：

- Writer frontend 不再保留旧 `/api/core/sessions/{id}/messages` 和 events helper。
- Writer GUI 主线进一步收敛到 session/provider + app-server snapshot store。

下一步：

- Step 5 继续：从 Writer backend `/api/core/sessions/{id}/messages` / `events` 旧接口入手，核实是否只剩非 Writer 主线使用；可删则删除或明确降级。

### 9.107 执行记录：2026-07-01 第一百零七切片

目标：

- 继续 Step 5：删除 Writer backend Core HTTP adapter 中的旧 message route。
- 让 Writer `/api/core` adapter 只保留当前仍服务 GUI 的 session/provider/usage 能力；消息显示继续由 app-server snapshot 提供。

已完成：

- `members/writer/backend/app/routers/core_http.py`
  - 删除 `CoreMessageCreate`。
  - 删除 `_message_to_core()`。
  - 删除 `GET /api/core/sessions/{session_id}/messages`。
  - 删除 `POST /api/core/sessions/{session_id}/messages`。
  - 删除不再需要的 `WriterMessage` / `Field` 引用。
- `members/writer/backend/tests/test_core_http_writer_unit.py`
  - 删除旧 message ordering 保护测试。
  - 新增测试确认 Writer Core message GET/POST route 不再挂载。
  - 保留 events route 未挂载测试。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/routers/core_http.py members/writer/backend/tests/test_core_http_writer_unit.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_core_http_writer_unit.py members/writer/backend/tests/test_main_core_app_unit.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_core_http_writer_unit.py members/writer/backend/tests/test_main_core_app_unit.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_cli.py -q`
- `py -3.14 -m pytest core/tests/test_agent_app_contract.py core/tests/test_app_factory.py core/tests/test_member_manifest.py core/tests/test_member_registry.py core/tests/test_run_item_snapshot.py -q`
- `rg -n -F 'CoreMessageCreate' ...` / `WriterMessage` / `_message_to_core` / `/sessions/{session_id}/messages`

验证备注：

- Writer backend targeted tests 25 passed。
- Writer/backend app-server + core-http 回归 114 passed。
- Core contract 相关回归 42 passed。
- Windows / Python 3.14 下测试仍出现一次 asyncio closed pipe 的 unraisable warning，测试结果为通过，未影响断言。

当前收缩：

- Writer 前后端旧 Core message route 已从 Writer 主线删除。
- Writer GUI 的消息事实源进一步收敛到 app-server snapshot，而不是 `/api/core/messages`。

下一步：

- Step 5 继续：检查 Writer `members/writer/frontend/src/api/index.ts` 和旧 `/api/sessions/{id}/messages` 是否仍是历史 transcript/API 兼容；若 GUI 主线不再依赖，标注或收敛到 transcript/app-server 边界。

### 9.108 执行记录：2026-07-01 第一百零八切片

目标：

- 继续 Step 5：删除 Writer 前端旧 `/api/sessions/{id}/messages` helper 和 session store 中无调用方的 message state。
- 保留 `clearMessages()` 作为兼容 no-op，避免碰当前 workbench 会话切换代码。

已完成：

- `members/writer/frontend/src/api/index.ts`
  - 删除 `getMessages()`。
  - 删除 `sendMessage()`。
  - 删除不再需要的 `Message` import。
- `members/writer/frontend/src/stores/session.ts`
  - 删除 `messages` state。
  - 删除 `fetchMessages()`。
  - 删除 `appendMessage()`。
  - 删除 `upsertMessage()`。
  - `clearMessages()` 改为 no-op，并明确注释：Writer messages 由 app-server snapshot 渲染。
- 保留 `members/writer/frontend/src/types/index.ts#Message`，因为 `runtime-types.ts` 仍作为历史 runtime union 使用该类型。

验证：

- `rg -n "getMessages\\(|sendMessage\\(|fetchMessages\\(|appendMessage\\(|upsertMessage\\(|sessionStore\\.messages|/api/sessions/\\$\\{sessionId\\}/messages|\\bMessage\\b" members/writer/frontend/src -g "*.ts" -g "*.vue"`
- `npm.cmd test -- --runInBand`，工作目录 `members/writer/frontend`
- `npm.cmd run build`，工作目录 `members/writer/frontend`

验证备注：

- Writer frontend app-server tests 20 passed。
- Writer frontend build 通过。
- 搜索结果只剩 `Message` 类型定义及 `runtime-types.ts` 历史 union 引用；旧 messages API/helper/store 方法无匹配。
- Vite build 仍输出 chunk-size warning，构建成功，未影响本切片。

当前收缩：

- Writer 前端不再调用旧 `/api/sessions/{id}/messages`。
- Writer 主 UI 的消息来源已进一步限定到 app-server snapshot store。

下一步：

- Step 5 继续：核实 backend `app/routers/session.py` 中旧 `/api/sessions/{id}/messages` 是否还被非前端路径使用；若仅服务历史兼容，改为 deprecated 或删除。

### 9.109 执行记录：2026-07-01 第一百零九切片

目标：

- 继续 Step 5：删除 Writer 后端普通 session 层旧 `/api/sessions/{id}/messages` GET/POST 路由。
- 保留内部 `writer_messages` 表和 Writer service message 方法，因为 runtime/transcript 历史上下文仍依赖这层存储事实。
- 移除写死 session id/workdir、依赖旧 messages 路由的临时轮询脚本，避免留下误导入口。

已完成：

- `members/writer/backend/app/routers/session.py`
  - 删除普通 session messages GET 路由。
  - 删除普通 session messages POST 路由。
  - 删除只服务该路由的 request/response schema。
- `members/writer/backend/app/main.py`
  - Core HTTP manifest 描述移除 `messages`。
- `members/writer/backend/tests/test_core_http_writer_unit.py`
  - 增加断言：`/api/sessions/{id}/messages` GET/POST 不再挂载。
  - 保留 `/api/sessions` 创建和列表测试，确认普通 session CRUD 未被误删。
- 删除临时脚本：
  - `members/writer/backend/tests/poll_final.py`
  - `members/writer/backend/tests/poll_until_done.py`
  - `members/writer/backend/tests/wait_final.py`

验证：

- `rg -n "MessageCreate|MessageResponse|def get_messages\\(|def send_message\\(|/sessions/\\{session_id\\}/messages|/api/sessions/.*/messages" members/writer/backend/app members/writer/backend/tests -g "*.py"`
- `py -3.14 -m pytest members/writer/backend/tests/test_core_http_writer_unit.py members/writer/backend/tests/test_main_core_app_unit.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_core_http_writer_unit.py members/writer/backend/tests/test_main_core_app_unit.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_cli.py -q`

验证备注：

- Writer backend session/core-http 定向测试 26 passed。
- Writer backend app-server + core-http 回归 115 passed。
- Windows / Python 3.14 下仍出现一次 asyncio closed pipe 的 unraisable warning，断言全部通过。
- 搜索结果中旧 HTTP route 只剩测试断言；`writer_service.py` 的 `get_messages` / `send_message` 是内部 service 方法，暂不删除。

当前收缩：

- Writer GUI 和普通 `/api/sessions` 层都不再暴露旧 messages HTTP surface。
- Writer 消息事实源继续向 app-server snapshot / transcript 存储收敛。

下一步：

- Step 5 继续：盘点 `writer_service.py` 内部 message 方法是否仍是 runtime 必需接口；若仅是历史双写/旧 service 封装，再拆到 transcript 边界或删除调用方。

### 9.110 执行记录：2026-07-01 第一百一十切片

目标：

- 继续 Step 5：删除 `writer_service.py` 中已无调用方的 message 查询 service 面。
- 保留 `send_message` 执行入口，因为 app-server bridge、Writer service 测试和 transcript/runtime 路径仍通过它覆盖主执行流程。

已完成：

- `members/writer/backend/app/services/writer_service.py`
  - 删除 `get_messages` closure。
  - 从 service dict 中移除 `"get_messages"`。
  - 删除只服务 `get_messages` 的 `_message_to_dict()`。
  - 更新 service dict 说明，只保留 `send_message`。

验证：

- `rg -n "get_messages|_message_to_dict|send_message, get_messages" members/writer/backend/app members/writer/backend/tests docs/core-member-architecture-refactor-design-2026-06-30.md -g "*.py" -g "*.md"`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_realtime_transcript_contract.py members/writer/backend/tests/test_writer_app_runtime_bridge.py -q`

验证备注：

- Writer service/runtime 定向测试 52 passed。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。
- 代码搜索中 `get_messages` 只剩历史执行记录文本；app/tests 中无调用方。

当前收缩：

- Writer service 对外返回面少一个历史查询入口。
- 旧 message 读取职责不再同时存在于 HTTP route、frontend store、service dict 三个位置。

下一步：

- Step 5 继续：检查 Writer message 写入是否仍存在双路径；若 app-server 已能提供 turn/user message，则把剩余写入收敛到 transcript/app-server 发起点，避免旧 service 自建用户消息成为并行入口。

### 9.111 执行记录：2026-07-01 第一百一十一切片

目标：

- 继续 Step 5：收敛 Writer 用户输入写入规则，避免 app-server queue 和 Writer service fallback 各自手写 `WriterMessage + TranscriptTurn`。
- 不删除 `send_message`，因为它仍是 app-server runtime 调用 Writer 执行的入口，也承载非 app-server service 测试覆盖。

已完成：

- `members/writer/backend/app/services/transcript_service.py`
  - 新增 `create_user_message_turn()`，统一创建 user message、transcript turn，并可绑定 attachment。
- `members/writer/backend/app/app_server/queue.py`
  - `accept_turn_start()` 改为复用 `create_user_message_turn()`。
  - 保留 queue item 自身 id 的 `gen_uuid()`。
- `members/writer/backend/app/services/writer_service.py`
  - 非 app-server fallback 分支改为复用 `create_user_message_turn()`。
  - 保留 app-server 传入 `transcript_turn_id/user_message_id` 时的复用校验，防止重复创建 user message/turn。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/transcript_service.py members/writer/backend/app/app_server/queue.py members/writer/backend/app/services/writer_service.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_runtime_bridge.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_realtime_transcript_contract.py members/writer/backend/tests/test_writer_transcript_service.py -q`

验证备注：

- 语法检查通过。
- Writer app-server queue/runtime bridge 36 passed。
- Writer service/realtime transcript/transcript service 31 passed。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- 用户输入写入规则从两个手写实现收敛到 transcript 边界的一处 helper。
- app-server 主路径和 service fallback 都以同一 invariant 创建 user message + transcript turn。

下一步：

- Step 5 继续：检查 `send_message` 是否可以改名或缩窄为 `run_existing_or_new_turn` 这类更准确的内部接口；若外部只剩 app-server runtime，可进一步把 Writer service dict 的接口面缩小。

### 9.112 执行记录：2026-07-01 第一百一十二切片

目标：

- 继续 Step 5：把 Writer service dict 中历史聊天语义的 `send_message` interface 改成运行语义的 `run_turn`。
- 明确该 interface 是 app-server runtime 调用 Writer 执行一轮 transcript turn，不再暗示旧 HTTP message/chat surface。

已完成：

- `members/writer/backend/app/services/writer_service.py`
  - `send_message()` 更名为 `run_turn()`。
  - service dict key 从 `"send_message"` 改为 `"run_turn"`。
  - docstring 改为运行一轮 transcript turn。
- `members/writer/backend/app/app_server/runtime.py`
  - app-server runtime 改为调用 `service["run_turn"]`。
- 后端测试同步使用 `run_turn`：
  - `members/writer/backend/tests/test_writer_service.py`
  - `members/writer/backend/tests/test_writer_realtime_transcript_contract.py`
  - `members/writer/backend/tests/test_writer_app_runtime_bridge.py`
  - `members/writer/backend/tests/test_writer_app_server_protocol.py`

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/writer_service.py members/writer/backend/app/app_server/runtime.py members/writer/backend/app/app_server/connection.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_realtime_transcript_contract.py -q`
- `rg -n -F '["send_message"]' members/writer/backend/app members/writer/backend/tests -g "*.py"`
- `rg -n -F "['send_message']" members/writer/backend/app members/writer/backend/tests -g "*.py"`
- `rg -n "def send_message|async def send_message|send_message\\(" members/writer/backend/app members/writer/backend/tests -g "*.py"`

验证备注：

- 语法检查通过。
- Writer app-server protocol/runtime bridge/service/realtime transcript 76 passed。
- 旧 `send_message` backend app/tests 搜索无匹配。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- Writer service dict 不再暴露聊天/消息发送命名。
- app-server runtime 与 Writer service 的 seam 更贴近真实职责：运行一个 turn。

下一步：

- Step 5 继续：检查 app-server runtime 是否还通过全局 `session_router._service` 取 service dict；若只剩一个 adapter，可考虑把 runtime lifecycle 的依赖显式注入，减少全局可变入口。

### 9.113 执行记录：2026-07-01 第一百一十三切片

目标：

- 继续 Step 5：收敛 app-server runtime 对 Writer service 全局 `_service` 的直接读取。
- 让 `WriterRuntimeLifecycle` 的 Writer service 依赖成为可注入 interface，默认 provider 仍兼容当前启动注册路径。

已完成：

- `members/writer/backend/app/app_server/runtime.py`
  - `WriterRuntimeLifecycle` 新增 `service_provider` 构造参数。
  - 增加 `_writer_service()` 统一处理 service 缺失错误。
  - `_run()` 和 `continue_resolved_approval()` 不再直接在方法体内 import/read `session_router._service`。
  - 默认 provider 集中到 `_default_service_provider()`，作为当前启动路径的兼容 adapter。
- `members/writer/backend/tests/test_writer_app_server_protocol.py`
  - 新增测试：runtime lifecycle 可直接注入 fake Writer service，不依赖 monkeypatch 全局 `_service`。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_queue.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_core_http_writer_unit.py members/writer/backend/tests/test_main_core_app_unit.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_cli.py -q`
- `rg -n "session_router\\._service|_default_service_provider|service_provider|run_turn" members/writer/backend/app/app_server members/writer/backend/tests/test_writer_app_server_protocol.py -g "*.py"`

验证备注：

- 语法检查通过。
- Writer app-server protocol/runtime bridge/queue 61 passed。
- Writer app-server + core-http 回归 116 passed。
- 搜索显示 app-server runtime 内只剩 `_default_service_provider()` 这一处默认 adapter 读取 `session_router._service`；主逻辑通过 `service_provider` seam 获取 service。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- runtime lifecycle 的 Writer service dependency 从隐式全局读取收敛为显式可注入 interface。
- 旧全局 `_service` 仍存在，但被限制为默认 adapter；下一步可以考虑把启动阶段也迁到 app-server router/runtime factory。

下一步：

- Step 5 继续：检查 app-server connection 是否每次构造都隐式创建 runtime lifecycle；若需要更强测试/运行 seam，可让 connection 接收 runtime lifecycle 或 runtime factory。

### 9.114 执行记录：2026-07-01 第一百一十四切片

目标：

- 继续 Step 5：收敛 `WriterAppServerConnection` 对 runtime lifecycle 的硬编码创建。
- 让 connection 可接收 runtime lifecycle dependency，默认行为保持不变。

已完成：

- `members/writer/backend/app/app_server/connection.py`
  - `WriterAppServerConnection.__init__()` 新增 `runtime` 参数。
  - 未传入时仍默认创建 `WriterRuntimeLifecycle(session_factory=async_session)`。
  - `_start_writer_runtime()`、queue dispatch、approval continuation 继续通过 `self.runtime` 调用。
- `members/writer/backend/tests/test_writer_app_server_protocol.py`
  - 新增测试：connection 会使用注入的 runtime lifecycle dependency。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_runtime_bridge.py -q`

验证备注：

- 语法检查通过。
- Writer app-server protocol/runtime bridge 52 passed。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- connection 不再只能内部创建 runtime lifecycle。
- runtime lifecycle 已可注入 service provider，connection 已可注入 runtime；app-server transport 与 runtime 执行 seam 更清楚。

下一步：

- Step 5 继续：检查 app-server router 是否需要接收 connection factory；若无需继续加 seam，则转向 Step 6/完成定义中的 runtime 体量和旧事件族搜索。

### 9.115 执行记录：2026-07-01 第一百一十五切片

目标：

- 进入 Step 9：继续降低 `core_kernel_adapter.py` 体量，把启动预热、静态 prompt cache、MCP registry cache、stream HTTP client 资源管理抽到独立 module。
- 保持 WriterKit / CoreLoopKernel 主执行语义不变。

已完成：

- 新增 `members/writer/backend/app/core/writer/runtime_resources.py`
  - `stream_http_client()`
  - `static_prompt_messages()`
  - `cached_mcp_registry()`
  - `schedule_writer_startup_prewarm()`
  - `close_writer_runtime_resources()`
  - `runtime_now_prompt()`
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - 删除内联 startup/prompt/MCP/resource cache 实现。
  - 改为从 `runtime_resources.py` 导入小 interface。
  - `WriterLLMClientAdapter` streaming 路径改用 `stream_http_client()`。
  - `WriterKit.build_model_request()` 改用 `runtime_now_prompt()`。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/runtime_resources.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_prompt_assembler.py members/writer/backend/tests/test_hook_context_contract.py members/writer/backend/tests/test_tool_contracts.py members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `rg -n "_platform_prompt|_runtime_now_prompt|_stream_http_client|prewarm_writer_startup|_STATIC_PROMPT|_MCP_REGISTRY|_STREAM_HTTP|ProjectInstructionLoader|PROJECT_INSTRUCTION_FILES|get_writer_system_prompt" members/writer/backend/app/core/writer/core_kernel_adapter.py`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：4921 行。
  - `members/writer/backend/app/core/writer/runtime_resources.py`：206 行。

验证备注：

- 语法检查通过。
- Writer prompt/hook/tool/service/core-kernel targeted tests 251 passed。
- 旧 prompt/resource helper 在 `core_kernel_adapter.py` 无残留匹配。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 减少约 188 行，启动资源管理从主 adapter 中移出。
- Writer adapter 主文件更聚焦 LLM bridge、tool executor、WriterKit、run entry。

下一步：

- Step 9 继续：优先抽 `ReadOnlyToolExecutor` / `ReadWriteToolExecutor` 的工具执行实现，或把 network tools 与 command runner 分离，进一步让 `core_kernel_adapter.py` 接近 WriterKit + run entry。

### 9.116 执行记录：2026-07-01 第一百一十六切片

目标：

- 继续 Step 9：把 `web_search` / `web_fetch` / `browser_check` 网络工具从 `core_kernel_adapter.py` 移到独立 module。
- 保持 `ReadWriteToolExecutor.as_dict()` 暴露的工具名和外部契约不变。

已完成：

- 新增 `members/writer/backend/app/core/writer/web_tools.py`
  - `make_web_search_handler()`
  - `make_web_fetch_handler()`
  - `make_browser_check_handler()`
  - 内部保留 HTTP client cache 和 HTML readable text extraction。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - 删除内联网络工具实现、fetch timeout/user-agent 常量和 readable text helper。
  - `ReadWriteToolExecutor.as_dict()` 改为导入并注册 `web_tools.py` 的 handler factory。
- `members/writer/backend/tests/test_tool_contracts.py`
  - 网络工具测试的 monkeypatch 目标从旧主 adapter 改到 `web_tools.py`，断言不变。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/web_tools.py members/writer/backend/tests/test_tool_contracts.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `rg -n "_make_web_search_handler|_make_web_fetch_handler|_make_browser_check_handler|_extract_readable_text|_DEFAULT_FETCH_TIMEOUT|_FETCH_USER_AGENT|_WEB_SEARCH_URL|_HTTP_CLIENT" members/writer/backend/app/core/writer/core_kernel_adapter.py`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：4617 行。
  - `members/writer/backend/app/core/writer/web_tools.py`：316 行。

验证备注：

- 语法检查通过。
- Tool contracts 32 passed。
- Writer core kernel adapter 172 passed。
- Writer service 23 passed。
- 旧网络工具私有符号在 `core_kernel_adapter.py` 无残留匹配。
- 首次三组测试合并运行超过 124 秒超时，拆分后全部通过。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 从 4921 行降到 4617 行，减少 304 行。
- 网络工具成为单独 module，主 adapter 只负责把工具挂入 Writer 默认 executor。

下一步：

- Step 9 继续：优先抽命令执行/后台探测工具，或把 `ReadOnlyToolExecutor` / `ReadWriteToolExecutor` 拆成文件工具、命令工具、git 工具三组，继续减少主 adapter 体量。

### 9.117 执行记录：2026-07-01 第一百一十七切片

目标：

- 继续 Step 9：把 checklist / task plan 的纯数据变换从 `core_kernel_adapter.py` 移出。
- 保持 WriterKit 状态 metadata、checklist 工具和自动推进语义不变。

已完成：

- 新增 `members/writer/backend/app/core/writer/task_plan.py`
  - `normalize_checklist_steps()`
  - `new_plan_revision()`
  - `plan_to_active_plan()`
  - `format_checklist_markdown()`
  - `apply_checklist_update()`
  - `has_delivery_progress()`
  - `auto_advance_plan()`
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - 删除内联 checklist / task plan helper 实现。
  - 通过导入别名保留原调用点，避免混入大规模命名改动。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/task_plan.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `rg -n "^def _normalize_checklist_steps|^def _new_plan_revision|^def _plan_to_active_plan|^def _format_checklist_markdown|^def _apply_checklist_update|^def _has_delivery_progress|^def _auto_advance_plan|^def _plan_is_completed|^def _produced_paths" members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/task_plan.py`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：4420 行。
  - `members/writer/backend/app/core/writer/task_plan.py`：209 行。

验证备注：

- 语法检查通过。
- Tool contracts 32 passed。
- Writer core kernel adapter 172 passed。
- Writer service 23 passed。
- checklist / task plan 私有实现不再留在 `core_kernel_adapter.py`。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 从 4617 行降到 4420 行，减少 197 行。
- checklist / task plan 成为可单独理解的深 module；主 adapter 只消费计划结果。

下一步：

- Step 9 继续：抽命令执行/后台探测实现，或先拆只读/读写工具 executor，让主 adapter 继续靠近 WriterKit + run entry。

### 9.118 执行记录：2026-07-01 第一百一十八切片

目标：

- 继续 Step 9：把工具失败提示和结构化错误摘要从 `core_kernel_adapter.py` 移出。
- 保持 WriterKit 格式化 tool result 的调用点和输出结构不变。

已完成：

- 新增 `members/writer/backend/app/core/writer/tool_feedback.py`
  - `tool_error_hint()`
  - `tool_structured_error_summary()`
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - 删除内联 `_TOOL_ERROR_HINTS`、`_tool_error_hint()`、`_tool_structured_error_summary()`。
  - 通过导入别名保留原调用点。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/tool_feedback.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `rg -n "_TOOL_ERROR_HINTS|^def _tool_error_hint|^def _tool_structured_error_summary" members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/tool_feedback.py`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：4362 行。
  - `members/writer/backend/app/core/writer/tool_feedback.py`：62 行。

验证备注：

- 语法检查通过。
- Writer core kernel adapter 172 passed。
- Tool contracts 32 passed。
- Writer service 23 passed。
- 工具反馈私有实现不再留在 `core_kernel_adapter.py`。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 从 4420 行降到 4362 行，减少 58 行。
- 工具失败反馈成为独立 formatting module，主 adapter 只在 tool result 组装点消费。

下一步：

- Step 9 继续：抽命令执行/后台探测实现，优先把 subprocess、readiness probe、背景进程分类移入独立 command runner module。

### 9.119 执行记录：2026-07-01 第一百一十九切片

目标：

- 继续 Step 9：把 subprocess、后台进程、HTTP readiness probe、端口占用分类等命令 runner 实现从 `core_kernel_adapter.py` 移出。
- 保持 `ReadWriteToolExecutor.run_command()` / `run_tests()` 的业务编排和现有测试导入路径兼容。

已完成：

- 新增 `members/writer/backend/app/core/writer/command_runner.py`
  - `_CommandExecution`
  - `_BackgroundHttpProbe`
  - `_run_subprocess()`
  - `_run_background_subprocess()`
  - `_make_background_http_probe()`
  - `_make_readiness_http_probe()`
  - `_cleanup_background_http_probe()`
  - `_looks_like_python_http_server()`
  - `_extract_local_server_port()`
  - `_is_local_tcp_port_listening()`
  - `_local_server_error_metadata()`
  - `_validate_readiness_url()`
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - 删除内联 command runner / background probe 实现。
  - 通过导入别名保留旧私有名，兼容 `test_writer_command_cancel.py` 对 `_run_subprocess` 的导入。
  - 保留 `httpx` import 作为旧 monkeypatch surface；流式 HTTP client 已在 `runtime_resources.py`，但测试仍通过共享 module object patch `httpx.AsyncClient`。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/command_runner.py members/writer/backend/tests/test_writer_command_cancel.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_command_cancel.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "run_command or run_tests or background"`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q -k "run_command or run_tests"`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `rg -n "^@dataclass\\(|^def _run_subprocess|^def _run_background_subprocess|^def _wait_for_background_http_probe|^def _terminate_process_tree|^class _CommandExecution|^class _BackgroundHttpProbe" members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/command_runner.py`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：3752 行。
  - `members/writer/backend/app/core/writer/command_runner.py`：639 行。

验证备注：

- 语法检查通过。
- Command cancel 1 passed。
- Command-related core adapter subset 19 passed。
- Command-related tool contracts subset 5 passed。
- Writer core kernel adapter 172 passed。
- Tool contracts 32 passed。
- Writer service 23 passed。
- 中间全量 core adapter 曾因旧测试 patch `app.core.writer.core_kernel_adapter.httpx.AsyncClient` 失败；恢复兼容 `httpx` import 后失败点 2 passed，随后全量通过。
- command runner 私有实现不再留在 `core_kernel_adapter.py`。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 从 4362 行降到 3752 行，减少 610 行。
- 命令执行和后台探测形成独立 deep module；主 adapter 继续保留工具业务编排和权限处理。

下一步：

- Step 9 继续：拆 `ReadOnlyToolExecutor` / `ReadWriteToolExecutor`，优先把文件读写、搜索、git 工具分组，进一步让 `core_kernel_adapter.py` 靠近 WriterKit + run entry。

### 9.120 执行记录：2026-07-01 第一百二十切片

目标：

- 继续 Step 9：把命令输出格式化、Windows shell 包装、skill script 路径改写从 `core_kernel_adapter.py` 并入 `command_runner.py`。
- 保持 `ReadWriteToolExecutor.run_command()` / `run_tests()` 业务编排不变。

已完成：

- `members/writer/backend/app/core/writer/command_runner.py`
  - 新增 `_format_command_output()`。
  - 新增 `_format_running_command_output()`。
  - 新增 `_resolve_skill_script_paths()`。
  - 新增 `_normalize_windows_shell_command()`。
  - 新增 `_windows_shell_argv()`。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - 删除上述命令辅助实现。
  - 通过导入别名继续在原调用点使用。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/command_runner.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_command_cancel.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "run_command or run_tests or background"`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q -k "run_command or run_tests"`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `rg -n "^def _format_command_output|^def _format_running_command_output|^def _resolve_skill_script_paths|^def _normalize_windows_shell_command|^def _windows_shell_argv" members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/command_runner.py`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：3626 行。
  - `members/writer/backend/app/core/writer/command_runner.py`：771 行。

验证备注：

- 语法检查通过。
- Command cancel 1 passed。
- Command-related core adapter subset 19 passed。
- Command-related tool contracts subset 5 passed。
- Writer core kernel adapter 172 passed。
- Tool contracts 32 passed。
- Writer service 23 passed。
- 命令输出 / Windows shell / skill path rewrite 实现不再留在 `core_kernel_adapter.py`。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 从 3752 行降到 3626 行，减少 126 行。
- `command_runner.py` 包住底层执行、后台探测、输出格式化和 shell 包装，接口更集中。

下一步：

- Step 9 继续：拆文件工具和 git 工具，或抽 `ReadOnlyToolExecutor` 的项目探测/文件读取实现。

### 9.121 执行记录：2026-07-01 第一百二十一切片

目标：

- 继续 Step 9：先抽文件/项目工具的纯辅助函数，降低后续拆 `ReadOnlyToolExecutor` 的粘连。
- 不在本切片迁移 executor 类本体。

已完成：

- 新增 `members/writer/backend/app/core/writer/file_tool_helpers.py`
  - `_format_size()`
  - `_infer_project_stack()`
  - `_infer_test_commands()`
  - `_relative_tool_uri()`
  - `_line_count()`
  - `_unified_diff()`
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - 删除上述纯 helper 实现。
  - 导入 helper 并保留原调用点。
  - `ReadOnlyToolExecutor` / `ReadWriteToolExecutor` 仍留在主 adapter，避免本切片扩大到多依赖 executor 迁移。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/file_tool_helpers.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `rg -n "^def _format_size|^def _infer_project_stack|^def _infer_test_commands|^def _relative_tool_uri|^def _line_count|^def _unified_diff|^class ReadOnlyToolExecutor" members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/file_tool_helpers.py`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：3581 行。
  - `members/writer/backend/app/core/writer/file_tool_helpers.py`：55 行。

验证备注：

- 语法检查通过。
- Tool contracts 32 passed。
- Writer core kernel adapter 172 passed。
- Writer service 23 passed。
- 中间机械迁移边界一度过宽，把 `ReadOnlyToolExecutor` 也移入 helper；已修正为只保留纯 helper。
- 文件/项目工具纯 helper 不再留在 `core_kernel_adapter.py`。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 从 3626 行降到 3581 行，减少 45 行。
- 文件工具格式化和项目推断逻辑成为独立 pure helper module。

下一步：

- Step 9 继续：正式拆 `ReadOnlyToolExecutor` 或先抽 git 工具 handler。

### 9.122 执行记录：2026-07-01 第一百二十二切片

目标：

- 继续 Step 9：把 `git_status` / `git_diff` 默认工具 handler 从 `core_kernel_adapter.py` 移出。
- 保持 `ReadWriteToolExecutor.as_dict()` 暴露的工具名和行为不变。

已完成：

- 新增 `members/writer/backend/app/core/writer/git_tools.py`
  - `make_git_status_handler()`
  - `make_git_diff_handler()`
  - git diff path 越界校验。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - 删除内联 `git_status()` / `git_diff()` 方法。
  - `ReadWriteToolExecutor.as_dict()` 改为注册 git handler factory。
- `members/writer/backend/tests/test_tool_contracts.py`
  - 新增 git 工具行为测试：临时 git repo、status、path-filtered diff、越界路径失败。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/git_tools.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q -k "git_tools"`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `rg -n "async def git_status|async def git_diff|make_git_status_handler|make_git_diff_handler" members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/git_tools.py`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：3521 行。
  - `members/writer/backend/app/core/writer/git_tools.py`：94 行。

验证备注：

- 语法检查通过。
- Git tools targeted test 1 passed。
- Tool contracts 33 passed。
- Writer core kernel adapter 172 passed。
- Writer service 23 passed。
- `git_status` / `git_diff` 方法不再留在 `core_kernel_adapter.py`，只保留 factory 注册点。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 从 3581 行降到 3521 行，减少 60 行。
- Git 默认工具成为独立 module；主 adapter 只负责把它挂入默认 executor。

下一步：

- Step 9 继续：拆 `ReadOnlyToolExecutor` 文件读取/搜索 handler，或抽 request_commit_review/checklist/verify_design 这些 Writer 管理工具。

### 9.123 执行记录：2026-07-01 第一百二十三切片

目标：

- 继续 Step 9：把 `request_commit_review`、`write_checklist`、`update_checklist`、`verify_design` 这组 Writer 管理工具实现从 `core_kernel_adapter.py` 移出。
- 保持直接调用 `ReadWriteToolExecutor` 方法的现有测试兼容。

已完成：

- 新增 `members/writer/backend/app/core/writer/management_tools.py`
  - `request_commit_review()`
  - `write_checklist()`
  - `update_checklist()`
  - `verify_design()`
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - `ReadWriteToolExecutor.as_dict()` 对前三个无状态管理工具直接注册 `management_tools` handler。
  - 保留 `request_commit_review()` / `write_checklist()` / `update_checklist()` / `verify_design()` 薄 wrapper，兼容现有测试和外部调用。
  - 删除管理工具的内联实现。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/management_tools.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q -k "checklist or commit_review or default_executor"`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "request_commit_review or default_executor"`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `rg -n "async def request_commit_review|async def write_checklist|async def update_checklist|async def verify_design|management_tools\\." members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/management_tools.py`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：3384 行。
  - `members/writer/backend/app/core/writer/management_tools.py`：151 行。

验证备注：

- 语法检查通过。
- Management tools targeted tests 3 passed。
- Request commit review targeted test 1 passed。
- Tool contracts 33 passed。
- Writer core kernel adapter 172 passed。
- Writer service 23 passed。
- 管理工具实现已移到 `management_tools.py`；主 adapter 只保留兼容 wrapper 和注册点。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 从 3521 行降到 3384 行，减少 137 行。
- Writer 管理工具形成独立 module，降低 `ReadWriteToolExecutor` 后续拆分粘连。

下一步：

- Step 9 继续：拆 `ReadOnlyToolExecutor` 文件读取/搜索 handler，或将写文件/edit/run_command 之外的剩余默认工具继续下沉。

### 9.124 执行记录：2026-07-01 第一百二十四切片

目标：

- 继续 Step 9：把 `ReadOnlyToolExecutor` 从 `core_kernel_adapter.py` 移到独立 module。
- 保持测试和调用方从 `core_kernel_adapter` 导入 `ReadOnlyToolExecutor` 的旧路径兼容。

已完成：

- 新增 `members/writer/backend/app/core/writer/read_tools.py`
  - `ReadOnlyToolExecutor`
  - read-only path/resource root resolution
  - read/list/search/inspect/load-skill 默认工具实现
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - 删除内联 `ReadOnlyToolExecutor` 和 read-only 专用 helper。
  - 从 `read_tools.py` 导入 `ReadOnlyToolExecutor`，旧导入路径继续可用。
  - `ReadWriteToolExecutor` 继续继承 `ReadOnlyToolExecutor`，写入/命令编排不变。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/read_tools.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "ReadOnlyToolExecutor or read_file or list_dir or search_files or search_content or inspect_project or load_skill"`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `rg -n "^class ReadOnlyToolExecutor|_resolve_read_resource_path|_SKIP_SEARCH_DIRS|from app.core.writer.read_tools" members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/read_tools.py`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：2970 行。
  - `members/writer/backend/app/core/writer/read_tools.py`：439 行。

验证备注：

- 语法检查通过。
- Read-only targeted tests 28 passed。
- Tool contracts 33 passed。
- Writer core kernel adapter 172 passed。
- Writer service 23 passed。
- `ReadOnlyToolExecutor` 实现、read-only path resolver 和 skip dirs 不再留在 `core_kernel_adapter.py`。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 从 3384 行降到 2970 行，减少 414 行。
- 只读文件/项目工具成为独立 deep module；主 adapter 现在集中在 `ReadWriteToolExecutor`、WriterKit、run entry。

下一步：

- Step 9 继续：拆 `ReadWriteToolExecutor` 的写文件/edit/run_command 组合，优先将 write/edit 文件修改工具抽到独立 module。

### 9.125 执行记录：2026-07-01 第一百二十五切片

目标：

- 继续 Step 9：把 `write_file` / `edit_file` 文件修改工具实现从 `core_kernel_adapter.py` 移出。
- 保持 `ReadWriteToolExecutor.write_file()` / `edit_file()` 方法兼容现有直接调用测试。

已完成：

- 新增 `members/writer/backend/app/core/writer/write_tools.py`
  - `make_write_file_handler()`
  - `make_edit_file_handler()`
  - `write_file_tool()`
  - `edit_file_tool()`
  - 写入路径校验、diff artifact、preview/context 输出。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - `ReadWriteToolExecutor.as_dict()` 改为注册 `write_tools.py` handler factory。
  - 保留 `write_file()` / `edit_file()` 薄 wrapper，兼容现有测试和外部调用。
  - 删除 write/edit 内联实现。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/write_tools.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "write_file or edit_file"`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q -k "write_file or edit_file"`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `rg -n "async def write_file|async def edit_file|write_file_tool|edit_file_tool|make_write_file_handler|make_edit_file_handler" members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/write_tools.py`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：2759 行。
  - `members/writer/backend/app/core/writer/write_tools.py`：232 行。

验证备注：

- 语法检查通过。
- write/edit targeted core tests 28 passed。
- write/edit targeted tool contracts 2 passed。
- Tool contracts 33 passed。
- Writer core kernel adapter 172 passed。
- Writer service 23 passed。
- write/edit 实现已移到 `write_tools.py`；主 adapter 只保留兼容 wrapper 和注册点。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 从 2970 行降到 2759 行，减少 211 行。
- 文件修改工具成为独立 deep module；`ReadWriteToolExecutor` 剩余主体集中在 run_command/run_tests 和兼容工具挂载。

下一步：

- Step 9 继续：拆 `run_command` / `run_tests` 的工具编排，或把 `ReadWriteToolExecutor` 剩余命令工具改成对 `command_runner` 的薄 adapter。

### 9.126 执行记录：2026-07-01 第一百二十六切片

目标：

- 继续 Step 9：把 `run_command` / `run_tests` 工具编排从 `core_kernel_adapter.py` 移出。
- 保持 `_validate_command_paths` 旧导入路径兼容，避免现有测试和外部调用被迫同步迁移。

已完成：

- 新增 `members/writer/backend/app/core/writer/command_tools.py`
  - `CommandToolHandlers`
  - `_validate_command_paths()`
  - `run_command()`
  - `run_tests()`
  - `_detect_test_command()`
  - 命令路径校验、后台命令探测、readiness probe、进度事件、命令输出 artifact、测试结果 contract。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - `ReadWriteToolExecutor` 初始化 `CommandToolHandlers`。
  - `run_command()` / `run_tests()` 保留兼容 wrapper。
  - 删除命令执行、测试命令探测、命令 artifact 拼装等内联实现。
  - 删除不再需要的命令 runner、文件 artifact、shell 解析相关直接导入。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/command_tools.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "run_command or run_tests or validate_command_paths or background"`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q -k "run_command or run_tests"`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `rg -n "_validate_command_paths|CommandToolHandlers|async def run_command|async def run_tests|_detect_test_command" members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/command_tools.py`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：2366 行。
  - `members/writer/backend/app/core/writer/command_tools.py`：426 行。

验证备注：

- 语法检查通过。
- command targeted core tests 19 passed，153 deselected。
- command targeted tool contracts 5 passed，28 deselected。
- Tool contracts 33 passed。
- Writer core kernel adapter 172 passed。
- Writer service 23 passed，1 warning。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 从 2759 行降到 2366 行，减少 393 行。
- 命令工具成为独立 deep module；主 adapter 只保留工具注册、兼容 wrapper、WriterKit 和运行入口。

下一步：

- Step 9 继续：盘点 `core_kernel_adapter.py` 剩余职责，优先处理 `ReadWriteToolExecutor` 的组合职责或 WriterKit 内仍可独立的业务 hook。

### 9.127 执行记录：2026-07-01 第一百二十七切片

目标：

- 继续 Step 9：把 WriterKit 内的 architecture handoff 文档上下文逻辑移出主 adapter。
- 保留 WriterKit 现有兼容方法，避免同时改动 sub-agent 调用链。

已完成：

- 新增 `members/writer/backend/app/core/writer/architecture_handoff.py`
  - `architecture_handoff_context()`
  - `inject_architecture_handoff_context()`
  - `persist_architecture_handoff_doc()`
  - `architecture_handoff_doc_from_call()`
  - handoff 文件名清理、路径边界校验、持久化失败降级。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - WriterKit handoff 相关方法改为调用 `architecture_handoff.py`。
  - 删除 `_safe_context_filename()` 和 handoff 持久化内联实现。
  - 保留 `_architecture_handoff_context()` 等兼容 wrapper，减少本切片风险。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/architecture_handoff.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "architecture_handoff or sub_agent"`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `rg -n "architecture_handoff_context|inject_architecture_handoff_context|persist_architecture_handoff_doc|architecture_handoff_doc_from_call|_safe_context_filename" members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/architecture_handoff.py`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：2330 行。
  - `members/writer/backend/app/core/writer/architecture_handoff.py`：72 行。

验证备注：

- 语法检查通过。
- architecture handoff / sub-agent targeted tests 4 passed，168 deselected。
- Writer core kernel adapter 172 passed。
- Writer service 23 passed，1 warning。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 从 2366 行降到 2330 行，减少 36 行。
- architecture handoff 的文件上下文、持久化和 call 解析成为独立 deep module；WriterKit 只保留调用点。

下一步：

- Step 9 继续：优先处理 `_copy_sub_agent_context_files()` / `_cleanup_sub_agent_context_files()` / `_default_sub_agent_workspace()` 这组 sub-agent workspace 逻辑，或先抽 tool execution / completion verification 中更低风险的纯函数。

### 9.128 执行记录：2026-07-01 第一百二十八切片

目标：

- 继续 Step 9：把 sub-agent 隔离工作区创建、handoff 上下文文件注入、注入文件清理从 WriterKit 移出。
- 本切片不碰 sub-agent kernel runner 和 workspace delivery/merge，降低回归面。

已完成：

- 新增 `members/writer/backend/app/core/writer/sub_agent_workspace.py`
  - `create_default_sub_agent_workspace()`
  - `copy_sub_agent_context_files()`
  - `cleanup_sub_agent_context_files()`
  - 工作区路径边界校验、git worktree 创建、handoff 文件复制、注入文件清理。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - `_default_sub_agent_workspace()` 改为调用 workspace module。
  - `_copy_sub_agent_context_files()` / `_cleanup_sub_agent_context_files()` 保留兼容 wrapper。
  - 删除内联复制文件逻辑和 `shutil` 直接导入。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/sub_agent_workspace.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "sub_agent or architecture_handoff"`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：2275 行。
  - `members/writer/backend/app/core/writer/sub_agent_workspace.py`：92 行。

验证备注：

- 语法检查通过。
- sub-agent / architecture handoff targeted tests 4 passed，168 deselected。
- Writer core kernel adapter 172 passed。
- Writer service 23 passed，1 warning。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 从 2330 行降到 2275 行，减少 55 行。
- sub-agent workspace 创建、上下文注入和清理成为独立 deep module；WriterKit 仍负责 sub-agent 运行编排和 delivery 判定。

下一步：

- Step 9 继续：评估是否抽出 sub-agent workspace delivery/merge；若风险过高，先处理 tool execution 或 verifier 决策里的纯函数。

### 9.129 执行记录：2026-07-01 第一百二十九切片

目标：

- 继续 Step 9：把 sub-agent 隔离工作区 delivery/commit 判定从 WriterKit 移到 workspace module。
- 不改变策略：sub-agent 只提交到自己的分支，主 Writer 后续人工接收或放弃。

已完成：

- `members/writer/backend/app/core/writer/sub_agent_workspace.py`
  - 新增 `finalize_sub_agent_workspace()`。
  - 接管 worktree dirty 文件扫描、sub-agent branch commit、delivery metadata 拼装。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - `_finalize_sub_agent_workspace()` 改为调用 workspace module。
  - 删除 delivery/commit 内联实现。
  - 删除不再需要的 `WriterGitManager` 直接导入。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/sub_agent_workspace.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "sub_agent or architecture_handoff"`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：2212 行。
  - `members/writer/backend/app/core/writer/sub_agent_workspace.py`：162 行。

验证备注：

- 语法检查通过。
- sub-agent / architecture handoff targeted tests 4 passed，168 deselected。
- Writer core kernel adapter 172 passed。
- Writer service 23 passed，1 warning。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 从 2275 行降到 2212 行，减少 63 行。
- sub-agent workspace 生命周期的创建、上下文注入、清理、delivery commit 已集中到 `sub_agent_workspace.py`。

下一步：

- Step 9 继续：盘点 WriterKit 剩余大块，优先抽出 sub-agent nested event forwarding 或 tool-result formatting 中可独立验证的深模块。

### 9.130 执行记录：2026-07-01 第一百三十切片

目标：

- 继续 Step 9：把 sub-agent nested event forwarding 从 WriterKit 内部类移出。
- 保持事件语义不变：nested event 仍进入本地 event log，并将 runtime part/tool 事件转发为 `source="sub_agent"`。

已完成：

- 新增 `members/writer/backend/app/core/writer/sub_agent_events.py`
  - `SubAgentEventForwardingSink`
  - 负责记录 nested event、补充 sub-agent metadata、转发 runtime part/tool 事件。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - `_run_sub_agent_kernel()` 改为装配 `SubAgentEventForwardingSink`。
  - 删除内部 `_NestedEventSink` 类。
  - 删除转移后无用的 `sub_line_id` / `agent_run_id` 局部变量。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/sub_agent_events.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "sub_agent or architecture_handoff"`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：2183 行。
  - `members/writer/backend/app/core/writer/sub_agent_events.py`：50 行。

验证备注：

- 语法检查通过。
- sub-agent / architecture handoff targeted tests 4 passed，168 deselected。
- Writer core kernel adapter 172 passed。
- Writer service 23 passed，1 warning。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 从 2212 行降到 2183 行，减少 29 行。
- sub-agent 事件转发成为独立 deep module；WriterKit 只负责把 event sink 交给 CoreLoopKernel。

下一步：

- Step 9 继续：抽出 sub-agent nested result projection，或转入 tool-result formatting / verification decision 的纯逻辑收缩。

### 9.131 执行记录：2026-07-01 第一百三十一切片

目标：

- 继续 Step 9：把 sub-agent nested kernel 结果投影从 WriterKit 移出。
- 保持 sub-agent 执行策略不变，只移动 `KernelResult + nested events -> data/tool_records/reasoning/diagnostics` 的转换逻辑。

已完成：

- 新增 `members/writer/backend/app/core/writer/sub_agent_projection.py`
  - `project_sub_agent_result()`
  - nested reasoning blocks 投影。
  - nested tool records 投影。
  - final text fallback 和 diagnostics 拼装。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - `_run_sub_agent_kernel()` 改为调用 `project_sub_agent_result()`。
  - 保留 workspace cleanup / delivery 后处理在主流程中。
  - 删除 tool_records、reasoning_blocks、final_text、diagnostics 的内联拼装。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/sub_agent_projection.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "sub_agent or architecture_handoff"`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `rg -n "project_sub_agent_result|reasoning_by_id|content_preview|tool_records" members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/sub_agent_projection.py`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：2124 行。
  - `members/writer/backend/app/core/writer/sub_agent_projection.py`：77 行。

验证备注：

- 语法检查通过。
- sub-agent / architecture handoff targeted tests 4 passed，168 deselected。
- Writer core kernel adapter 172 passed。
- Tool contracts 33 passed。
- Writer service 23 passed，1 warning。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 从 2183 行降到 2124 行，减少 59 行。
- sub-agent nested result projection 成为独立 deep module；WriterKit 的 sub-agent runner 更接近“装配并运行 nested kernel”。

下一步：

- Step 9 继续：评估 tool-result formatting、verification decision、writeback 中可独立的纯逻辑；避免把 WriterKit 切成浅 wrapper。

### 9.132 执行记录：2026-07-01 第一百三十二切片

目标：

- 继续 Step 9：把工具失败签名、失败上下文、测试断言失败识别从 WriterKit 移出。
- 保留 `WriterKit._tool_failure_signature()` 等兼容静态方法，避免破坏现有测试入口。

已完成：

- 新增 `members/writer/backend/app/core/writer/tool_failure.py`
  - `tool_failure_signature()`
  - `tool_failure_context()`
  - `looks_like_test_assertion_failure()`
  - 稳定失败签名、测试输出摘要、断言失败识别。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - verify/writeback/repeated failure decision 改为调用 `tool_failure.py`。
  - 兼容静态方法改为薄转发。
  - 删除 `sha1` 直接导入和内联失败摘要实现。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/tool_failure.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "tool_failure or assertion or repeated or verification"`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `rg -n "sha1|tool_failure_signature|tool_failure_context|looks_like_test_assertion_failure|_tool_failure_signature|_tool_failure_context|_looks_like_test_assertion_failure" members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/tool_failure.py members/writer/backend/tests/test_writer_core_kernel_adapter.py`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：2075 行。
  - `members/writer/backend/app/core/writer/tool_failure.py`：63 行。

验证备注：

- 语法检查通过。
- failure/verification targeted tests 3 passed，169 deselected。
- Writer core kernel adapter 172 passed。
- Tool contracts 33 passed。
- Writer service 23 passed，1 warning。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 从 2124 行降到 2075 行，减少 49 行。
- 工具失败判断成为独立 deep module；WriterKit 只负责把判断结果用于验收、重复失败停止和 writeback 记录。

下一步：

- Step 9 继续：评估 written-file/html-reference verification 是否能抽为独立 verifier；或先做 Step 9 阶段性结构验收，确认继续拆分是否仍有净收益。

### 9.133 执行记录：2026-07-01 第一百三十三切片

目标：

- 继续 Step 9：把 write/edit 文件存在性、stub 提示、HTML 本地引用检查从 WriterKit `verify()` 中移出。
- 保持失败工具处理和 completion verifier 顺序不变。

已完成：

- 新增 `members/writer/backend/app/core/writer/tool_verification.py`
  - `verify_written_tool_results()`
  - write/edit 结果路径提取。
  - 写入文件存在性检查。
  - 非 HTML/CSS 文件 stub hint 检查。
  - HTML 本地 `href/src` 引用检查。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - `verify()` 在无工具失败、无 completion verifier 时调用 `verify_written_tool_results()`。
  - 删除 written-file / HTML reference 内联验收逻辑。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/tool_verification.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "verification or write_file or edit_file or html or stub"`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `rg -n "verify_written_tool_results|File written but not found|HTML reference warnings|Possible stub|missing reference|_path_from_write_result" members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/tool_verification.py`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：1995 行。
  - `members/writer/backend/app/core/writer/tool_verification.py`：93 行。

验证备注：

- 首次 targeted verification 暴露回归：`WriterKit._work_root` 在默认 write/edit 测试路径中是字符串，新 module 直接使用 `/` 拼接导致 default write/edit 失败。
- 已修正：`verify_written_tool_results()` 入口统一把 `str | Path | None` 规整为 `Path | None`。
- 修正后 targeted verification 30 passed，142 deselected。
- Writer core kernel adapter 172 passed。
- Tool contracts 33 passed。
- Writer service 23 passed，1 warning。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 从 2075 行降到 1995 行，减少 80 行。
- written-file / HTML reference 验收成为独立 deep module；WriterKit `verify()` 只负责调度失败处理、completion verifier 和写入产物验收。

下一步：

- Step 9 继续：`core_kernel_adapter.py` 已低于 2000 行；下一步应先做阶段性结构验收，确认剩余拆分是否还有净收益，再决定是否继续抽 writeback 或 execute_tool 子逻辑。

### 9.134 执行记录：2026-07-01 第一百三十四切片

目标：

- 继续 Step 9：把 `writeback()` 中的工具结果轨迹记录移出 WriterKit。
- 保留 checklist / active plan 推进在 WriterKit 内，避免把任务计划副作用和工具轨迹记录混成同一切片。

已完成：

- 新增 `members/writer/backend/app/core/writer/tool_outcomes.py`
  - `record_tool_outcomes()`
  - recent tool/status/failure signature 记录。
  - failed tool context 摘要记录。
  - empty/useless tool category 记录。
  - write/edit 成功后的 `written_files` 记录。
  - successful tool run 的 `forced_continue_count` 重置。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - `writeback()` 改为调用 `record_tool_outcomes()`。
  - 删除 `_TOOL_CATEGORIES`、read/write/git tool category 常量和轨迹记录内联实现。
  - 保留 checklist creation/update/auto-advance 逻辑。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/tool_outcomes.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "recent or repeated or drift or written_files or writeback or tool_failure"`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q`
- `rg -n "_TOOL_CATEGORIES|record_tool_outcomes|recent_category_empty|recent_failure_signatures|forced_continue_count|written_files" members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/tool_outcomes.py`
- 行数统计：
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py`：1908 行。
  - `members/writer/backend/app/core/writer/tool_outcomes.py`：82 行。

验证备注：

- 语法检查通过。
- writeback/outcome targeted tests 2 passed，170 deselected。
- Writer core kernel adapter 172 passed。
- Tool contracts 33 passed。
- Writer service 23 passed，1 warning。
- Windows / Python 3.14 下仍出现 asyncio closed pipe unraisable warning，断言全部通过。

当前收缩：

- `core_kernel_adapter.py` 从 1995 行降到 1908 行，减少 87 行。
- 工具结果轨迹记录成为独立 deep module；WriterKit `writeback()` 只剩任务计划推进和 active plan 投影。

阶段性结构扫描：

- `core_kernel_adapter.py` 当前 1908 行，已经低于 2000 行。
- Writer 旧 `TaskManager`、`core_adapter.py`、私有 `runtime_fact_projection.py`、私有 `runtime_fact_helpers.py` 在当前 Writer 生产代码中未命中；相关命中主要来自历史设计文档。
- Artist `TaskManager` 仍在生产路径中命中，是 Step 10 明确遗留，不属于本切片处理范围。
- 当前工作区仍有无关未提交改动，本切片未触碰。

下一步：

- Step 9 可继续小幅收缩 task-plan writeback 或 execute_tool 子逻辑，但更大目标已经转向 Step 10：让 Artist 作为第二个 thin member 接入同一 Core/Member 主线。

## 10. 完成定义

阶段性完成：

- Core 能跑一个 minimal agent，不依赖 Writer。
- Writer run 和 GUI turn 走同一个 Core operation。
- UI 只消费 snapshot。
- Writer backend runtime 降到 10k 以下。

最终完成：

- Writer runtime <= 6,000。
- Writer 专属业务核心 <= 1,500。
- Artist 也作为 thin member 跑通。
- 新 member scaffold 不复制 Writer runtime。
- `rg` 查不到旧事件族、TaskManager SSE 产品链路、Writer SSE -> CoreEvent 反向适配。
- 一个工程师看目录即可说出：Core 是 agent 基座，Writer/Artist 是领域示例。

### 10.1 执行记录：2026-07-01 Step 10 第一切片

目标：

- 开始 Step 10：让 Artist 也朝 thin member 形态收缩。
- 先处理 Artist Core adapter 内部的低风险视觉验收逻辑，不直接删除 TaskManager/SSE 主线。

已完成：

- 新增 `members/artist/backend/app/core/artist/visual_verification.py`
  - `VERIFICATION_SYSTEM_PROMPT`
  - `build_verification_user_message()`
  - `parse_verification_response()`
  - VLM 验收 prompt、multimodal user content、JSON 解析 fallback。
- `members/artist/backend/app/core/artist/core_kernel_adapter.py`
  - `verify()` 改为调用 `visual_verification.py`。
  - 删除本地 `_VERIFICATION_SYSTEM_PROMPT`、`_build_verification_user_message()`、`_parse_verification_response()`。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/visual_verification.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q -k "vlm or verification or generate"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `rg -n "VERIFICATION_SYSTEM_PROMPT|build_verification_user_message|parse_verification_response|_VERIFICATION_SYSTEM_PROMPT|_build_verification_user_message|_parse_verification_response" members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/visual_verification.py members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py`
- 行数统计：
  - `members/artist/backend/app/core/artist/core_kernel_adapter.py`：1694 行。
  - `members/artist/backend/app/core/artist/visual_verification.py`：48 行。

验证备注：

- 语法检查通过。
- Artist VLM / verification / generate targeted tests 19 passed，42 deselected。
- Artist core kernel adapter unit tests 61 passed。
- Artist core HTTP unit tests 21 passed。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。

当前收缩：

- `members/artist/backend/app/core/artist/core_kernel_adapter.py` 从 1741 行降到 1694 行，减少 47 行。
- Artist VLM 验收 prompt/parser 成为独立 module；ArtistKit `verify()` 只保留验收流程调度。

当前遗留：

- Artist `services/task_manager.py` 仍在 session router、CLI、generate service、executor engine 中使用。
- Artist `/api/sessions/events` 仍是旧 SSE 队列。
- Step 10 未完成；下一步要么继续收缩 Artist Core adapter 的 lineage/reference 逻辑，要么开始替换 Artist TaskManager/SSE 主线。

### 10.2 执行记录：2026-07-01 Step 10 第二切片

目标：

- 继续 Step 10：收缩 Artist Core adapter 中的 visual context / reference resolution 逻辑。
- 保留旧测试导入面和 ArtistKit 兼容方法，避免同时改动测试协议和运行协议。

已完成：

- 新增 `members/artist/backend/app/core/artist/visual_context.py`
  - `VisualContextItem`
  - `ReferenceResolution`
  - `visual_context_from_initial_items()`
  - `resolve_reference_images_from_args()`
  - `resolve_reference_images_from_visual_context()`
  - `resolve_artifact_index_references()`
  - `build_reference_images_with_context()`
  - `reference_metadata()`
- `members/artist/backend/app/core/artist/core_kernel_adapter.py`
  - 删除本地 `VisualContextItem` / `_ReferenceResolution` dataclass。
  - `_visual_context_from_initial_items()` 和 ArtistKit reference helper 改为转发到 `visual_context.py`。
  - 保留 `_build_reference_images()` / `_build_reference_images_with_context()` / `_reference_metadata()` 兼容方法。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/visual_context.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q -k "reference or lineage or VisualContextItem or source_image_urls"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `rg -n "ReferenceResolution|VisualContextItem|visual_context_from_initial_items|resolve_reference_images|build_reference_images_with_context|reference_metadata|_ReferenceResolution" members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/visual_context.py members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py`
- 行数统计：
  - `members/artist/backend/app/core/artist/core_kernel_adapter.py`：1510 行。
  - `members/artist/backend/app/core/artist/visual_context.py`：160 行。

验证备注：

- 语法检查通过。
- Artist reference / lineage / visual context targeted tests 10 passed，51 deselected。
- Artist core kernel adapter unit tests 61 passed。
- Artist core HTTP unit tests 21 passed。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。

当前收缩：

- `members/artist/backend/app/core/artist/core_kernel_adapter.py` 从 1694 行降到 1510 行，减少 184 行。
- visual context 和 reference resolution 成为独立 deep module；ArtistKit 只保留兼容 wrapper 和工具执行调度。

当前遗留：

- Artist Core adapter 仍包含 lineage inspect / set head、generate_image 执行、artifact review verification、decide/writeback 等多类职责。
- Artist `services/task_manager.py` 和 `/api/sessions/events` 旧 SSE 主线仍未替换。

下一步：

- Step 10 继续：优先抽 Artist generation tool execution 或 artifact verification checks；随后再进入 TaskManager/SSE 主线替换。

### 10.3 执行记录：2026-07-01 Step 10 第三切片

目标：

- 继续 Step 10：把 Artist lineage 工具逻辑从 ArtistKit 移出。
- 保留 ArtistKit `_execute_inspect_lineage()` / `_execute_set_lineage_head()` / `_append_generated_lineage_items()` 兼容 wrapper。

已完成：

- 新增 `members/artist/backend/app/core/artist/lineage_tools.py`
  - `inspect_lineage_tool()`
  - `set_lineage_head_tool()`
  - `append_generated_lineage_items()`
  - `lineage_items_for_state()`
  - lineage head candidate 构造、HEAD metadata 更新、inspect payload 拼装。
- `members/artist/backend/app/core/artist/core_kernel_adapter.py`
  - lineage inspect / set head / append generated lineage 改为调用 `lineage_tools.py`。
  - 删除本地 lineage inspect、set head、append generated lineage 内联实现。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/lineage_tools.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q -k "lineage or set_lineage_head or inspect_lineage"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `rg -n "inspect_lineage_tool|set_lineage_head_tool|append_generated_lineage_items|lineage_items_for_state|json\\.dumps|import json" members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/lineage_tools.py`
- 行数统计：
  - `members/artist/backend/app/core/artist/core_kernel_adapter.py`：1372 行。
  - `members/artist/backend/app/core/artist/lineage_tools.py`：150 行。

验证备注：

- 语法检查通过。
- Artist lineage targeted tests 8 passed，53 deselected。
- Artist core kernel adapter unit tests 61 passed。
- Artist core HTTP unit tests 21 passed。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。

当前收缩：

- `members/artist/backend/app/core/artist/core_kernel_adapter.py` 从 1510 行降到 1372 行，减少 138 行。
- lineage inspect / set head / append generated lineage 成为独立 deep module；ArtistKit 只保留工具 dispatch 和兼容 wrapper。

当前遗留：

- Artist generate_image 单项/批量执行仍在 ArtistKit 内。
- Artist artifact review verification / decide_next / writeback 仍在 ArtistKit 内。
- Artist `TaskManager` / `/api/sessions/events` 旧 SSE 主线仍未替换。

下一步：

- Step 10 继续：优先抽 Artist generate_image execution；之后再评估 TaskManager/SSE 替换方案。

### 10.4 执行记录：2026-07-01 Step 10 第四切片

目标：

- 继续 Step 10：把 Artist runtime context extractor 从 Artist Core adapter 移出。
- 保留 `_extract_visual_context()` 等兼容函数，避免破坏现有测试和调用点。

已完成：

- 新增 `members/artist/backend/app/core/artist/runtime_context.py`
  - `extract_visual_context()`
  - `extract_lineage_context()`
  - `extract_generation_params()`
  - `extract_artifact_review_status()`
  - visible artifacts、lineage metadata、visual memory generation params、artifact review status 投影。
- `members/artist/backend/app/core/artist/core_kernel_adapter.py`
  - `_extract_visual_context()` / `_extract_lineage_context()` / `_extract_generation_params()` / `_extract_artifact_review_status()` 改为调用 `runtime_context.py`。
  - 删除四段 metadata 投影内联实现。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/runtime_context.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q -k "context or review or metadata or generation_params"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `rg -n "extract_visual_context|extract_lineage_context|extract_generation_params|extract_artifact_review_status|_extract_visual_context|_extract_lineage_context|_extract_generation_params|_extract_artifact_review_status" members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/runtime_context.py members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py`
- 行数统计：
  - `members/artist/backend/app/core/artist/core_kernel_adapter.py`：1269 行。
  - `members/artist/backend/app/core/artist/runtime_context.py`：109 行。

验证备注：

- 语法检查通过。
- Artist context/review targeted tests 13 passed，48 deselected。
- Artist core kernel adapter unit tests 61 passed。
- Artist core HTTP unit tests 21 passed。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。

当前收缩：

- `members/artist/backend/app/core/artist/core_kernel_adapter.py` 从 1372 行降到 1269 行，减少 103 行。
- runtime context projection 成为独立 deep module；ArtistKit build_context / verify / writeback 使用统一 extractor。

当前遗留：

- Artist generate_image execution 仍在 ArtistKit 内。
- Artist decide_next / writeback 仍在 ArtistKit 内。
- Artist `TaskManager` / `/api/sessions/events` 旧 SSE 主线仍未替换。

下一步：

- Step 10 继续：优先抽 Artist generate_image execution；随后再进入 TaskManager/SSE 主线替换。

### 10.5 执行记录：2026-07-01 Step 10 第五切片

目标：

- 继续 Step 10：把 Artist `generate_image` 单项/批量执行逻辑从 Artist Core adapter 移出。
- 保留 `_execute_generate_image()` / `_execute_generate_image_single()` / `_execute_generate_image_items()` 兼容 wrapper，避免破坏现有测试和调用点。

已完成：

- 新增 `members/artist/backend/app/core/artist/generation_tools.py`
  - `execute_generate_image_tool()`
  - `execute_generate_image_single_tool()`
  - `execute_generate_image_items_tool()`
  - image_count 校验、reference image resolution、单项生成、批量生成、artifact metadata、usage 汇总。
- `members/artist/backend/app/core/artist/core_kernel_adapter.py`
  - `generate_image` 执行改为调用 `generation_tools.py`。
  - 删除本地 `LLMUsage` / `ToolArtifact` 依赖和生成执行内联实现。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/generation_tools.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q -k "generate or items or source_image_urls or reference"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `rg -n "execute_generate_image_tool|execute_generate_image_single_tool|execute_generate_image_items_tool|MAX_GENERATE_IMAGE_COUNT|LLMUsage|ToolArtifact|_execute_generate_image_single|_execute_generate_image_items" members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/generation_tools.py members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py`
- `git diff --check -- members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/generation_tools.py`
- 行数统计：
  - `members/artist/backend/app/core/artist/core_kernel_adapter.py`：1089 行。
  - `members/artist/backend/app/core/artist/generation_tools.py`：234 行。

验证备注：

- 语法检查通过。
- Artist generate/reference targeted tests 23 passed，38 deselected。
- Artist core kernel adapter unit tests 61 passed。
- Artist core HTTP unit tests 21 passed。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- `members/artist/backend/app/core/artist/core_kernel_adapter.py` 从 1269 行降到 1089 行，减少 180 行。
- generate_image 单项/批量执行成为独立 deep module；ArtistKit 只保留工具 dispatch 和兼容 wrapper。

当前遗留：

- Artist decide_next / writeback 仍在 ArtistKit 内。
- Artist `TaskManager` / `/api/sessions/events` 旧 SSE 主线仍未替换。
- Step 10 尚未完成，下一切片需要进入 Artist 旧 TaskManager/SSE 主线替换前的精确扫描。

下一步：

- Step 10 继续：扫描 Artist `TaskManager`、`/api/sessions/events`、runtime state/event 写入链路，先确定替换口径，再做最小切片。

### 10.6 执行记录：2026-07-01 Step 10 第六切片

目标：

- 继续 Step 10：先拆 Artist 旧 `TaskManager` 中的 SSE/event log 职责，不直接删除任务状态、取消、checkpoint 和并发限流语义。
- 为后续替换 `/api/sessions/events` 主线建立可测试的事件 hub seam。

已完成：

- 新增 `members/artist/backend/app/services/session_event_hub.py`
  - `SessionEventHub`
  - `publish_task_event()`
  - `publish_runtime_event()`
  - `subscribe()` / `unsubscribe()`
  - SSE 序列化、session queue fan-out、Last-Event-ID replay、checkpoint replay skip。
- `members/artist/backend/app/services/task_manager.py`
  - 删除本地 event log、queue registry、SSE serialize/replay 内联实现。
  - 保留 `TaskManager` 的任务状态、取消、checkpoint、并发限流职责。
  - `publish()` / `subscribe()` / `unsubscribe()` 改为委托 `SessionEventHub`。
- `members/artist/backend/app/routers/session.py`
  - `/api/sessions/events` 日志不再读取 `TaskManager` 私有队列字段，改用 `queue_count()`。
- 新增 `members/artist/backend/tests/test_session_event_hub_unit.py`
  - 覆盖 session replay 过滤。
  - 覆盖 checkpoint 不回放。
  - 覆盖 checkpoint 同时送达 global 和其它 session subscriber。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/services/session_event_hub.py members/artist/backend/app/services/task_manager.py members/artist/backend/app/routers/session.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_session_event_hub_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `rg -n "SessionEventHub|queue_count|_queue_registry|_event_log|serialize_sse|publish_task_event|publish_runtime_event|/events" members/artist/backend/app/services/task_manager.py members/artist/backend/app/services/session_event_hub.py members/artist/backend/app/routers/session.py members/artist/backend/tests/test_session_event_hub_unit.py`
- `git diff --check -- members/artist/backend/app/services/session_event_hub.py members/artist/backend/app/services/task_manager.py members/artist/backend/app/routers/session.py members/artist/backend/tests/test_session_event_hub_unit.py`
- 行数统计：
  - `members/artist/backend/app/services/task_manager.py`：161 行。
  - `members/artist/backend/app/services/session_event_hub.py`：105 行。
  - `members/artist/backend/tests/test_session_event_hub_unit.py`：42 行。

验证备注：

- 语法检查通过。
- Session event hub unit tests 3 passed。
- Generate service unit tests 5 passed。
- Artist core HTTP unit tests 21 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Artist session lifecycle tests 2 passed。
- Artist CLI unit tests 10 passed。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- `TaskManager` 从约 259 行降到 161 行，减少约 98 行。
- SSE/event log/replay 成为独立 deep module；`TaskManager` 不再直接维护 queue registry 或 EventLog。
- SSE payload 保留旧 `object` 字段，同时补出前端已按代码读取的 `event_type` 字段，避免 Core display/runtime event 分支依赖缺字段。

当前遗留：

- `/api/sessions/events` 仍是旧 Artist endpoint，尚未切到 Core `/api/core/sessions/{id}/events` 或产品中立 event store。
- `TaskManager` 仍承载 checkpoint、取消和并发限流；后续需判断哪些是 Artist 专属，哪些应下沉 Core。
- Artist Core adapter 的 decide_next / writeback 仍未继续抽取。

下一步：

- Step 10 继续：用 `SessionEventHub` 作为过渡 seam，继续扫描 `/api/sessions/events` 与 `/api/core/sessions/{id}/events` 的差异，决定是桥接 Core event store，还是先让旧 SSE 只消费 Core display/runtime events。

### 10.7 执行记录：2026-07-01 Step 10 第七切片

目标：

- 继续 Step 10：让 Artist `/api/core/sessions/{session_id}/events` 不再恒返回空数组。
- 使用 10.6 新增的 `SessionEventHub` 作为过渡 seam，把 Core-shaped event history 读口先桥到现有 live event hub，不改旧 `/api/sessions/events` SSE live 协议。

已完成：

- `members/artist/backend/app/services/session_event_hub.py`
  - 新增 `list_events(session_id=...)`。
  - 将 `LamEvent` 投影为 Core-shaped runtime event：
    - `id`
    - `session_id`
    - `name`
    - `type`
    - `category`
    - `payload`
    - `run_id`
    - `source_product`
    - `created_at`
    - `sequence`
- `members/artist/backend/app/services/task_manager.py`
  - 新增 `list_events()`，继续只做委托。
- `members/artist/backend/app/routers/core_http.py`
  - `/api/core/sessions/{session_id}/events` 改为返回 `task_manager.list_events(session_id)`。
  - 保留 session existence check；不存在 session 仍返回 404。
- `members/artist/backend/tests/test_core_http_artist_unit.py`
  - 保留新 session 无事件时返回 `[]` 的兼容测试。
  - 新增有事件时返回 task manager runtime event 的测试。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/services/session_event_hub.py members/artist/backend/app/services/task_manager.py members/artist/backend/app/routers/core_http.py members/artist/backend/tests/test_core_http_artist_unit.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_session_event_hub_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `rg -n "list_events|/sessions/\\{session_id\\}/events|task_manager|LamEvent|task_started|SessionEventHub|created_at|category" members/artist/backend/app/services/session_event_hub.py members/artist/backend/app/services/task_manager.py members/artist/backend/app/routers/core_http.py members/artist/backend/tests/test_core_http_artist_unit.py`
- `git diff --check -- members/artist/backend/app/services/session_event_hub.py members/artist/backend/app/services/task_manager.py members/artist/backend/app/routers/core_http.py members/artist/backend/tests/test_core_http_artist_unit.py`
- 行数统计：
  - `members/artist/backend/app/services/session_event_hub.py`：129 行。
  - `members/artist/backend/app/services/task_manager.py`：164 行。
  - `members/artist/backend/app/routers/core_http.py`：352 行。

验证备注：

- 语法检查通过。
- Session event hub unit tests 3 passed。
- Artist core HTTP unit tests 22 passed。
- Generate service unit tests 5 passed。
- Artist session lifecycle tests 2 passed。
- Artist CLI unit tests 10 passed。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- Core events 历史读口不再是空壳；它现在读取同一条 live event hub 历史。
- 这是桥接，不是最终 Core event store 替换；它先移除“Core endpoint 永远空”的债务，同时保持旧 SSE 消费端稳定。

当前遗留：

- `/api/sessions/events` 仍是旧 live SSE endpoint。
- `SessionEventHub` 仍使用 Artist `LamEvent` / `EventLog`，尚未替换为 Core `RuntimeEventRecord` / `RuntimeEventStore`。
- `TaskManager` 的 checkpoint、取消、并发限流职责仍需进一步分类：Artist 专属保留，通用运行期能力再考虑下沉 Core。

下一步：

- Step 10 继续：评估 `SessionEventHub` 是否应以 Core `RuntimeEventRecord` 为内部事实源；若可行，下一切片先替换内部 event record，再保持 SSE 输出兼容。

### 10.8 执行记录：2026-07-01 Step 10 第八切片

目标：

- 继续 Step 10：把 `SessionEventHub` 内部事实源从 Artist `EventLog` 换成 Core `RuntimeEventRecord` / `RuntimeEventStore`。
- 保持旧 Artist `LamEvent` 入参和 `/api/sessions/events` SSE 输出兼容，避免一次性改动 live 前端协议。

已完成：

- `members/artist/backend/app/services/session_event_hub.py`
  - 删除内部 `EventLog` 依赖。
  - 新增 `RuntimeEventStore` 注入点，默认使用 Core `InMemoryRuntimeEventStore`。
  - `publish_task_event()` / `publish_runtime_event()` 将 Artist `LamEvent` 写成 Core `RuntimeEventRecord`。
  - `serialize_sse()` 从 Core event record 还原旧 SSE payload：
    - `event_id`
    - `timestamp`
    - `source_product`
    - `target_product`
    - `object`
    - `event_type`
    - `correlation_id`
    - `payload`
  - `subscribe()` 的 Last-Event-ID replay 改为按 Core record id 回放。
  - `list_events()` 直接读取 Core event store，并过滤掉内部 `_source_product` / `_target_product` payload key。
  - 保留 `max_events` trimming，避免内存事件无限增长。
- `members/artist/backend/tests/test_session_event_hub_unit.py`
  - 新增 Last-Event-ID replay 测试。
  - 新增 Core-shaped event list 测试，确认 payload 不泄漏内部字段。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/services/session_event_hub.py members/artist/backend/app/services/task_manager.py`
- `py -3.14 -m py_compile members/artist/backend/app/services/session_event_hub.py members/artist/backend/tests/test_session_event_hub_unit.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_session_event_hub_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `rg -n "EventLog|RuntimeEventRecord|RuntimeEventStore|InMemoryRuntimeEventStore|_event_store|list_events|last_event_id|_source_product|serialize_sse|publish_runtime_event" members/artist/backend/app/services/session_event_hub.py members/artist/backend/app/services/task_manager.py members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_core_http_artist_unit.py`
- `git diff --check -- members/artist/backend/app/services/session_event_hub.py members/artist/backend/tests/test_session_event_hub_unit.py`
- 行数统计：
  - `members/artist/backend/app/services/session_event_hub.py`：174 行。
  - `members/artist/backend/tests/test_session_event_hub_unit.py`：68 行。

验证备注：

- 语法检查通过。
- Session event hub unit tests 5 passed。
- Artist core HTTP unit tests 22 passed。
- Generate service unit tests 5 passed。
- Artist session lifecycle tests 2 passed。
- Artist CLI unit tests 10 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- Artist event history 的内部事实源已经转为 Core runtime event store。
- `SessionEventHub` 现在只负责三件事：Core event store 写读、SSE 兼容投影、subscriber fan-out。
- Artist `EventLog` 仍存在于 `app.core.events`，但当前 live hub 已不再使用它。

当前遗留：

- 外部发布入口仍接收 Artist `LamEvent`；后续可继续把调用方逐步改为 Core event record 或 Core display/runtime event。
- `/api/sessions/events` 仍是旧 live SSE endpoint；内部已更接近 Core，但 URL 和前端消费协议尚未统一。
- `TaskManager` 的 checkpoint、取消、并发限流职责仍待分类。

下一步：

- Step 10 继续：扫描 `app.core.events.EventLog` 是否只剩历史兼容用途；若可安全收缩，下一切片处理 Artist event model 与 Core event model 的重复定义。

### 10.9 执行记录：2026-07-01 Step 10 第九切片

目标：

- 继续 Step 10：处理 10.8 后遗留的 Artist `app.core.events.EventLog` 重复定义。
- 只删除已无调用点的旧 event log，不触碰仍作为兼容发布 DTO 的 `LamEvent`。

已完成：

- `members/artist/backend/app/core/events/__init__.py`
  - 删除未使用的 `EventLog`。
  - 保留 `LamEvent`，继续供 Artist 旧发布入口和 `SessionEventHub` 兼容输入使用。

验证：

- `rg -n "EventLog|replay_since\\(|LamEvent" members/artist/backend/app members/artist/backend/tests -g "*.py"`
- `py -3.14 -m py_compile members/artist/backend/app/core/events/__init__.py members/artist/backend/app/services/session_event_hub.py members/artist/backend/app/services/task_manager.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_session_event_hub_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `git diff --check -- members/artist/backend/app/core/events/__init__.py`
- 行数统计：
  - `members/artist/backend/app/core/events/__init__.py`：13 行。

验证备注：

- 引用扫描确认 Artist app/tests 内已无 `EventLog` 或 `replay_since()` 调用点；只剩 `LamEvent` 调用点。
- 语法检查通过。
- Session event hub unit tests 5 passed。
- Artist core HTTP unit tests 22 passed。
- Generate service unit tests 5 passed。
- Artist session lifecycle tests 2 passed。
- Artist CLI unit tests 10 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- `members/artist/backend/app/core/events/__init__.py` 从约 41 行降到 13 行。
- Artist 自研 event log 已删除；event history 事实源统一到 Core runtime event store。

当前遗留：

- `LamEvent` 仍是 Artist 兼容发布 DTO，多个 service 仍直接构造它。
- `/api/sessions/events` 仍是旧 live SSE endpoint。
- `TaskManager` 的 checkpoint、取消、并发限流职责仍待分类。

下一步：

- Step 10 继续：扫描 Artist `LamEvent` 构造点，优先选择最小一类事件改为更靠近 Core runtime/display event 的发布 helper，减少调用方直接拼 event payload。

### 10.10 执行记录：2026-07-01 Step 10 第十切片

目标：

- 继续 Step 10：把 Artist `TaskManager` 内的 checkpoint 状态机抽出。
- 保留 `TaskManager` 的旧方法作为兼容 wrapper，不一次性改动调用方。

已完成：

- 新增 `members/artist/backend/app/services/checkpoint_state.py`
  - `CheckpointStateStore`
  - `set_checkpoint_event()`
  - `wait_checkpoint()`
  - `resolve_checkpoint()`
  - `cancel()`
  - `set_state()` / `get_state()`
  - `store_graph_config()` / `get_graph_config()`
  - `clear()`
- `members/artist/backend/app/services/task_manager.py`
  - 删除 checkpoint dict 的内联状态机逻辑。
  - `cancel_task()` 保留取消事件处理，并把 checkpoint release 委托给 `CheckpointStateStore`。
  - checkpoint 相关公开方法保持旧名称，内部转发到 `CheckpointStateStore`。
- 新增 `members/artist/backend/tests/test_checkpoint_state_unit.py`
  - 覆盖 approve resolve。
  - 覆盖 timeout reject。
  - 覆盖 cancel release。
  - 覆盖 graph config roundtrip / clear。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/services/checkpoint_state.py members/artist/backend/app/services/task_manager.py members/artist/backend/tests/test_checkpoint_state_unit.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_checkpoint_state_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `rg -n "CheckpointStateStore|_checkpoint_states|set_checkpoint|wait_checkpoint|resolve_checkpoint|store_graph_config|get_graph_config|clear_checkpoint_state|cancel_task" members/artist/backend/app/services/task_manager.py members/artist/backend/app/services/checkpoint_state.py members/artist/backend/tests/test_checkpoint_state_unit.py`
- `git diff --check -- members/artist/backend/app/services/checkpoint_state.py members/artist/backend/app/services/task_manager.py members/artist/backend/tests/test_checkpoint_state_unit.py`
- 行数统计：
  - `members/artist/backend/app/services/task_manager.py`：136 行。
  - `members/artist/backend/app/services/checkpoint_state.py`：57 行。
  - `members/artist/backend/tests/test_checkpoint_state_unit.py`：29 行。

验证备注：

- 语法检查通过。
- Checkpoint state unit tests 4 passed。
- Generate service unit tests 5 passed。
- Artist session lifecycle tests 2 passed。
- Artist core HTTP unit tests 22 passed。
- Artist CLI unit tests 10 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- `TaskManager` 从 164 行降到 136 行，减少 28 行。
- checkpoint 等待/批准/超时/图配置状态成为独立 deep module；调用方仍可通过原 `TaskManager` 方法使用。

当前遗留：

- `TaskManager` 仍包含任务状态、取消事件、并发 semaphore、event hub 委托。
- `LamEvent` 兼容 DTO 仍由多个 service 直接构造。
- `/api/sessions/events` 仍是旧 live SSE endpoint。

下一步：

- Step 10 继续：优先抽 `TaskManager` 的 task progress 状态与事件发布，进一步让它退化为薄 facade；随后评估是否还能删除 facade。

### 10.11 执行记录：2026-07-01 Step 10 第十一切片

目标：

- 继续 Step 10：把 Artist `TaskManager` 内的 task progress 状态和 `task_progress` 事件发布抽出。
- 保留 `TaskManager.update_task()` / `get_task()` / `get_all_tasks()` / `cleanup_task()` 兼容入口。

已完成：

- 新增 `members/artist/backend/app/services/task_progress.py`
  - `TaskStatus`
  - `TaskInfo`
  - `TaskProgressStore`
  - task snapshot 构造。
  - `task_progress` event 构造和发布。
- `members/artist/backend/app/services/task_manager.py`
  - 删除 `_tasks` 字典和 task snapshot 内联实现。
  - 删除 `update_task()` 内部 `LamEvent(event_type="task_progress")` 构造逻辑。
  - task 相关公开方法改为委托 `TaskProgressStore`。
  - 继续在 `TaskStatus.IDLE` 时清理 cancel event，保留原取消语义。
- 新增 `members/artist/backend/tests/test_task_progress_unit.py`
  - 覆盖 task snapshot 存储。
  - 覆盖 idle 清理但仍发布 progress event。
  - 覆盖 SSE payload 旧协议形状。
- 修正 task status 序列化：
  - 使用 `TaskStatus.value` 输出 `generating` / `idle` / `error`，避免 `TaskStatus.GENERATING` 泄漏到前端协议。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/services/task_progress.py members/artist/backend/app/services/task_manager.py members/artist/backend/tests/test_task_progress_unit.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_task_progress_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `rg -n "TaskProgressStore|TaskStatus|TaskInfo|_task_progress|_tasks|update_task|get_all_tasks|get_task|cleanup_task|task_progress" members/artist/backend/app/services/task_manager.py members/artist/backend/app/services/task_progress.py members/artist/backend/tests/test_task_progress_unit.py members/artist/backend/app members/artist/backend/tests -g "*.py"`
- `git diff --check -- members/artist/backend/app/services/task_progress.py members/artist/backend/app/services/task_manager.py members/artist/backend/tests/test_task_progress_unit.py`
- 行数统计：
  - `members/artist/backend/app/services/task_manager.py`：93 行。
  - `members/artist/backend/app/services/task_progress.py`：79 行。
  - `members/artist/backend/tests/test_task_progress_unit.py`：44 行。

验证备注：

- 首轮新增测试暴露状态字符串化问题：`str(TaskStatus.GENERATING)` 会输出 `TaskStatus.GENERATING`。
- 已改为 `.value` 后重跑通过。
- Task progress unit tests 3 passed。
- Generate service unit tests 5 passed。
- Artist session lifecycle tests 2 passed。
- Artist core HTTP unit tests 22 passed。
- Artist CLI unit tests 10 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。
- 语法检查和 diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- `TaskManager` 从 136 行降到 93 行，减少 43 行。
- task progress 状态和事件发布成为独立 deep module。
- `TaskManager` 当前主要剩余：event hub facade、checkpoint facade、cancel event、semaphore。

当前遗留：

- `TaskManager` 仍是多 facade 聚合体，尚未确认是否可以删除。
- `LamEvent` 兼容 DTO 仍由多个 service 直接构造。
- `/api/sessions/events` 仍是旧 live SSE endpoint。

下一步：

- Step 10 继续：抽取消状态或并发 semaphore；随后评估 `TaskManager` 是否已足够薄，能否改名为 runtime coordination facade 或进一步删除。

### 10.12 执行记录：2026-07-01 Step 10 第十二切片

目标：

- 继续 Step 10：删除 Artist `TaskManager` 中未使用的 cancel event 状态。
- 保留 `/api/sessions/{session_id}/cancel` 现有实际语义：释放 checkpoint wait。

已完成：

- `members/artist/backend/app/services/task_manager.py`
  - 删除 `_cancel_events` 字典。
  - 删除无调用点的 `get_cancel_event()`。
  - 删除 `update_task(IDLE)` / `cleanup_task()` 中对 cancel event 的空清理。
  - `cancel_task()` 只保留当前实际生效的 checkpoint release。

验证：

- `rg -n "get_cancel_event|_cancel_events|cancel_task|cleanup_task|TaskManager" members/artist/backend/app members/artist/backend/tests -g "*.py"`
- `py -3.14 -m py_compile members/artist/backend/app/services/task_manager.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_task_progress_unit.py members/artist/backend/tests/test_checkpoint_state_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `git diff --check -- members/artist/backend/app/services/task_manager.py`
- 行数统计：
  - `members/artist/backend/app/services/task_manager.py`：82 行。

验证备注：

- 引用扫描确认无 `get_cancel_event` 或 `_cancel_events` 残留。
- 语法检查通过。
- Task progress + checkpoint state unit tests 7 passed。
- Generate service unit tests 5 passed。
- Artist session lifecycle tests 2 passed。
- Artist core HTTP unit tests 22 passed。
- Artist CLI unit tests 10 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- `TaskManager` 从 93 行降到 82 行，减少 11 行。
- 未被调用的取消事件状态已删除；取消 endpoint 的当前有效行为变得明确：释放 checkpoint。

当前遗留：

- `TaskManager` 仍持有 semaphore 和三个 facade：event hub、task progress、checkpoint state。
- `/api/sessions/events` 仍是旧 live SSE endpoint。
- `LamEvent` 兼容 DTO 仍由多个 service 直接构造。

下一步：

- Step 10 继续：检查 `TaskManager.acquire()` / `release()` 是否有真实调用点；如果没有，删除 semaphore；如果有，则抽成独立 concurrency limiter。

### 10.13 执行记录：2026-07-01 Step 10 第十三切片

目标：

- 继续 Step 10：检查并处理 Artist `TaskManager` 中的 semaphore facade。
- 如果 `TaskManager.acquire()` / `release()` 没有真实调用点，直接删除，不保留空抽象。

已完成：

- `members/artist/backend/app/services/task_manager.py`
  - 删除 `_semaphore = asyncio.Semaphore(5)`。
  - 删除无调用点的 `acquire()` / `release()`。
  - 保留 engine / generate_service 内部各自真实使用的局部 semaphore，不改其行为。

验证：

- `rg -n "TaskManager\\(|\\.acquire\\(|\\.release\\(|acquire\\(|release\\(|_semaphore|Semaphore\\(" members/artist/backend/app members/artist/backend/tests -g "*.py"`
- `py -3.14 -m py_compile members/artist/backend/app/services/task_manager.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_task_progress_unit.py members/artist/backend/tests/test_checkpoint_state_unit.py members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `git diff --check -- members/artist/backend/app/services/task_manager.py`
- 行数统计：
  - `members/artist/backend/app/services/task_manager.py`：77 行。

验证备注：

- 引用扫描确认 `TaskManager.acquire()` / `TaskManager.release()` 无调用点。
- 真实 semaphore 调用仍存在于 `generate_service.py` 和 `executors/engine.py` 的局部并发控制中，本切片未改动。
- 语法检查通过。
- Task progress + checkpoint + generate service unit tests 12 passed。
- Artist session lifecycle + core HTTP unit tests 24 passed。
- Artist CLI unit tests 10 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- `TaskManager` 从 82 行降到 77 行，减少 5 行。
- 未使用的并发 facade 已删除；实际并发控制仍在真实调用点附近。

当前遗留：

- `TaskManager` 现在只聚合 event hub、task progress、checkpoint state 三类 facade。
- `/api/sessions/events` 仍是旧 live SSE endpoint。
- `LamEvent` 兼容 DTO 仍由多个 service 直接构造。

下一步：

- Step 10 继续：评估 `TaskManager` 是否仍有存在价值；优先把 `/api/sessions/events`、`/api/core/sessions/{id}/events` 和服务发布入口直接改用更明确的 facade，减少 `TaskManager` 这个泛名聚合体。

### 10.14 执行记录：2026-07-01 Step 10 第十四切片

目标：

- 继续 Step 10：把 Artist Core adapter 内的 `decide_next` 规则抽为独立 decision policy。
- 保留 `ArtistKit.decide_next()` 兼容 async 方法，避免改动 KernelKit 接口。

已完成：

- 新增 `members/artist/backend/app/core/artist/decision_policy.py`
  - `GENERATE_TOOLS`
  - `decide_next_action()`
  - wait / generated image observation / verification retry / pending observation / retry stop / tool failure / text-only done 等决策规则。
- `members/artist/backend/app/core/artist/core_kernel_adapter.py`
  - `decide_next()` 改为调用 `decide_next_action()`。
  - 删除 adapter 内联决策规则。

验证：

- `rg -n "_GENERATE_TOOLS|decide_next_action|GENERATE_TOOLS|decision_hint|retry_stop|pending_observation_indices" members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/decision_policy.py members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py`
- `py -3.14 -m py_compile members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/decision_policy.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q -k "decide or decision or verification or generate_image"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `git diff --check -- members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/decision_policy.py`
- 行数统计：
  - `members/artist/backend/app/core/artist/core_kernel_adapter.py`：1017 行。
  - `members/artist/backend/app/core/artist/decision_policy.py`：60 行。

验证备注：

- 语法检查通过。
- Artist decision targeted tests 14 passed，47 deselected。
- Artist core kernel adapter unit tests 61 passed。
- Artist core HTTP unit tests 22 passed。
- Generate service unit tests 5 passed。
- Artist session lifecycle tests 2 passed。
- Artist CLI unit tests 10 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- `members/artist/backend/app/core/artist/core_kernel_adapter.py` 从 1089 行降到 1017 行，减少 72 行。
- Artist loop decision rules 成为独立 deep module；Kit 只保留 KernelKit seam 的兼容方法。

当前遗留：

- Artist `writeback()` 仍在 Core adapter 内。
- `TaskManager` 仍是 event hub / task progress / checkpoint state 的 facade。
- `/api/sessions/events` 仍是旧 live SSE endpoint。
- `LamEvent` 兼容 DTO 仍由多个 service 直接构造。

下一步：

- Step 10 继续：优先抽 Artist `writeback()`；之后再评估 `TaskManager` facade 和旧 SSE endpoint 是否还能继续收缩。

### 10.15 执行记录：2026-07-01 Step 10 第十五切片

目标：

- 继续 Step 10：把 Artist Core adapter 内的 `writeback()` 元数据持久化逻辑抽为独立 module。
- 保留 `ArtistKit.writeback()` 兼容 async 方法，避免改动 KernelKit 接口。

已完成：

- 新增 `members/artist/backend/app/core/artist/writeback.py`
  - `MAX_ARTIFACT_REGISTRY_ITEMS`
  - `execute_artist_writeback()`
  - verification attempt counter 写回。
  - lineage head / persisted count 写回。
  - visual memory summary 写回。
  - artifact registry bounded append。
  - `artist_writeback` lifecycle event 发射。
  - `artist_last_decision` 写回。
- `members/artist/backend/app/core/artist/core_kernel_adapter.py`
  - `writeback()` 改为调用 `execute_artist_writeback()`。
  - 删除 adapter 内联 writeback 实现。
  - 移除 adapter 内的 `_MAX_VISUAL_MEMORY_ARTIFACTS`。

验证：

- `rg -n "execute_artist_writeback|MAX_ARTIFACT_REGISTRY_ITEMS|_MAX_VISUAL_MEMORY_ARTIFACTS|artist_writeback|artist_last_decision|artifact_registry|lineage_items_persisted|visual_memory_artifact_count" members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/writeback.py members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py`
- `py -3.14 -m py_compile members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/writeback.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q -k "writeback or lineage or artifact_registry or visual_memory or verification"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `git diff --check -- members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/writeback.py`
- 行数统计：
  - `members/artist/backend/app/core/artist/core_kernel_adapter.py`：961 行。
  - `members/artist/backend/app/core/artist/writeback.py`：73 行。

验证备注：

- 语法检查通过。
- Artist writeback targeted tests 9 passed，52 deselected。
- Artist core kernel adapter unit tests 61 passed。
- Artist core HTTP unit tests 22 passed。
- Generate service unit tests 5 passed。
- Artist session lifecycle tests 2 passed。
- Artist CLI unit tests 10 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- `members/artist/backend/app/core/artist/core_kernel_adapter.py` 从 1017 行降到 961 行，减少 56 行。
- Artist writeback metadata mutation 成为独立 deep module；Kit 只保留 KernelKit seam 的兼容方法。

当前遗留：

- `TaskManager` 仍是 event hub / task progress / checkpoint state 的 facade。
- `/api/sessions/events` 仍是旧 live SSE endpoint。
- `LamEvent` 兼容 DTO 仍由多个 service 直接构造。

下一步：

- Step 10 继续：评估 Artist Core adapter 剩余大块职责，优先处理 verification 或 format_tool_result；同时继续评估 `TaskManager` facade 是否可以被明确 facade 替代。

### 10.16 执行记录：2026-07-01 Step 10 第十六切片

目标：

- 继续 Step 10：把 Artist Core adapter 内的 `verify()` 视觉验收和补充检查逻辑抽为独立 module。
- 保留 `ArtistKit.verify()` 兼容 async 方法，避免改动 KernelKit 接口。

已完成：

- 新增 `members/artist/backend/app/core/artist/verification.py`
  - `GENERATE_TOOLS`
  - `verify_artist_turn()`
  - generated artifact URL 收集。
  - `_pending_verify_artifacts` fallback 读取与清理。
  - supplementary checks：
    - generated artifacts
    - identity consistency
    - artifact review status
    - ineffective retry
  - `artist_verification_passed` / `artist_verification_failed` event 发射。
  - VLM visual verification request 构造。
  - VLM failure / parse failure fallback。
  - `_verify_attempt` 计数和 `VerificationResult` 构造。
- `members/artist/backend/app/core/artist/core_kernel_adapter.py`
  - `verify()` 改为调用 `verify_artist_turn()`。
  - 删除 adapter 内联 verification 实现。
  - 清理不再使用的 verification imports。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/verification.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q -k "verification or verify or vlm or artifact_review or retry"`
- `rg -n "verify_artist_turn|CompletionCheck|artist_verification|VERIFICATION_SYSTEM_PROMPT|parse_verification_response|build_verification_user_message|_pending_verify_artifacts|_verify_attempt" members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/verification.py members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `git diff --check -- members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/verification.py`
- 行数统计：
  - `members/artist/backend/app/core/artist/core_kernel_adapter.py`：793 行。
  - `members/artist/backend/app/core/artist/verification.py`：185 行。

验证备注：

- 语法检查通过。
- Artist verification targeted tests 5 passed，56 deselected。
- Artist core kernel adapter unit tests 61 passed。
- Artist core HTTP unit tests 22 passed。
- Generate service unit tests 5 passed。
- Artist session lifecycle tests 2 passed。
- Artist CLI unit tests 10 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- `members/artist/backend/app/core/artist/core_kernel_adapter.py` 从 961 行降到 793 行，减少 168 行。
- Artist verification 成为独立 deep module；Kit 只保留 KernelKit seam 的兼容方法。

当前遗留：

- `format_tool_result_for_model()` 仍在 Core adapter 内。
- `TaskManager` 仍是 event hub / task progress / checkpoint state 的 facade。
- `/api/sessions/events` 仍是旧 live SSE endpoint。
- `LamEvent` 兼容 DTO 仍由多个 service 直接构造。

下一步：

- Step 10 继续：抽 `format_tool_result_for_model()`；随后评估 Artist adapter 是否已足够薄，进入 TaskManager/SSE façade 收口。

### 10.17 执行记录：2026-07-01 Step 10 第十七切片

目标：

- 继续 Step 10：把 Artist Core adapter 内的 `format_tool_result_for_model()` 业务格式化和元数据更新逻辑抽为独立 module。
- 保留 `ArtistKit.format_tool_result_for_model()` 兼容 async 方法，避免改动 KernelKit 接口。

已完成：

- 新增 `members/artist/backend/app/core/artist/tool_result_formatting.py`
  - `GENERATE_TOOLS`
  - `format_artist_tool_result_for_model()`
  - tool result content fallback。
  - generated image history 写入。
  - `artist_artifact_generated` lifecycle event 发射。
  - `artist_tool_failure` error event 发射。
  - visual memory artifact count 更新。
  - generated image URL 注入 tool message。
  - `_pending_verify_artifacts` 写入，供 verification 使用。
- `members/artist/backend/app/core/artist/core_kernel_adapter.py`
  - `format_tool_result_for_model()` 改为调用 `format_artist_tool_result_for_model()`。
  - 删除 adapter 内联 tool result formatting 实现。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/tool_result_formatting.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q -k "format or pending_verify or generation_history or tool_failure or artifact_generated"`
- `rg -n "format_artist_tool_result_for_model|artist_artifact_generated|artist_tool_failure|generation_history|_pending_verify_artifacts|visual_memory_artifact_count|ChatMessage|CoreEvent" members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/tool_result_formatting.py members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `git diff --check -- members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/tool_result_formatting.py`
- 行数统计：
  - `members/artist/backend/app/core/artist/core_kernel_adapter.py`：728 行。
  - `members/artist/backend/app/core/artist/tool_result_formatting.py`：81 行。

验证备注：

- 语法检查通过。
- Artist format targeted tests 2 passed，59 deselected。
- Artist core kernel adapter unit tests 61 passed。
- Artist core HTTP unit tests 22 passed。
- Generate service unit tests 5 passed。
- Artist session lifecycle tests 2 passed。
- Artist CLI unit tests 10 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- `members/artist/backend/app/core/artist/core_kernel_adapter.py` 从 793 行降到 728 行，减少 65 行。
- Artist tool result formatting 成为独立 deep module；Kit 只保留 KernelKit seam 的兼容方法。

当前遗留：

- Artist adapter 已低于 1000 行，但仍包含 prompt assembly、LLM adapter 和 tool dispatch facade。
- `TaskManager` 仍是 event hub / task progress / checkpoint state 的 facade。
- `/api/sessions/events` 仍是旧 live SSE endpoint。
- `LamEvent` 兼容 DTO 仍由多个 service 直接构造。

下一步：

- Step 10 继续：对 Artist adapter 做剩余职责扫描，确认是否继续抽 prompt assembly / LLM adapters，或转入 TaskManager/SSE facade 收口。

### 10.18 执行记录：2026-07-01 Step 10 第十八切片

目标：

- 继续 Step 10：把 Artist Core adapter 内的 LLM/VLM client adapter 抽成独立 module。
- 保留 `core_kernel_adapter.py` 对 `ArtistLLMClientAdapter` / `ArtistVLMClientAdapter` 的 re-export，避免破坏现有测试和外部导入路径。

已完成：

- 新增 `members/artist/backend/app/core/artist/llm_adapters.py`
  - `ArtistLLMClientAdapter`
  - `ArtistVLMClientAdapter`
  - Core `LLMRequest` 到 Artist callable 的 payload 转换。
  - text-only / multimodal routing。
  - usage normalization。
  - streaming unsupported 行为保持不变。
- `members/artist/backend/app/core/artist/core_kernel_adapter.py`
  - 删除内联 LLM/VLM adapter 实现。
  - 仅从 `llm_adapters.py` 导入并继续导出同名入口。
  - 清理不再使用的 `AsyncIterator`、`LLMStreamEvent`、`build_openai_payload`、`normalize_usage` import。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/llm_adapters.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q -k "LLMClientAdapter or VLMClientAdapter or text_only or visual_context"`
- `rg -n "ArtistLLMClientAdapter|ArtistVLMClientAdapter|build_openai_payload|normalize_usage|LLMStreamEvent|LLMResponse" members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/llm_adapters.py members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `git diff --check -- members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/llm_adapters.py`
- 行数统计：
  - `members/artist/backend/app/core/artist/core_kernel_adapter.py`：642 行。
  - `members/artist/backend/app/core/artist/llm_adapters.py`：71 行。

验证备注：

- 语法检查通过。
- Artist LLM/VLM adapter targeted tests 18 passed，43 deselected。
- Artist core kernel adapter unit tests 61 passed。
- Artist core HTTP unit tests 22 passed。
- Generate service unit tests 5 passed。
- Artist session lifecycle tests 2 passed。
- Artist CLI unit tests 10 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- `members/artist/backend/app/core/artist/core_kernel_adapter.py` 从 728 行降到 642 行，减少 86 行。
- LLM/VLM callable 适配成为独立 module；Kit/runner 只选择具体 client adapter，不承载 payload 转换细节。

当前遗留：

- Artist adapter 仍包含 prompt assembly、model output parsing 和 tool dispatch facade。
- `TaskManager` 仍是 event hub / task progress / checkpoint state 的 facade。
- `/api/sessions/events` 仍是旧 live SSE endpoint。
- `LamEvent` 兼容 DTO 仍由多个 service 直接构造。

下一步：

- Step 10 继续：优先评估 `build_context()` / `build_model_request()` 是否可抽成 prompt/request module；若抽取收益不足，转入 TaskManager/SSE facade 收口。

### 10.19 执行记录：2026-07-01 Step 10 第十九切片

目标：

- 继续 Step 10：把 Artist Core adapter 内的 prompt context 和 model request 构建抽成独立 module。
- 保持 `ArtistKit.build_context()` / `ArtistKit.build_model_request()` 作为 KernelKit seam 的兼容方法，只做委托。

已完成：

- 新增 `members/artist/backend/app/core/artist/prompt_request.py`
  - `build_artist_prompt_context()`
  - `build_artist_model_request()`
  - runtime metadata 到 prompt context 的提取。
  - hook/context metadata 到 system constraint message 的格式化。
  - visual context 到 multimodal user message 的构造。
  - Artist request 参数：temperature、max_tokens、json response_format 保持不变。
- `members/artist/backend/app/core/artist/core_kernel_adapter.py`
  - 删除 `_extract_visual_context()` / `_extract_lineage_context()` / `_extract_generation_params()` / `_extract_artifact_review_status()` pass-through wrapper。
  - `build_context()` 改为调用 `build_artist_prompt_context()`。
  - `build_model_request()` 改为调用 `build_artist_model_request()`。
  - 清理不再需要的 identity/runtime context imports。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/prompt_request.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q -k "BuildContext or BuildModelRequest or visual_context or multimodal"`
- `rg -n "build_artist_prompt_context|build_artist_model_request|ARTIST_RUNTIME_SYSTEM|extract_visual_context|extract_lineage_context|extract_generation_params|extract_artifact_review_status|_extract_visual_context" members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/prompt_request.py members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `git diff --check -- members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/prompt_request.py`
- 行数统计：
  - `members/artist/backend/app/core/artist/core_kernel_adapter.py`：536 行。
  - `members/artist/backend/app/core/artist/prompt_request.py`：130 行。

验证备注：

- 语法检查通过。
- Artist prompt/request targeted tests 10 passed，51 deselected。
- Artist core kernel adapter unit tests 61 passed。
- Artist core HTTP unit tests 22 passed。
- Generate service unit tests 5 passed。
- Artist session lifecycle tests 2 passed。
- Artist CLI unit tests 10 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- `members/artist/backend/app/core/artist/core_kernel_adapter.py` 从 642 行降到 536 行，减少 106 行。
- Prompt context 和 model request 构建成为独立 deep module；Kit 只保留 KernelKit seam。
- 删除 4 个 adapter 内 pass-through wrapper，复杂度没有新增接口层。

当前遗留：

- Artist adapter 仍包含 model output parsing、tool dispatch facade、run_core_kernel 装配。
- `TaskManager` 仍是 event hub / task progress / checkpoint state 的 facade。
- `/api/sessions/events` 仍是旧 live SSE endpoint。
- `LamEvent` 兼容 DTO 仍由多个 service 直接构造。

下一步：

- Step 10 继续：评估 model output parsing 是否可抽成 `model_output.py`，或转入 tool dispatch / TaskManager-SSE facade 收口。

### 10.20 执行记录：2026-07-01 Step 10 第二十切片

目标：

- 继续 Step 10：把 Artist Core adapter 内的 model output parsing 和 `KernelTurn` 映射抽成独立 module。
- 保持 `ArtistKit.parse_model_output()` 作为 KernelKit seam 的兼容方法，只做委托。

已完成：

- 新增 `members/artist/backend/app/core/artist/model_output.py`
  - `parse_artist_model_output()`
  - Artist JSON turn 解析。
  - tool call id 生成和 arguments fallback。
  - `is_complete` / `needs_user_input` 到 Core `decision_hint` 的映射。
  - usage 和 `artist_turn_raw` metadata 保持不变。
- `members/artist/backend/app/core/artist/core_kernel_adapter.py`
  - `parse_model_output()` 改为调用 `parse_artist_model_output()`。
  - 删除 adapter 内联 parse/mapping 实现。
  - 清理不再使用的 `uuid4` 和 `parse_artist_loop_turn` import。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/model_output.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q -k "parse_model_output or text_reply or generate_image or ask_user"`
- `rg -n "parse_artist_model_output|parse_artist_loop_turn|uuid4|artist_turn_raw|decision_hint" members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/model_output.py members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `git diff --check -- members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/model_output.py`
- 行数统计：
  - `members/artist/backend/app/core/artist/core_kernel_adapter.py`：503 行。
  - `members/artist/backend/app/core/artist/model_output.py`：39 行。

验证备注：

- 语法检查通过。
- Artist parse/model-output targeted tests 14 passed，47 deselected。
- Artist core kernel adapter unit tests 61 passed。
- Artist core HTTP unit tests 22 passed。
- Generate service unit tests 5 passed。
- Artist session lifecycle tests 2 passed。
- Artist CLI unit tests 10 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- `members/artist/backend/app/core/artist/core_kernel_adapter.py` 从 536 行降到 503 行，减少 33 行。
- Artist output parsing 和 Core turn 映射成为独立 module；Kit 只保留 KernelKit seam。

当前遗留：

- Artist adapter 仍包含 tool dispatch facade、run_core_kernel 装配和少量 lifecycle glue。
- `TaskManager` 仍是 event hub / task progress / checkpoint state 的 facade。
- `/api/sessions/events` 仍是旧 live SSE endpoint。
- `LamEvent` 兼容 DTO 仍由多个 service 直接构造。

下一步：

- Step 10 继续：评估 tool dispatch 是否还能减法抽取；随后进入 TaskManager/SSE facade 收口。

### 10.21 执行记录：2026-07-01 Step 10 第二十一切片

目标：

- 继续 Step 10：把 Artist Core adapter 内的 tool dispatch 和浅层 reference/generation wrapper 收口到独立 module。
- 保持 `ArtistKit.execute_tool()` 作为 KernelKit seam 的兼容方法，只做委托。

已完成：

- 新增 `members/artist/backend/app/core/artist/tool_dispatch.py`
  - `execute_artist_tool()`
  - `generate_image` task prompt 写入和 `_pending_verify_artifacts` 清理。
  - 生成图工具调用后追加 lineage items。
  - `finish` / `ask_user` / `inspect_lineage` / `set_lineage_head` / unsupported tool 映射。
- `members/artist/backend/app/core/artist/core_kernel_adapter.py`
  - `execute_tool()` 改为调用 `execute_artist_tool()`。
  - 删除 `_execute_inspect_lineage()` / `_execute_set_lineage_head()`。
  - 删除 `_append_generated_lineage_items()`。
  - 删除 `_resolve_reference_images_from_args()` / `_resolve_reference_images_from_visual_context()` / `_resolve_artifact_index_references()`。
  - 删除 `_build_reference_images()` / `_build_reference_images_with_context()` / `_reference_metadata()`。
  - 删除 `_execute_generate_image()` / `_execute_generate_image_single()` / `_execute_generate_image_items()`。
  - 清理不再需要的 generation / lineage / visual reference imports。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/tool_dispatch.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q -k "execute_tool or generate_image or lineage or source_image_urls"`
- `rg -n "execute_artist_tool|_execute_generate_image|_build_reference_images|_resolve_reference_images|_resolve_artifact_index_references|_execute_inspect_lineage|_execute_set_lineage_head|append_generated_lineage_items|inspect_lineage_tool|set_lineage_head_tool|execute_generate_image_tool" members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/tool_dispatch.py members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_http_e2e.py -q`
- `git diff --check -- members/artist/backend/app/core/artist/core_kernel_adapter.py members/artist/backend/app/core/artist/tool_dispatch.py`
- 行数统计：
  - `members/artist/backend/app/core/artist/core_kernel_adapter.py`：366 行。
  - `members/artist/backend/app/core/artist/tool_dispatch.py`：53 行。

验证备注：

- 语法检查通过。
- Artist tool dispatch targeted tests 18 passed，43 deselected。
- Artist core kernel adapter unit tests 61 passed。
- Artist core HTTP unit tests 22 passed。
- Generate service unit tests 5 passed。
- Artist session lifecycle tests 2 passed。
- Artist CLI unit tests 10 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Artist core HTTP e2e 2 skipped；当前环境按测试条件跳过，不作为完成证明。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- `members/artist/backend/app/core/artist/core_kernel_adapter.py` 从 503 行降到 366 行，减少 137 行。
- 删除多个无外部入边的 adapter private wrapper；tool dispatch 成为独立 module，生成图细节继续留在 `generation_tools.py`。
- Artist adapter 现在主要剩 KernelKit lifecycle glue、event sink 和 `run_core_kernel()` 装配。

当前遗留：

- Artist adapter 仍包含 `InMemoryEventSink` 和 `run_core_kernel()` 装配。
- `TaskManager` 仍是 event hub / task progress / checkpoint state 的 facade。
- `/api/sessions/events` 仍是旧 live SSE endpoint。
- `LamEvent` 兼容 DTO 仍由多个 service 直接构造。

下一步：

- Step 10 转入 TaskManager/SSE facade 收口：优先核对 live SSE 与 Core event history 的关系，选择最小可验证切片。

### 10.22 执行记录：2026-07-01 Step 10 第二十二切片

目标：

- Step 10 转入 TaskManager/SSE facade 收口。
- 先清理 `/api/sessions` router 内的重复 `TaskManager()` 构造，让 live SSE 和 cancel 路由使用模块级全局 `task_manager`。

已完成：

- `members/artist/backend/app/routers/session.py`
  - `from app.services.task_manager import TaskManager, TaskStatus` 改为 `TaskStatus, task_manager`。
  - `/api/sessions/events` 不再在请求路径内构造 `TaskManager()`。
  - `_run_artist_background()` 删除局部 `task_manager` import，直接使用模块级全局。
  - `/api/sessions/{session_id}/cancel` 不再构造 `TaskManager()`。
- `members/artist/backend/tests/test_core_http_artist_unit.py`
  - 新增 `test_existing_cancel_route_uses_global_task_manager()`，验证 cancel 路由调用 `app.routers.session.task_manager.cancel_task`。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/routers/session.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q -k "existing_sessions_route or cancel_route or events"`
- `rg -n "from app\\.services\\.task_manager import TaskManager|TaskManager\\(\\)|task_manager\\.subscribe|task_manager\\.cancel_task|task_manager\\.get_all_tasks" members/artist/backend/app/routers/session.py members/artist/backend/tests/test_core_http_artist_unit.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `git diff --check -- members/artist/backend/app/routers/session.py members/artist/backend/tests/test_core_http_artist_unit.py`
- `rg -n "TaskManager\\(\\)" members/artist/backend/app/routers/session.py members/artist/backend/app/services/generate_service.py members/artist/backend/app/services/artist_service.py`

验证备注：

- 语法检查通过。
- Session/Core HTTP targeted tests 5 passed，18 deselected。
- Artist core HTTP unit tests 23 passed。
- Artist session lifecycle tests 2 passed。
- Generate service unit tests 5 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。
- `TaskManager()` 直接构造点已从 `routers/session.py` 清除；当前剩余构造点：
  - `members/artist/backend/app/services/generate_service.py:824`
  - `members/artist/backend/app/services/artist_service.py:735`

当前收缩：

- `/api/sessions/events` 和 `/api/sessions/{session_id}/cancel` 统一使用全局 task manager；请求路径不再生成 facade 实例。
- 这是 TaskManager/SSE 收口的第一片，未改变 live SSE 协议。

当前遗留：

- `TaskManager` 仍是 event hub / task progress / checkpoint state 的 facade。
- `generate_service.py` 和 `artist_service.py` 仍有直接 `TaskManager()` fallback。
- `/api/sessions/events` 仍是旧 live SSE endpoint。
- `LamEvent` 兼容 DTO 仍由多个 service 直接构造。

下一步：

- Step 10 继续：清理 `generate_service.py` / `artist_service.py` 的直接 `TaskManager()` fallback，随后再判断 TaskManager facade 是否可以拆成更明确的 event/task/checkpoint 入口。

### 10.23 执行记录：2026-07-01 Step 10 第二十三切片

目标：

- 继续 TaskManager/SSE facade 收口：清理 `generate_service.py` / `artist_service.py` 内的直接 `TaskManager()` fallback。
- 让业务路径统一使用模块级全局 `task_manager`，避免隐藏构造新的 facade 实例。

已完成：

- `members/artist/backend/app/services/generate_service.py`
  - `handle_artist_generate()` 内 `task_manager = TaskManager()` 改为 `task_manager = global_task_manager`。
- `members/artist/backend/app/services/artist_service.py`
  - `_execution_engine_run()` 内 `from app.services.task_manager import TaskManager` 改为导入 `task_manager as global_task_manager`。
  - `task_mgr or TaskManager()` 改为 `task_mgr or global_task_manager`。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/services/generate_service.py members/artist/backend/app/services/artist_service.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `rg -n "TaskManager\\(\\)|from app\\.services\\.task_manager import TaskManager" members/artist/backend/app members/artist/backend/tests -g "*.py"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `git diff --check -- members/artist/backend/app/services/generate_service.py members/artist/backend/app/services/artist_service.py`

验证备注：

- 语法检查通过。
- Generate service unit tests 5 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Artist core kernel adapter unit tests 61 passed。
- Artist core HTTP unit tests 23 passed。
- Artist session lifecycle tests 2 passed。
- Artist CLI unit tests 10 passed。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。
- `TaskManager()` 生产业务路径构造已清除；当前扫描剩余：
  - `members/artist/backend/app/services/task_manager.py:104` 模块级单例创建。
  - `members/artist/backend/app/services/generate_service.py:26` / `executors/engine.py:27` 类型导入。
  - `members/artist/backend/tests/test_generate_service_unit.py` 测试 fake 名称。

当前收缩：

- Artist 业务主线不再临时构造 `TaskManager` facade。
- TaskManager 使用点集中到模块级 `task_manager` 和显式参数注入，后续可以更清楚地拆分 event/task/checkpoint 入口。

当前遗留：

- `TaskManager` 仍是 event hub / task progress / checkpoint state 的 facade。
- `/api/sessions/events` 仍是旧 live SSE endpoint。
- `LamEvent` 兼容 DTO 仍由多个 service 直接构造。
- `executors/engine.py` 仍以 `TaskManager` 类型作为进度发布参数。

下一步：

- Step 10 继续：评估 TaskManager facade 拆分，优先把 event publish/subscribe/history 暴露为明确 event gateway，减少业务层对大 facade 的认知。

### 10.24 执行记录：2026-07-01 Step 10 第二十四切片

目标：

- 继续 TaskManager/SSE facade 收口：把事件 publish / subscribe / history 职责从 `TaskManager` 内部抽成明确 event stream module。
- 保持现有 `TaskManager.publish()` / `subscribe()` / `list_events()` 外部兼容，先做内部职责拆分，不改 live SSE 协议。

已完成：

- 新增 `members/artist/backend/app/services/task_events.py`
  - `TaskEventStream`
  - `publish()`：LamEvent 到 Core-shaped runtime event 的发布、日志和关键事件无订阅者告警。
  - `subscribe()`：SSE 订阅，继续跳过 checkpoint replay。
  - `unsubscribe()` / `queue_count()` / `list_events()`。
  - 暴露 `event_hub` 给 `TaskProgressStore` 继续复用同一事件存储和 fan-out。
- `members/artist/backend/app/services/task_manager.py`
  - 删除内部 `_event_hub` 直接管理。
  - 使用 `_events = TaskEventStream(max_events=2000)`。
  - `TaskProgressStore` 绑定到 `_events.event_hub`。
  - event 相关方法改为委托 `_events`。
- 新增 `members/artist/backend/tests/test_task_events_unit.py`
  - 覆盖 publish、subscribe、history、unsubscribe、queue_count。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/services/task_manager.py members/artist/backend/app/services/task_events.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_progress_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q -k "events or cancel_route"`
- `rg -n "SessionEventHub|max_events|publish: type|critical event|_event_hub|_events|TaskEventStream" members/artist/backend/app/services/task_manager.py members/artist/backend/app/services/task_events.py members/artist/backend/tests/test_task_events_unit.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `git diff --check -- members/artist/backend/app/services/task_manager.py members/artist/backend/app/services/task_events.py members/artist/backend/tests/test_task_events_unit.py`
- 行数统计：
  - `members/artist/backend/app/services/task_manager.py`：69 行。
  - `members/artist/backend/app/services/task_events.py`：48 行。

验证备注：

- 语法检查通过。
- Task event/session hub/task progress tests 9 passed。
- Core HTTP event/cancel targeted tests 4 passed，19 deselected。
- Generate service unit tests 5 passed。
- Artist session lifecycle tests 2 passed。
- Artist CLI unit tests 10 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- `TaskManager` 不再直接管理 session event hub 和事件发布细节。
- Event stream 成为可单独测试的 module，后续可把 `/api/sessions/events`、CLI live watch、Core event history 逐步迁到更明确的 event 入口。

当前遗留：

- `TaskManager` 仍聚合 task progress 和 checkpoint state。
- `/api/sessions/events` 仍通过 `task_manager.subscribe()`，尚未直接使用 event stream。
- `LamEvent` 兼容 DTO 仍由多个 service 直接构造。
- `executors/engine.py` 仍以 `TaskManager` 类型作为进度发布参数。

下一步：

- Step 10 继续：把 live SSE route / Core events route / CLI live watch 的事件读写入口逐步迁到 `TaskEventStream` 或全局 event gateway，进一步降低 `TaskManager` 的事件职责。

### 10.25 执行记录：2026-07-01 Step 10 第二十五切片

目标：

- 为后续迁移 live SSE route / Core event history / CLI live watch 铺入口。
- 将 `TaskEventStream` 提升为模块级共享 `task_events`，让 `TaskManager` 使用同一个 event gateway，而不是自行创建私有 event stream。

已完成：

- `members/artist/backend/app/services/task_events.py`
  - 新增模块级 `task_events = TaskEventStream(max_events=2000)`。
- `members/artist/backend/app/services/task_manager.py`
  - 改为 `from app.services.task_events import task_events`。
  - `self._events = task_events`。
  - `TaskProgressStore` 继续绑定 `self._events.event_hub`，保持 task progress 与 runtime event SSE/history 使用同一 hub。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/services/task_manager.py members/artist/backend/app/services/task_events.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_progress_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q -k "events or cancel_route"`
- `rg -n "TaskEventStream\\(|task_events|_events =|SessionEventHub\\(max_events=2000\\)" members/artist/backend/app/services/task_events.py members/artist/backend/app/services/task_manager.py members/artist/backend/tests/test_task_events_unit.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `git diff --check -- members/artist/backend/app/services/task_manager.py members/artist/backend/app/services/task_events.py`
- 行数统计：
  - `members/artist/backend/app/services/task_manager.py`：69 行。
  - `members/artist/backend/app/services/task_events.py`：49 行。

验证备注：

- 语法检查通过。
- Task event/session hub/task progress tests 9 passed。
- Core HTTP event/cancel targeted tests 4 passed，19 deselected。
- Generate service unit tests 5 passed。
- Artist session lifecycle tests 2 passed。
- Artist CLI unit tests 10 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。
- `TaskEventStream(max_events=2000)` 当前只有模块级 `task_events` 一个共享创建点；测试仍可创建局部实例隔离验证。

当前收缩：

- Event gateway 已具备全局入口；后续可以让 `/api/sessions/events`、`/api/core/sessions/{id}/events` 和 CLI live watch 直接依赖事件入口，而不是绕过 `TaskManager` 大 facade。

当前遗留：

- `TaskManager` 仍对外承载 publish/subscribe/list_events 兼容方法。
- `/api/sessions/events`、Core events route 和 CLI live watch 尚未直接迁到 `task_events`。
- `LamEvent` 兼容 DTO 仍由多个 service 直接构造。
- `TaskManager` 仍聚合 task progress 和 checkpoint state。

下一步：

- Step 10 继续：把 `/api/sessions/events` 和 `/api/core/sessions/{session_id}/events` 的事件读写入口从 `task_manager` 迁到 `task_events`，保留旧 SSE 输出协议。

### 10.26 执行记录：2026-07-01 Step 10 第二十六切片

目标：

- 继续 TaskManager/SSE facade 收口：把 HTTP 事件读写入口从 `task_manager` 迁到共享 `task_events`。
- 保留旧 `/api/sessions/events` SSE 输出协议和 task snapshot 来源。

已完成：

- `members/artist/backend/app/routers/session.py`
  - `/api/sessions/events` 的 `subscribe()` / `unsubscribe()` / `queue_count()` 改用 `task_events`。
  - 初始 snapshot 仍通过 `task_manager.get_all_tasks()` 读取任务状态。
  - cancel 和 background task 状态仍保留在 `task_manager`。
- `members/artist/backend/app/routers/core_http.py`
  - `/api/core/sessions/{session_id}/events` 改为 `task_events.list_events(session_id)`。
- `members/artist/backend/tests/test_core_http_artist_unit.py`
  - event history 测试改为直接通过 `task_events.publish()` 写入事件。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/routers/session.py members/artist/backend/app/routers/core_http.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q -k "events or existing_sessions_route or cancel_route"`
- `py -3.14 -m pytest members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_events_unit.py -q`
- `rg -n "task_manager\\.subscribe|task_manager\\.unsubscribe|task_manager\\.queue_count|task_manager\\.list_events|task_events\\.subscribe|task_events\\.unsubscribe|task_events\\.list_events|from app\\.services\\.task_manager import task_manager" members/artist/backend/app/routers members/artist/backend/tests/test_core_http_artist_unit.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_progress_unit.py -q`
- `git diff --check -- members/artist/backend/app/routers/session.py members/artist/backend/app/routers/core_http.py members/artist/backend/tests/test_core_http_artist_unit.py`

验证备注：

- 语法检查通过。
- Core HTTP event/session/cancel targeted tests 5 passed，18 deselected。
- Session event hub + task events targeted tests 6 passed。
- Core HTTP unit tests 23 passed。
- Artist session lifecycle tests 2 passed。
- Generate service unit tests 5 passed。
- Artist CLI unit tests 10 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Task event/session hub/task progress tests 9 passed。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。
- HTTP 路由中不再出现 `task_manager.subscribe` / `unsubscribe` / `queue_count` / `list_events`。

当前收缩：

- `/api/sessions/events` 的 live event stream 和 `/api/core/sessions/{session_id}/events` 的 history 读取已直接依赖 `task_events`。
- `TaskManager` 在 HTTP event path 中只剩 task snapshot / cancel / background status 角色，不再承载 event gateway 入口。

当前遗留：

- CLI live watch 仍通过 `global_task_manager.subscribe()` / `unsubscribe()`。
- `TaskManager` 仍对外保留 publish/subscribe/list_events 兼容方法供服务层旧调用。
- `LamEvent` 兼容 DTO 仍由多个 service 直接构造。
- `/api/sessions/events` URL 仍是旧 live SSE endpoint，协议未统一到 Core endpoint。

下一步：

- Step 10 继续：把 CLI live watch 的订阅入口迁到 `task_events`，或先收缩服务层发布入口对 `TaskManager.publish()` 的依赖。

### 10.27 执行记录：2026-07-01 Step 10 第二十七切片

目标：

- 继续 TaskManager/SSE facade 收口：把 CLI live watch 的事件订阅入口从 `global_task_manager` 迁到共享 `task_events`。
- 保持 CLI 输出和 SSE payload 解析逻辑不变。

已完成：

- `members/artist/backend/app/cli.py`
  - 删除 `task_manager as global_task_manager` import。
  - 改为导入 `task_events`。
  - `_stream_cli_events()` 的 `subscribe()` / `unsubscribe()` 改为调用 `task_events`。
- `members/artist/backend/tests/test_artist_cli_unit.py`
  - 新增 `test_artist_cli_stream_uses_task_events()`。
  - 验证 CLI live watch 使用 `app.cli.task_events.subscribe` / `unsubscribe`。
  - 验证真实 SSE data 包含 `payload` 时，CLI 仍输出 progress message。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/cli.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `rg -n "global_task_manager|task_manager\\.subscribe|task_manager\\.unsubscribe|task_events\\.subscribe|task_events\\.unsubscribe|_stream_cli_events" members/artist/backend/app/cli.py members/artist/backend/tests/test_artist_cli_unit.py`
- `py -3.14 -m py_compile members/artist/backend/app/cli.py members/artist/backend/tests/test_artist_cli_unit.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_progress_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `git diff --check -- members/artist/backend/app/cli.py members/artist/backend/tests/test_artist_cli_unit.py`
- `rg -n "global_task_manager|task_manager\\.subscribe|task_manager\\.unsubscribe|task_events\\.subscribe|task_events\\.unsubscribe|TaskManager\\.publish|await task_manager\\.publish" members/artist/backend/app members/artist/backend/tests -g "*.py"`

验证备注：

- 语法检查通过。
- Artist CLI unit tests 11 passed。
- Core HTTP unit tests 23 passed。
- Generate service unit tests 5 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Task event/session hub/task progress tests 9 passed。
- Artist session lifecycle tests 2 passed。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。
- CLI 中不再出现 `global_task_manager`、`task_manager.subscribe` 或 `task_manager.unsubscribe`。

当前收缩：

- HTTP live SSE、Core event history 和 CLI live watch 的事件订阅/读取入口都已迁到 `task_events`。
- `TaskManager` 的事件订阅职责继续保留为兼容方法，但主入口已从路由和 CLI 移走。

当前遗留：

- 服务层发布仍多处通过 `task_manager.publish()`。
- `TaskManager` 仍对外保留 publish/subscribe/list_events 兼容方法。
- `LamEvent` 兼容 DTO 仍由多个 service 直接构造。
- `/api/sessions/events` URL 仍是旧 live SSE endpoint，协议未统一到 Core endpoint。

下一步：

- Step 10 继续：收缩服务层发布入口对 `TaskManager.publish()` 的依赖，优先抽出 `publish_artist_event()` / `publish_artist_payload()` helper，减少直接 `LamEvent(...)` 构造点。

### 10.28 执行记录：2026-07-01 Step 10 第二十八切片

目标：

- 继续收缩服务层发布入口对 `TaskManager.publish()` 的依赖。
- 先在 `task_events` 中提供事件发布 helper，并迁移 `generate_service.py` 的顶层发布点。
- 保留 `_HeartbeatTaskManager` 传给 `artist_orchestrate()` 的行为，因为它还负责心跳和收集中途生成的 artifacts。

已完成：

- `members/artist/backend/app/services/task_events.py`
  - 新增 `TaskEventStream.publish_event()`。
  - 新增模块级 `publish_artist_event()` helper。
- `members/artist/backend/app/services/generate_service.py`
  - 导入 `publish_artist_event`。
  - `handle_artist_generate()` 顶层事件发布从 `task_manager.publish(LamEvent(...))` 改为 `publish_artist_event(...)`。
  - 覆盖场景：
    - clarification done。
    - task_started。
    - partial timeout completed。
    - timeout failed。
    - generic failure。
    - db_write_request。
    - db_write_response。
    - task_completed。
    - session_metadata_update。
- `members/artist/backend/tests/test_task_events_unit.py`
  - 新增 `test_task_event_stream_publish_event_builds_lam_event()`，覆盖 helper 构造 LamEvent 后写入 history。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/services/generate_service.py members/artist/backend/app/services/task_events.py`
- `rg -n "await task_manager\\.publish\\(LamEvent|from app\\.core\\.events import LamEvent|publish_artist_event|publish_event\\(" members/artist/backend/app/services/generate_service.py members/artist/backend/app/services/task_events.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_progress_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `git diff --check -- members/artist/backend/app/services/generate_service.py members/artist/backend/app/services/task_events.py members/artist/backend/tests/test_task_events_unit.py`
- `rg -n "await task_manager\\.publish\\(LamEvent|LamEvent\\(event_type|publish_artist_event|TaskManager\\.publish" members/artist/backend/app members/artist/backend/tests -g "*.py"`

验证备注：

- 语法检查通过。
- Task events + generate service targeted tests 6 passed。
- Task event/session hub/task progress tests 10 passed。
- Generate service unit tests 5 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Core HTTP unit tests 23 passed。
- Artist CLI unit tests 11 passed。
- Artist session lifecycle tests 2 passed。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。
- `generate_service.py` 已无直接 `LamEvent` 构造和 `task_manager.publish(LamEvent(...))`。

当前收缩：

- `generate_service.py` 的事件发布入口已从 TaskManager facade 移到 `task_events` helper。
- TaskManager 在 `handle_artist_generate()` 中主要保留 task status / heartbeat 相关职责。

当前遗留：

- `artist_service.py` 仍多处直接 `task_manager.publish(LamEvent(...))`。
- `routers/session.py` error path 仍直接通过 `task_manager.publish(LamEvent(...))`。
- `TaskManager` 仍对外保留 publish/subscribe/list_events 兼容方法。
- `LamEvent` 兼容 DTO 仍在服务层和测试中直接构造。

下一步：

- Step 10 继续：迁移 `artist_service.py` 内部 `_publish_debug()` / `_event_publish()` 等发布入口到 `publish_artist_event()`，减少直接 LamEvent 构造点。

### 10.29 执行记录：2026-07-01 Step 10 第二十九切片

目标：

- 继续收缩服务层发布入口对 `TaskManager.publish()` 的依赖。
- 迁移 `artist_service.py` 内部集中发布点到 `publish_artist_event()`，减少直接 `LamEvent(...)` 构造。

已完成：

- `members/artist/backend/app/services/artist_service.py`
  - 删除 `LamEvent` import。
  - 导入 `publish_artist_event`。
  - `_publish_debug()` 改为调用 `publish_artist_event()`。
  - candidate selection progress 事件改为调用 `publish_artist_event()`。
  - LLM token streaming 事件改为调用 `publish_artist_event()`。
  - `_event_publish()` 改为调用 `publish_artist_event()`。
  - final `artist_done` 事件改为调用 `publish_artist_event()`。
- `members/artist/backend/tests/test_artist_pipeline.py`
  - SSE/event integrity 测试从 mock `TaskManager.publish` 改为 mock `generate_service.publish_artist_event` 和 `artist_service.publish_artist_event`。
  - 断言对象从 LamEvent 实例改为 helper 参数字典。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/services/artist_service.py`
- `rg -n "LamEvent|await task_manager\\.publish|publish_artist_event|from app\\.core\\.events" members/artist/backend/app/services/artist_service.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_progress_unit.py -q`
- `rg -n "await task_manager\\.publish\\(LamEvent|LamEvent\\(event_type|publish_artist_event|TaskManager\\.publish" members/artist/backend/app members/artist/backend/tests -g "*.py"`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q`
- `git diff --check -- members/artist/backend/app/services/artist_service.py members/artist/backend/tests/test_artist_pipeline.py`

验证备注：

- 语法检查通过。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Generate service unit tests 5 passed。
- Task event/session hub/task progress tests 10 passed。
- Core HTTP unit tests 23 passed。
- Artist CLI unit tests 11 passed。
- Artist session lifecycle tests 2 passed。
- Artist core kernel adapter unit tests 61 passed。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。
- `artist_service.py` 已无直接 `LamEvent` import 和 `task_manager.publish(...)`。

当前收缩：

- `artist_service.py` 事件发布入口已从 TaskManager facade 移到 `task_events` helper。
- Artist 主要服务层的事件发布已集中到 `publish_artist_event()`。

当前遗留：

- `routers/session.py` error path 仍直接通过 `task_manager.publish(LamEvent(...))`。
- `TaskManager` 仍对外保留 publish/subscribe/list_events 兼容方法。
- `LamEvent` 兼容 DTO 仍在 event hub/checkpoint/task progress tests 和少量低层模块中直接使用。
- `/api/sessions/events` URL 仍是旧 live SSE endpoint，协议未统一到 Core endpoint。

下一步：

- Step 10 继续：迁移 `routers/session.py` error path 到 `publish_artist_event()`；随后评估是否可以删除或降级 `TaskManager.publish()` 兼容方法。

### 10.30 执行记录：2026-07-01 Step 10 第三十切片

目标：

- 继续收缩服务层发布入口对 `TaskManager.publish()` 的依赖。
- 迁移 `routers/session.py` background error path 到 `publish_artist_event()`，清除生产代码里的直接 `task_manager.publish(LamEvent(...))`。

已完成：

- `members/artist/backend/app/routers/session.py`
  - 导入 `publish_artist_event`。
  - 删除 `_run_artist_background()` 内局部 `LamEvent` import。
  - background exception 的 `task_failed` 事件改为调用 `publish_artist_event()`。
- `members/artist/backend/tests/test_artist_session_lifecycle.py`
  - 新增 `test_artist_background_exception_publishes_error_event()`。
  - 覆盖 background exception 时调用 `session_router.publish_artist_event`。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/routers/session.py members/artist/backend/tests/test_artist_session_lifecycle.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `rg -n "await task_manager\\.publish\\(LamEvent|task_manager\\.publish\\(|LamEvent\\(event_type|from app\\.core\\.events import LamEvent|publish_artist_event" members/artist/backend/app members/artist/backend/tests -g "*.py"`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `git diff --check -- members/artist/backend/app/routers/session.py members/artist/backend/tests/test_artist_session_lifecycle.py`

验证备注：

- 语法检查通过。
- Artist session lifecycle tests 3 passed。
- Core HTTP unit tests 23 passed。
- Generate service unit tests 5 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Artist CLI unit tests 11 passed。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。
- 生产代码中已无 `task_manager.publish(LamEvent(...))`。

当前收缩：

- Artist 生产事件发布入口已集中到 `publish_artist_event()` / `task_events`。
- `TaskManager.publish()` 现在主要是兼容方法，主线发布、HTTP 订阅、Core history、CLI live watch 都已从 TaskManager event facade 迁走。

当前遗留：

- `TaskManager.publish()` / `subscribe()` / `list_events()` 兼容方法仍存在，需确认是否还有外部或测试依赖。
- `TaskManager` 仍聚合 task progress 和 checkpoint state。
- `LamEvent` 兼容 DTO 仍在低层 event hub、checkpoint、task progress 和测试中使用。
- `/api/sessions/events` URL 仍是旧 live SSE endpoint，协议未统一到 Core endpoint。

下一步：

- Step 10 继续：扫描 `TaskManager.publish()` / `subscribe()` / `list_events()` 入边，若生产无入边则删除或降级兼容方法；继续收缩 TaskManager 到 task progress + checkpoint facade。

### 10.31 执行记录：2026-07-01 Step 10 第三十一切片

目标：

- 修正 10.29 发布入口迁移后的心跳语义。
- 迁移到 `publish_artist_event()` 后，事件发布不再经过 `_HeartbeatTaskManager.publish()`；需要在 `artist_service.py` 的发布路径显式刷新 heartbeat，避免长任务被误判 idle timeout。

已完成：

- `members/artist/backend/app/services/artist_service.py`
  - 新增局部 `_mark_task_activity()`。
  - 如果当前 `task_manager` 提供 `heartbeat()`，在发布 debug/progress/token/event/done 前刷新心跳。
  - 不改变 `publish_artist_event()` 的事件 payload 和 SSE 输出。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/services/artist_service.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `git diff --check -- members/artist/backend/app/services/artist_service.py members/artist/backend/tests/test_artist_pipeline.py`

验证备注：

- 语法检查通过。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Generate service unit tests 5 passed。
- Core HTTP unit tests 23 passed。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- 发布入口继续保持 `task_events` helper；同时保住原来由 `_HeartbeatTaskManager.publish()` 隐式提供的活跃信号。

当前遗留：

- `TaskManager.publish()` / `subscribe()` / `list_events()` 兼容方法仍存在，需确认是否可以删除。
- `TaskManager` 仍聚合 task progress 和 checkpoint state。

下一步：

- Step 10 继续：删除或降级 TaskManager event 兼容方法，继续收缩 TaskManager 到 task progress + checkpoint facade。

### 10.32 执行记录：2026-07-02 Step 10 第三十二切片

目标：

- 删除 Artist `TaskManager` 剩余 event 兼容方法。
- 保留长任务 heartbeat 和超时 partial artifact 返回能力，避免把旧 `publish()` 隐式副作用带入新的事件主线。

已完成：

- `members/artist/backend/app/services/task_manager.py`
  - 删除 `publish()` / `subscribe()` / `unsubscribe()` / `queue_count()` / `list_events()` 事件转发方法。
  - `TaskManager` 收缩为 task progress + checkpoint state facade。
- `members/artist/backend/app/services/generate_service.py`
  - `_HeartbeatTaskManager.publish()` 改为显式 `note_artist_event(payload)`。
  - partial timeout artifact 收集不再依赖旧 `TaskManager.publish()`。
- `members/artist/backend/app/services/artist_service.py`
  - `_event_publish()` 发布前调用 `note_artist_event()`，保留 `artist_image_ready` artifact 捕获。
- `members/artist/backend/tests/test_generate_service_unit.py`
  - 删除测试 fake manager 的旧 `publish()`。
  - 新增 heartbeat manager artifact 捕获测试。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/services/task_manager.py members/artist/backend/app/services/generate_service.py members/artist/backend/app/services/artist_service.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_progress_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q`
- `rg -n "task_manager\\.publish|TaskManager\\.publish|global_task_manager\\.subscribe|global_task_manager\\.unsubscribe|task_manager\\.subscribe|task_manager\\.list_events|\\.publish\\(LamEvent|async def publish\\(" members/artist/backend/app members/artist/backend/tests -g "*.py"`
- `git diff --check -- members/artist/backend/app/services/task_manager.py members/artist/backend/app/services/generate_service.py members/artist/backend/app/services/artist_service.py members/artist/backend/tests/test_generate_service_unit.py`

验证备注：

- 语法检查通过。
- Task event/session hub/task progress tests 10 passed。
- Generate service unit tests 6 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- Core HTTP unit tests 23 passed。
- Artist CLI unit tests 11 passed。
- Artist session lifecycle tests 3 passed。
- Artist core kernel adapter unit tests 61 passed。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。
- 旧 `TaskManager` event 兼容入口扫描只剩 `task_events.py` 的正式 `publish()` 接口。

当前收缩：

- Artist live SSE、Core event history、CLI watch、服务层发布都已脱离 `TaskManager` event facade。
- `TaskManager` 现在只承担任务进度和 checkpoint 状态，删除测试通过的 pass-through 事件接口。

当前遗留：

- `TaskManager` 仍同时聚合 task progress 和 checkpoint state，下一轮可继续拆分 checkpoint facade。
- `LamEvent` 兼容 DTO 仍在低层 event hub、checkpoint、task progress 和测试中使用。
- `/api/sessions/events` URL 仍是旧 live SSE endpoint，协议未统一到 Core endpoint。

下一步：

- Step 10 继续：评估 `TaskManager` 是否继续拆成 `TaskProgressStore` + `CheckpointStateStore` 显式依赖，减少全局 facade；随后处理旧 `/api/sessions/events` endpoint 命名和 Core operation 对齐。

### 10.33 执行记录：2026-07-02 Step 10 第三十三切片

目标：

- 继续收缩 `TaskManager`，删除没有生产入边的 checkpoint 转发方法。
- 保留当前路由仍使用的取消入口，不改变 HTTP 行为。

已完成：

- `members/artist/backend/app/services/task_manager.py`
  - 删除 `set_checkpoint_event()` / `wait_checkpoint()` / `resolve_checkpoint()`。
  - 删除 `set_checkpoint_state()` / `get_checkpoint_state()`。
  - 删除 `store_graph_config()` / `get_graph_config()`。
  - 删除 `clear_checkpoint_state()`。
  - 移除随之无用的 `asyncio` 和 `LamEvent` import。
  - 保留 `cancel_task()`、task progress 查询/更新和 cleanup。

验证：

- `rg -n "task_manager\\.(set_checkpoint_event|wait_checkpoint|resolve_checkpoint|set_checkpoint_state|get_checkpoint_state|store_graph_config|get_graph_config|clear_checkpoint_state)|global_task_manager\\.(set_checkpoint_event|wait_checkpoint|resolve_checkpoint|set_checkpoint_state|get_checkpoint_state|store_graph_config|get_graph_config|clear_checkpoint_state)" members/artist/backend/app members/artist/backend/tests -g "*.py"`
- `py -3.14 -m py_compile members/artist/backend/app/services/task_manager.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_task_progress_unit.py members/artist/backend/tests/test_core_http_artist_unit.py members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_checkpoint_state_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `git diff --check -- members/artist/backend/app/services/task_manager.py`

验证备注：

- 旧 checkpoint facade 入边扫描无匹配。
- 语法检查通过。
- Task progress + Core HTTP + session lifecycle tests 29 passed。
- Generate service + Artist CLI tests 17 passed。
- Checkpoint state unit tests 4 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- `TaskManager` 已不再公开 event facade，也不再公开未使用的 checkpoint facade。
- checkpoint 复杂度集中回 `CheckpointStateStore`，当前 `TaskManager` 只保留取消桥接和 task progress facade。

当前遗留：

- `TaskManager` 仍持有 `CheckpointStateStore` 只服务 `cancel_task()`；如果取消语义可以迁到明确 cancel store/operation，可继续删除这层持有关系。
- `/api/sessions/events` URL 仍是旧 live SSE endpoint，协议未统一到 Core endpoint。

下一步：

- Step 10 继续：处理 Artist live SSE endpoint 命名/兼容策略，或将 `cancel_task()` 从 `TaskManager` 移到更明确的 session/operation 入口。

### 10.34 执行记录：2026-07-02 Step 10 第三十四切片

目标：

- 将 Artist cancel 入口从 `TaskManager` 移出。
- 让 `TaskManager` 只承担 task progress facade，不再持有 checkpoint state。

已完成：

- `members/artist/backend/app/services/checkpoint_state.py`
  - 新增模块级 `checkpoint_states` 实例，作为 checkpoint/cancel 状态的明确入口。
- `members/artist/backend/app/services/task_manager.py`
  - 删除 `CheckpointStateStore` import。
  - 删除 `_checkpoint_states` 持有关系。
  - 删除 `cancel_task()`。
- `members/artist/backend/app/routers/session.py`
  - `/api/sessions/{session_id}/cancel` 改为直接调用 `checkpoint_states.cancel(session_id)`。
- `members/artist/backend/tests/test_core_http_artist_unit.py`
  - cancel route 测试改为 mock `checkpoint_states.cancel`。

验证：

- `rg -n "cancel_task|CheckpointStateStore|checkpoint_states|task_manager\\.(cancel|cancel_task|set_checkpoint|wait_checkpoint|resolve_checkpoint|get_checkpoint|store_graph|clear_checkpoint)" members/artist/backend/app members/artist/backend/tests -g "*.py"`
- `py -3.14 -m py_compile members/artist/backend/app/services/checkpoint_state.py members/artist/backend/app/services/task_manager.py members/artist/backend/app/routers/session.py members/artist/backend/tests/test_core_http_artist_unit.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_checkpoint_state_unit.py members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_task_progress_unit.py members/artist/backend/tests/test_artist_session_lifecycle.py members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `git diff --check -- members/artist/backend/app/services/checkpoint_state.py members/artist/backend/app/services/task_manager.py members/artist/backend/app/routers/session.py members/artist/backend/tests/test_core_http_artist_unit.py`

验证备注：

- `TaskManager.cancel_task` 已无匹配。
- 语法检查通过。
- Checkpoint state + Core HTTP tests 27 passed。
- Task progress + session lifecycle + generate service tests 12 passed。
- Artist CLI tests 11 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- `TaskManager` 已收缩到 task progress facade：`update_task()` / `get_task()` / `get_all_tasks()` / `cleanup_task()`。
- checkpoint/cancel 状态有了独立入口，不再挂在 task progress facade 上。

当前遗留：

- `TaskManager` 仍是全局 facade，HTTP SSE snapshot 仍读取 `task_manager.get_all_tasks()`。
- `/api/sessions/events` URL 仍是旧 live SSE endpoint，协议未统一到 Core endpoint。

下一步：

- Step 10 继续：评估是否把 `TaskManager` 重命名/替换为 `TaskProgressStore` 显式入口，或先处理旧 live SSE endpoint 兼容策略。

### 10.35 执行记录：2026-07-02 Step 10 第三十五切片

目标：

- 删除 Artist `TaskManager` 浅壳。
- 将剩余任务进度入口改为显式 `TaskProgressStore` / `task_progress_store`。

已完成：

- `members/artist/backend/app/services/task_progress.py`
  - 新增模块级 `task_progress_store = TaskProgressStore(task_events.event_hub)`。
- 删除 `members/artist/backend/app/services/task_manager.py`。
- `members/artist/backend/app/services/generate_service.py`
  - 改为导入 `TaskProgressStore`、`TaskStatus`、`task_progress_store`。
  - `_HeartbeatTaskManager` 重命名为 `_HeartbeatTaskProgress`。
- `members/artist/backend/app/services/artist_service.py`
  - execution engine fallback 改为使用 `task_progress_store`。
- `members/artist/backend/app/services/executors/engine.py`
  - 类型依赖从 `TaskManager` 改为 `TaskProgressStore`。
- `members/artist/backend/app/routers/session.py`
  - SSE snapshot 和 background error cleanup 改为使用 `task_progress_store`。
- `members/artist/backend/app/cli.py`
  - logging suppression 从 `app.services.task_manager` 改为 `app.services.task_progress`。
- `members/artist/backend/tests/test_generate_service_unit.py`、`members/artist/backend/tests/test_core_http_artist_unit.py`
  - 测试命名从 task manager 改为 task progress。

验证：

- `rg -n "app\\.services\\.task_manager|TaskManager|_HeartbeatTaskManager|task_manager\\.py" members/artist/backend/app members/artist/backend/tests -g "*.py"`
- `py -3.14 -m py_compile members/artist/backend/app/services/task_progress.py members/artist/backend/app/services/generate_service.py members/artist/backend/app/services/artist_service.py members/artist/backend/app/services/executors/engine.py members/artist/backend/app/routers/session.py members/artist/backend/app/cli.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_task_progress_unit.py members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_session_event_hub_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `git diff --check -- members/artist/backend/app/services/task_progress.py members/artist/backend/app/services/generate_service.py members/artist/backend/app/services/artist_service.py members/artist/backend/app/services/executors/engine.py members/artist/backend/app/routers/session.py members/artist/backend/app/cli.py members/artist/backend/app/services/task_manager.py members/artist/backend/tests/test_generate_service_unit.py members/artist/backend/tests/test_core_http_artist_unit.py`

验证备注：

- 旧 `TaskManager` / `app.services.task_manager` 扫描无匹配。
- 语法检查通过。
- Task progress + task events + session event hub tests 10 passed。
- Generate service + Core HTTP tests 29 passed。
- 追加整理后 Task progress + Generate service + Core HTTP tests 32 passed。
- Artist CLI tests 11 passed。
- Artist session lifecycle tests 3 passed。
- Artist pipeline event targeted test 1 passed，13 deselected。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- Artist `TaskManager` 已删除。
- Artist 任务进度、事件流、checkpoint/cancel 三类职责已经拆成明确模块：
  - `task_progress_store`
  - `task_events`
  - `checkpoint_states`

当前遗留：

- `artist_service.py` 内部参数名仍叫 `task_manager`，实际已是带 heartbeat 的 task progress adapter；后续可在低风险切片中改名。
- `/api/sessions/events` URL 仍是旧 live SSE endpoint，协议未统一到 Core endpoint。

下一步：

- Step 10 继续：处理 `/api/sessions/events` 旧 endpoint 的兼容策略，或清理 `artist_service.py` 内部 `task_manager` 参数命名。

### 10.36 执行记录：2026-07-02 Step 10 第三十六切片

目标：

- 处理 Artist live SSE 旧 endpoint 的兼容策略。
- 让有 session 的前端 live 订阅走 Core 路由，旧 `/api/sessions/events` 只保留兼容入口。

已完成：

- `members/artist/backend/app/services/live_events.py`
  - 新增 `stream_session_events()`，集中处理 live SSE subscribe、snapshot、ping、unsubscribe。
- `members/artist/backend/app/routers/core_http.py`
  - 新增 `/api/core/sessions/{session_id}/events/live`。
  - 复用 `stream_session_events()`，并保留 session 404 校验。
- `members/artist/backend/app/routers/session.py`
  - `/api/sessions/events` 改为调用 `stream_session_events()`，不再内联 SSE 实现。
- `members/artist/frontend/src/composables/useSessionEvents.ts`
  - 有当前 session 时改连 `/api/core/sessions/{sessionId}/events/live`。
  - 无 session 的全局兼容订阅仍保留 `/api/sessions/events`。
- `members/artist/backend/tests/test_core_http_artist_unit.py`
  - 新增 Core live SSE 路由测试。
  - 新增 Core live 404 测试。
  - 新增旧 live SSE URL 兼容测试。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/services/live_events.py members/artist/backend/app/routers/session.py members/artist/backend/app/routers/core_http.py members/artist/backend/tests/test_core_http_artist_unit.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_progress_unit.py -q`
- `npm --prefix members/artist/frontend run build`
- `rg -n "/sessions/events|events/live|stream_session_events|text/event-stream" members/artist/backend/app members/artist/backend/tests members/artist/frontend/src -g "*.py" -g "*.ts" -g "*.vue"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `git diff --check -- members/artist/backend/app/services/live_events.py members/artist/backend/app/routers/session.py members/artist/backend/app/routers/core_http.py members/artist/backend/tests/test_core_http_artist_unit.py members/artist/frontend/src/composables/useSessionEvents.ts`

验证备注：

- 语法检查通过。
- Core HTTP Artist unit tests 26 passed。
- Task events + session event hub + task progress tests 10 passed。
- Artist frontend build 通过。
- Artist CLI tests 11 passed。
- Artist session lifecycle tests 3 passed。
- endpoint 扫描显示：前端 session live 订阅走 `/core/sessions/{sessionId}/events/live`；旧 `/sessions/events` 只剩全局兼容和后端兼容路由。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- live SSE 实现从旧 session router 内联逻辑抽到 `live_events.py`。
- Core live route 成为有 session 的前端主线。
- 旧 `/api/sessions/events` 退为兼容入口。

当前遗留：

- 旧 `/api/sessions/events` 仍需保留一段时间，支持无 session 的全局订阅和旧调用方。
- `artist_service.py` 内部参数名仍叫 `task_manager`，实际已是带 heartbeat 的 task progress adapter。

下一步：

- Step 10 继续：清理 `artist_service.py` / `generate_service.py` 内部 `task_manager` 命名残留，或进一步把 live event 协议映射到 Core runtime event schema。

### 10.37 执行记录：2026-07-02 Step 10 第三十七切片

目标：

- 清理 Artist 服务层内部 `task_manager` 命名残留。
- 保持行为不变，仅让当前 task progress 语义和命名一致，避免后续扫描误判旧 `TaskManager` 仍存在。

已完成：

- `members/artist/backend/app/services/generate_service.py`
  - `_apply_image_context_resolution()` 参数从 `task_manager` 改为 `task_progress`。
  - `handle_artist_generate()` 局部变量从 `task_manager` 改为 `task_progress`。
  - `heartbeat_task_manager` 改为 `heartbeat_task_progress`。
  - 调用 `artist_orchestrate()` 时改传 `task_progress=...`。
- `members/artist/backend/app/services/artist_service.py`
  - `artist_orchestrate()` 参数从 `task_manager` 改为 `task_progress`。
  - 内部 heartbeat、event note、debug、token、done 发布路径同步改名。
- `members/artist/backend/app/services/executors/engine.py`
  - `ExecutionEngine.step()` / `run_parallel_group()` / `run_all()` 参数从 `task_manager` 改为 `task_progress`。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/services/generate_service.py members/artist/backend/app/services/artist_service.py members/artist/backend/app/services/executors/engine.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `rg -n "task_manager|heartbeat_task_manager|app\\.services\\.task_manager|TaskManager" members/artist/backend/app members/artist/backend/tests -g "*.py"`
- `git diff --check -- members/artist/backend/app/services/generate_service.py members/artist/backend/app/services/artist_service.py members/artist/backend/app/services/executors/engine.py`

验证备注：

- 语法检查通过。
- Generate service unit tests 6 passed。
- Artist pipeline targeted tests 2 passed，18 deselected。
- Artist CLI + session lifecycle tests 14 passed。
- 旧 `task_manager` / `TaskManager` 命名扫描无匹配。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

非本切片遗留风险：

- `members/artist/backend/tests/test_artist_orchestrate.py::test_artist_orchestrate_direct_draw` 当前失败，表现为 direct `artist_orchestrate()` 返回 0 个 artifacts。
- 已用临时干净 HEAD worktree 单跑确认同样失败，说明不是本切片命名清理引入。
- 该问题应作为后续 Artist direct orchestrate 回归单独处理。

当前收缩：

- Artist app/tests 中已无 `TaskManager` / `task_manager` 命名残留。
- task progress、task events、checkpoint/cancel 三类职责命名和模块入口保持一致。

当前遗留：

- `artist_orchestrate` direct draw 测试存在既有失败。
- live event 协议仍输出 Artist LamEvent shape，尚未完全映射到 Core runtime event schema。

下一步：

- Step 10 继续：修复 `artist_orchestrate()` direct draw artifact 回归，或继续把 live event payload 映射到 Core runtime event schema。

### 10.38 执行记录：2026-07-02 Step 10 第三十八切片

目标：

- 修复 `artist_orchestrate()` direct draw artifact 回归。
- 保留 Core Kernel 路径对旧 Artist LLM 输出 `plan.steps[{tool, params}]` 的兼容解析，避免旧 fixture / provider 输出无法触发生图工具。

已完成：

- `members/artist/backend/app/core/artist/parse_helpers.py`
  - 新增 `_tool_calls_from_legacy_plan()`。
  - 当模型输出没有 `tool_calls` / `actions` / `action` 时，从 `plan.steps` 提取工具调用。
  - 将旧参数 `prompt` / `n` / `size` 映射为当前 `task` / `image_count` / `image_size`。
- `members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py`
  - 新增 `test_parse_artist_loop_turn_accepts_legacy_plan_steps()`。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/core/artist/parse_helpers.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_orchestrate.py::test_artist_orchestrate_direct_draw -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_orchestrate.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_generate_service_unit.py members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py members/artist/backend/tests/test_artist_cli_unit.py members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `rg -n "legacy_plan|_tool_calls_from_legacy_plan|plan.*steps|prompt.*image_count" members/artist/backend/app/core/artist/parse_helpers.py members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py`
- `git diff --check -- members/artist/backend/app/core/artist/parse_helpers.py members/artist/backend/tests/test_artist_core_kernel_adapter_unit.py`

验证备注：

- 语法检查通过。
- Direct draw 单测 1 passed。
- Artist orchestrate tests 9 passed。
- Artist core kernel adapter unit tests 62 passed。
- Generate service + Artist pipeline targeted tests 2 passed，18 deselected。
- Core HTTP + Artist CLI + session lifecycle tests 40 passed。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- Core Kernel 主线继续保留；修复点在解析适配层，不恢复旧 runtime。
- 旧 `plan.steps` 只作为输入兼容被归一化为当前工具调用形态。

当前遗留：

- live event payload 仍是 Artist LamEvent shape，尚未完全映射到 Core runtime event schema。
- 旧 `/api/sessions/events` 仍作为兼容入口存在。

下一步：

- Step 10 继续：进一步把 live event payload 映射到 Core runtime event schema，或开始审计 Artist 是否还有旧 runtime / fallback mapper 残留。

### 10.39 执行记录：2026-07-02 Step 10 第三十九切片

目标：

- 将 Artist live SSE / history event 输出进一步映射到 Core runtime event shape。
- 保留旧字段兼容，避免前端和 CLI 立即断裂。

已完成：

- `members/artist/backend/app/services/session_event_hub.py`
  - 新增 `runtime_event_payload(record)`。
  - `serialize_sse()` 改为复用 `runtime_event_payload()`。
  - `list_events()` 改为复用同一投影。
  - 输出新增 Core shape 字段：`id`、`session_id`、`name`、`type`、`category`、`run_id`、`created_at`、`data`。
  - 继续保留兼容字段：`event_id`、`event_type`、`correlation_id`、`payload`、`source_product`、`target_product`、`object`。
- `members/artist/backend/tests/test_session_event_hub_unit.py`
  - 扩展 replay / list events 断言，覆盖 Core shape 和兼容字段同时存在。
  - 新增 `test_serialize_sse_includes_core_runtime_event_shape_and_legacy_fields()`。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/services/session_event_hub.py members/artist/backend/tests/test_session_event_hub_unit.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_task_progress_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py members/artist/backend/tests/test_artist_cli_unit.py -q`
- `npm --prefix members/artist/frontend run build`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_session_lifecycle.py members/artist/backend/tests/test_artist_orchestrate.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `rg -n "runtime_event_payload|data|event_type|correlation_id|payload" members/artist/backend/app/services/session_event_hub.py members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_core_http_artist_unit.py`
- `git diff --check -- members/artist/backend/app/services/session_event_hub.py members/artist/backend/tests/test_session_event_hub_unit.py`

验证备注：

- 语法检查通过。
- Session event hub + task events + task progress tests 11 passed。
- Core HTTP + Artist CLI tests 37 passed。
- Artist frontend build 通过。
- Artist session lifecycle + orchestrate tests 12 passed。
- Artist pipeline targeted test 1 passed，13 deselected。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- live SSE 和 history list 共用一个 runtime event 投影。
- Artist 事件流开始暴露 Core runtime event shape，同时保留旧 LamEvent 字段兼容。

当前遗留：

- `payload` 兼容字段仍保留；前端 `useSessionEvents.ts` 还主要读取 `event_type` / `payload`。
- 旧 `/api/sessions/events` 仍作为兼容入口存在。

下一步：

- Step 10 继续：让 Artist 前端事件消费优先读取 Core shape `type` / `data`，再把旧字段降级为 fallback。

### 10.40 执行记录：2026-07-02 Step 10 第四十切片

目标：

- 让 Artist 前端 live event 消费优先读取 Core runtime event shape。
- 继续保留旧 `event_type` / `payload` fallback，避免一次性破坏旧 SSE 兼容入口。

已完成：

- `members/artist/frontend/src/composables/useSessionEvents.ts`
  - 新增 `RuntimeSseEvent` 本地类型。
  - 新增 `eventPayload()` / `eventType()` / `normalizeRuntimeEvent()`。
  - 解析 SSE 时优先使用 Core shape：
    - event type：`type` 优先，`event_type` fallback。
    - event data：`data` 优先，`payload` fallback。
  - 传给 store 的 runtime event 仍补齐旧 `LamEvent` 字段，降低下游改动面。
  - snapshot 特殊处理：继续把 snapshot 的 `data` 作为任务字典传给 `onSnapshot()`。

验证：

- `npm --prefix members/artist/frontend run build`
- `rg -n "event_type|payload\\?|data\\?|normalizeRuntimeEvent|eventPayload|eventType" members/artist/frontend/src/composables/useSessionEvents.ts`
- `py -3.14 -m pytest members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `git diff --check -- members/artist/frontend/src/composables/useSessionEvents.ts`

验证备注：

- Artist frontend build 通过。
- Session event hub + task events + Core HTTP tests 34 passed。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- 后端 event 投影和前端 event 消费都已支持 Core runtime event shape。
- 旧 `event_type` / `payload` 现在是兼容 fallback，而不是前端唯一主线。

当前遗留：

- `stores/session.ts` 内部仍接收补齐后的 `LamEvent` 兼容对象。
- 旧 `/api/sessions/events` 仍作为兼容入口存在。

下一步：

- Step 10 继续：审计 Artist 是否还有旧 runtime / fallback mapper 残留，或逐步把 store 内部事件类型改为 Core runtime event。

### 10.41 执行记录：2026-07-02 Step 10 第四十一切片

目标：

- 让 Artist 前端历史事件读取也优先消费 Core runtime event shape。
- 删除过时的 “Artist fallback unknown schema” 注释。

已完成：

- `members/artist/frontend/src/api/core.ts`
  - `getCoreEvents()` 改为优先读取后端 Core 字段：
    - `id`
    - `type`
    - `created_at` / `timestamp`
    - `data`
  - 旧 `event_type` / `payload` 仅作为 fallback。
  - 删除顶部和 events 区块中关于 Artist unknown schema fallback 的说明。

验证：

- `npm --prefix members/artist/frontend run build`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py members/artist/backend/tests/test_session_event_hub_unit.py -q`
- `rg -n "Artist fallback|unknown schema|event_type|payload|e\\.data|e\\.payload|getCoreEvents" members/artist/frontend/src/api/core.ts`
- `git diff --check -- members/artist/frontend/src/api/core.ts`

验证备注：

- Artist frontend build 通过。
- Core HTTP + session event hub tests 32 passed。
- 扫描确认过时注释已删除；旧 `event_type` / `payload` 只作为 fallback 留在 `getCoreEvents()`。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- Artist live event 和 history event 前端入口均已 Core shape 优先。
- Artist-specific schema fallback 已降级为兼容逻辑。

当前遗留：

- `stores/session.ts` 内部仍接收补齐后的 `LamEvent` 兼容对象。
- 旧 `/api/sessions/events` 仍作为兼容入口存在。

下一步：

- Step 10 继续：审计 `LamEvent` 兼容 DTO 是否还能继续下沉或替换，尤其是 `task_events.py`、`task_progress.py`、`checkpoint_state.py` 的生产入边。

### 10.42 执行记录：2026-07-02 Step 10 第四十二切片

目标：

- 收口 Artist `LamEvent` 兼容 DTO 的生产入边。
- 让 task progress / artist event 发布主线改用 Core runtime event 语义：`name`、`session_id`、`run_id`、`data`。
- 保留 `LamEvent` 只作为低层兼容入口，避免一次性破坏旧调用方和旧测试。

已完成：

- `members/artist/backend/app/services/session_event_hub.py`
  - 新增 `publish_runtime_record()`，直接写入 Core `RuntimeEventRecord`。
  - `publish_task_event()` 改为接收 `name/session_id/run_id/data`，不再接收 `LamEvent`。
  - `_append_event()` 降级为旧 `LamEvent` 兼容转换，实际写入复用 `_append_runtime_record()`。
- `members/artist/backend/app/services/task_events.py`
  - `publish_event()` 不再构造 `LamEvent`，改为调用 `publish_runtime_record()`。
  - 保留 `publish(LamEvent)` 作为兼容路径。
- `members/artist/backend/app/services/task_progress.py`
  - 删除 `LamEvent` import。
  - `TaskProgressStore.update_task()` 直接发布 Core runtime event 参数。
- `members/artist/backend/tests/test_task_events_unit.py`
  - 将测试名从旧 `LamEvent` 构造语义改为 Core record 写入语义。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/services/session_event_hub.py members/artist/backend/app/services/task_events.py members/artist/backend/app/services/task_progress.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_task_progress_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py members/artist/backend/tests/test_artist_cli_unit.py members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `npm --prefix members/artist/frontend run build`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `rg -n "LamEvent|publish_task_event\\(|publish_runtime_record\\(|publish_event\\(" members/artist/backend/app/services members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_task_progress_unit.py members/artist/backend/tests/test_session_event_hub_unit.py -g "*.py"`
- `git diff --check -- members/artist/backend/app/services/session_event_hub.py members/artist/backend/app/services/task_events.py members/artist/backend/app/services/task_progress.py members/artist/backend/tests/test_task_events_unit.py`

验证备注：

- 语法检查通过。
- Session event hub + task events + task progress tests 11 passed。
- Core HTTP + Artist CLI + session lifecycle tests 40 passed。
- Artist frontend build 通过。
- Artist pipeline targeted test 1 passed，13 deselected。
- `TaskProgressStore` 和 `TaskEventStream.publish_event()` 已不再构造 `LamEvent`。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- Artist 事件发布主线从 `LamEvent` DTO 进一步收口到 Core runtime event 参数。
- `SessionEventHub` 成为旧 DTO 到 Core record 的唯一低层兼容转换点。

当前遗留：

- `TaskEventStream.publish(LamEvent)` 和 `SessionEventHub.publish_runtime_event(LamEvent)` 仍保留给旧入口与兼容测试。
- `checkpoint_state.py` 仍保存 `LamEvent` 对象，下一步可改为只保存 checkpoint data / wait state。
- 前端 `stores/session.ts` 内部仍接收补齐后的 `LamEvent` 兼容对象。

下一步：

- Step 10 继续：把 `checkpoint_state.py` 从保存 `LamEvent` 改为保存 checkpoint data，或把 Artist store 内部事件类型改为 Core runtime event。

### 10.43 执行记录：2026-07-02 Step 10 第四十三切片

目标：

- 删除 `checkpoint_state.py` 对 `LamEvent` 的依赖。
- 将 checkpoint wait state 从“保存旧事件对象”改为“保存等待状态和可选数据”。

已完成：

- `members/artist/backend/app/services/checkpoint_state.py`
  - 删除 `LamEvent` import。
  - `set_checkpoint_event()` 改为 `start_checkpoint()`。
  - state 中不再保存 `"event"`，改为保存可选 `"data"`。
- `members/artist/backend/tests/test_checkpoint_state_unit.py`
  - 删除 `LamEvent` fixture。
  - 单测改为调用 `start_checkpoint()`。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/services/checkpoint_state.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_checkpoint_state_unit.py members/artist/backend/tests/test_core_http_artist_unit.py members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_events_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `rg -n 'set_checkpoint_event|from app\\.core\\.events import LamEvent|LamEvent' members/artist/backend/app/services/checkpoint_state.py members/artist/backend/tests/test_checkpoint_state_unit.py members/artist/backend/app/services members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_task_progress_unit.py members/artist/backend/tests/test_session_event_hub_unit.py -g '*.py'`
- `git diff --check -- members/artist/backend/app/services/checkpoint_state.py members/artist/backend/tests/test_checkpoint_state_unit.py`

验证备注：

- 语法检查通过。
- Checkpoint + Core HTTP + session event hub + task event tests 38 passed。
- Artist pipeline targeted test 1 passed，13 deselected。
- `checkpoint_state.py` 已无 `LamEvent` 依赖，旧 `set_checkpoint_event` 无残留。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- checkpoint wait state 不再保存旧 `LamEvent` 对象。
- Artist 后端生产服务中 `LamEvent` 只剩事件流兼容入口：`TaskEventStream.publish(LamEvent)`、`SessionEventHub.publish_runtime_event(LamEvent)`。

当前遗留：

- `SessionEventHub` 和 `TaskEventStream.publish()` 仍保留旧 `LamEvent` 兼容方法。
- 兼容测试仍直接覆盖 `publish_runtime_event(LamEvent)`。
- 前端 `stores/session.ts` 内部仍接收补齐后的 `LamEvent` 兼容对象。

下一步：

- Step 10 继续：把 `SessionEventHub` 单测主线迁移到 `publish_runtime_record()`，再决定是否删除或隔离 `publish_runtime_event(LamEvent)` 兼容入口。

### 10.44 执行记录：2026-07-02 Step 10 第四十四切片

目标：

- 删除 Artist 后端旧 `LamEvent` DTO 和旧发布入口。
- 让事件测试主线全部改到 Core runtime record 发布接口。

已完成：

- `members/artist/backend/app/services/session_event_hub.py`
  - 删除 `publish_runtime_event(LamEvent)`。
  - 删除旧 `_append_event()` 兼容转换。
  - `SessionEventHub` 只保留 Core record 写入路径。
- `members/artist/backend/app/services/task_events.py`
  - 删除 `TaskEventStream.publish(LamEvent)`。
  - 事件发布入口只保留 `publish_event(event_type/correlation_id/payload)`。
- `members/artist/backend/app/core/events/__init__.py`
  - 删除旧 `LamEvent` DTO 文件。
- `members/artist/backend/tests/test_session_event_hub_unit.py`
  - 全部改用 `publish_runtime_record()`。
- `members/artist/backend/tests/test_task_events_unit.py`
  - 改用 `publish_event()`。
- `members/artist/backend/tests/test_core_http_artist_unit.py`
  - 改用 `task_events.publish_event()` 准备 history fixture。
- `members/artist/backend/tests/test_artist_pipeline.py`
  - 删除测试断言文案里的旧 `LamEvent` 术语。

验证：

- `rg -n 'app\\.core\\.events|LamEvent|publish_runtime_event\\(|task_events\\.publish\\(' members/artist/backend/app members/artist/backend/tests -g '*.py'`
- `py -3.14 -m py_compile members/artist/backend/app/services/session_event_hub.py members/artist/backend/app/services/task_events.py members/artist/backend/app/services/task_progress.py members/artist/backend/app/services/checkpoint_state.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_task_progress_unit.py members/artist/backend/tests/test_checkpoint_state_unit.py members/artist/backend/tests/test_core_http_artist_unit.py members/artist/backend/tests/test_artist_cli_unit.py members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `git diff --check -- members/artist/backend/app/services/session_event_hub.py members/artist/backend/app/services/task_events.py members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_core_http_artist_unit.py members/artist/backend/tests/test_artist_pipeline.py members/artist/backend/app/core/events/__init__.py`

验证备注：

- 旧 `LamEvent` / `app.core.events` / `publish_runtime_event()` / `task_events.publish()` 扫描无匹配。
- 语法检查通过。
- Artist event/checkpoint/Core HTTP/CLI/session lifecycle tests 55 passed。
- Artist pipeline targeted test 1 passed，13 deselected。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- Artist 后端旧 `LamEvent` DTO 已删除。
- Artist event hub 的内部事实只剩 Core `RuntimeEventRecord`。
- Artist task event 发布主线统一为 `publish_event()`。

当前遗留：

- 后端输出仍保留 `event_type` / `payload` 兼容字段，前端 store 内部仍使用补齐后的兼容对象。
- 旧 `/api/sessions/events` 仍作为兼容入口存在。

下一步：

- Step 10 继续：把 Artist 前端 `stores/session.ts` 内部 runtime event 类型从 `LamEvent` 迁移到 Core runtime event，或审计旧 `/api/sessions/events` 的真实调用方后决定保留期限。

### 10.45 执行记录：2026-07-02 Step 10 第四十五切片

目标：

- 把 Artist 前端 runtime event 主线从 `LamEvent` 兼容对象迁移到 Core runtime event shape。
- 将旧 `event_type` / `payload` / `event_id` 兼容读取限制在 SSE/API 边缘解析层。

已完成：

- `members/artist/frontend/src/types/index.ts`
  - `LamEventPayload` 改为 `RuntimeEventData`。
  - `LamEvent` 改为 `RuntimeEvent`。
  - 主事件字段改为 `id`、`type`、`run_id`、`data`。
- `members/artist/frontend/src/composables/useSessionEvents.ts`
  - `onRuntimeEvent` 回调类型改为 `RuntimeEvent`。
  - `normalizeRuntimeEvent()` 输出 Core shape。
  - 旧 `event_id` / `event_type` / `payload` 仅作为 SSE 输入兼容读取。
- `members/artist/frontend/src/stores/session.ts`
  - `handleRuntimeEvent()` 改为消费 `RuntimeEvent.data` 和 `RuntimeEvent.type`。
  - `handleCoreDisplayEvent()` 改为使用 `RuntimeEvent`。
  - runtime step id 从旧 `event.event_id` 改为 `event.id`。

验证：

- `npm --prefix members/artist/frontend run build`
- `py -3.14 -m pytest members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_task_progress_unit.py members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `rg -n "LamEvent|LamEventPayload|event_id|event_type|payload" members/artist/frontend/src -g "*.ts" -g "*.vue"`
- `git diff --check -- members/artist/frontend/src/types/index.ts members/artist/frontend/src/composables/useSessionEvents.ts members/artist/frontend/src/stores/session.ts`

验证备注：

- Artist frontend build 通过。
- 后端 session event hub + task events + task progress + Core HTTP tests 37 passed。
- Artist pipeline targeted test 1 passed，13 deselected。
- 扫描确认 `LamEvent` / `LamEventPayload` 已无残留。
- `event_id` / `event_type` / `payload` 仅留在 `useSessionEvents.ts` 和 `api/core.ts` 的边缘兼容读取中。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- Artist 前端 runtime store 内部已经 Core event shape 优先，不再接收补齐后的 `LamEvent` 兼容对象。
- 前后端事件主线均已摆脱 Artist 私有 `LamEvent` 命名。

当前遗留：

- 后端输出仍保留 `event_type` / `payload` 兼容字段。
- 前端 `useSessionEvents.ts` / `api/core.ts` 仍保留旧字段输入 fallback。
- 旧 `/api/sessions/events` 仍作为兼容入口存在。

下一步：

- Step 10 继续：审计旧 `/api/sessions/events` 的真实调用方，确认是否只剩无 session 全局订阅兼容；再决定是否收缩后端输出兼容字段或删除旧 live endpoint。

### 10.46 执行记录：2026-07-02 Step 10 第四十六切片

目标：

- 让 Artist CLI SSE 消费优先读取 Core runtime event shape。
- 将旧 `payload` 读取降级为 CLI 输入兼容 fallback。

已完成：

- `members/artist/backend/app/cli.py`
  - `_parse_sse_payload()` 改为先读取 SSE JSON 的 `data` 字段。
  - 仅当 `data` 不是对象时，才 fallback 到旧 `payload` 字段。
- `members/artist/backend/tests/test_artist_cli_unit.py`
  - 新增 Core SSE `data` 优先解析测试。
  - 新增旧 `payload` fallback 解析测试。
  - CLI live stream 测试 fixture 改为 Core `type/data` shape。

验证：

- `py -3.14 -m py_compile members/artist/backend/app/cli.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `rg -n '_parse_sse_payload|data\\\":\\{\"type\\\":\\\"task_progress|event_type\\\":\\\"task_progress|payload\\\":\\{\"type\\\":\\\"task_progress' members/artist/backend/app/cli.py members/artist/backend/tests/test_artist_cli_unit.py`

验证备注：

- 语法检查通过。
- Artist CLI unit tests 13 passed。
- Session event hub + task events + Core HTTP tests 34 passed。
- 扫描确认 CLI 流测试主线已使用 Core `data` shape；旧 `payload` 仅保留在 fallback 单测中。

当前收缩：

- Artist 前端和 CLI 都已优先消费 Core runtime event `data`。
- 旧 `payload` 在当前消费端只作为输入兼容，不再是主路径。

当前遗留：

- 后端 `SessionEventHub.runtime_event_payload()` 仍输出 `event_type` / `payload` 兼容字段。
- 旧 `/api/sessions/events` 仍作为无 session 全局订阅兼容入口存在。
- 部分单测仍断言兼容字段存在，需要后续先改为 Core shape 断言，再考虑删除输出兼容字段。

下一步：

- Step 10 继续：把后端事件单测主断言改为 `type/data`，将 `event_type/payload` 断言降级为兼容专项；随后评估是否可以移除后端兼容字段。

### 10.47 执行记录：2026-07-02 Step 10 第四十七切片

目标：

- 把 Artist 后端事件测试主线断言切到 Core runtime event shape。
- 将旧 `event_type` / `payload` / `event_id` / `correlation_id` 断言降级为兼容专项，而不是散落在主路径测试中。

已完成：

- `members/artist/backend/tests/test_session_event_hub_unit.py`
  - replay / last-event-id / list events 主断言改为 `type` / `data`。
  - 原兼容字段断言集中到 `test_runtime_event_payload_keeps_legacy_fields_for_compatibility()`。
- `members/artist/backend/tests/test_task_events_unit.py`
  - SSE 和 history 断言改为 `id` / `type` / `data`。
- `members/artist/backend/tests/test_task_progress_unit.py`
  - task progress history 和 SSE 断言改为 `type` / `data`。
  - 测试名从 legacy shape 改为 Core shape。
- `members/artist/backend/tests/test_core_http_artist_unit.py`
  - Core events endpoint 断言改为读取 `data`。

验证：

- `py -3.14 -m pytest members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_task_progress_unit.py members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `npm --prefix members/artist/frontend run build`
- `rg -n 'event_type|payload|event_id|correlation_id' members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_task_progress_unit.py members/artist/backend/tests/test_core_http_artist_unit.py -g '*.py'`
- `git diff --check -- members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_task_progress_unit.py members/artist/backend/tests/test_core_http_artist_unit.py`

验证备注：

- 后端事件相关 tests 38 passed。
- Artist CLI unit tests 13 passed。
- Artist frontend build 通过。
- 旧字段扫描确认仅剩：发布函数参数名、通用 “payload” 变量名、以及 session event hub 的兼容专项测试。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- 后端事件测试的主路径已经保护 Core `type/data` shape。
- 旧兼容字段不再被主路径测试当作必需事实。

当前遗留：

- `SessionEventHub.runtime_event_payload()` 仍输出 `event_id`、`event_type`、`correlation_id`、`payload` 兼容字段。
- CLI 和前端仍保留旧输入 fallback，但主线已优先读取 `data`。
- 旧 `/api/sessions/events` 仍作为无 session 全局订阅兼容入口存在。

下一步：

- Step 10 继续：删除 `SessionEventHub.runtime_event_payload()` 的旧输出字段，保留消费端输入 fallback；再跑前端、CLI、后端事件契约验证。

### 10.48 执行记录：2026-07-02 Step 10 第四十八切片

目标：

- 删除 Artist 后端事件输出中的旧兼容字段。
- 让 SSE / history 输出只保留 Core runtime event shape。
- 保留前端和 CLI 的旧输入 fallback，用于读取历史或外部旧格式输入。

已完成：

- `members/artist/backend/app/services/session_event_hub.py`
  - `runtime_event_payload()` 删除旧字段：
    - `event_id`
    - `event_type`
    - `correlation_id`
    - `payload`
    - `source_product`
    - `target_product`
    - `object`
  - 输出保留 Core shape：`id`、`session_id`、`name`、`type`、`category`、`run_id`、`timestamp`、`created_at`、`data`。
- `members/artist/backend/tests/test_session_event_hub_unit.py`
  - 删除旧字段正向断言。
  - 新增/调整为确认旧兼容字段不再出现在 runtime event payload 中。

验证：

- `py -3.14 -m pytest members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_task_progress_unit.py members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `npm --prefix members/artist/frontend run build`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `rg -n 'event_id|event_type|correlation_id|payload|source_product|target_product|object' members/artist/backend/app/services/session_event_hub.py members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_task_progress_unit.py members/artist/backend/tests/test_core_http_artist_unit.py`
- `git diff --check -- members/artist/backend/app/services/session_event_hub.py members/artist/backend/tests/test_session_event_hub_unit.py`

验证备注：

- 后端事件相关 tests 38 passed。
- Artist CLI unit tests 13 passed。
- Artist frontend build 通过。
- Artist pipeline targeted test 1 passed，13 deselected。
- 扫描剩余命中仅为发布函数参数名、内部 store 字段、`last_event_id` replay 参数，以及旧字段不存在断言；后端输出兼容字段已删除。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- Artist SSE / history event 输出已是 Core runtime event shape。
- `event_type` / `payload` 不再由后端事件投影输出。
- 前端、CLI、history API 消费端仍可容忍旧输入格式，但主线读取 Core `data`。

当前遗留：

- 旧 `/api/sessions/events` endpoint 仍存在，当前用于无 session 全局订阅兼容。
- `publish_artist_event(event_type=..., payload=...)` 仍作为 Artist 服务内部发布函数接口，下一步可改名为 Core event 语义参数。
- `SessionEventHub._append_runtime_record()` 内部仍把 `_source_product` 写进 store payload 再过滤，已不输出；后续可删除这组内部产品元数据。

下一步：

- Step 10 继续：把 `publish_artist_event()` / `TaskEventStream.publish_event()` 参数名从 `event_type/payload` 改为 `name/data`，或删除 `SessionEventHub` 内部 `_source_product` / `_target_product` 写入。

### 10.49 执行记录：2026-07-02 Step 10 第四十九切片

目标：

- 删除 `SessionEventHub` 内部 `_source_product` / `_target_product` 写入。
- 让 Artist event store payload 本身也保持 Core runtime event data，不再先写产品元数据再过滤。

已完成：

- `members/artist/backend/app/services/session_event_hub.py`
  - `_append_runtime_record()` 删除 `source_product` / `target_product` 参数。
  - 不再向 event store payload 写入 `_source_product` / `_target_product`。
- `members/artist/backend/tests/test_session_event_hub_unit.py`
  - 测试名从 “without internal payload keys” 改为直接确认 Core shape。
  - 删除 `_source_product` 过滤断言，因为内部写入已不存在。

验证：

- `py -3.14 -m pytest members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_task_progress_unit.py members/artist/backend/tests/test_core_http_artist_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_cli_unit.py -q`
- `npm --prefix members/artist/frontend run build`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `rg -n '_source_product|_target_product|source_product|target_product' members/artist/backend/app members/artist/backend/tests -g '*.py'`
- `git diff --check -- members/artist/backend/app/services/session_event_hub.py members/artist/backend/tests/test_session_event_hub_unit.py`

验证备注：

- 后端事件相关 tests 38 passed。
- Artist CLI unit tests 13 passed。
- Artist frontend build 通过。
- Artist pipeline targeted test 1 passed，13 deselected。
- `_source_product` / `_target_product` / `source_product` / `target_product` 扫描无残留。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- Artist event store payload 不再携带产品元数据。
- Artist SSE/history 输出和内部 record data 都保持 Core runtime event shape。

当前遗留：

- `publish_artist_event(event_type=..., payload=...)` / `TaskEventStream.publish_event()` 参数名仍是旧 Artist event 语义，虽然内部已经写 Core record。
- 旧 `/api/sessions/events` endpoint 仍作为无 session 全局订阅兼容入口存在。

下一步：

- Step 10 继续：把 Artist 事件发布函数参数名从 `event_type/payload` 改为 `name/data`，并把旧命名限制在业务调用点或删除。

### 10.50 执行记录：2026-07-02 Step 10 第五十切片

目标：

- 将 Artist 事件发布接口从旧 `event_type` / `payload` 命名迁移到 Core runtime event 语义：`name` / `data`。
- 将 run 标识从 `correlation_id` 命名迁移到 `run_id`。

已完成：

- `members/artist/backend/app/services/task_events.py`
  - `TaskEventStream.publish_event()` 参数改为 `name`、`run_id`、`data`。
  - `publish_artist_event()` 参数改为 `name`、`run_id`、`data`。
  - 内部写入继续调用 `SessionEventHub.publish_runtime_record()`。
- `members/artist/backend/app/services/generate_service.py`
  - 所有 `publish_artist_event()` 调用改为 `name/run_id/data`。
  - `handle_artist_generate()` 内部 run 标识局部变量从 `correlation_id` 改为 `run_id`。
  - `_apply_image_context_resolution()` 参数从 `correlation_id` 改为 `run_id`。
- `members/artist/backend/app/services/artist_service.py`
  - 所有 `publish_artist_event()` 调用改为 `name/run_id/data`。
  - `_event_publish()` 内部发布变量改为 `name` / `run_id`。
- `members/artist/backend/app/routers/session.py`
  - 背景任务异常事件发布改为 `name/run_id/data`。
- 测试同步：
  - `test_task_events_unit.py`
  - `test_core_http_artist_unit.py`
  - `test_artist_session_lifecycle.py`
  - `test_artist_pipeline.py`

验证：

- `py -3.14 -m py_compile members/artist/backend/app/services/task_events.py members/artist/backend/app/services/artist_service.py members/artist/backend/app/services/generate_service.py members/artist/backend/app/routers/session.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_progress_unit.py members/artist/backend/tests/test_core_http_artist_unit.py members/artist/backend/tests/test_artist_session_lifecycle.py members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `npm --prefix members/artist/frontend run build`
- `rg -n 'event_type=|correlation_id=|payload=|correlation_id|"event_type"|"correlation_id"|"payload"' members/artist/backend/app/services/task_events.py members/artist/backend/app/services/artist_service.py members/artist/backend/app/services/generate_service.py members/artist/backend/app/routers/session.py members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_core_http_artist_unit.py members/artist/backend/tests/test_artist_session_lifecycle.py members/artist/backend/tests/test_artist_pipeline.py`
- `git diff --check -- members/artist/backend/app/services/task_events.py members/artist/backend/app/services/artist_service.py members/artist/backend/app/services/generate_service.py members/artist/backend/app/routers/session.py members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_core_http_artist_unit.py members/artist/backend/tests/test_artist_session_lifecycle.py members/artist/backend/tests/test_artist_pipeline.py`

验证备注：

- 语法检查通过。
- 后端事件 + Core HTTP + session lifecycle + CLI tests 54 passed。
- Artist pipeline targeted test 1 passed，13 deselected。
- Artist frontend build 通过。
- 发布接口旧参数名扫描无残留；剩余 `payload` 命中是普通业务数据变量、debug body 或测试标题。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- Artist 事件发布接口、event hub、SSE/history 输出已经统一到 Core runtime event 语义。
- 旧 `event_type/payload/correlation_id` 不再作为发布接口 contract 存在。

当前遗留：

- `publish_artist_event()` 函数名仍带 Artist 产品名，但其参数和输出已是 Core runtime event shape。
- 旧 `/api/sessions/events` endpoint 仍作为无 session 全局订阅兼容入口存在。
- 业务数据内仍有 `payload` 普通字段，例如 debug 的 request payload，不属于事件协议字段。

下一步：

- Step 10 继续：评估是否将 `publish_artist_event()` 重命名为产品无关的 `publish_runtime_event()`，或审计旧 `/api/sessions/events` 是否可以收缩到 Core live endpoint。

### 10.51 执行记录：2026-07-02 Step 10 第五十一切片

目标：

- 删除 Artist 事件发布函数名中的产品名残留。
- 将 `publish_artist_event()` 重命名为产品无关的 `publish_runtime_event()`。

已完成：

- `members/artist/backend/app/services/task_events.py`
  - `publish_artist_event()` 改名为 `publish_runtime_event()`。
- 生产调用点同步：
  - `members/artist/backend/app/services/artist_service.py`
  - `members/artist/backend/app/services/generate_service.py`
  - `members/artist/backend/app/routers/session.py`
- 测试 patch / mock 同步：
  - `members/artist/backend/tests/test_artist_session_lifecycle.py`
  - `members/artist/backend/tests/test_artist_pipeline.py`

验证：

- `rg -n "publish_artist_event|publish_runtime_event" members/artist/backend/app members/artist/backend/tests -g "*.py"`
- `py -3.14 -m py_compile members/artist/backend/app/services/task_events.py members/artist/backend/app/services/artist_service.py members/artist/backend/app/services/generate_service.py members/artist/backend/app/routers/session.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_progress_unit.py members/artist/backend/tests/test_core_http_artist_unit.py members/artist/backend/tests/test_artist_session_lifecycle.py members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `npm --prefix members/artist/frontend run build`
- `git diff --check -- members/artist/backend/app/services/task_events.py members/artist/backend/app/services/artist_service.py members/artist/backend/app/services/generate_service.py members/artist/backend/app/routers/session.py members/artist/backend/tests/test_artist_session_lifecycle.py members/artist/backend/tests/test_artist_pipeline.py`

验证备注：

- `publish_artist_event` 扫描无残留。
- 语法检查通过。
- 后端事件 + Core HTTP + session lifecycle + CLI tests 54 passed。
- Artist pipeline targeted test 1 passed，13 deselected。
- Artist frontend build 通过。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- Artist 事件发布函数名、参数、后端输出、前端消费、CLI 消费均已迁到 Core runtime event 语义。
- Artist 后端当前不再保留 `LamEvent` DTO、`event_type/payload` 输出字段、产品元数据字段或 `publish_artist_event` 函数名。

当前遗留：

- `TaskEventStream` / `task_events` 模块名仍是 task/event 语义，尚未抽到 Core 通用运行事件模块。
- 旧 `/api/sessions/events` endpoint 仍作为无 session 全局订阅兼容入口存在。

下一步：

- Step 10 继续：审计旧 `/api/sessions/events` 当前真实用途，决定是否保留为显式 global live endpoint，或收缩到 Core live endpoint。

### 10.52 执行记录：2026-07-02 Step 10 第五十二切片

目标：

- 删除旧 `/api/sessions/events` live 兼容入口。
- 将无 session 的全局 live 订阅迁移到明确的 Core endpoint：`/api/core/events/live`。

已完成：

- `members/artist/backend/app/routers/core_http.py`
  - 新增 `GET /api/core/events/live`，调用 `stream_session_events(..., session_id=None)`。
- `members/artist/backend/app/routers/session.py`
  - 删除 `GET /api/sessions/events`。
  - 删除无用 `Request` import。
- `members/artist/frontend/src/composables/useSessionEvents.ts`
  - 无 session 订阅 URL 从 `/api/sessions/events` 改为 `/api/core/events/live`。
- `members/artist/backend/tests/test_core_http_artist_unit.py`
  - 新增 Core global live endpoint 测试。
  - 删除旧 `/api/sessions/events?session_id=...` 兼容测试。

验证：

- `rg -n "sessions/events|core/events/live|stream_core_global_events|stream_session_events|Request" members/artist/backend/app/routers members/artist/backend/tests/test_core_http_artist_unit.py members/artist/frontend/src/composables/useSessionEvents.ts`
- `py -3.14 -m py_compile members/artist/backend/app/routers/core_http.py members/artist/backend/app/routers/session.py`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_events_unit.py -q`
- `npm --prefix members/artist/frontend run build`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py members/artist/backend/tests/test_artist_session_lifecycle.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `git diff --check -- members/artist/backend/app/routers/core_http.py members/artist/backend/app/routers/session.py members/artist/backend/tests/test_core_http_artist_unit.py members/artist/frontend/src/composables/useSessionEvents.ts`

验证备注：

- 旧 `/api/sessions/events` 扫描无残留。
- 路由语法检查通过。
- Core HTTP + session event hub + task events tests 35 passed。
- Core HTTP + session lifecycle tests 29 passed。
- Artist pipeline targeted test 1 passed，13 deselected。
- Artist frontend build 通过。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- Artist live event 入口已经全部在 `/api/core` 命名下：
  - session live：`/api/core/sessions/{session_id}/events/live`
  - global live：`/api/core/events/live`
- `/api/sessions` 不再承载 runtime event stream。

当前遗留：

- `TaskEventStream` / `task_events.py` 仍是 Artist backend 内的事件 facade，尚未抽到 Core 通用模块。
- `live_events.py` 仍在 Artist backend 内，虽然协议已经是 Core shape。

下一步：

- Step 10 继续：评估 `TaskEventStream` / `live_events.py` 是否能下沉到 Core，或先对 Artist Step 10 做阶段性验收，确认是否还有旧 runtime / SSE 残留。

### 10.53 执行记录：2026-07-02 Step 10 第五十三切片

目标：

- 删除 Artist 前端 `RuntimeEvent` 类型里的产品元字段。
- 让前端 runtime event 对象与后端 Core-only 输出保持一致。

已完成：

- `members/artist/frontend/src/types/index.ts`
  - `RuntimeEvent` 删除 `source_product` / `target_product` 字段。
- `members/artist/frontend/src/composables/useSessionEvents.ts`
  - `RuntimeSseEvent` 删除 `source_product` / `target_product` 输入字段。
  - `normalizeRuntimeEvent()` 不再补齐 `source_product` / `target_product`。

验证：

- `npm --prefix members/artist/frontend run build`
- `py -3.14 -m pytest members/artist/backend/tests/test_core_http_artist_unit.py members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_events_unit.py -q`
- `rg -n 'source_product|target_product|event_type|payload|event_id|correlation_id' members/artist/frontend/src/composables/useSessionEvents.ts members/artist/frontend/src/types/index.ts`
- `git diff --check -- members/artist/frontend/src/types/index.ts members/artist/frontend/src/composables/useSessionEvents.ts`

验证备注：

- Artist frontend build 通过。
- Core HTTP + session event hub + task events tests 35 passed。
- `source_product` / `target_product` 扫描无残留。
- `event_type` / `payload` / `event_id` / `correlation_id` 只剩旧输入 fallback，主线仍读取 Core `type` / `data` / `id` / `run_id`。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- Artist 前端 runtime event 类型与后端 Core-only event 输出一致。
- 产品元字段已从后端输出、后端内部 record data、前端 event 类型三处删除。

当前遗留：

- `useSessionEvents.ts` 和 CLI 仍保留旧输入 fallback，用于容忍历史或外部旧格式。
- `TaskEventStream` / `live_events.py` 仍在 Artist backend 内，尚未抽到 Core 通用模块。

下一步：

- Step 10 继续：对 Artist Step 10 做阶段性验收扫描，确认是否还有旧 runtime / SSE / TaskManager 残留；再决定是否把 `TaskEventStream` / `live_events.py` 下沉 Core。

### 10.54 执行记录：2026-07-02 Step 10 第五十四切片

目标：

- 收缩 Artist 前端历史事件读取里的旧协议 fallback。
- 保持 live SSE 对历史/外部输入的容错，不把容错当成后端输出 contract。

已完成：

- `members/artist/frontend/src/api/core.ts`
  - `getCoreEvents()` 历史事件读取只按 Core shape 映射：`id` / `type` / `data`。
  - 删除 `event_type` / `payload` 作为历史事件读取备选字段。

验证：

- `npm --prefix members/artist/frontend run build`
- `rg -n 'event_type|payload|event_id|correlation_id|source_product|target_product|sessions/events|publish_artist_event|TaskManager|LamEvent' members/artist/frontend/src/api/core.ts members/artist/frontend/src/composables/useSessionEvents.ts members/artist/frontend/src/types/index.ts members/artist/backend/app members/artist/backend/tests -g '*.py' -g '*.ts' -g '*.vue'`

验证备注：

- Artist frontend build 通过。
- `members/artist/frontend/src/api/core.ts` 不再读取旧 `event_type` / `payload`。
- 旧 `TaskManager`、`LamEvent`、`publish_artist_event`、`sessions/events`、`source_product`、`target_product` 在 Artist 当前生产代码扫描无残留。
- 剩余 `event_type` / `event_id` / `correlation_id` 只在 live SSE 旧输入容错、SSE replay id、测试 fixture 或内部变量名中出现；不是后端输出字段。
- 剩余 `payload` 多数是普通业务请求、provider 请求、Core event 内部 payload 或测试命名；不是旧 Artist SSE 输出 contract。

当前收缩：

- Artist 历史事件读取与后端 Core-only event 输出保持一致。
- Artist 当前 runtime event 输出、live endpoint、history endpoint、前端 history consumer 均不再依赖旧 Artist event 字段。

当前遗留：

- `useSessionEvents.ts` 和 CLI 仍保留旧输入 fallback，用于容忍历史或外部旧格式。
- `TaskEventStream` / `live_events.py` 仍在 Artist backend 内，尚未抽到 Core 通用模块。

下一步：

- Step 10 继续：做阶段性验收判断，决定 `TaskEventStream` / `live_events.py` 是下沉 Core，还是暂时作为 Artist 到 Core event shape 的 adapter 保留。

### 10.55 执行记录：2026-07-02 Step 10 第五十五切片

目标：

- 将 Artist 私有的 runtime event fan-out / replay / SSE 序列化能力下沉到 Core。
- 保留 Artist 专属 task snapshot 首包、live route 和产品进度状态，不把产品 adapter 过早抽成 Core。

已完成：

- `core/src/lamtools_core/run_event/hub.py`
  - 新增 `RuntimeEventHub`，承接内存 runtime event log、SSE subscriber fan-out、Last-Event-ID replay、Core-only event payload 输出。
- `core/src/lamtools_core/run_event/__init__.py`
  - 导出 `RuntimeEventHub`。
  - 文档措辞从 product-shell 收回到中性 session / run。
- `members/artist/backend/app/services/task_events.py`
  - `TaskEventStream` 改为依赖 Core `RuntimeEventHub`。
- `members/artist/backend/app/services/task_progress.py`
  - `TaskProgressStore` 改为通过 `RuntimeEventHub.publish_runtime_record()` 发布进度事件。
- `members/artist/backend/app/services/session_event_hub.py`
  - 删除 Artist 私有 hub 实现。
- 测试同步：
  - 新增 `core/tests/test_runtime_event_hub.py`。
  - `test_session_event_hub_unit.py` / `test_task_progress_unit.py` 改为直接覆盖 Core hub。

验证：

- `py -3.14 -m py_compile core/src/lamtools_core/run_event/__init__.py core/src/lamtools_core/run_event/hub.py members/artist/backend/app/services/task_events.py members/artist/backend/app/services/task_progress.py`
- `py -3.14 -m pytest core/tests/test_runtime_event_hub.py core/tests/test_run_event_store.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_events_unit.py members/artist/backend/tests/test_task_progress_unit.py members/artist/backend/tests/test_core_http_artist_unit.py members/artist/backend/tests/test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members/artist/backend/tests/test_artist_pipeline.py -q -k "event or publish or task_progress or checkpoint"`
- `npm --prefix members/artist/frontend run build`
- `rg -n "SessionEventHub|session_event_hub|publish_task_event|TaskManager|LamEvent|publish_artist_event|sessions/events|source_product|target_product" members/artist/backend/app members/artist/backend/tests members/artist/frontend/src core/src/lamtools_core core/tests -g "*.py" -g "*.ts" -g "*.vue"`
- `rg -n "Writer|Artist|LamWriter|LamArtist|product-shell" core/src/lamtools_core/run_event core/tests/test_runtime_event_hub.py -g "*.py"`
- `git diff --check -- core/src/lamtools_core/run_event/__init__.py core/src/lamtools_core/run_event/hub.py core/tests/test_runtime_event_hub.py members/artist/backend/app/services/session_event_hub.py members/artist/backend/app/services/task_events.py members/artist/backend/app/services/task_progress.py members/artist/backend/tests/test_session_event_hub_unit.py members/artist/backend/tests/test_task_progress_unit.py`

验证备注：

- Core runtime event tests 16 passed。
- Artist event / task progress / Core HTTP / CLI tests 51 passed。
- Artist pipeline targeted test 1 passed，13 deselected。
- Artist frontend build 通过。
- 旧 Artist hub、`publish_task_event`、`TaskManager`、`LamEvent`、`publish_artist_event`、旧 `sessions/events`、产品元字段扫描无残留。
- Core run_event 新模块不含 Writer/Artist 产品名，也不含旧 product-shell 文案。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- runtime event log、SSE fan-out、replay、Core event payload shape 已进入 Core。
- Artist 只保留事件发布 facade、task progress adapter、live HTTP adapter 和图像业务事件数据。
- Artist 私有 `SessionEventHub` 已删除。

当前遗留：

- `TaskEventStream` 仍是 Artist 侧 facade，用于绑定产品日志、critical event warning、checkpoint replay skip 策略和 task progress store。
- `live_events.py` 仍在 Artist backend，因为它发送 Artist task snapshot 首包并绑定 FastAPI route。
- `useSessionEvents.ts` 和 CLI 仍保留旧输入 fallback，用于容忍历史或外部旧格式。

下一步：

- Step 10 阶段性验收：确认 Artist 作为第二样例已经不再复制 runtime event/SSE hub；再回到总计划评估 Step 2/3/4 中 Core operation / MemberKit 主线缺口。

### 10.56 执行记录：2026-07-02 Step 10 阶段验收

目标：

- 对 Artist Step 10 当前成果做阶段性验收。
- 明确哪些能力已经下沉 Core，哪些保留为 Artist adapter，避免继续在 Artist 内做低收益细碎删除。

验收结论：

- Artist `TaskManager` 已删除。
- Artist 私有 `LamEvent` DTO 已删除。
- Artist 私有 `SessionEventHub` 已删除，runtime event fan-out / replay / SSE 序列化已由 Core `RuntimeEventHub` 承接。
- Artist runtime event 发布接口、history 输出、live 输出、前端 history consumer 已使用 Core-only event shape。
- 旧 `/api/sessions/events` 已删除，live runtime events 统一在 `/api/core/.../events/live`。
- Artist 前端 `RuntimeEvent` 类型不再包含产品元字段。

当前保留边界：

- `TaskEventStream` 保留为 Artist adapter：
  - 绑定产品日志。
  - 包装 Core `RuntimeEventHub`。
  - 保留 critical event warning。
  - 给 CLI / live route / task progress store 提供单一入口。
- `live_events.py` 保留为 Artist adapter：
  - 负责 FastAPI `StreamingResponse`。
  - 发送 Artist task snapshot 首包。
  - 绑定 `task_progress_store`。
- `useSessionEvents.ts` 和 CLI 保留旧输入 fallback：
  - 只用于容忍历史或外部旧格式。
  - 不代表后端输出 contract。

验证：

- `git status --short`
- `rg -n "TaskManager|task_manager|LamEvent|app\\.core\\.events|publish_artist_event|/api/sessions/events|sessions/events|event_type|event_id|correlation_id|source_product|target_product|_source_product|_target_product|SessionEventHub|session_event_hub|publish_task_event" members/artist/backend/app members/artist/backend/tests members/artist/frontend/src core/src/lamtools_core/run_event core/tests/test_runtime_event_hub.py -g "*.py" -g "*.ts" -g "*.vue"`
- `rg -n "from app\\.services\\.task_events|task_events|live_events|stream_session_events|RuntimeEventHub|publish_runtime_event" members/artist/backend/app members/artist/backend/tests -g "*.py"`
- `git log --oneline -5`

验证备注：

- 当前工作区只剩此前已有的未提交改动和未跟踪简历文件；本阶段提交后没有新的未提交代码改动。
- 旧 Artist event/SSE 关键残留扫描无生产问题。
- `event_id` 在 Core hub 内是 SSE replay id；不是旧输出字段。
- `event_type` / `correlation_id` 只在 live fallback 或测试断言中出现。
- `payload` 未纳入本次阶段验收扫描的失败条件，因为大量 provider / image / debug 业务请求仍合理使用该词；旧 Artist SSE 输出 contract 已通过 `data` 字段替代。

下一步：

- Step 10 暂停继续细碎收缩，回到总计划主线。
- 下一阶段优先评估 Step 2/3/4：Core Contract、Operation 主线、Event / Snapshot 最终收口，尤其是 `AgentApp` / `MemberKit` / `OperationCatalog` 是否已经形成目标接口。

### 10.57 执行记录：2026-07-02 Step 3 接续切片

目标：

- 将 operation 方法名规范化规则从 Writer app-server 下沉到 Core operation 层。
- Writer 继续保留自己的兼容别名，但通用 `turn/start` -> `turn.start` 规则不再只藏在 Writer。

已完成：

- `core/src/lamtools_core/app/operation_catalog.py`
  - 新增 operation 名称规范化入口。
  - 支持 slash-to-dot 和显式别名前后两次匹配。
- `core/src/lamtools_core/app/__init__.py`
  - 导出 operation 名称规范化入口。
- `core/src/lamtools_core/__init__.py`
  - 顶层 Core 包同步导出。
- `members/writer/backend/app/app_server/operations.py`
  - `operation_name()` 改为调用 Core 通用规则。
  - Writer 只保留 `turn/interrupt` / `turn.interrupt` 到 `turn.cancel` 的兼容别名表。
- `core/tests/test_agent_app_contract.py`
  - 增加 slash method 和别名规范化测试。

验证：

- `py -3.14 -m py_compile core/src/lamtools_core/app/operation_catalog.py core/src/lamtools_core/app/__init__.py core/src/lamtools_core/__init__.py members/writer/backend/app/app_server/operations.py`
- `py -3.14 -m pytest core/tests/test_agent_app_contract.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q -k "operation_name or operation_catalog or turn_start_operation_returns_error or approval_respond_operation_returns_error"`
- `rg -n 'normalize_operation_name|OPERATION_ALIASES|def operation_name|replace\\("/","\\."\\)' core/src/lamtools_core/app core/src/lamtools_core/__init__.py core/tests/test_agent_app_contract.py members/writer/backend/app/app_server/operations.py members/writer/backend/tests/test_writer_app_server_protocol.py -g '*.py'`
- `git diff --check -- core/src/lamtools_core/app/operation_catalog.py core/src/lamtools_core/app/__init__.py core/src/lamtools_core/__init__.py core/tests/test_agent_app_contract.py members/writer/backend/app/app_server/operations.py`

验证备注：

- Core app contract tests 4 passed。
- Writer app-server operation targeted tests 5 passed，21 deselected。
- 语法检查通过。
- 扫描确认 slash-to-dot 规则已进入 Core；Writer 只保留别名和薄包装。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- Operation 命名规则成为 Core app contract 的一部分。
- Writer app-server operation 层减少一处自管通用规则。

当前遗留：

- Writer operation handlers 仍在 Writer app-server 内实现；这符合当前阶段，因为它们依赖 Writer DB、queue、approval、artifact 和 runtime continuation。
- Artist 还没有接入 OperationCatalog；后续需要决定 Artist 是通过 HTTP operation facade 接入，还是先等待 Core `AgentApp` / `MemberKit` 装配主线更稳定。

下一步：

- 继续 Step 3/4：审计 Writer 当前 operation handler 中哪些是通用运行事实，哪些必须留在 Writer app-server adapter。

### 10.58 执行记录：2026-07-02 Step 3 第五十八切片

目标：

- 将 Writer CLI `list` 纳入 app-server operation 主线。
- 补齐计划中明确点名的 `session.list` operation。
- 避免 app-server operation 依赖 HTTP router 私有函数。

已完成：

- `members/writer/backend/app/services/session_projection.py`
  - 新增 Writer 会话投影 service。
  - 将会话基础字段、lifecycle 合并、transcript 最新状态合并集中到 service。
- `members/writer/backend/app/routers/session.py`
  - HTTP session route 改为调用 `session_response_projected()`。
  - 删除 route 内重复的 `_session_response` / `_session_response_projected` 实现。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `handle_session_list_operation()`。
  - `build_writer_operation_catalog()` 注册 `session.list`。
  - `session.list` 返回 `{"sessions": [...]}`，会话行形状与 HTTP route 保持一致。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入 `_session_list` handler。
- `members/writer/backend/writer_cli/app_server_client.py`
  - 新增 `list_sessions()`，通过 JSON-RPC 调 `session.list`。
- `members/writer/backend/writer_cli/__main__.py`
  - `cmd_list` 从直接 GET `/api/sessions?limit=...` 改为 app-server `session.list`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 `session.list` catalog 覆盖和真实 DB 查询测试。
  - `test_writer_cli.py` 增加 CLI list 使用 app-server operation 的测试。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/session_projection.py members/writer/backend/app/routers/session.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/writer_cli/app_server_client.py members/writer/backend/writer_cli/__main__.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_cli.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_core_http_writer_unit.py -q -k "sessions"`
- `rg -n "session\\.list|/api/sessions\\?limit|def cmd_list|list_sessions\\(" members/writer/backend/writer_cli members/writer/backend/app/app_server members/writer/backend/tests/test_writer_cli.py members/writer/backend/tests/test_writer_app_server_protocol.py -g "*.py"`
- `rg -n "_session_response|from app\\.routers\\.session import _session|session_response_projected" members/writer/backend/app members/writer/backend/tests -g "*.py"`
- `git diff --check -- members/writer/backend/app/services/session_projection.py members/writer/backend/app/routers/session.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/writer_cli/app_server_client.py members/writer/backend/writer_cli/__main__.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_cli.py`

验证备注：

- Writer app-server protocol tests 27 passed。
- Writer CLI tests 27 passed。
- Writer Core HTTP session targeted tests 7 passed，15 deselected；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- 语法检查通过。
- 扫描确认 `cmd_list` 已走 app-server `session.list`；`/api/sessions?limit` 在 CLI list 主线无残留。
- 会话投影已进入 service 层，app-server operation 不再依赖 HTTP router 私有函数。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- Writer CLI `list` 与 GUI/app-server 运行通道更接近同一 operation 主线。
- 会话列表投影从 HTTP router 抽到 service，operation 和 HTTP route 共享同一业务投影。

当前遗留：

- `writer new` 仍直接走 HTTP `/api/sessions`，尚未接入 `session.create` 或 `thread.start` operation。
- `writer messages/status/result` 仍直接读 HTTP session/messages route。
- Settings / provider / model 仍是 HTTP config route，尚未接入 `settings.get/update` operation。

下一步：

- Step 3 继续：评估 `writer new` 是否应接入 `session.create`，或者先收口 `settings.get/update` 到 operation。

### 10.59 执行记录：2026-07-02 Step 3 第五十九切片

目标：

- 将 `writer new` / `writer run` 的会话创建纳入 app-server operation 主线。
- 补齐计划中 `session.list` 之后的 `session.create` operation。
- 把 project/work_root/session 创建规则从 HTTP router 抽到 service，避免 operation 反向依赖 router 或复制逻辑。

已完成：

- `members/writer/backend/app/services/project_management.py`
  - 新增项目归一 service。
  - 承接 work_root 规范化、项目创建、重复项目合并、AGENTS.md 预读、项目名派生。
- `members/writer/backend/app/services/session_management.py`
  - 新增会话创建 service。
  - 承接 session mode 规范化、project_id 校验、work_root 继承、自动项目创建、git init、startup prewarm、会话投影。
- `members/writer/backend/app/routers/project.py`
  - `create_project()` / project dedupe 改为调用 `project_management`。
  - 删除 router 内重复的项目创建/去重实现。
- `members/writer/backend/app/routers/session.py`
  - `create_session()` 改为调用 `create_writer_session()`。
  - 删除 router 内重复的 session create 逻辑和 mode 规范化函数。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `handle_session_create_operation()`。
  - `build_writer_operation_catalog()` 注册 `session.create`。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入 `_session_create` handler。
- `members/writer/backend/writer_cli/app_server_client.py`
  - 新增 `create_session()`，通过 JSON-RPC 调 `session.create`。
- `members/writer/backend/writer_cli/__main__.py`
  - `_create_visible_session()` 改为 app-server `session.create`。
  - `cmd_new` / `cmd_run` 不再直接 POST `/api/projects` 和 `/api/sessions`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 `session.create` catalog 覆盖和真实 DB 创建测试。
  - `test_writer_cli.py` 更新创建会话测试，断言 CLI 使用 app-server operation。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/project_management.py members/writer/backend/app/services/session_management.py members/writer/backend/app/routers/project.py members/writer/backend/app/routers/session.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/writer_cli/app_server_client.py members/writer/backend/writer_cli/__main__.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_cli.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_project_crud.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_core_http_writer_unit.py -q -k "sessions"`
- `rg -n "session\\.create|/api/sessions|/api/projects|_ensure_project_for_work_root|create_writer_session|ensure_writer_project|project_name_from_work_root|dedupe_writer_projects" members/writer/backend/writer_cli members/writer/backend/app members/writer/backend/tests/test_writer_cli.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_project_crud.py -g "*.py"`
- `git diff --check -- members/writer/backend/app/services/project_management.py members/writer/backend/app/services/session_management.py members/writer/backend/app/routers/project.py members/writer/backend/app/routers/session.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/writer_cli/app_server_client.py members/writer/backend/writer_cli/__main__.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_cli.py`

验证备注：

- Writer app-server protocol tests 28 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- Writer CLI tests 27 passed。
- Writer project CRUD tests 3 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- Writer Core HTTP session targeted tests 7 passed，15 deselected；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- 语法检查通过。
- 扫描确认 `writer new` / `writer run` 创建主线通过 `session.create`；CLI 创建路径不再 POST `/api/projects` 或 `/api/sessions`。
- `messages/status/result` 仍直接读取 HTTP session/messages route，未纳入本切片。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- Writer CLI `list/new/run` 已通过 app-server operation 进入会话主线。
- 会话创建和项目创建规则从 HTTP router 下沉 service，operation 和 HTTP route 共享同一业务创建逻辑。

当前遗留：

- `writer messages/status/result` 仍直接读 HTTP session/messages route。
- Settings / provider / model 仍是 HTTP config route，尚未接入 `settings.get/update` operation。
- GUI 前端仍通过 HTTP Core/session/config route 读取大量状态，尚未全部经 app-server operation/snapshot。

下一步：

- Step 3 继续：优先评估 `settings.get/update` operation，或者将 `writer status/result/messages` 的读取逐步改到 app-server snapshot/operation。

### 10.60 执行记录：2026-07-02 Step 3 第六十切片

目标：

- 将 `writer status` / `writer result` 从 HTTP session/messages 读路径切到 app-server `thread.read`。
- 保留原有用户可见元数据：session id、status、phase、mode、work_root。
- 避免 CLI 为了补元数据重新拼两条 HTTP 读路径。

已完成：

- `members/writer/backend/app/app_server/operations.py`
  - `thread.read` 返回值补充 `session` 投影。
  - `thread.read` 继续返回 `thread` 与 `snapshot`，保持现有调用兼容。
- `members/writer/backend/writer_cli/app_server_client.py`
  - 新增 `read_thread()`，通过 JSON-RPC 调 `thread.read`。
- `members/writer/backend/writer_cli/__main__.py`
  - `cmd_status` 改为 app-server `thread.read`。
  - `cmd_result` 改为 app-server `thread.read`。
  - 增加 CLI 侧 snapshot 消息提取，仅用于 `status/result` 的最近消息和 summary 展示。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 `thread.read` 返回 session projection 的真实 DB 测试。
  - `test_writer_cli.py` 增加 `status/result` 不走 HTTP、只走 app-server `thread.read` 的测试。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/operations.py members/writer/backend/writer_cli/app_server_client.py members/writer/backend/writer_cli/__main__.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_cli.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `rg -n "cmd_status|cmd_result|/api/sessions/\\{args\\.session_id\\}|messages\\?limit|thread\\.read|read_thread\\(" members/writer/backend/writer_cli members/writer/backend/tests/test_writer_cli.py members/writer/backend/app/app_server/operations.py members/writer/backend/tests/test_writer_app_server_protocol.py -g "*.py"`
- `git diff --check -- members/writer/backend/app/app_server/operations.py members/writer/backend/writer_cli/app_server_client.py members/writer/backend/writer_cli/__main__.py members/writer/backend/tests/test_writer_cli.py members/writer/backend/tests/test_writer_app_server_protocol.py`

验证备注：

- Writer CLI tests 29 passed。
- Writer app-server protocol tests 29 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- 语法检查通过。
- 扫描确认 `cmd_status` / `cmd_result` 已走 app-server `thread.read`；CLI 中 HTTP `messages?limit` 只剩 `writer messages` 命令。
- diff whitespace check 通过；仅提示 Windows 工作区换行规范会在 Git 写入时转换。

当前收缩：

- Writer CLI `list/new/run/status/result` 已进入 app-server operation 主线。
- `thread.read` 成为 CLI 读线程状态的深接口，调用者不再需要同时理解 session route 与 messages route。

当前遗留：

- `writer messages` 仍直接读取 HTTP session/messages route，因其语义是完整消息列表，需单独切片处理。
- Settings / provider / model 仍是 HTTP config route，尚未接入 `settings.get/update` operation。
- GUI 前端仍通过 HTTP Core/session/config route 读取部分状态，尚未全部经 app-server operation/snapshot。

下一步：

- Step 3 继续：优先处理 `writer messages` 读路径，或补 `settings.get/update` operation。

### 10.61 执行记录：2026-07-02 Step 3 第六十一切片

目标：

- 将 `writer messages` 从 HTTP session/messages 读路径切到 app-server `thread.read`。
- 让 Writer CLI 的会话读侧统一通过 app-server operation/snapshot。

已完成：

- `members/writer/backend/writer_cli/__main__.py`
  - `cmd_messages` 改为 app-server `thread.read`。
  - 复用 10.60 增加的 snapshot 消息提取逻辑。
  - `--limit` 在 CLI 侧对 snapshot 投影后的可见消息做尾部截取。
- `members/writer/backend/tests/test_writer_cli.py`
  - 增加 `writer messages` 使用 app-server `thread.read` 的测试。
  - 测试显式禁止回落 `_request_json` HTTP 路径。

验证：

- `py -3.14 -m py_compile members/writer/backend/writer_cli/__main__.py members/writer/backend/writer_cli/app_server_client.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_cli.py -q`
- `rg -n "cmd_messages|cmd_status|cmd_result|/api/sessions/\\{args\\.session_id\\}|messages\\?limit|thread\\.read|read_thread\\(" members/writer/backend/writer_cli members/writer/backend/tests/test_writer_cli.py -g "*.py"`

验证备注：

- Writer CLI tests 30 passed。
- 语法检查通过。
- 扫描确认 `cmd_messages` / `cmd_status` / `cmd_result` 均走 app-server `thread.read`；CLI 会话消息读侧不再命中 HTTP `/api/sessions/{id}/messages`。

当前收缩：

- Writer CLI `list/new/run/messages/status/result` 已进入 app-server operation 主线。
- CLI 会话读侧从 HTTP session/messages route 收口到 `thread.read` + snapshot projection。

当前遗留：

- Settings / provider / model 仍是 HTTP config route，尚未接入 `settings.get/update` operation。
- `health` 仍是普通 HTTP 健康检查，属于服务存活探针，不纳入本次会话 operation 收口。
- GUI 前端仍通过 HTTP Core/session/config route 读取部分状态，尚未全部经 app-server operation/snapshot。

下一步：

- Step 3 继续：补 `settings.get/update` operation，并评估 Writer CLI / GUI 配置路径是否可以切到 operation。

### 10.62 执行记录：2026-07-02 Step 3 第六十二切片

目标：

- 补齐计划点名的 `settings.get` / `settings.update` operation。
- 将 app setting 读写规则从 HTTP config router 下沉到共享业务层。
- 暂不迁移 provider/model CRUD，避免把配置大面一次性改乱。

已完成：

- `members/writer/backend/app/services/app_settings.py`
  - 新增 app setting 读写 service。
  - 承接普通 setting 读写和 `lamwriter.modelRouting` 的特殊路由规则。
- `members/writer/backend/app/routers/config.py`
  - `/config/settings/{namespace}` GET/PUT 改为调用 app setting service。
  - 保留原 HTTP route 返回形状。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `handle_settings_get_operation()`。
  - 新增 `handle_settings_update_operation()`。
  - `build_writer_operation_catalog()` 注册 `settings.get` / `settings.update`。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入 `_settings_get` / `_settings_update`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 catalog 覆盖、handler 存在性、参数校验和真实 DB round-trip 测试。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/app_settings.py members/writer/backend/app/routers/config.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_model_routing_config.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_core_http_writer_unit.py -q -k "config or settings or model"`
- `rg -n "settings\\.get|settings\\.update|handle_settings|get_app_setting_value|update_app_setting_value|/config/settings" members/writer/backend/app members/writer/backend/tests/test_writer_app_server_protocol.py -g "*.py"`

验证备注：

- Writer app-server protocol tests 31 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- model routing config tests 5 passed。
- Core HTTP unit tests 按 `config/settings/model` 关键字筛选没有命中用例：22 deselected，未执行断言。
- 语法检查通过。
- 扫描确认 `settings.get` / `settings.update` 已注册并接入 app-server connection；HTTP `/config/settings` 与 operation 共用 app setting service。

当前收缩：

- Writer app setting 读写不再只存在于 HTTP router 内。
- operation 主线已覆盖 turn、approval、queue、artifact、session、settings 的核心请求面。

当前遗留：

- Provider / model CRUD 仍是 HTTP config route，未迁移为 operation。
- GUI SettingsView 仍通过 HTTP config store 访问配置；本切片只先补后端 operation。
- GUI 前端仍通过 HTTP Core/session/config route 读取部分状态，尚未全部经 app-server operation/snapshot。

下一步：

- Step 3 继续：审计 GUI config store，决定是否先把 app setting 读写切到 app-server operation，还是先处理 provider/model CRUD operation。

### 10.63 执行记录：2026-07-02 Step 3 第六十三切片

目标：

- 将前端 app setting 读写切到 app-server `settings.get` / `settings.update`。
- 保持 provider/model CRUD 继续走 HTTP，避免配置页大面积迁移。

已完成：

- `members/writer/frontend/src/api/index.ts`
  - 新增短连接 app-server operation helper。
  - `getAppSetting()` 改为请求 `settings.get`。
  - `putAppSetting()` 改为请求 `settings.update`。
  - 保持 config store 和 SettingsView 调用面不变。

验证：

- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "getAppSetting|putAppSetting|settings\\.get|settings\\.update|/api/config/settings|appServerOperation" members/writer/frontend/src/api/index.ts members/writer/frontend/src/stores/config.ts members/writer/frontend/src/views -g "*.ts" -g "*.vue"`
- `git status --short`

验证备注：

- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 构建没有留下 `dist` 改动。
- 扫描确认 `getAppSetting()` / `putAppSetting()` 已经请求 app-server operation；前端源码中不再直接调用 `/api/config/settings`。

当前收缩：

- GUI app setting 读写已进入 app-server operation 主线。
- SettingsView / CoreWorkbenchView 不需要知道 transport 变化，仍调用 config store。

当前遗留：

- Provider / model CRUD、resolved config、runtime capabilities、subagent config 仍是 HTTP config route。
- GUI 前端仍通过 HTTP Core/session/config route 读取部分状态，尚未全部经 app-server operation/snapshot。

下一步：

- Step 3 继续：评估 provider/model CRUD 是否需要 operation 化；或转入 GUI session/config HTTP 残留清点，决定下一批最小切片。

### 10.64 执行记录：2026-07-02 Step 3 第六十四切片

目标：

- 修复 app-server JSON-RPC result 的 JSON 可发送性。
- 避免 `settings.get/update`、`session.list/create/read` 等 operation 返回 `datetime` 后 WebSocket `send_json()` 失败。

已完成：

- `members/writer/backend/app/app_server/protocol.py`
  - `rpc_result()` 改为 `model_dump(mode="json", exclude_none=True)`。
  - `rpc_error()` 同步改为 JSON mode，保持 error data 也可安全发送。
- `members/writer/backend/tests/test_writer_app_server_protocol.py`
  - 增加 JSON-RPC result 中嵌套 `datetime` 会转为 ISO 字符串的测试。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/protocol.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `rg -n "model_dump|rpc_result|updated_at.*2026-07-02|mode=\\x22json\\x22" members/writer/backend/app/app_server/protocol.py members/writer/backend/tests/test_writer_app_server_protocol.py`

验证备注：

- Writer app-server protocol tests 32 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- 语法检查通过。
- 扫描确认 `rpc_result` / `rpc_error` 已统一使用 JSON mode。

当前收缩：

- operation handler 不需要逐个手写 datetime 转换。
- `settings.get/update` 前端切换到 app-server 后具备实际可发送的响应形状。

当前遗留：

- Provider / model CRUD、resolved config、runtime capabilities、subagent config 仍是 HTTP config route。
- GUI 前端仍通过 HTTP Core/session/config route 读取部分状态，尚未全部经 app-server operation/snapshot。

下一步：

- Step 3 继续：做 GUI/HTTP 残留清点，按风险选择 provider/model read-only operation 或 session HTTP route 收口。

### 10.65 执行记录：2026-07-02 Step 3 第六十五切片

目标：

- 将 GUI 配置页启动所需的只读配置面切到 app-server operation。
- 先处理低风险 read-only：providers、models、resolved config、adapter profiles。
- provider/model 的创建、更新、删除仍保留 HTTP，后续单独切片。

已完成：

- `members/writer/backend/app/services/config_read.py`
  - 新增配置只读 service。
  - 集中 provider/model 投影、API key mask、resolved config 投影、adapter profile 投影。
- `members/writer/backend/app/routers/config.py`
  - provider list、model list、resolved config、adapter profiles HTTP route 改为复用 `config_read`。
  - 保持原 HTTP route 返回形状。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `config.providers.list`。
  - 新增 `config.models.list`。
  - 新增 `config.resolved.get`。
  - 新增 `config.adapter_profiles.list`。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入 4 个配置只读 operation。
- `members/writer/frontend/src/api/index.ts`
  - `listProviders()` 改为 `config.providers.list`。
  - `listModels()` 改为 `config.models.list`。
  - `getResolvedConfig()` 改为 `config.resolved.get`。
  - `listAdapterProfiles()` 改为 `config.adapter_profiles.list`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 catalog 覆盖、handler 存在性、真实 DB provider/model/resolved 查询测试、adapter profiles 形状测试。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/config_read.py members/writer/backend/app/routers/config.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_model_routing_config.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "config\\.providers\\.list|config\\.models\\.list|config\\.resolved\\.get|config\\.adapter_profiles\\.list|handle_config_.*operation|list_provider_configs|list_model_configs|resolved_config_response" members/writer/backend/app members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/frontend/src/api/index.ts -g "*.py" -g "*.ts"`
- `git status --short`

验证备注：

- Writer app-server protocol tests 34 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- model routing config tests 5 passed。
- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 构建没有留下 `dist` 改动。
- 扫描确认 4 个配置只读 operation 已注册、接入 connection，并被前端 API 使用。

当前收缩：

- GUI SettingsView 初始加载中的 providers/models/resolved/adapter profiles 读路径已进入 app-server operation 主线。
- HTTP config route 与 app-server operation 共享同一只读投影 service，不再各自维护读取形状。

当前遗留：

- Provider / model create/update/delete 仍是 HTTP config route。
- import-env、runtime capabilities、subagent config 仍是 HTTP config route。
- 会话工程、附件、git/undo/checkpoint 等产品副作用 HTTP route 尚未收口。

下一步：

- Step 3 继续：优先评估 provider/model CRUD operation，或先把 `import-env` / `runtime-capabilities` 这类配置读写继续下沉 service 并接 operation。

### 10.66 执行记录：2026-07-02 Step 3 第六十六切片

目标：

- 将 provider create/update/delete 从 HTTP-only 配置 route 收口到 app-server operation。
- 保留 HTTP route，但让 HTTP 和 operation 共用同一 provider mutation service。
- 暂不处理 model CRUD 和 import-env，保持切片边界清楚。

已完成：

- `members/writer/backend/app/services/config_write.py`
  - 新增 provider mutation service。
  - 集中 provider 创建、更新、删除和删除 provider 时级联删除 model。
  - provider 返回形状复用 `config_read.provider_response()`，保持 API key mask。
- `members/writer/backend/app/routers/config.py`
  - provider create/update/delete HTTP route 改为调用 `config_write`。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `config.provider.create`。
  - 新增 `config.provider.update`。
  - 新增 `config.provider.delete`。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入 3 个 provider mutation operation。
- `members/writer/frontend/src/api/index.ts`
  - `createProvider()` 改为 `config.provider.create`。
  - `updateProvider()` 改为 `config.provider.update`。
  - `deleteProvider()` 改为 `config.provider.delete`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 catalog 覆盖、handler 存在性、参数校验、真实 DB 创建/更新/删除/级联删除测试。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/config_write.py members/writer/backend/app/routers/config.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_model_routing_config.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "config\\.provider\\.(create|update|delete)|handle_config_provider|create_provider_config|update_provider_config|delete_provider_config" members/writer/backend/app members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/frontend/src/api/index.ts -g "*.py" -g "*.ts"`

验证备注：

- Writer app-server protocol tests 36 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- model routing config tests 5 passed。
- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 构建没有留下 `dist` 改动。
- 扫描确认 provider create/update/delete operation 已注册、接入 connection，并被前端 API 使用。

当前收缩：

- GUI provider 的读写主线均已进入 app-server operation。
- HTTP provider route 不再单独维护 mutation 逻辑。

当前遗留：

- Model create/update/delete 仍是 HTTP config route。
- import-env、runtime capabilities、subagent config 仍是 HTTP config route。
- 会话工程、附件、git/undo/checkpoint 等产品副作用 HTTP route 尚未收口。

下一步：

- Step 3 继续：优先处理 model CRUD operation；之后再评估 import-env 和 runtime-capabilities。

### 10.67 执行记录：2026-07-02 Step 3 第六十七切片

目标：

- 将 model create/update/delete 从 HTTP-only 配置 route 收口到 app-server operation。
- 保留 HTTP route，但让 HTTP 和 operation 共用同一 model mutation service。
- 保留删除 model 后的 routing 修正规则。

已完成：

- `members/writer/backend/app/services/config_write.py`
  - 新增 model 创建、更新、删除 service。
  - 创建/改 provider 时校验 provider 存在。
  - 删除 model 后调用 model routing 修正逻辑。
- `members/writer/backend/app/routers/config.py`
  - model create/update/delete HTTP route 改为调用 `config_write`。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `config.model.create`。
  - 新增 `config.model.update`。
  - 新增 `config.model.delete`。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入 3 个 model mutation operation。
- `members/writer/frontend/src/api/index.ts`
  - `createModel()` 改为 `config.model.create`。
  - `updateModel()` 改为 `config.model.update`。
  - `deleteModel()` 改为 `config.model.delete`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 catalog 覆盖、handler 存在性、参数校验、真实 DB 创建/更新/删除测试。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/config_write.py members/writer/backend/app/routers/config.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_model_routing_config.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "config\\.model\\.(create|update|delete)|handle_config_model|create_model_config|update_model_config|delete_model_config" members/writer/backend/app members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/frontend/src/api/index.ts -g "*.py" -g "*.ts"`

验证备注：

- Writer app-server protocol tests 38 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- model routing config tests 5 passed。
- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 构建没有留下 `dist` 改动。
- 扫描确认 model create/update/delete operation 已注册、接入 connection，并被前端 API 使用。

当前收缩：

- GUI provider/model 的读写主线均已进入 app-server operation。
- HTTP provider/model route 不再单独维护 mutation 逻辑。

当前遗留：

- import-env、runtime capabilities、subagent config 仍是 HTTP config route。
- 会话工程、附件、git/undo/checkpoint 等产品副作用 HTTP route 尚未收口。

下一步：

- Step 3 继续：处理 import-env operation，或将 runtime-capabilities 读路径下沉 service 并接 operation。

### 10.68 执行记录：2026-07-02 Step 3 第六十八切片

目标：

- 将 `import-env` 从 HTTP-only 配置 route 收口到 app-server operation。
- 保留 HTTP route，但让 HTTP 和 operation 共用同一导入逻辑。
- 保持导入 provider/model 后更新 Writer model route 的行为。

已完成：

- `members/writer/backend/app/services/config_write.py`
  - 新增 `import_env_provider_model_config()`。
  - 承接环境变量 provider/model 导入、已有记录复用、model 参数刷新、Writer route 更新。
- `members/writer/backend/app/routers/config.py`
  - `/config/import-env` 改为调用 `config_write`。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `config.import_env`。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入 import-env operation。
- `members/writer/frontend/src/api/index.ts`
  - `importEnvConfig()` 改为 `config.import_env`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 catalog 覆盖、handler 存在性、真实 DB import-env 测试，并断言 Writer route 更新。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/config_write.py members/writer/backend/app/routers/config.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_model_routing_config.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "config\\.import_env|handle_config_import_env|import_env_provider_model_config|importEnvConfig" members/writer/backend/app members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/frontend/src/api/index.ts -g "*.py" -g "*.ts"`

验证备注：

- Writer app-server protocol tests 39 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- model routing config tests 5 passed。
- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 构建没有留下 `dist` 改动。
- 扫描确认 `config.import_env` 已注册、接入 connection，并被前端 API 使用。

当前收缩：

- GUI 配置页的 provider/model/import-env 读写主线已进入 app-server operation。
- HTTP config route 不再单独维护 import-env 逻辑。

当前遗留：

- runtime capabilities、subagent config 仍是 HTTP config route。
- 会话工程、附件、git/undo/checkpoint 等产品副作用 HTTP route 尚未收口。

下一步：

- Step 3 继续：处理 runtime-capabilities 读路径，或评估 subagent config 是否先下沉 service 并接 operation。

### 10.69 执行记录：2026-07-02 Step 3 第六十九切片

目标：

- 将 `runtime-capabilities` 从 HTTP-only 配置读取收口到 app-server operation。
- 保留 HTTP route，但让 HTTP 和 operation 共用同一份运行能力读取逻辑。
- 保持 settings UI 的返回结构不变。

已完成：

- `members/writer/backend/app/services/runtime_capabilities.py`
  - 新增 `runtime_capabilities_response()`，集中生成 agents/subagents/tools/command_policies。
  - 新增 `runtime_controls()`，供运行能力读取和 subagent route 复用。
- `members/writer/backend/app/routers/config.py`
  - `/config/runtime-capabilities` 改为调用 service。
  - subagent upsert 复用 `runtime_controls()`。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `config.runtime_capabilities.get`。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入 runtime capabilities operation。
- `members/writer/frontend/src/api/index.ts`
  - `getRuntimeCapabilities()` 改为 `config.runtime_capabilities.get`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 catalog 覆盖、handler 存在性、真实 DB runtime controls 读取测试。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/runtime_capabilities.py members/writer/backend/app/routers/config.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_model_routing_config.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "config_runtime_capabilities_get|config\\.runtime_capabilities|getRuntimeCapabilities|runtime-capabilities" members/writer/backend/app members/writer/backend/tests members/writer/frontend/src/api/index.ts`

验证备注：

- Writer app-server protocol tests 40 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- model routing config tests 5 passed。
- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 构建没有留下 `dist` 改动。
- 扫描确认 `config.runtime_capabilities.get` 已注册、接入 connection，并被前端 API 使用。

当前收缩：

- GUI 配置页的 provider/model/import-env/runtime-capabilities 主线已进入 app-server operation。
- HTTP config route 不再单独维护 runtime-capabilities 读取逻辑。

当前遗留：

- subagent config 仍是 HTTP config route。
- 会话工程、附件、git/undo/checkpoint 等产品副作用 HTTP route 尚未收口。

下一步：

- Step 3 继续：处理 subagent config 写入/删除路径，或先盘点配置页残留 HTTP 调用后确定下一切片。

### 10.70 执行记录：2026-07-02 Step 3 第七十切片

目标：

- 将项目 subagent 保存/删除从 HTTP-only 配置 route 收口到 app-server operation。
- 保留 HTTP route，但让 HTTP 和 operation 共用同一份 subagent 写入/删除逻辑。
- 配置页不再直接调用 `/api/config/subagents/*`。

已完成：

- `members/writer/backend/app/services/subagent_config.py`
  - 新增 `upsert_project_subagent_config()`，集中处理名称校验、项目 work root、定义写入和 enabled 状态。
  - 新增 `delete_project_subagent_config()`，集中处理项目定义删除。
- `members/writer/backend/app/routers/config.py`
  - subagent upsert/delete HTTP route 改为调用 service。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `config.subagent.upsert`。
  - 新增 `config.subagent.delete`。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入 subagent upsert/delete operation。
- `members/writer/frontend/src/api/index.ts`
  - `saveProjectSubAgent()` 改为 `config.subagent.upsert`。
  - `deleteProjectSubAgent()` 改为 `config.subagent.delete`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 catalog 覆盖、handler 存在性、参数校验、真实项目定义创建/删除测试。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/subagent_config.py members/writer/backend/app/routers/config.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_agent_runtime.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_model_routing_config.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "config_subagent|config\\.subagent|subagent_config|saveProjectSubAgent|deleteProjectSubAgent|/api/config/subagents" members/writer/backend/app members/writer/backend/tests members/writer/frontend/src/api/index.ts`

验证备注：

- Writer app-server protocol tests 42 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- agent runtime tests 21 passed。
- model routing config tests 5 passed。
- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 构建没有留下 `dist` 改动。
- 扫描确认 `config.subagent.upsert/delete` 已注册、接入 connection，并被前端 API 使用。

当前收缩：

- GUI 配置页的 provider/model/import-env/runtime-capabilities/subagent 主线已进入 app-server operation。
- HTTP config route 不再单独维护 subagent 写入/删除逻辑。

当前遗留：

- 配置页主线已基本收口；下一步应盘点 `frontend/src/api/index.ts` 中剩余 HTTP 调用，区分项目/附件/git 等产品副作用是否继续并入 app-server。
- 会话工程、附件、git/undo/checkpoint 等产品副作用 HTTP route 尚未收口。

下一步：

- Step 3 继续：盘点配置页之外的剩余 HTTP 产品副作用路径，优先选择可独立验证的一条 operation 化。

### 10.71 执行记录：2026-07-02 Step 3 第七十一切片

目标：

- 将前端会话列表/创建入口从 HTTP route 切到既有 app-server operation。
- 不改后端业务逻辑；复用已存在的 `session.list` / `session.create`。

已完成：

- `members/writer/frontend/src/api/index.ts`
  - `listSessions()` 改为 `session.list`。
  - `createSession()` 改为 `session.create`。
  - 保持对调用方的返回结构不变。

验证：

- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "listSessions\\(\\)|createSession\\(|session\\.list|session\\.create|return request<Session\\[]>\\('/api/sessions'|return request<Session>\\('/api/sessions'" members/writer/frontend/src/api/index.ts members/writer/backend/app/app_server/operations.py members/writer/backend/tests/test_writer_app_server_protocol.py`

验证备注：

- Writer app-server protocol tests 42 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 构建没有留下 `dist` 改动。
- 扫描确认前端会话列表/创建已使用 `session.list/create`，不再直接调用 `/api/sessions` 列表/创建 HTTP route。

当前收缩：

- Writer 前端会话首页常用的 list/create 主线已进入 app-server operation。

当前遗留：

- session get/update/delete、project、attachments、git/undo/checkpoint 仍走 HTTP route。

下一步：

- Step 3 继续：优先处理 session get/update/delete，或先把 project list/create 这类入口补齐 operation。

### 10.72 执行记录：2026-07-02 Step 3 第七十二切片

目标：

- 将前端 session get/update/delete 从 HTTP route 切到 app-server operation。
- 将 HTTP route 中的 session get/update/delete 业务逻辑下沉到会话管理模块，让 HTTP 和 operation 共用。
- 保持 get 预热、update 字段归一化/git 初始化、delete 级联清理的既有行为。

已完成：

- `members/writer/backend/app/services/session_management.py`
  - 新增 `get_writer_session_response()`。
  - 新增 `update_writer_session()`。
  - 新增 `delete_writer_session()`。
- `members/writer/backend/app/routers/session.py`
  - session get/update/delete HTTP route 改为调用会话管理模块。
  - 删除这些 route 上不再使用的旧导入。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `session.get`。
  - 新增 `session.update`。
  - 新增 `session.delete`。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入 session get/update/delete operation。
- `members/writer/frontend/src/api/index.ts`
  - `getSession()` 改为 `session.get`。
  - `updateSession()` 改为 `session.update`。
  - `deleteSession()` 改为 `session.delete`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 catalog 覆盖、handler 存在性、参数校验、真实 DB get/update/delete round trip，并断言 delete 清理 session/message/attachment/queued input。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/session_management.py members/writer/backend/app/routers/session.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_model_routing_config.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "session_get|session_update|session_delete|session\\.get|session\\.update|session\\.delete|getSession\\(|updateSession\\(|deleteSession\\(|/api/sessions/\\$\\{id\\}" members/writer/backend/app members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/frontend/src/api/index.ts`

验证备注：

- Writer app-server protocol tests 44 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- model routing config tests 5 passed。
- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 构建没有留下 `dist` 改动。
- 扫描确认前端 session get/update/delete 已使用 `session.get/update/delete`，不再直接调用 `/api/sessions/${id}` HTTP route。

当前收缩：

- Writer 前端 session CRUD 主线已进入 app-server operation。
- session get/update/delete 的业务逻辑从 HTTP route 下沉到共享会话管理模块。

当前遗留：

- project、attachments、git/undo/checkpoint 等产品副作用 HTTP route 尚未收口。
- `listProjectSessions()` 仍走项目维度 HTTP 查询。

下一步：

- Step 3 继续：优先补 project list/create/get/update/delete operation，或先处理附件/文件预览这类会话详情页残留 HTTP 路径。

### 10.73 执行记录：2026-07-02 Step 3 第七十三切片

目标：

- 将前端 project list/create/get/update/delete 从 HTTP route 切到 app-server operation。
- 将 HTTP route 中的 project CRUD 业务逻辑下沉到项目管理模块，让 HTTP 和 operation 共用。
- 保留 `agents-md` 和 project sessions HTTP 路径不动，避免本片混入文件读写和会话查询。

已完成：

- `members/writer/backend/app/services/project_management.py`
  - 新增 `project_response()`。
  - 新增 `create_writer_project_response()`。
  - 新增 `list_writer_project_responses()`。
  - 新增 `get_writer_project_response()`。
  - 新增 `update_writer_project()`。
  - 新增 `delete_writer_project()`。
- `members/writer/backend/app/routers/project.py`
  - project CRUD HTTP route 改为调用项目管理模块。
  - HTTP route 继续返回 `ProjectResponse`，兼容直接调用 route 的旧测试。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `project.list`。
  - 新增 `project.create`。
  - 新增 `project.get`。
  - 新增 `project.update`。
  - 新增 `project.delete`。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入 project CRUD operation。
- `members/writer/frontend/src/api/index.ts`
  - `listProjects()` 改为 `project.list`。
  - `createProject()` 改为 `project.create`。
  - `getProject()` 改为 `project.get`。
  - `updateProject()` 改为 `project.update`。
  - `deleteProject()` 改为 `project.delete`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 catalog 覆盖、handler 存在性、参数校验、真实 DB project create/list/update/get/delete 测试。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/project_management.py members/writer/backend/app/routers/project.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_project_crud.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_model_routing_config.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "project_create|project_update|project_delete|project\\.list|project\\.create|project\\.get|project\\.update|project\\.delete|listProjects\\(|createProject\\(|getProject\\(|updateProject\\(|deleteProject\\(|/api/projects'|/api/projects/\\$\\{id\\}" members/writer/backend/app members/writer/backend/tests members/writer/frontend/src/api/index.ts`

验证备注：

- Writer app-server protocol tests 46 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- project CRUD tests 3 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- model routing config tests 5 passed。
- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 构建没有留下 `dist` 改动。
- 扫描确认前端 project CRUD 已使用 `project.*` operation；`agents-md` HTTP 路径仍保留，符合本片边界。

当前收缩：

- Writer 前端 project CRUD 主线已进入 app-server operation。
- project CRUD 的业务逻辑从 HTTP route 下沉到共享项目管理模块。

当前遗留：

- `agents-md` 文件读写仍走 HTTP route。
- `listProjectSessions()` 仍走项目维度 HTTP 查询。
- attachments、git/undo/checkpoint/commit-review/agent-branches 等产品副作用 HTTP route 尚未收口。

下一步：

- Step 3 继续：优先处理 `agents-md` 或 `listProjectSessions()`，再进入附件和 git/checkpoint 类会话详情路径。

### 10.74 执行记录：2026-07-02 Step 3 第七十四切片

目标：

- 将前端 `AGENTS.md` 读取/保存从 HTTP route 切到 app-server operation。
- 将 HTTP route 中的 `AGENTS.md` 文件读写逻辑下沉到项目管理模块，让 HTTP 和 operation 共用。
- 保持无文件返回空内容、读取后同步 DB 缓存、写入后同步文件和 DB 缓存的既有行为。

已完成：

- `members/writer/backend/app/services/project_management.py`
  - 新增 `read_project_agents_md()`。
  - 新增 `write_project_agents_md()`。
- `members/writer/backend/app/routers/project.py`
  - `/projects/{project_id}/agents-md` GET/PUT 改为调用项目管理模块。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `project.agents_md.get`。
  - 新增 `project.agents_md.update`。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入 AGENTS.md read/write operation。
- `members/writer/frontend/src/api/index.ts`
  - `getAgentsMd()` 改为 `project.agents_md.get`。
  - `updateAgentsMd()` 改为 `project.agents_md.update`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 catalog 覆盖、handler 存在性、参数校验、真实 DB + 文件系统读写测试。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/project_management.py members/writer/backend/app/routers/project.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_project_crud.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "project_agents_md|project\\.agents_md|getAgentsMd|updateAgentsMd|/api/projects/\\$\\{id\\}/agents-md|read_project_agents_md|write_project_agents_md" members/writer/backend/app members/writer/backend/tests members/writer/frontend/src/api/index.ts`

验证备注：

- Writer app-server protocol tests 47 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- project CRUD tests 3 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 构建没有留下 `dist` 改动。
- 扫描确认前端 `AGENTS.md` 入口已使用 `project.agents_md.*` operation。

当前收缩：

- Project CRUD 与 AGENTS.md 文件读写主线已进入 app-server operation。
- project route 中的 AGENTS.md 文件读写业务逻辑已下沉到共享项目管理模块。

当前遗留：

- `listProjectSessions()` 仍走项目维度 HTTP 查询。
- attachments、git/undo/checkpoint/commit-review/agent-branches 等产品副作用 HTTP route 尚未收口。

下一步：

- Step 3 继续：处理 `listProjectSessions()`，或进入附件 read/list/open 路径。

### 10.75 执行记录：2026-07-02 Step 3 第七十五切片

目标：

- 将前端 `listProjectSessions()` 从 HTTP route 切到 app-server operation。
- 将 HTTP route 中的项目会话汇总查询下沉到项目管理模块，让 HTTP 和 operation 共用。

已完成：

- `members/writer/backend/app/services/project_management.py`
  - 新增 `project_session_summary()`。
  - 新增 `list_project_session_summaries()`。
- `members/writer/backend/app/routers/project.py`
  - `/projects/{project_id}/sessions` 改为调用项目管理模块。
  - 清理 project route 中不再使用的导入。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `project.sessions.list`。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入 project sessions list operation。
- `members/writer/frontend/src/api/index.ts`
  - `listProjectSessions()` 改为 `project.sessions.list`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 catalog 覆盖、handler 存在性、参数校验、真实 DB 项目会话筛选与排序测试。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/project_management.py members/writer/backend/app/routers/project.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_project_crud.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "project_sessions|project\\.sessions\\.list|listProjectSessions|/api/projects/\\$\\{projectId\\}/sessions|list_project_session_summaries" members/writer/backend/app members/writer/backend/tests members/writer/frontend/src/api/index.ts`

验证备注：

- Writer app-server protocol tests 48 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- project CRUD tests 3 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 构建没有留下 `dist` 改动。
- 扫描确认前端 `listProjectSessions()` 已使用 `project.sessions.list` operation。

当前收缩：

- Project CRUD、AGENTS.md 文件读写、项目会话列表主线均已进入 app-server operation。
- project route 中的项目会话查询逻辑已下沉到共享项目管理模块。

当前遗留：

- attachments、git/undo/checkpoint/commit-review/agent-branches 等产品副作用 HTTP route 尚未收口。

下一步：

- Step 3 继续：进入附件 list/read/open 路径，或先处理 git/checkpoint 类会话详情路径。

### 10.76 执行记录：2026-07-02 Step 3 第七十六切片

目标：

- 将前端附件 `list/read/preview/open` 从 HTTP route 切到 app-server operation。
- 将 HTTP route 中的附件查询、预览、打开逻辑下沉到共享附件模块，让 HTTP 和 operation 共用。
- 保留 multipart 上传和下载 HTTP 形态，不把二进制传输混入本切片。

已完成：

- `members/writer/backend/app/services/attachment_service.py`
  - 新增附件列表、读取、预览、打开的共享响应函数。
  - 打开附件支持注入 opener，测试不启动外部应用。
- `members/writer/backend/app/routers/attachment.py`
  - 附件 list/read/preview/open route 改为调用共享附件模块。
  - route 只负责 HTTP 404 错误映射。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `attachment.list`、`attachment.get`、`attachment.preview`、`attachment.open`。
  - 新增四个附件 operation handler。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入四个附件 operation。
- `members/writer/frontend/src/api/index.ts`
  - `listAttachments()`、`getAttachment()`、`previewAttachment()`、`openAttachment()` 改为 app-server operation。
  - `uploadAttachment()` 继续保留 multipart HTTP 上传。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 catalog 覆盖、handler 存在性、参数校验、真实 DB + 临时文件的 list/read/preview/open 验证。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/attachment_service.py members/writer/backend/app/routers/attachment.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "attachment\\.list|attachment\\.get|attachment\\.preview|attachment\\.open|listAttachments|/api/sessions/\\$\\{sessionId\\}/attachments|/api/attachments/\\$\\{id\\}/preview|/api/attachments/\\$\\{id\\}/open|list_session_attachment_responses|preview_attachment_response|open_attachment_response" members/writer/backend/app members/writer/backend/tests members/writer/frontend/src/api/index.ts`
- `git diff --check`

验证备注：

- Writer app-server protocol tests 50 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 扫描确认前端附件 list/read/preview/open 已使用 `attachment.*` operation。
- 扫描确认 `uploadAttachment()` 仍保留 multipart HTTP 上传，本切片未处理二进制上传。

当前收缩：

- 附件普通 JSON 动作已进入 app-server operation。
- 附件查询、预览、打开逻辑已从 route 下沉到共享附件模块。

当前遗留：

- 附件 upload/download 仍走 HTTP。
- git/undo/checkpoint/commit-review/agent-branches 等产品副作用 HTTP route 尚未收口。

下一步：

- Step 3 继续：处理 git/checkpoint/undo/commit-review/agent-branches 会话详情路径，或单独收口附件上传/下载。

### 10.77 执行记录：2026-07-02 Step 3 第七十七切片

目标：

- 将前端会话详情中的 `git-graph` 与 `changes` 只读查询从 HTTP route 切到 app-server operation。
- 将 route 中的会话 git 图谱与变更统计查询下沉到共享会话 git 查询模块。
- 不处理 undo、checkpoint restore、commit-review decision、agent branch merge 等会改变工作区或状态的动作。

已完成：

- `members/writer/backend/app/services/session_git_queries.py`
  - 新增会话 git 图谱查询。
  - 新增会话变更统计查询，包含 tracked diff、untracked 文件统计、checkpoint fallback、diff stat 与 patch 摘要。
- `members/writer/backend/app/routers/session.py`
  - `/sessions/{session_id}/git-graph` 改为调用共享会话 git 查询模块。
  - `/sessions/{session_id}/changes` 改为调用共享会话 git 查询模块，并保留原响应模型。
  - 删除 route 内已迁出的 untracked diff 辅助逻辑。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `session.git_graph.get`。
  - 新增 `session.changes.get`。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入两个会话 git 查询 operation。
- `members/writer/frontend/src/api/index.ts`
  - `getGitGraph()` 改为 `session.git_graph.get`。
  - `getSessionChanges()` 改为 `session.changes.get`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 catalog 覆盖、handler 存在性、参数校验、临时 git 仓库下的图谱与变更查询验证。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/session_git_queries.py members/writer/backend/app/routers/session.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_session_changes.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "session\\.git_graph\\.get|session\\.changes\\.get|getGitGraph|getSessionChanges|/api/sessions/\\$\\{sessionId\\}/git-graph|/api/sessions/\\$\\{sessionId\\}/changes|get_git_graph_response|get_session_changes_response" members/writer/backend/app members/writer/backend/tests members/writer/frontend/src/api/index.ts`
- `git diff --check`

验证备注：

- Writer app-server protocol tests 51 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- session changes tests 7 passed。
- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 扫描确认前端 `getGitGraph()` 与 `getSessionChanges()` 已使用 `session.*` operation。
- 扫描确认 undo/undo-file 仍走 HTTP，本切片未处理会改变工作区的动作。

当前收缩：

- 会话 git 图谱与变更统计查询已进入 app-server operation。
- route 中一段较长的变更统计实现已下沉到共享查询模块，HTTP 和 operation 复用同一实现。

当前遗留：

- checkpoint list/create/restore、commit-review、undo/undo-file、agent-branches 仍走 HTTP。
- 附件 upload/download 仍走 HTTP。

下一步：

- Step 3 继续：优先处理 checkpoint list/create 这种结构清晰的 session operation；restore/undo/merge 等改工作区动作单独切片。

### 10.78 执行记录：2026-07-02 Step 3 第七十八切片

目标：

- 将前端 checkpoint list/create 从 HTTP route 切到 app-server operation。
- 复用已有 checkpoint 模块，减少 session route 中 checkpoint 创建逻辑复制。
- 暂不处理 checkpoint restore，因为 restore 会回滚工作区，应单独切片验证。

已完成：

- `members/writer/backend/app/services/checkpoint_service.py`
  - 新增 `list_session_checkpoint_responses()`。
  - 新增 `create_session_checkpoint_response()`。
  - checkpoint list/create 统一输出传输层可直接使用的 dict。
- `members/writer/backend/app/routers/session.py`
  - `/sessions/{session_id}/checkpoints` list/create 改为调用 checkpoint 模块。
  - route 保留原响应模型与 HTTP 错误映射。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `session.checkpoints.list`。
  - 新增 `session.checkpoint.create`。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入 checkpoint list/create operation。
- `members/writer/frontend/src/api/index.ts`
  - `listSessionCheckpoints()` 改为 `session.checkpoints.list`。
  - `createSessionCheckpoint()` 改为 `session.checkpoint.create`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 catalog 覆盖、handler 存在性、参数校验。
  - 临时 git 仓库测试中增加真实 checkpoint 创建与列表读取验证。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/checkpoint_service.py members/writer/backend/app/routers/session.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_session_changes.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "session\\.checkpoints\\.list|session\\.checkpoint\\.create|listSessionCheckpoints|createSessionCheckpoint|/api/sessions/\\$\\{sessionId\\}/checkpoints|list_session_checkpoint_responses|create_session_checkpoint_response" members/writer/backend/app members/writer/backend/tests members/writer/frontend/src/api/index.ts`
- `git diff --check`

验证备注：

- Writer app-server protocol tests 51 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- session changes tests 7 passed。
- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 扫描确认前端 checkpoint list/create 已使用 `session.checkpoint*` operation。
- 扫描确认 checkpoint restore 仍走 HTTP，本切片未处理回滚工作区动作。

当前收缩：

- checkpoint list/create 已进入 app-server operation。
- checkpoint 创建主线开始复用 checkpoint 模块，session route 的职责进一步收窄。

当前遗留：

- checkpoint restore、commit-review、undo/undo-file、agent-branches 仍走 HTTP。
- 附件 upload/download 仍走 HTTP。

下一步：

- Step 3 继续：处理 commit-review 读取/创建这种 session 状态类 operation；undo、restore、merge 继续单独切片。

### 10.79 执行记录：2026-07-02 Step 3 第七十九切片

目标：

- 将前端 commit-review read/decision 从 HTTP route 切到 app-server operation。
- 将 commit-review 读取与决策逻辑下沉到 commit-review 模块，让 route 和 operation 共用。
- 不处理 `request_commit_review`，因为当前前端 API 没有暴露该入口。

已完成：

- `members/writer/backend/app/services/commit_review_service.py`
  - 新增 `get_commit_review_response()`。
  - 新增 `decide_commit_review_response()`。
  - commit-review 的反馈、延期、批准提交逻辑从 route 下沉到服务模块。
  - 保留 worktree changed 的专用异常，route 可继续映射为 409。
- `members/writer/backend/app/routers/session.py`
  - `/sessions/{session_id}/commit-review` 改为调用 commit-review 模块。
  - `/sessions/{session_id}/commit-review/decision` 改为调用 commit-review 模块。
  - route 保留原响应模型与 HTTP 错误映射。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `session.commit_review.get`。
  - 新增 `session.commit_review.decide`。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入 commit-review read/decision operation。
- `members/writer/frontend/src/api/index.ts`
  - `getCommitReview()` 改为 `session.commit_review.get`。
  - `decideCommitReview()` 改为 `session.commit_review.decide`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 catalog 覆盖、handler 存在性、参数校验。
  - 增加 commit-review read 与 request_changes 决策 operation 行为测试。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/commit_review_service.py members/writer/backend/app/routers/session.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_session_changes.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "session\\.commit_review\\.get|session\\.commit_review\\.decide|getCommitReview|decideCommitReview|/api/sessions/\\$\\{sessionId\\}/commit-review|get_commit_review_response|decide_commit_review_response" members/writer/backend/app members/writer/backend/tests members/writer/frontend/src/api/index.ts`
- `git diff --check`

验证备注：

- Writer app-server protocol tests 52 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- session changes tests 7 passed，覆盖 commit-review approve 正式提交路径。
- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 扫描确认前端 commit-review read/decision 已使用 `session.commit_review.*` operation。
- 当前前端 API 没有 `request_commit_review` 暴露入口，本切片未处理该 route。

当前收缩：

- commit-review read/decision 已进入 app-server operation。
- commit-review 决策逻辑从 session route 下沉到 commit-review 模块。

当前遗留：

- checkpoint restore、undo/undo-file、agent-branches 仍走 HTTP。
- 附件 upload/download 仍走 HTTP。
- 后端 `request_commit_review` route 仍存在，但当前前端未调用。

下一步：

- Step 3 继续：处理 agent-branches 的 list/diff 只读路径；merge/abandon 单独切片。

### 10.80 执行记录：2026-07-02 Step 3 第八十切片

目标：

- 将前端 agent-branches list/diff 从 HTTP route 切到 app-server operation。
- 将 agent branch 只读查询下沉到共享模块，让 route 和 operation 共用。
- 不处理 merge/abandon，因为它们会改变分支和 worktree，单独切片验证。

已完成：

- `members/writer/backend/app/services/agent_branch_service.py`
  - 新增 `list_agent_branch_responses()`。
  - 新增 `get_agent_branch_diff_response()`。
  - 新增共享分支名校验。
- `members/writer/backend/app/routers/session.py`
  - `/sessions/{session_id}/agent-branches` 改为调用 agent branch 模块。
  - `/sessions/{session_id}/agent-branches/diff` 改为调用 agent branch 模块。
  - route 保留原响应模型与 HTTP 错误映射。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `session.agent_branches.list`。
  - 新增 `session.agent_branch.diff`。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入 agent branch list/diff operation。
- `members/writer/frontend/src/api/index.ts`
  - `listAgentBranches()` 改为 `session.agent_branches.list`。
  - `getAgentBranchDiff()` 改为 `session.agent_branch.diff`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 catalog 覆盖、handler 存在性、参数校验。
  - 临时 git 仓库测试中创建真实 `writer/agent/*` 分支并验证 list/diff operation。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/agent_branch_service.py members/writer/backend/app/routers/session.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_session_changes.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "session\\.agent_branches\\.list|session\\.agent_branch\\.diff|listAgentBranches|getAgentBranchDiff|/api/sessions/\\$\\{sessionId\\}/agent-branches|list_agent_branch_responses|get_agent_branch_diff_response" members/writer/backend/app members/writer/backend/tests members/writer/frontend/src/api/index.ts`
- `git diff --check`

验证备注：

- Writer app-server protocol tests 52 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- session changes tests 7 passed。
- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 扫描确认前端 agent branch list/diff 已使用 `session.agent_branch*` operation。
- 扫描确认 merge/abandon 仍走 HTTP，本切片未处理会改变分支/worktree 的动作。

当前收缩：

- agent branch list/diff 已进入 app-server operation。
- agent branch 只读查询从 session route 下沉到共享模块。

当前遗留：

- checkpoint restore、undo/undo-file、agent branch merge/abandon 仍走 HTTP。
- 附件 upload/download 仍走 HTTP。
- 后端 `request_commit_review` route 仍存在，但当前前端未调用。

下一步：

- Step 3 继续：处理 undo/undo-file 或 checkpoint restore 这类工作区修改动作，需单独加强回滚验证。

### 10.81 执行记录：2026-07-02 Step 3 第八十一切片

目标：

- 将前端 undo/undo-file 从 HTTP route 切到 app-server operation。
- 将工作区回滚逻辑下沉到共享 undo 模块，让 route 和 operation 共用。
- 使用真实临时 git 仓库验证 tracked 与 untracked 文件回滚。

已完成：

- `members/writer/backend/app/services/session_undo_service.py`
  - 新增 `undo_session_changes_response()`。
  - 新增 `undo_session_file_change_response()`。
  - 迁入工作区路径校验、untracked 删除、tracked restore、checkpoint fallback 逻辑。
- `members/writer/backend/app/routers/session.py`
  - `/sessions/{session_id}/changes/undo` 改为调用 undo 模块。
  - `/sessions/{session_id}/changes/undo-file` 改为调用 undo 模块。
  - 删除 route 内旧路径/删除辅助逻辑。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `session.changes.undo`。
  - 新增 `session.change_file.undo`。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入 undo/undo-file operation。
- `members/writer/frontend/src/api/index.ts`
  - `undoSessionChanges()` 改为 `session.changes.undo`。
  - `undoSessionFileChange()` 改为 `session.change_file.undo`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 catalog 覆盖、handler 存在性、参数校验。
  - 增加真实 git 仓库下的单文件 undo 与整体 undo operation 行为测试。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/session_undo_service.py members/writer/backend/app/routers/session.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_session_changes.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "session\\.changes\\.undo|session\\.change_file\\.undo|undoSessionChanges|undoSessionFileChange|/api/sessions/\\$\\{sessionId\\}/changes/undo|undo_session_changes_response|undo_session_file_change_response" members/writer/backend/app members/writer/backend/tests members/writer/frontend/src/api/index.ts`
- `git diff --check`

验证备注：

- Writer app-server protocol tests 53 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- session changes tests 7 passed，覆盖原 HTTP route 行为。
- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 扫描确认前端 undo/undo-file 已使用 `session.*.undo` operation。

当前收缩：

- undo/undo-file 已进入 app-server operation。
- 工作区回滚逻辑从 session route 下沉到共享 undo 模块。

当前遗留：

- checkpoint restore、agent branch merge/abandon 仍走 HTTP。
- 附件 upload/download 仍走 HTTP。
- 后端 `request_commit_review` route 仍存在，但当前前端未调用。

下一步：

- Step 3 继续：处理 checkpoint restore，保留真实 git 仓库回滚验证。

### 10.82 执行记录：2026-07-02 Step 3 第八十二切片

目标：

- 将前端 checkpoint restore 从 HTTP route 切到 app-server operation。
- 将 checkpoint restore 逻辑下沉到 checkpoint 模块。
- 保留真实 git 仓库回滚验证，确认恢复到指定 checkpoint 内容。

已完成：

- `members/writer/backend/app/services/checkpoint_service.py`
  - 新增 `restore_session_checkpoint_response()`。
  - 迁入 checkpoint 归属校验、回退前自动存档、restore 执行、last_restore 记录更新。
- `members/writer/backend/app/routers/session.py`
  - `/sessions/{session_id}/checkpoints/restore` 改为调用 checkpoint 模块。
  - 删除 route 内旧 checkpoint 私有记录/创建辅助。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `session.checkpoint.restore`。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入 checkpoint restore operation。
- `members/writer/frontend/src/api/index.ts`
  - `restoreSessionCheckpoint()` 改为 `session.checkpoint.restore`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 catalog 覆盖、handler 存在性、参数校验。
  - 临时 git 仓库测试中增加 checkpoint restore operation，并断言文件内容恢复到 checkpoint 版本。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/checkpoint_service.py members/writer/backend/app/routers/session.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_session_changes.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "session\\.checkpoint\\.restore|restoreSessionCheckpoint|/api/sessions/\\$\\{sessionId\\}/checkpoints/restore|restore_session_checkpoint_response" members/writer/backend/app members/writer/backend/tests members/writer/frontend/src/api/index.ts`
- `git diff --check`

验证备注：

- Writer app-server protocol tests 53 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- session changes tests 7 passed，覆盖原 HTTP route restore 行为。
- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 扫描确认前端 checkpoint restore 已使用 `session.checkpoint.restore` operation。

当前收缩：

- checkpoint restore 已进入 app-server operation。
- checkpoint restore 逻辑从 session route 下沉到 checkpoint 模块。

当前遗留：

- agent branch merge/abandon 仍走 HTTP。
- 附件 upload/download 仍走 HTTP。
- 后端 `request_commit_review` route 仍存在，但当前前端未调用。

下一步：

- Step 3 继续：处理 agent branch merge/abandon；需要真实 git 分支合并和删除验证。

### 10.83 执行记录：2026-07-02 Step 3 第八十三切片

目标：

- 将前端 agent branch merge/abandon 从 HTTP route 切到 app-server operation。
- 将 agent branch 合并/放弃逻辑下沉到共享 agent branch 模块，让 route 和 operation 共用。
- 使用真实临时 git 仓库验证分支合并与删除。

已完成：

- `members/writer/backend/app/services/agent_branch_service.py`
  - 新增 `merge_agent_branch_response()`。
  - 新增 `abandon_agent_branch_response()`。
  - 迁入 session work_root 校验、agent branch 校验、当前分支读取、merge/delete 执行与响应组装。
- `members/writer/backend/app/routers/session.py`
  - `/sessions/{session_id}/agent-branches/merge` 改为调用 agent branch 模块。
  - `/sessions/{session_id}/agent-branches/abandon` 改为调用 agent branch 模块。
  - 删除 route 内旧 work_root/branch 私有辅助逻辑。
- `members/writer/backend/app/app_server/operations.py`
  - 新增 `session.agent_branch.merge`。
  - 新增 `session.agent_branch.abandon`。
- `members/writer/backend/app/app_server/connection.py`
  - app-server connection 接入 agent branch merge/abandon operation。
- `members/writer/frontend/src/api/index.ts`
  - `mergeAgentBranch()` 改为 `session.agent_branch.merge`。
  - `abandonAgentBranch()` 改为 `session.agent_branch.abandon`。
- 测试同步：
  - `test_writer_app_server_protocol.py` 增加 catalog 覆盖、handler 存在性、参数校验。
  - 临时 git 仓库测试中增加 agent branch merge，并断言合并后的文件进入当前工作树。
  - 临时 git 仓库测试中增加 agent branch abandon，并断言目标分支从 agent branch 列表移除。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/agent_branch_service.py members/writer/backend/app/routers/session.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_session_changes.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`
- `rg -n "session\\.agent_branch\\.merge|session\\.agent_branch\\.abandon|mergeAgentBranch|abandonAgentBranch|/api/sessions/\\$\\{sessionId\\}/agent-branches/(merge|abandon)|merge_agent_branch_response|abandon_agent_branch_response" members/writer/backend/app members/writer/backend/tests members/writer/frontend/src/api/index.ts`

验证备注：

- Writer app-server protocol tests 53 passed；Windows asyncio transport cleanup 产生 warning，但无断言失败。
- session changes tests 7 passed。
- Frontend app-server tests 20 passed。
- Frontend build 通过；仅 Vite 输出既有的大 chunk 体积提示。
- 扫描确认前端 merge/abandon 已使用 `session.agent_branch.*` operation；旧 HTTP URL 已退出前端主线。

当前收缩：

- agent branch merge/abandon 已进入 app-server operation。
- agent branch 行为逻辑从 session route 下沉到共享 agent branch 模块。
- 前端常规 JSON 业务请求已收敛到 app-server operation；剩余 HTTP 主线主要是附件 multipart upload。

当前遗留：

- 附件 upload/download 仍走 HTTP；upload 属于 multipart/binary 传输，需要单独设计边界。
- 后端 `request_commit_review` route 仍存在，但当前前端未调用。

下一步：

- Step 3 收尾：核对前端 API 中剩余 HTTP 调用，明确 attachment upload/download 与未使用后端 route 的处理策略。

### 10.84 执行记录：2026-07-02 Step 3 收尾切片

目标：

- 核对 Writer 前端剩余 HTTP 调用，确认 Step 3 的 operation 主线边界。
- 删除 `members/writer/frontend/src/api/index.ts` 中已经无调用方的 JSON HTTP helper。
- 明确附件 multipart 上传和 Core-shaped `/api/core` 兼容面不混入本切片。

已完成：

- `members/writer/frontend/src/api/index.ts`
  - 删除已无调用方的 `request()` JSON helper。
  - 保留 `requestForm()`，仅用于附件 multipart 上传。
- 现状核对：
  - `members/writer/frontend/src/api/index.ts` 中普通 JSON 业务调用均已使用 app-server operation。
  - 剩余 `/api/sessions/{session_id}/attachments` 是 multipart 上传，属于二进制传输边界。
  - `members/writer/frontend/src/api/core.ts` 仍访问 `/api/core`，这是 Core-shaped compatibility/controller 面，后续应单独按 Core UI 边界处理，不与 Writer 业务 API 收敛混做。

验证：

- `rg -n "request<|requestForm|fetch\\(|/api/|appServerOperation" members/writer/frontend/src members/writer/backend/app/routers members/writer/backend/app/app_server -g "*.ts" -g "*.vue" -g "*.py"`
- `rg -n "from '@/api/core'|@/api/core|listCore|createCore|api/core|CoreSession|CoreProvider" members/writer/frontend/src members/writer/backend/app/routers/core_http.py`

当前收缩：

- Writer 前端业务 API 主线已经从 HTTP JSON 收敛到 app-server operation。
- `api/index.ts` 不再保留通用 JSON HTTP helper。

当前遗留：

- 附件 multipart upload/download 仍是 HTTP/binary 边界。
- `/api/core` compatibility/controller 面仍在 CoreWorkbench 使用，需要作为后续 Core UI/compatibility 专项处理。
- 后端旧 REST route 仍作为兼容 adapter 存在；生产前端主线已不再调用这些 Writer JSON 业务 route。

下一步：

- 进入 Step 4：Event / Snapshot 最终收口，优先核对 Writer app-server runtime lifecycle 与 snapshot 写入链路中仍由 Writer 独占的运行事实。

### 10.85 执行记录：2026-07-02 Step 4 第一切片

目标：

- 进入 Event / Snapshot 最终收口。
- 收敛 Writer app-server runtime lifecycle 中重复的 RunItemEvent 持久化、snapshot 应用和 hub 发布顺序。
- 保持运行失败和审批续跑错误的外部行为不变。

已完成：

- `members/writer/backend/app/app_server/runtime.py`
  - 新增 runtime lifecycle 内部的 RunItemEvent 持久化/发布统一入口。
  - `_finish_failed()` 改为复用该入口。
  - `_publish_approval_continuation_error()` 改为复用该入口。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_queue.py -q`

验证备注：

- app-server protocol/runtime bridge/approvals/queue 相关测试 92 passed。
- Windows asyncio transport cleanup 产生 warning，但无断言失败。

当前收缩：

- runtime lifecycle 不再在多个位置手写同一段 `RunItemEvent -> app event/snapshot -> commit -> hub publish` 顺序。
- 运行事实写入继续集中在 `persist_run_item_events_as_app_events()` 和 snapshot 应用链路。

当前遗留：

- runtime bridge 仍是 Writer app-server 内部适配层；后续需要继续核对哪些映射属于 Core run item，哪些只是 Writer 产品副作用。
- queue/operation 中仍有多处 product event 写入后读取 snapshot 的流程，需要继续按风险逐步收敛。

下一步：

- Step 4 继续：核对 runtime bridge 的 artifact/request 副作用边界，避免把 Core 运行事实和 Writer 产品副作用混在同一层。

### 10.86 执行记录：2026-07-02 Step 4 第二切片

目标：

- 拆清 runtime bridge 中的 Core 运行事实入账与 Writer 产品副作用边界。
- 让 `runtime_bridge.py` 只保留 RunItemEvent 持久化编排，不直接承载 artifact/request 细节。

已完成：

- `members/writer/backend/app/app_server/runtime_side_effects.py`
  - 新增 `persist_run_item_side_effects()`。
  - 承接 Writer artifact 持久化。
  - 承接 approval request 记录持久化。
- `members/writer/backend/app/app_server/runtime_bridge.py`
  - 删除 artifact id 生成、artifact 记录写入、approval request 写入的私有实现。
  - 改为先调用 runtime side effects，再写入 `core/runItem` 并应用 snapshot。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime_bridge.py members/writer/backend/app/app_server/runtime_side_effects.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_server_protocol.py -q`

验证备注：

- runtime bridge / approvals / app-server protocol 相关测试 82 passed。
- Windows asyncio transport cleanup 产生 warning，但无断言失败。

当前收缩：

- Core run item 入账路径与 Writer artifact/request 副作用分层更清楚。
- `runtime_bridge.py` 从混合实现变成编排层。

当前遗留：

- `runtime_fact_recorder.py` 和 runtime bridge 的关系仍需继续核对，确认是否还有旧 runtime fact 到 app-server projection 的过渡逻辑可删除或标注。
- snapshot reducer 中外层 Writer event 与 `snapshot.core` 的职责边界仍需继续收口。

下一步：

- Step 4 继续：检查 `runtime_fact_recorder.py` 是否仍承担旧运行事实主线，优先删除或标注无生产入边的过渡逻辑。

### 10.87 执行记录：2026-07-02 Step 4 第三切片

目标：

- 核对 `runtime_fact_recorder.py` 是否仍是生产主线。
- 在确认不能删除后，收缩其内部 runtime fact -> RunItemEvent projection 发布边界。
- 去掉“app projection”命名，避免误导为旧 Writer AppEvent 运行事实主线。

已完成：

- 现状核对：
  - `WriterRuntimeRunner` 仍创建 `RuntimeFactRecorder`。
  - `RuntimeFactRecorder` 仍负责 CoreEvent -> transcript sink -> Core RunItemEvent -> app snapshot projection。
  - 因此该文件不是无入口旧代码，不能删除。
- `members/writer/backend/app/services/runtime_fact_recorder.py`
  - 将两个重复的 `runtime_projection_to_run_item_events(...) -> publish(...)` 调用收敛到 `_publish_run_item_projection()`。
  - 将旧 `_publish_app_projection` 命名改为 `_publish_run_items()`，明确发布对象是 Core `RunItemEvent`。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/services/runtime_fact_recorder.py members/writer/backend/app/services/runtime_runner.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_server_protocol.py -q`
- `rg -n "_publish_app_projection|_publish_run_item_projection|_publish_run_items|runtime_projection_to_run_item_events|RuntimeFactRecorder" members/writer/backend/app/services/runtime_fact_recorder.py members/writer/backend/app/services/runtime_runner.py`

验证备注：

- Writer service / runtime bridge / app-server protocol 相关测试 102 passed。
- Windows asyncio transport cleanup 产生 warning，但无断言失败。
- 搜索确认旧 `_publish_app_projection` 命名已退出。

当前收缩：

- `RuntimeFactRecorder` 仍保留为生产主线适配器，但内部边界更清楚：先同步 transcript，再投影 Core RunItemEvent。
- 旧 AppEvent 语义没有继续扩散。

当前遗留：

- `RuntimeFactRecorder` 名称仍保留 runtime fact 过渡语言；后续可继续把输入类型收敛为更直接的 Core RunItemEvent sink。
- snapshot reducer 中外层 Writer event 与 `snapshot.core` 的职责边界仍需继续收口。

下一步：

- Step 4 继续：检查 reducer / snapshot 中外层 Writer event 是否还承载运行事实；优先删除已被 `snapshot.core` 替代的外层归约分支。

### 10.88 执行记录：2026-07-02 Step 4 第四切片

目标：

- 继续收敛 reducer 中外层 Writer event 与 `snapshot.core` 的职责边界。
- 将 `serverRequest/resolved` 从外层 item 归约分支中拆出，避免审批回执污染运行 item。
- 保持审批卡状态和 Core approval response 行为不变。

已完成：

- `members/writer/backend/app/app_server/reducer.py`
  - `item/started` 只负责外层产品 item。
  - `serverRequest/resolved` 独立归约，只更新外层 `requests`。
  - 不再因为审批回执携带 `item_id` 而写入外层 `items` / `item_order`。
- `members/writer/backend/tests/test_writer_app_server_protocol.py`
  - 新增回归，验证 `serverRequest/resolved` 只更新 `requests`，不产生外层 item。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/reducer.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_queue.py -q`
- `npm run test`，工作目录 `members/writer/frontend`

验证备注：

- app-server protocol / approvals / queue 相关测试 67 passed。
- Frontend app-server tests 20 passed。
- Windows asyncio transport cleanup 产生 warning，但无断言失败。

当前收缩：

- 外层 Writer `items` 更明确地只承载产品 item，不再承载审批回执。
- 审批运行事实继续由 `core/runItem` 写入 `snapshot.core.requests`，外层 `requests` 只作为产品回执/兼容状态。

当前遗留：

- `item/started` 仍用于用户输入/队列分发这类产品显示事实。
- `turn/*` 和 `queue/*` 仍是外层产品事实；后续需继续确认哪些可以进入 Core run item，哪些应保留为 Member 产品状态。

下一步：

- Step 4 继续：核对 `turn/interrupted` 外层事件是否仍需要作为产品控制事实，或是否可进一步以 Core status 表达。

### 10.89 执行记录：2026-07-02 Step 4 第五切片

目标：

- 核对 `turn/interrupted` 是否仍需要保留为外层产品控制事实。
- 在保留兼容回执的同时，让取消中的运行状态进入 Core `RunItemEvent` / `snapshot.core`。
- 确认 runtime 捕获取消后仍以 Core failed status 写入最终状态。

已完成：

- 现状核对：
  - 前端仍通过 `turn/interrupt` 触发取消。
  - `turn/interrupted` 仍用于立即回执和产品控制状态，暂不删除。
  - runtime 取消完成后已有 Core failed status。
- `members/writer/backend/app/app_server/operations.py`
  - `handle_turn_cancel_operation()` 在写入外层 `turn/interrupted` 后，同时写入 Core `RunItemEvent(kind="status", status="interrupting")`。
  - 返回 snapshot 现在立即包含 `snapshot.core.status == "interrupting"`。
  - hub publish 同时发布外层产品回执和 Core run item。
- `members/writer/backend/tests/test_writer_app_server_protocol.py`
  - 扩展取消测试：断言 interrupt response 的 `snapshot.core` 立即进入 interrupting。
  - 断言 app ledger 中存在 Core interrupting status。
  - 保留原断言：runtime 取消后继续写入 raw_end_reason 为 `user_interrupt` 的 Core failed status。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/operations.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_queue.py -q`

验证备注：

- app-server protocol / queue 相关测试 64 passed。
- Windows asyncio transport cleanup 产生 warning，但无断言失败。

当前收缩：

- 取消中的运行状态不再只存在于外层 Writer `turn/interrupted`。
- Core snapshot 可以立即表达 interrupting，后续 failed/completed 仍由 Core runtime status 接管。

当前遗留：

- `turn/interrupted` 仍作为产品控制回执保留；完全删除需要先确认前端通知、队列和 CLI 不再依赖该外层事件。
- 外层 `turn/accepted` / `turn/started` 仍承载产品输入和队列启动事实。

下一步：

- Step 4 继续：核对 `turn/accepted`、`turn/started`、`item/started` 在队列/用户输入链路中的职责，判断是否能将运行启动状态也补充到 Core status。

### 10.90 执行记录：2026-07-02 Step 4 第六切片

目标：

- 核对 `turn/accepted`、`turn/started`、`item/started` 在启动链路中的职责。
- 保留用户输入和队列产品事实，同时让运行启动状态进入 Core `RunItemEvent` / `snapshot.core`。

已完成：

- 现状判断：
  - `turn/accepted` 承载客户端幂等、输入、transcript turn、user message 绑定，仍是产品事实。
  - `item/started` 承载用户消息展示，仍是产品事实。
  - `turn/started` 承载外层启动回执，暂时保留。
- `members/writer/backend/app/app_server/queue.py`
  - `accept_turn_start()` 在原三条外层事件后追加 Core `RunItemEvent(kind="status", status="running")`。
  - 直接启动和队列分发启动都会得到 `snapshot.core.status == "running"`。
- `members/writer/backend/tests/test_writer_app_queue.py`
  - 更新启动与队列分发事件序列，断言追加 `core/runItem`。
  - 增加启动后 `snapshot.core.status == "running"` 断言。
- `members/writer/backend/tests/test_writer_app_server_protocol.py`
  - 更新 turn start response 的 snapshot seq。
  - 增加 turn start response 中 `snapshot.core.status == "running"` 断言。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/queue.py members/writer/backend/tests/test_writer_app_queue.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_runtime_bridge.py -q`
- `npm run test`，工作目录 `members/writer/frontend`
- `rg -n 'core/runItem|snapshot.*core.*status|event_id=f' members/writer/backend/app/app_server/queue.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_server_protocol.py`

验证备注：

- app-server queue / protocol / runtime bridge 相关测试 90 passed。
- Frontend app-server tests 20 passed。
- Windows asyncio transport cleanup 产生 warning，但无断言失败。

当前收缩：

- 运行启动状态不再只存在于外层 Writer turn 事件。
- Core snapshot 现在覆盖 running、interrupting、completed、failed、waiting 等主要运行状态。

当前遗留：

- 外层 `turn/accepted`、`item/started`、`turn/started` 仍作为产品输入/回执事实保留。
- 后续若要删除外层 `turn/started`，需要先确认 app-server response、CLI、queue 和前端通知不再依赖它。

下一步：

- Step 4 继续：检查外层 `turn/started` 是否还能缩成纯回执或由 operation response 替代，避免重复表达运行启动事实。

### 10.91 执行记录：2026-07-02 Step 4 第七切片

目标：

- 核对外层 `turn/started` 的依赖面。
- 在暂不删除 `turn/started` 的前提下，先收敛 runtime 启动上下文提取逻辑。
- 减少 operations/runtime 两处对 `turn/accepted` 事件结构的重复理解，为后续弱化外层 turn 事件做准备。

已完成：

- 现状判断：
  - runtime 启动真正依赖的是 `turn/accepted` 中的 `turn_id` 与 `user_message_id`。
  - `turn/started` 仍是 app-server response、通知、CLI/测试中的外层回执，暂不删除。
- `members/writer/backend/app/app_server/runtime_context.py`
  - 新增 `runtime_context_from_events()`。
  - 新增 `input_text()`。
- `members/writer/backend/app/app_server/operations.py`
  - turn start operation 改为复用 `runtime_context_from_events()` 与 `input_text()`。
  - 删除本文件重复的 `_runtime_context()` / `_input_text()`。
- `members/writer/backend/app/app_server/runtime.py`
  - queue dispatch 后启动 runtime 时复用同一上下文 helper。
  - 删除本文件重复的 `_runtime_context()` / `_input_text()`。

验证：

- `rg -n "def _runtime_context|def _input_text|runtime_context_from_events|input_text\\(" members/writer/backend/app/app_server members/writer/backend/tests -g "*.py"`
- `py -3.14 -m py_compile members/writer/backend/app/app_server/runtime_context.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/runtime.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_runtime_bridge.py -q`

验证备注：

- app-server queue / protocol / runtime bridge 相关测试 90 passed。
- Windows asyncio transport cleanup 产生 warning，但无断言失败。
- 搜索确认 operations/runtime 中重复的 `_runtime_context()` / `_input_text()` 已退出；queue 内 `_input_text()` 仍用于创建 transcript user message，不属于本片重复 runtime 启动上下文。

当前收缩：

- runtime 启动上下文读取集中到一个 helper，不再散落在 operation 和 lifecycle 两侧。
- 外层 `turn/started` 的剩余职责更清楚：目前是产品回执/通知，不是 runtime 启动上下文来源。

当前遗留：

- `turn/started` 仍未删除。
- 后续要删除或弱化它，需要先改 app-server response/notification 与 CLI 测试，不应和上下文提取混在同一切片。

下一步：

- Step 4 继续：扫描 `turn/started` 的消费者，决定是否可以把响应里的启动事实改为 Core status + explicit runtime_start，而外层事件仅保留兼容通知。

### 10.92 执行记录：2026-07-02 Step 4 第八切片

目标：

- 扫描 `turn/started` 消费者，先从 CLI 展示面降低外层 turn lifecycle 的运行事实权重。
- 避免 CLI 同时输出外层 `turn/started` phase 和 Core status phase。
- 让 CLI 的完成/失败判断继续只依赖 Core run item 终态。

已完成：

- 现状判断：
  - 前端只吃 snapshot，不直接格式化 `turn/started`。
  - CLI formatter 仍把 `turn/started` 输出为 `[phase] running`，与 Core running status 重复。
  - CLI `_is_done_event()` 仍把 `turn/interrupted` 当终态，早于 runtime Core failed status。
- `members/writer/backend/writer_cli/__main__.py`
  - `CliRunFormatter` 对 `turn/accepted`、`turn/started`、`turn/steered`、`turn/interrupted` 静默。
  - 轻量 `_format_app_server_event()` 对同一组外层 turn lifecycle 事件静默。
  - `_is_done_event()` 不再把 `turn/interrupted` 当完成；终态仍由 Core `RunItemEvent(kind="status")` 判断。
- `members/writer/backend/tests/test_writer_cli.py`
  - 更新测试：外层 `turn/started` 不再格式化为 phase。
  - 新增测试：外层 `turn/interrupted` 没有 Core status 时不作为终态。

验证：

- `py -3.14 -m py_compile members/writer/backend/writer_cli/__main__.py members/writer/backend/tests/test_writer_cli.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_cli.py members/writer/backend/tests/test_writer_app_server_protocol.py -q`

验证备注：

- Writer CLI / app-server protocol 相关测试 85 passed。
- Windows asyncio transport cleanup 产生 warning，但无断言失败。

当前收缩：

- CLI 展示层的运行状态来源继续向 Core `RunItemEvent` 收敛。
- 外层 turn lifecycle 事件保留在 ledger/通知中，但不再作为 CLI 运行状态展示和终态判断依据。

当前遗留：

- `turn/started` 仍在 app-server ledger 和响应事件列表里存在。
- 删除或进一步降级它，需要先处理 app-server response 事件序列和 queue 测试对该事件的结构性依赖。

下一步：

- Step 4 继续：检查 `accept_turn_start()` 返回事件列表中 `turn/started` 是否可从 runtime 启动上下文中完全移除，只保留为兼容通知或后续删除。

### 10.93 执行记录：2026-07-02 Step 4 第九切片

目标：

- 将 `turn/started` 从 `accept_turn_start()` 的生产事件序列中移除。
- 保留真正需要的产品事实：`turn/accepted` 负责幂等/输入/turn/message 绑定，`item/started` 负责用户消息展示。
- 让运行启动事实只由 Core `RunItemEvent(kind="status", status="running")` 表达。

已完成：

- `members/writer/backend/app/app_server/queue.py`
  - `accept_turn_start()` 不再生成外层 `turn/started`。
  - 启动序列变为 `turn/accepted`、`item/started`、`core/runItem`。
  - 队列分发启动序列变为 `queue/itemDispatched`、`turn/accepted`、`item/started`、`core/runItem`。
- `members/writer/backend/tests/test_writer_app_queue.py`
  - 更新直接启动和队列分发的事件序列断言。
  - 测试名称从 started event 改为 core status event。
- `members/writer/backend/tests/test_writer_app_server_protocol.py`
  - turn start response 的 snapshot seq 从 4 回到 3，同时继续断言 `snapshot.core.status == "running"`。

验证：

- `rg -n "turn/started|snapshot_seq\\] == 4|queue/itemDispatched.*turn/accepted|accepted_user_item_and_started" members/writer/backend/app/app_server/queue.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m py_compile members/writer/backend/app/app_server/queue.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_cli.py -q`
- `npm run test`，工作目录 `members/writer/frontend`

验证备注：

- app-server queue / protocol / runtime bridge / CLI 相关测试 121 passed。
- Frontend app-server tests 20 passed。
- Windows asyncio transport cleanup 产生 warning，但无断言失败。
- 搜索中剩余 `turn/started` 位于兼容/手写回归，不再来自 `accept_turn_start()` 生产路径。

当前收缩：

- Writer app-server 生产启动路径不再重复写外层 `turn/started` 运行事实。
- 启动状态由 `snapshot.core` 承担，产品层保留输入和用户消息事实。

当前遗留：

- reducer 仍能兼容归约历史 `turn/started`。
- 少量测试仍手写 `turn/started` 构造旧状态，用于兼容和终端状态回归。

下一步：

- Step 4 继续：检查 reducer 中 `turn/started` 兼容归约是否可以降级为历史兼容路径，并明确当前生产路径只使用 `turn/accepted` + Core status。

### 10.94 执行记录：2026-07-02 Step 4 第十切片

目标：

- 将 reducer 中的 `turn/started` 从当前 turn lifecycle 主分支中移出。
- 保留历史 ledger replay 兼容，但明确当前生产启动路径只使用 `turn/accepted` + Core running status。
- 避免测试继续把 `turn/started` 当作普通运行启动事件。

已完成：

- `members/writer/backend/app/app_server/reducer.py`
  - 当前主分支只处理 `turn/accepted`、`turn/steered`、`turn/interrupted`。
  - `turn/started` 改为单独 legacy replay 路径。
- `members/writer/backend/tests/test_writer_app_server_protocol.py`
  - 新增历史兼容测试：旧 ledger 中的 `turn/started` 仍可 replay 为 running turn。
  - 将非兼容目的的手写启动事件改为当前主线 `turn/accepted`。
  - 更新 terminal interrupt 回归中的事件序列断言。

验证：

- `rg -n "turn/started|legacy_turn_started|replays_legacy" members/writer/backend/app/app_server/reducer.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_cli.py`
- `py -3.14 -m py_compile members/writer/backend/app/app_server/reducer.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_queue.py -q`

验证备注：

- app-server protocol / queue 相关测试 65 passed。
- Windows asyncio transport cleanup 产生 warning，但无断言失败。
- 搜索确认 `turn/started` 只剩 reducer legacy 分支、一个历史兼容测试、CLI 静默测试。

当前收缩：

- `turn/started` 不再位于当前 reducer lifecycle 主线。
- 当前生产路径语义更清楚：产品启动事实为 `turn/accepted`，运行启动状态为 Core `core/runItem` running。

当前遗留：

- 仍保留 `turn/started` 历史 replay 兼容，避免旧 ledger 无法还原。
- CLI 仍有外层 turn lifecycle 静默测试覆盖旧事件不进入展示。

下一步：

- Step 4 继续：审计外层 `turn/accepted`、`turn/steered`、`turn/interrupted` 的剩余职责，确认哪些是产品事实，哪些还能继续下沉到 Core status / request state。

### 10.95 执行记录：2026-07-02 Step 4 第十一切片

目标：

- 收敛 `turn/steered` 的语义：它是运行中的用户指导输入，不是运行状态事件。
- 去掉 guidance 事件里的 `"status": "running"`，避免外层 Writer event 继续承载运行状态。
- 保留现有交互：前端/CLI 仍可发送指导，后端仍校验 active turn 并通知客户端。

已完成：

- `members/writer/backend/app/app_server/queue.py`
  - `accept_turn_steer()` 生成的 `turn/steered` payload 改为只包含 `type` 和 `input`。
  - active turn 校验仍通过 `snapshot.core` 优先判断，终态 Core turn 会让 guidance 过期。
- `members/writer/backend/app/app_server/reducer.py`
  - `turn/steered` 从当前运行 lifecycle 主分支移出。
  - 新增 guidance 归约路径，只记录输入事实，不主动刷新 thread running 状态。
- `members/writer/backend/tests/test_writer_app_queue.py`
  - 增加断言：`turn/steered` payload 不再包含运行状态。

验证：

- `rg -n 'turn/steered|_apply_turn_guidance|payload=\{\"type\": \"turn\", \"status\": \"running\", \"input\"' members/writer/backend/app/app_server members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m py_compile members/writer/backend/app/app_server/queue.py members/writer/backend/app/app_server/reducer.py members/writer/backend/tests/test_writer_app_queue.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_server_protocol.py -q`

验证备注：

- app-server queue / protocol 相关测试 65 passed。
- Windows asyncio transport cleanup 产生 warning，但无断言失败。
- 搜索确认旧的 `turn/steered` running payload 已退出当前 app-server 代码。

当前收缩：

- 外层 `turn/steered` 不再表达运行状态。
- 当前运行状态继续由 Core status 负责；指导输入仍作为产品事实保留在 Writer ledger。

当前遗留：

- `turn/accepted` 仍带 `"status": "running"`，因为当前 UI/历史 snapshot 仍依赖 outer turns 中存在 active turn；后续应将 UI active turn selector 改为 Core-first 后再继续收缩。
- `turn/interrupted` 仍作为产品取消回执存在，同时已有 Core interrupting status。

下一步：

- Step 4 继续：先把前端 active turn 判断改为 Core-first，再评估 `turn/accepted` 的 outer running 状态是否可以弱化为纯输入/绑定事实。

### 10.96 执行记录：2026-07-02 Step 4 第十二切片

目标：

- 将前端发送 guidance 时的 active turn 判断改为 Core-first。
- 避免 Core turn 已完成/失败后，前端仍因 outer turn 残留 running 而向已终止 turn 发送指导。
- 为后续弱化 `turn/accepted` 的 outer running 状态铺路。

已完成：

- `members/writer/frontend/src/views/CoreWorkbenchView.vue`
  - `latestActiveAppServerTurnId()` 改为优先读取 `snapshot.core.turns[turn_id].status`。
  - outer turn status 仅作为没有 Core turn 状态时的兼容兜底。
  - 排序仍使用 outer turn seq，保持现有 UI 行为。

验证：

- `npm run test`，工作目录 `members/writer/frontend`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_server_protocol.py -q`

验证备注：

- Frontend app-server tests 20 passed。
- app-server queue / protocol 相关测试 65 passed。
- Windows asyncio transport cleanup 产生 warning，但无断言失败。

当前收缩：

- 前端 active turn 选择不再只信 outer Writer turn 状态。
- `turn/steered` 过期判断和 UI 发送判断都开始以 Core turn 状态为准。

当前遗留：

- `turn/accepted` 仍写 outer `"status": "running"`；前端已具备 Core-first 兜底后，下一步可以继续评估是否把它弱化成输入/绑定事实。
- 当前文件存在用户已有 thinking UI 未提交改动；本切片提交时只应暂存 active turn 判断相关 hunk。

下一步：

- Step 4 继续：评估 `turn/accepted` 中 outer running 状态的依赖面，判断是否能保留 turn 记录但不再由 outer event 表达运行状态。

### 10.97 执行记录：2026-07-02 Step 4 第十三切片

目标：

- 弱化 `turn/accepted`：保留输入、work root、transcript turn、user message 绑定事实，不再在事件 payload 中表达 running。
- 让生产启动运行状态只由 Core `core/runItem` running 表达。
- 保留 reducer 对 outer turns 的 running 兜底，避免一次性破坏旧 snapshot/UI。

已完成：

- `members/writer/backend/app/app_server/queue.py`
  - `accept_turn_start()` 生成的 `turn/accepted` payload 移除 `"status": "running"`。
  - Core running status 事件仍紧随 `turn/accepted` / `item/started` 之后写入。
- `members/writer/backend/tests/test_writer_app_queue.py`
  - 增加断言：生产 `turn/accepted` payload 不再包含 `status`。
- `members/writer/backend/tests/test_writer_app_server_protocol.py`
  - 将非兼容目的的手写 `turn/accepted` payload 改成无 status。
- `members/writer/backend/tests/test_writer_app_event_ledger.py`
  - 将 ledger replay 测试的 `turn/accepted` payload 改成无 status。

验证：

- `rg -n 'turn/accepted.*status|payload=\{\"type\": \"turn\", \"status\": \"running\"\}|\"status\": \"running\"' members/writer/backend/app/app_server/queue.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_event_ledger.py`
- `py -3.14 -m py_compile members/writer/backend/app/app_server/queue.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_event_ledger.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_event_ledger.py -q`

验证备注：

- app-server queue / protocol / ledger 相关测试 70 passed。
- Windows asyncio transport cleanup 产生 warning，但无断言失败。
- 搜索确认当前生产和相关测试不再把 `turn/accepted` payload 写成 running。

当前收缩：

- 外层 `turn/accepted` 事件不再承载运行状态。
- 运行启动事实只由 Core status event 表达；`turn/accepted` 回到产品输入/绑定事实。

当前遗留：

- reducer 仍会为 outer turn snapshot 设置 running 兜底，服务旧 UI/历史状态。
- 若要继续收缩 outer snapshot `status`，需要审计 `snapshot.status` 与 `turns[*].status` 的所有 UI/CLI 消费。

下一步：

- Step 4 继续：审计 `snapshot.status` / outer turn status 的剩余消费，决定是否可把线程级运行状态也改为 Core-first selector。

### 10.98 执行记录：2026-07-02 Step 4 第十四切片

目标：

- 将 Writer app snapshot 的线程级 `status` 同步到 Core runtime status。
- 避免 Core 已完成/失败后，outer `snapshot.status` 仍停留在 running。
- 修正晚到 `turn/interrupted` 对 Core 终态 turn 的误覆盖。

已完成：

- `members/writer/backend/app/app_server/reducer.py`
  - 应用 `core/runItem` 后同步 outer `state.status`。
  - Core `failed` / `cancelled` / `error` 映射为 outer `failed`。
  - Core `idle` / `running` / `waiting` / `completed` 直接同步。
  - `turn/interrupted` 判断终态时改为 Core turn status 优先，避免 Core failed/completed 后被外层 interrupt 拉回 running。
- `members/writer/backend/tests/test_writer_app_server_protocol.py`
  - 更新 Core failed 后的 outer status 断言。
  - 增强晚到 interrupt 回归：Core failed 后 outer status 仍为 failed。
- `members/writer/backend/tests/test_writer_app_queue.py`
  - 更新 Core completed 后的 outer snapshot status 断言。

验证：

- `py -3.14 -m py_compile members/writer/backend/app/app_server/reducer.py members/writer/backend/tests/test_writer_app_server_protocol.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py::test_backend_reducer_late_interrupt_does_not_resurrect_completed_turn -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_event_ledger.py -q`

验证备注：

- 单用例回归 1 passed。
- app-server queue / protocol / ledger 相关测试 70 passed。
- Windows asyncio transport cleanup 产生 warning，但无断言失败。

当前收缩：

- 线程级 outer `snapshot.status` 也开始跟随 Core runtime status。
- 旧外层 interrupt 事件不再能覆盖 Core 终态。

当前遗留：

- outer `turns[*].status` 仍保留 running 兜底；当前前端 active turn 已 Core-first，因此风险下降。
- `turn/interrupted` 事件本身仍作为取消回执/通知存在。

下一步：

- Step 4 继续：扫描剩余外层运行状态写入点，确认是否只剩兼容 snapshot 字段；随后评估 Step 4 是否可进入收尾验收。

### 10.99 执行记录：2026-07-02 Step 4 第十五切片

目标：

- 去掉外层 `turn/interrupted` 事件 payload 中的运行状态。
- 保留取消产品事实：turn、reason、通知/回执。
- 继续由 Core status event 表达 interrupting。

已完成：

- `members/writer/backend/app/app_server/operations.py`
  - `turn/interrupted` payload 从 `{"type": "turn", "status": "interrupting", "reason": "user_interrupt"}` 收缩为 `{"type": "turn", "reason": "user_interrupt"}`。
  - Core `RunItemEvent(kind="status", status="interrupting")` 保持不变。
- `members/writer/backend/tests/test_writer_app_server_protocol.py`
  - 手写 late interrupt 事件改为当前 payload 形态。
- `members/writer/backend/tests/test_writer_cli.py`
  - 外层 turn lifecycle 静默测试改为当前 interrupt payload 形态。

验证：

- `rg -n 'turn/interrupted.*status|payload=\{\"type\": \"turn\", \"status\": \"interrupting\"|\"method\": \"turn/interrupted\"' members/writer/backend/app/app_server/operations.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_cli.py`
- `py -3.14 -m py_compile members/writer/backend/app/app_server/operations.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_cli.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_cli.py -q`
- `npm run test`，工作目录 `members/writer/frontend`

验证备注：

- 后端 app-server protocol / queue / CLI 相关测试 96 passed。
- Frontend app-server tests 20 passed。
- Windows asyncio transport cleanup 产生 warning，但无断言失败。
- 搜索确认外层 `turn/interrupted` 不再携带 interrupting status。

当前收缩：

- `turn/accepted`、`turn/steered`、`turn/interrupted` 当前生产 payload 均不再承载运行状态。
- 启动、取消、完成、失败、等待等运行状态由 Core `core/runItem` / `snapshot.core` 表达。
- outer `snapshot.status` 已同步 Core status，服务旧消费者。

当前遗留：

- outer `turns[*].status` 仍保留 reducer 兜底字段，用于历史 replay / UI 兼容。
- `item/started` 仍表示产品层 user message 展示事实，其中 userMessage status completed 属于消息事实，不是 runtime 状态。
- `thread/started` 仍有 `"status": "idle"`，属于 thread 初始化回执，未纳入运行状态收缩范围。

下一步：

- Step 4 收尾审计：逐项核对 message / tool / status / usage / artifact 是否均可由 `snapshot.core` 还原；若通过，进入 Step 5 前端去旧投影。

### 11.00 执行记录：2026-07-02 Step 4 收尾审计

目标：

- 证明 Step 4 的验收条件不是只靠局部搜索，而是由 Core snapshot、Writer runtime bridge、前端 selector 三层测试覆盖。
- 逐项核对 message / tool / status / usage / artifact 是否均可由 `snapshot.core` 还原。
- 修正仍保护旧 outer status 语义的测试。

审计结果：

- message：
  - Core reducer 覆盖 message delta 累积、顺序还原、幂等 replay。
  - Writer runtime bridge 覆盖 `runtime.reply_delta` / `runtime.part` 持久化为 `core/runItem` 后只进入 `snapshot.core.items`。
  - 前端 selector 覆盖 canonical core messages 可在没有 outer app projection items 时渲染。
- tool：
  - Core reducer 覆盖 `tool_call` / `tool_result` 的 item order、parent item、content。
  - Writer runtime bridge 覆盖 runtime tool started / finished 写入 `core/runItem`，outer `snapshot.items` 保持空。
  - 前端 selector 覆盖 canonical core tool calls 可渲染。
- status：
  - Core reducer 覆盖 running / waiting / completed / failed 等状态归约。
  - Writer reducer 已将 outer `snapshot.status` 同步到 Core status。
  - 修正 `test_runtime_bridge_persists_status_as_core_fact`：outer `snapshot.status` 应为 `completed`，不再是旧的 `idle`。
- usage：
  - Core reducer 覆盖 usage merge 与 replace。
  - Writer runtime bridge 覆盖 `runtime.usage` 与 `runtime.metrics` 写入 `snapshot.core.turns[*].usage`，outer `turns` 保持空。
  - 前端 selector 覆盖从 canonical core usage 读取 process metrics。
- artifact：
  - Core reducer 覆盖 artifact index 与 item artifact 关联。
  - Writer runtime bridge 覆盖 tool artifact / explicit artifact 写入 `snapshot.core.artifacts`，outer `snapshot.artifacts` 保持空。
  - 前端 selector 覆盖 canonical core artifacts 挂到对应 process item。

已完成：

- `members/writer/backend/tests/test_writer_app_runtime_bridge.py`
  - 将 runtime status bridge 测试中 outer `snapshot.status` 断言从 `idle` 更新为 `completed`，与 10.98 的 Core status 同步一致。

验证：

- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_cli.py -q`
- `py -3.14 -m pytest core/tests/test_run_item_snapshot.py -q`
- `npm run test`，工作目录 `members/writer/frontend`

验证备注：

- Writer app-server / runtime bridge / queue / protocol / CLI 相关测试 122 passed。
- Core snapshot tests 12 passed。
- Frontend app-server tests 20 passed。
- Windows asyncio transport cleanup 产生 warning，但无断言失败。

Step 4 结论：

- Step 4 当前验收条件通过：message / tool / status / usage / artifact 均已有 `snapshot.core` 还原路径和测试覆盖。
- 外层 Writer AppEvent 当前保留产品输入、队列、取消回执、审批回执、user message 展示事实；普通运行事实已由 Core `core/runItem` 承担。

下一步：

- 进入 Step 5：前端去旧投影，优先清理 `runtime/transcript.ts` 的主线导出和旧 fallback 语义，让 UI 只消费 snapshot selectors / canonical parts。

### 11.01 执行记录：2026-07-02 Step 5 第一切片

目标：

- 清理 `runtime/transcript.ts` 的主线导出。
- 保留当前 UI 仍需要的队列输入类型，但把它从旧 transcript 类型文件中拆出。
- 让 `types/index.ts` 不再把旧 transcript snapshot / turn / block 类型暴露为主线公共类型。

已完成：

- `members/writer/frontend/src/runtime/queue.ts`
  - 新增 `WriterQueuedInput` 类型，作为队列托盘当前 UI 类型来源。
- `members/writer/frontend/src/runtime/transcript.ts`
  - 移除 `WriterQueuedInput`，该文件降级为旧 transcript 结构定义，不再夹带主线队列类型。
- `members/writer/frontend/src/types/index.ts`
  - 停止导出 `WriterTranscriptSnapshot`、`WriterTranscriptTurn`、`WriterTranscriptBlock`、`WriterTranscriptModelCall`、`WriterTranscriptMetrics`、`WriterTranscriptArtifact`。
  - 改为只从 `runtime/queue.ts` 导出 `WriterQueuedInput`。

验证：

- `rg -n "WriterTranscript|runtime/transcript|../runtime/transcript|WriterQueuedInput" members/writer/frontend/src members/writer/frontend/tests -g '*.ts' -g '*.vue'`
- `npm run test`，工作目录 `members/writer/frontend`

验证备注：

- Frontend app-server tests 20 passed。
- 搜索确认旧 transcript 类型只剩 `runtime/transcript.ts` 自身定义；主线 `types/index.ts` 不再导出旧 transcript 类型。
- `WriterQueuedInput` 仍通过 `types/index.ts` 暴露，但来源已是 `runtime/queue.ts`。

当前收缩：

- 前端主线公共类型入口不再推广旧 transcript snapshot。
- 队列 UI 与旧 transcript 类型拆开，为后续删除或转移 `runtime/transcript.ts` 做准备。

当前遗留：

- `runtime/transcript.ts` 文件仍存在，但已无主线导出/消费者。
- 后续应继续扫描旧 content fallback 和 `runtime/transcript.ts` 是否可转入审计目录或删除。

下一步：

- Step 5 继续：检查 ChatThread / selector 中是否仍有旧 Writer runtime event 或旧 content fallback，优先收敛到 canonical snapshot parts。

### 11.02 执行记录：2026-07-02 Step 5 第二切片

目标：

- 清理前端 selector / Workbench 对旧 outer runtime metrics 的 fallback。
- 运行指标只从 canonical Core usage 经 selector 输出的 `processMetrics` 进入 UI。
- 保留测试夹具中的旧 `runtime_metrics`，但只用于证明旧字段会被忽略。

已完成：

- `members/writer/frontend/src/appServer/selectors.ts`
  - `selectChatMessages()` 不再从 outer `turn.runtime_metrics` / `turn.processMetrics` 读取运行指标。
  - assistant message metadata 只由 `state.core.turns[*].usage` 生成。
- `members/writer/frontend/src/views/CoreWorkbenchView.vue`
  - `latestRuntimeMetrics` 不再读取 `meta.runtime_metrics` 旧字段，只读取 selector 产出的 `meta.processMetrics`。
- `members/writer/frontend/tests/appServer/selectors.test.ts`
  - 将旧 metrics 测试改为断言 outer `runtime_metrics` 被忽略。
  - 保留 canonical core usage 测试，证明运行指标仍从 `snapshot.core` 渲染。

验证：

- `rg -n "meta\\.runtime_metrics|runtime_metrics|processMetrics" members/writer/frontend/src/appServer members/writer/frontend/src/views/CoreWorkbenchView.vue members/writer/frontend/tests/appServer`
- `npm run test`，工作目录 `members/writer/frontend`

验证备注：

- Frontend app-server tests 20 passed。
- 搜索确认生产代码不再读取 `runtime_metrics`；该字段仅保留在测试夹具中，用来证明旧 outer metrics 被忽略。

当前收缩：

- UI 运行指标链路已从 outer turn metrics 收敛到 Core usage。
- Workbench 不再需要旧 Writer runtime metrics fallback。

当前遗留：

- selector 仍包含 `dynamicToolCall` + `content === "runtime.part"` 的旧脏投影过滤，用于防止历史坏数据进入 UI；后续需要判断是保留为数据卫生保护，还是随旧投影删除。

下一步：

- Step 5 继续：审计并处理 selector 中 `runtime.part` 脏投影过滤和旧 outer app projection item fallback。

### 11.03 执行记录：2026-07-02 Step 5 第三切片

目标：

- 移除前端 selector 对旧 outer runtime projection items 的主线 fallback。
- 保留 outer `userMessage` 作为产品输入事实；运行项必须来自 canonical Core item。
- 删除 `runtime.part` 脏投影特判，让旧 runtime projection 通过更清楚的 outer runtime item 丢弃规则处理。

已完成：

- `members/writer/frontend/src/appServer/selectors.ts`
  - `selectChatMessages()` 的 item 读取从 `canonicalItemForId(...) ?? state.items?.[itemId]` 改为 `canonicalItemForId(...) ?? outerProductItemForId(...)`。
  - 新增 `outerProductItemForId()`，只允许 outer `userMessage` 进入 chat selector。
  - 移除 `dynamicToolCall` + `content === "runtime.part"` 的特殊过滤。
- `members/writer/frontend/tests/appServer/selectors.test.ts`
  - 将 approval、retry status、tool artifact 等运行项测试改为 canonical Core item / request / artifact。
  - 将旧脏投影测试改为断言所有 outer runtime projection item 被丢弃，而不是只过滤 `runtime.part` 字符串。
  - 将旧 outer runtime metrics 测试改为断言不会产生 assistant message。

验证：

- `npm run test`，工作目录 `members/writer/frontend`
- `rg -n "runtime\\.part|state\\.items\\?\\[itemId\\]|outer runtime|dynamicToolCall.*content" members/writer/frontend/src/appServer/selectors.ts members/writer/frontend/tests/appServer/selectors.test.ts`

验证备注：

- Frontend app-server tests 20 passed。
- 搜索确认生产 selector 不再包含 `runtime.part` 特判，也不再直接 fallback 到 `state.items?.[itemId]`。
- `runtime.part` 只剩在测试夹具中，用来证明旧 outer runtime projection 被丢弃。

当前收缩：

- Chat selector 主线只接受 canonical Core runtime item；outer app item 只保留 user message 产品事实。
- 前端不再需要理解旧 Writer runtime projection item 的局部坏形态。

当前遗留：

- `runtime/transcript.ts` 文件仍存在但无主线导出/消费者。
- `appServer/protocol.ts` 仍保留 outer `WriterAppItem` 类型，因为 userMessage、queue、requests 等产品事实仍需要类型承载。

下一步：

- Step 5 继续：确认 `ChatThread` 接收的 parts 全部来自 selectors/canonical mapping；若通过，评估是否删除或归档 `runtime/transcript.ts`。

### 11.04 执行记录：2026-07-02 Step 5 第四切片

目标：

- 删除已无主线导出/消费者的 `runtime/transcript.ts`。
- 确认 ChatThread 输入链路已由 `selectChatMessages()` 和 canonical item mapping 承担。

已完成：

- `members/writer/frontend/src/runtime/transcript.ts`
  - 删除旧 transcript snapshot / turn / block 类型文件。
- 现状确认：
  - `CoreWorkbenchView.vue` 通过 `selectChatMessages(appServerStore.state)` 构造 `CoreMessage`。
  - ChatThread 接收的是 selector 输出后的 `messages` / `parts`，不直接理解旧 transcript 类型。

验证：

- `rg -n "WriterTranscript|runtime/transcript|transcript.ts" members/writer/frontend/src members/writer/frontend/tests -g '*.ts' -g '*.vue'`
- `npm run test`，工作目录 `members/writer/frontend`

验证备注：

- 引用搜索无结果。
- Frontend app-server tests 20 passed。

当前收缩：

- 前端旧 transcript 类型面已从主线代码中删除。
- Step 5 的第一项“清理 `runtime/transcript.ts` 的主线导出”已完成到删除文件。

当前遗留：

- `appServerItemToPart()` 仍在 Workbench 中负责 Core item 到 ChatThread part 的最后映射。
- 需要继续确认 approval request / resolved request 的 request state 查找是否 Core-first。

下一步：

- Step 5 继续：让 `appServerItemToPart()` 的 approval request state 查找使用 Core-first selector 语义，避免只看 outer `state.requests`。

### 11.05 执行记录：2026-07-02 Step 5 第五切片

目标：

- 让 ChatThread decision part 的 request state 查找改为 Core-first。
- 避免 Core approval request / response 已进入 `snapshot.core.requests` 后，Workbench 仍只读取 outer `state.requests`。

已完成：

- `members/writer/frontend/src/views/CoreWorkbenchView.vue`
  - `appServerItemToPart()` 不再直接读 `appServerStore.state?.requests?.[requestId]`。
  - 新增 `requestStateForId()`，优先读取 `appServerStore.state?.core?.requests?.[requestId]`，再兜底 outer requests。
  - `WriterAppRequestState` 类型从 `appServer/protocol` 引入，用于 request state helper。

验证：

- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`

验证备注：

- Frontend app-server tests 20 passed。
- Frontend production build 通过。
- Vite 输出 chunk size / plugin timings warning，非断言失败。

当前收缩：

- ChatThread decision part 的 resolved/waiting 状态可以从 canonical Core request state 驱动。
- outer requests 仅作为兼容兜底。

当前遗留：

- Workbench 文件存在用户已有 thinking UI 未提交改动；本切片提交时只应暂存 request lookup 相关 hunk。

下一步：

- Step 5 收尾审计：确认前端实时 UI 已只通过 snapshot selectors / canonical parts 展示刷新、审批等待、工具结果和最终回复。

### 11.06 执行记录：2026-07-02 Step 5 收尾审计

目标：

- 验证 Step 5 的验收条件：刷新、审批等待、工具结果、最终回复都来自 snapshot selectors / canonical parts。
- 确认旧 transcript 和旧 outer runtime projection 不再参与实时 UI。

审计结果：

- 刷新：
  - app-server response / snapshot hydrate 测试覆盖 response snapshot 为权威状态来源。
  - Workbench 通过 `selectChatMessages(appServerStore.state)` 构造消息，不直接读取旧 transcript。
- 审批等待：
  - `selectApprovalCards()` 优先读取 `state.core.requests`。
  - `appServerItemToPart()` 的 request state 查找已改为 Core-first，outer requests 仅兜底。
- 工具结果：
  - selector 测试覆盖 canonical core tool calls / tool result artifacts 在没有 outer app items 时可渲染。
  - selector 已删除 outer runtime projection fallback，只保留 outer `userMessage` 产品事实。
- 最终回复：
  - selector 测试覆盖 canonical core message / thinking items 在没有 outer app projection items 时可渲染。
  - selector 测试覆盖 canonical core runtime items 优先于 outer app projection items。
- 旧 transcript：
  - `runtime/transcript.ts` 已删除。
  - 搜索 `WriterTranscript|runtime/transcript|transcript.ts` 无结果。
- 旧 metrics / runtime projection：
  - 生产代码不再读取 `runtime_metrics`。
  - 测试夹具保留旧字段，只用于证明 outer runtime metrics / projection items 被忽略。

验证：

- `rg -n "runtime/transcript|WriterTranscript|runtime_metrics|state\\.items\\?\\[itemId\\]|selectChatMessages|selectApprovalCards|canonical core|outer runtime|state\\.core|core\\?\\.requests|core\\?\\.items|core\\?\\.turns" members/writer/frontend/src members/writer/frontend/tests/appServer -g '*.ts' -g '*.vue'`
- `npm run test`，工作目录 `members/writer/frontend`
- `npm run build`，工作目录 `members/writer/frontend`

验证备注：

- Frontend app-server tests 20 passed。
- Frontend production build 通过。
- Vite 输出 chunk size warning，非断言失败。

Step 5 结论：

- Step 5 当前验收条件通过：实时 UI 已通过 snapshot selectors / canonical parts 展示刷新、审批、工具结果和最终回复。
- 旧 transcript 类型和旧 outer runtime projection 主线已删除或被明确丢弃。

当前遗留：

- `appServer/protocol.ts` 仍保留 outer app item / queue / request 类型，用于产品事实和兼容 snapshot。
- Workbench 文件存在用户已有 thinking UI 未提交改动，不属于本步骤提交范围。

下一步：

- 进入 Step 6：LLM / Provider 下沉 Core。先审计 Writer 当前 provider parser / adapter profile 入口，再设计最小 Core adapter 接管切片。

### 11.07 执行记录：2026-07-02 Step 6 第一切片

目标：

- 将 adapter profile 的纯解析、匹配、payload patch、stream chunk 归一化从 Writer 私有模块下沉到 Core。
- Writer 仅保留 profile 文件搜索目录、appdata / runtime resource 发现和缓存包装。
- 不改变现有 Writer 调用入口，降低迁移风险。

已完成：

- `core/src/lamtools_core/llm/profiles.py`
  - 新增 Core profile helper 模块。
  - 承接 JSONC 解析、profile dirs 加载、deep merge、path lookup、request/thinking payload patch、endpoint/response path、profile resolve、stream chunk normalization。
  - 修正原有顺序问题：自定义 finish path 与 usage 同时出现时优先生成 `done`，不再被 standalone usage 分支吞掉。
- `members/writer/backend/app/utils/llm_adapter_profiles.py`
  - 收缩为 Writer wrapper。
  - 保留 builtin/resource/appdata/env profile 目录发现和 `load_adapter_profiles()` 缓存。
  - 原有函数名继续 re-export，现有 `llm_client.py` / `core_kernel_adapter.py` 调用路径不变。
- `core/tests/test_llm_profiles.py`
  - 新增 Core 级 profile 测试，覆盖 JSONC、extra profile resolve、thinking payload、profile stream path。

验证：

- `py -3.14 -m py_compile core/src/lamtools_core/llm/profiles.py members/writer/backend/app/utils/llm_adapter_profiles.py core/tests/test_llm_profiles.py members/writer/backend/tests/test_llm_adapter_profiles.py`
- `py -3.14 -m pytest core/tests/test_llm_profiles.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_llm_adapter_profiles.py -q`
- `py -3.14 -m pytest core/tests/test_llm_helpers.py core/tests/test_llm_adapter.py -q`

验证备注：

- Core profile tests 3 passed。
- Writer adapter profile wrapper tests 6 passed。
- Core LLM helper / adapter tests 102 passed。
- 初次混跑 Core tests 时遇到 pytest `tests.*` 导入名冲突，改为按文件分跑；无业务断言失败。

当前收缩：

- provider profile 语义已进入 Core。
- Writer provider 模块只保留资源定位包装，后续可继续把 `llm_client.py` 的 response path / stream parse 调用改为 Core adapter 入口。

当前遗留：

- Writer `llm_client.py` 仍负责 aiohttp transport、provider-specific endpoint 选择、non-stream response parsing。
- Writer `core_kernel_adapter.py` 仍直接调用 adapter profile helpers 组装 streaming 请求。

下一步：

- Step 6 继续：把 non-stream response parsing 或 streaming request assembly 的下一段迁到 Core adapter，进一步减少 Writer 对 provider payload path 的直接理解。

### 11.08 执行记录：2026-07-02 Step 6 第二切片

目标：

- 将 OpenAI-compatible non-stream response 的 profile path 解析下沉到 Core。
- Writer 保留 transport 和本地响应对象映射，不再直接理解 `non_stream_response` 的 content / reasoning / tool_calls / finish_reason / usage path。

已完成：

- `core/src/lamtools_core/llm/profiles.py`
  - 新增 `normalize_response_with_profile()`，统一按 adapter profile 读取非流式响应字段。
  - usage 归一化改为复用 Core `normalize_usage()`，避免只支持 `prompt_tokens` / `completion_tokens` 的窄字段集。
- `members/writer/backend/app/utils/llm_adapter_profiles.py`
  - 继续作为 Writer wrapper re-export Core helper。
- `members/writer/backend/app/utils/llm_client.py`
  - OpenAI-compatible 非流式响应改为调用 Core profile normalizer。
  - 删除 Writer 私有的 response path / get_path / usage parse 逻辑。
- `core/tests/test_llm_profiles.py`
  - 新增 profile 自定义非流式响应路径测试，覆盖 content、reasoning、tool calls、finish reason、usage。

验证：

- `py -3.14 -m py_compile core/src/lamtools_core/llm/profiles.py members/writer/backend/app/utils/llm_adapter_profiles.py members/writer/backend/app/utils/llm_client.py core/tests/test_llm_profiles.py members/writer/backend/tests/test_writer_llm_client.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_llm_client.py -q`
- `py -3.14 -m pytest core/tests/test_llm_profiles.py -q`
- `py -3.14 -m pytest tests/test_llm_helpers.py tests/test_llm_adapter.py -q`，工作目录 `core`
- `py -3.14 -m pytest members/writer/backend/tests/test_llm_adapter_profiles.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_service.py -q`

验证备注：

- Writer LLM client tests 2 passed。
- Core profile tests 4 passed。
- Core LLM helper / adapter tests 102 passed。
- Writer adapter profile wrapper tests 6 passed。
- Writer runtime bridge / service tests 49 passed。
- 初次验证发现 usage alias 回归：`input_tokens` / `output_tokens` 被归零；已通过 Core `normalize_usage()` 修复并补跑通过。
- Writer runtime bridge / service 测试存在 Windows asyncio transport cleanup warning，非断言失败。

当前收缩：

- Writer 已不再直接解析 OpenAI-compatible 非流式响应路径。
- Provider response path 语义进一步进入 Core profile 主线。

当前遗留：

- Writer `llm_client.py` 仍负责 aiohttp transport、endpoint 选择、stream request assembly、Anthropic 非 OpenAI-compatible 响应映射。
- Writer `core_kernel_adapter.py` 仍直接调用 adapter profile helpers 组装 streaming 请求。

下一步：

- Step 6 继续：抽出 Core profile request assembly helper，统一 endpoint + payload patch + thinking payload，减少 Writer streaming / non-stream 两条路径对 provider payload 细节的重复理解。

### 11.09 执行记录：2026-07-02 Step 6 第三切片

目标：

- 将 OpenAI-compatible 请求装配下沉到 Core profile helper。
- 统一 endpoint、base payload、profile request body、unsupported fields、thinking payload、stream options 的组合逻辑。
- Writer 继续保留 HTTP transport、错误处理、SSE 行读取和 Anthropic 专用分支。

已完成：

- `core/src/lamtools_core/llm/profiles.py`
  - 新增 `build_profiled_openai_request()`。
  - Core 统一生成 `{endpoint, payload}`，并在同一入口应用 request body、unsupported fields、thinking payload 和 stream options。
- `members/writer/backend/app/utils/llm_adapter_profiles.py`
  - re-export Core request assembly helper。
- `members/writer/backend/app/utils/llm_client.py`
  - 非流式 OpenAI-compatible 请求改为调用 Core request assembly helper。
  - 流式 OpenAI-compatible 请求改为调用同一 Core request assembly helper。
  - 删除 Writer 私有 thinking payload helper。
  - Anthropic endpoint 仍保留现有 profile endpoint 兼容入口，未纳入本切片。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - Core bridge streaming 路径改为调用 Core request assembly helper。
  - 保留 Writer 侧 stream transport、HTTP 错误处理、SSE parse、tool call delta 聚合。
- `core/tests/test_llm_profiles.py`
  - 新增 request assembly 测试，覆盖自定义 endpoint、body 模板、unsupported fields、thinking payload、stream options。

验证：

- `py -3.14 -m py_compile core/src/lamtools_core/llm/profiles.py core/tests/test_llm_profiles.py members/writer/backend/app/utils/llm_adapter_profiles.py members/writer/backend/app/utils/llm_client.py members/writer/backend/app/core/writer/core_kernel_adapter.py`
- `py -3.14 -m pytest core/tests/test_llm_profiles.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_llm_client.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_llm_adapter_profiles.py -q`
- `py -3.14 -m pytest tests/test_llm_helpers.py tests/test_llm_adapter.py -q`，工作目录 `core`

验证备注：

- Core profile tests 5 passed。
- Writer LLM client tests 2 passed。
- Writer Core kernel adapter tests 172 passed。
- Writer adapter profile wrapper tests 6 passed。
- Core LLM helper / adapter tests 102 passed。

当前收缩：

- Writer OpenAI-compatible 非流式、Writer OpenAI-compatible 流式、Core bridge 流式三条路径已共用 Core request assembly。
- Writer 不再直接组合 OpenAI-compatible endpoint + profile body + thinking payload。

当前遗留：

- Writer 仍负责 aiohttp / httpx transport、SSE 行读取、stream event 聚合、Anthropic 专用 payload / response 映射。
- Writer wrapper 仍 re-export 部分低层 profile helpers，供旧测试和未迁完入口使用。

下一步：

- Step 6 收尾审计：搜索 Writer provider 入口，确认 LLM/provider profile 语义的主线边界；判断是否继续迁 Anthropic 专用分支，或将其标为 Writer 单产品兼容遗留。

### 11.10 执行记录：2026-07-02 Step 6 第四切片

目标：

- 将 Anthropic-compatible 的请求和响应纯映射下沉到 Core profile helper。
- 让 Writer Anthropic 分支只保留鉴权 header、HTTP transport 和错误处理。
- 保持现有 endpoint fallback 行为不变，避免改变用户已有 base URL 配置语义。

已完成：

- `core/src/lamtools_core/llm/profiles.py`
  - 新增 `build_profiled_anthropic_request()`。
  - Core 统一处理 system message 抽取、messages body、thinking payload、profile endpoint。
  - 新增 `normalize_anthropic_response_with_profile()`，统一处理 content blocks、thinking blocks、usage alias、stop reason。
- `members/writer/backend/app/utils/llm_adapter_profiles.py`
  - re-export Anthropic request / response helper。
- `members/writer/backend/app/utils/llm_client.py`
  - Anthropic 分支改为调用 Core profile helper。
  - 删除 Writer 私有的 system prompt 拆分、thinking body 组装、content block 解析。
- `core/tests/test_llm_profiles.py`
  - 新增 Anthropic request / response profile 测试。
- `members/writer/backend/tests/test_writer_llm_client.py`
  - 新增 Writer Anthropic 薄集成测试，覆盖 URL、system、thinking、header、usage 和 stop reason。

验证：

- `py -3.14 -m py_compile core/src/lamtools_core/llm/profiles.py core/tests/test_llm_profiles.py members/writer/backend/app/utils/llm_adapter_profiles.py members/writer/backend/app/utils/llm_client.py members/writer/backend/tests/test_writer_llm_client.py`
- `py -3.14 -m pytest core/tests/test_llm_profiles.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_llm_client.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_llm_adapter_profiles.py -q`
- `py -3.14 -m pytest tests/test_llm_helpers.py tests/test_llm_adapter.py -q`，工作目录 `core`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`

验证备注：

- Core profile tests 6 passed。
- Writer LLM client tests 3 passed。
- Writer adapter profile wrapper tests 6 passed。
- Core LLM helper / adapter tests 102 passed。
- Writer Core kernel adapter tests 172 passed。

当前收缩：

- OpenAI-compatible 和 Anthropic-compatible 的 request / response profile 语义都已进入 Core。
- Writer 不再手写 provider response path parser 或 Anthropic content block parser。

当前遗留：

- Writer `llm_client.py` 仍保留 HTTP transport、鉴权 header、错误处理、SSE 行读取。
- Writer `llm_adapter_profiles.py` 仍保留 profile 文件目录发现和缓存包装，并 re-export Core helper 供现有入口使用。

下一步：

- Step 6 收尾审计：确认 Writer 侧剩余 provider 代码都是配置读取、transport 或 thin wrapper；如通过则记录 Step 6 完成并进入 Step 7。

### 11.11 执行记录：2026-07-02 Step 6 收尾审计

目标：

- 验证 Step 6 验收条件：OpenAI-compatible 和 xfyun fixture 在 Core 测；Writer 不再出现 provider-specific response path parser。
- 收紧 Writer profile wrapper，避免通用 profile helper 继续伪装成 Writer 私有能力。

已完成：

- `members/writer/backend/app/utils/llm_adapter_profiles.py`
  - 收缩为 profile 文件目录发现、缓存、resolve wrapper。
  - 不再 re-export request / response / path / thinking 等通用 profile helper。
- `members/writer/backend/app/utils/llm_client.py`
  - Core profile helper 直接从 `lamtools_core.llm.profiles` 导入。
  - Writer 仅保留 provider resolve、HTTP transport、鉴权 header、错误处理、SSE 行读取。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - Core bridge streaming 直接使用 Core profile helper。
  - Writer wrapper 仅用于解析本成员的 profile 文件来源。
- `members/writer/backend/tests/test_llm_adapter_profiles.py`
  - 通用 JSONC / thinking payload 语义改为直接从 Core helper 测。
  - Writer wrapper 测试聚焦资源目录、环境目录、app resource override 和 resolve。

审计结果：

- Writer 生产代码中未再出现 `response_path`、`get_path()`、`choices.0`、`non_stream_response`、`stream_response` 等 provider response path parser。
- Writer 生产代码中仍出现 `build_profiled_*` / `normalize_*_with_profile`，但来源是 Core helper，属于调用 Core adapter 语义，不是 Writer 私有解析。
- Writer 侧剩余 provider 代码属于配置读取、profile 目录发现、transport、鉴权 header、错误处理、SSE 行读取。

验证：

- `rg -n "response_path|get_path\\(|apply_request_payload|apply_thinking_payload|choices\\.0|reasoning_content|content_blocks|stop_reason|enable_thinking|budget_tokens|stream_response|non_stream_response|build_profiled|normalize_.*with_profile|endpoint_path" members/writer/backend/app core/src/lamtools_core/llm -g '*.py'`
- `rg -n "from app\\.utils\\.llm_adapter_profiles import|llm_adapter_profiles import" members/writer/backend/app -g '*.py'`
- `py -3.14 -m py_compile members/writer/backend/app/utils/llm_adapter_profiles.py members/writer/backend/app/utils/llm_client.py members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/tests/test_llm_adapter_profiles.py`
- `py -3.14 -m pytest members/writer/backend/tests/test_llm_adapter_profiles.py members/writer/backend/tests/test_writer_llm_client.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest core/tests/test_llm_profiles.py -q`

验证备注：

- Writer adapter profile / LLM client tests 9 passed。
- Writer Core kernel adapter tests 172 passed。
- Core profile tests 6 passed。

Step 6 结论：

- Step 6 当前验收通过。
- OpenAI-compatible、xfyun、Anthropic-compatible 的 profile / request / response / stream 语义已下沉 Core。
- Writer 不再持有 provider-specific response path parser，剩余代码是成员配置读取和 transport 层。

下一步：

- 进入 Step 7：Tool / Permission 下沉 Core。先审计 Writer 当前通用工具、权限等待、恢复入口，再设计最小迁移切片。

### 11.12 执行记录：2026-07-02 Step 7 第一切片

目标：

- 先把通用工具安全边界下沉 Core，而不是一次性搬动所有工具执行逻辑。
- 消除 Writer 多处重复的 workspace path containment、path validation、relative URI、文件大小和行数 helper。

已完成：

- `core/src/lamtools_core/tool/workspace.py`
  - 新增 Core workspace helper。
  - 提供 `is_within_path()`、`validate_workspace_path()`、`relative_workspace_uri()`、`format_file_size()`、`line_count()`。
- `core/tests/test_tool_workspace.py`
  - 覆盖子路径允许、路径逃逸拒绝、相对 URI、文件大小和行数统计。
- Writer 工具侧改为复用 Core helper：
  - `file_tool_helpers.py`
  - `read_tools.py`
  - `write_tools.py`
  - `git_tools.py`
  - `command_tools.py`
  - `core_kernel_adapter.py`
  - `architecture_handoff.py`
  - `management_tools.py`
  - `sub_agent_workspace.py`

验证：

- `py -3.14 -m py_compile core/src/lamtools_core/tool/workspace.py core/tests/test_tool_workspace.py members/writer/backend/app/core/writer/architecture_handoff.py members/writer/backend/app/core/writer/management_tools.py members/writer/backend/app/core/writer/sub_agent_workspace.py members/writer/backend/app/core/writer/file_tool_helpers.py members/writer/backend/app/core/writer/read_tools.py members/writer/backend/app/core/writer/write_tools.py members/writer/backend/app/core/writer/git_tools.py members/writer/backend/app/core/writer/command_tools.py members/writer/backend/app/core/writer/core_kernel_adapter.py`
- `py -3.14 -m pytest core/tests/test_tool_workspace.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_agent_runtime.py -q`
- `rg -n "def _is_within_path|def _validate_path|def _format_size|def _relative_tool_uri|def _line_count|validate_workspace_path|is_within_path|format_file_size|relative_workspace_uri|line_count" members/writer/backend/app/core/writer core/src/lamtools_core/tool -g '*.py'`

验证备注：

- Core workspace tests 4 passed。
- Writer Core kernel adapter tests 172 passed。
- Writer agent runtime tests 21 passed。
- 扫描显示上述通用 helper 的定义只在 Core，Writer 仅保留 import/兼容别名。

当前收缩：

- 通用 workspace 安全边界进入 Core。
- Writer 工具执行逻辑暂未迁移，但不再各自维护路径边界实现。

当前遗留：

- `ReadOnlyToolExecutor`、`ReadWriteToolExecutor`、command/git/web/MCP/sub-agent 执行仍在 Writer。
- 权限规格、审批策略、恢复语义仍主要在 Writer tool specs / kernel adapter 周边。

下一步：

- Step 7 第二切片：把只依赖 workspace 边界的通用读/写文件工具向 Core toolkit 迁移，Writer 只组合启用工具和 Writer 专属工具。

### 11.13 执行记录：2026-07-02 Step 7 第二切片

目标：

- 将通用 workspace 读写文件工具执行下沉到 Core。
- Writer 只保留产品专属的 `inspect_project`、`load_skill` 和工具组合入口。
- 保持现有 Writer `ReadOnlyToolExecutor` / `write_tools` 导入兼容，降低迁移风险。

已完成：

- `core/src/lamtools_core/tool/workspace_files.py`
  - 新增 Core workspace file toolkit。
  - 承接 `read_file`、`list_dir`、`search_files`、`search_content`。
  - 承接 `write_file_tool`、`edit_file_tool`、`make_write_file_handler`、`make_edit_file_handler`。
  - 支持只读 resource roots，保留 Writer `load_skill` 后读取 skill reference 的能力。
- `core/tests/test_workspace_files.py`
  - 覆盖 read metadata/artifact、resource root read、search limit、write/edit workspace boundary。
- `members/writer/backend/app/core/writer/read_tools.py`
  - `ReadOnlyToolExecutor` 改为继承 Core `WorkspaceReadOnlyTools`。
  - Writer 只新增 `inspect_project` 和 `load_skill`。
- `members/writer/backend/app/core/writer/write_tools.py`
  - 收缩为 Core write helpers 的 re-export。
- `members/writer/backend/app/core/writer/file_tool_helpers.py`
  - 删除通用 size/line/diff/URI helper，只保留 Writer 项目栈和测试命令推断。

验证：

- `py -3.14 -m py_compile core/src/lamtools_core/tool/workspace_files.py core/tests/test_workspace_files.py members/writer/backend/app/core/writer/read_tools.py members/writer/backend/app/core/writer/write_tools.py members/writer/backend/app/core/writer/file_tool_helpers.py members/writer/backend/app/core/writer/core_kernel_adapter.py`
- `py -3.14 -m pytest core/tests/test_workspace_files.py core/tests/test_tool_workspace.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_agent_runtime.py -q`
- `rg -n "class WorkspaceReadOnlyTools|class ReadOnlyToolExecutor|async def read_file|async def list_dir|async def search_files|async def search_content|async def write_file_tool|async def edit_file_tool|make_write_file_handler|make_edit_file_handler|unified_diff|resolve_read_resource_path" core/src/lamtools_core/tool members/writer/backend/app/core/writer -g '*.py'`

验证备注：

- Core workspace file / path tests 8 passed。
- Writer tool contracts tests 33 passed。
- Writer Core kernel adapter tests 172 passed。
- Writer agent runtime tests 21 passed。
- 扫描显示通用读写执行定义只在 Core；Writer 保留继承类和 re-export 兼容入口。

当前收缩：

- 通用 workspace file read/write/search/edit 工具已进入 Core。
- Writer 读工具文件从通用执行器变为 Core toolkit 的 Writer 扩展。
- Writer 写工具文件从实现文件变为兼容导出文件。

当前遗留：

- Command/Git/Web/MCP/SubAgent 执行仍在 Writer。
- `ReadWriteToolExecutor` 仍在 Writer 组合通用工具和产品工具。
- 权限规格、审批策略、恢复语义仍待 Step 7 后续切片下沉。

下一步：

- Step 7 第三切片：审计并迁移 git / command 工具中可通用化的执行包装或权限元数据，避免 Writer 继续持有通用 shell/git tool runtime。

### 11.14 执行记录：2026-07-02 Step 7 第三切片

目标：

- 从 command/git 工具里先迁移低耦合的 git 工具语义。
- `run_command` 暂不迁移，因为它仍承载 Writer runtime progress events、后台 HTTP probe、Windows shell 包装和 skill script path rewrite，需要后续单独设计 Core contract。

已完成：

- `core/src/lamtools_core/tool/git_tools.py`
  - 新增 Core git tool handler factory。
  - 承接 `git_status`、`git_diff`、diff path boundary、exit/error metadata、输出截断。
  - 通过注入 `run_subprocess` 保持 Core 不绑定 Writer subprocess runtime。
- `core/tests/test_git_tools.py`
  - 覆盖 clean status、diff path escape block、failed exit 映射。
- `members/writer/backend/app/core/writer/git_tools.py`
  - 收缩为 thin wrapper。
  - 仅注入 Writer 当前 `_run_subprocess`，保持原 `make_git_status_handler()` / `make_git_diff_handler()` 签名兼容。

验证：

- `py -3.14 -m py_compile core/src/lamtools_core/tool/git_tools.py core/tests/test_git_tools.py members/writer/backend/app/core/writer/git_tools.py members/writer/backend/app/core/writer/core_kernel_adapter.py`
- `py -3.14 -m pytest core/tests/test_git_tools.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q`
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q`
- `rg -n "make_git_status_handler|make_git_diff_handler|validate_git_diff_path|git status --porcelain|git diff|_run_subprocess" core/src/lamtools_core/tool members/writer/backend/app/core/writer -g '*.py'`

验证备注：

- Core git tool tests 3 passed。
- Writer tool contracts tests 33 passed。
- Writer Core kernel adapter tests 172 passed。
- 扫描显示 git handler 逻辑在 Core；Writer `git_tools.py` 只注入命令执行器。

当前收缩：

- git tool runtime 语义进入 Core。
- Writer 不再维护 git status / diff 的业务包装和 path boundary 实现。

当前遗留：

- `run_command` / `run_tests` 仍在 Writer，因为它们还负责 runtime progress events、后台 HTTP probe、Windows shell 行为、skill script path rewrite。
- Command permission metadata 仍由 WriterKit 注入。

下一步：

- Step 7 第四切片：为 command tool 设计 Core 可接管的最小 contract，先分离纯命令执行结果模型和 runtime event side effects，再决定是否迁移 `run_command`。

### 11.15 执行记录：2026-07-02 Step 7 第四切片

目标：

- 先把 command tool 的纯通用 contract 下沉 Core。
- 暂不迁移完整 `run_command`，因为它仍绑定 Writer runtime progress event、后台 HTTP probe、Windows PowerShell 包装、skill script path rewrite 和当前权限策略。

已完成：

- `core/src/lamtools_core/tool/command.py`
  - 新增 `CommandExecution`。
  - 承接命令输出格式化、运行中输出格式化、命令路径边界校验、默认测试命令探测。
- `core/tests/test_command_tools.py`
  - 覆盖 command result 默认值、stdout/stderr 分段、截断、running 状态、路径逃逸、resource root 放行、测试命令探测。
- Writer command 侧改为复用 Core helper：
  - `command_runner.py` 保留 subprocess / background / probe / Windows shell 执行，导入 Core `CommandExecution` 和格式化函数。
  - `command_tools.py` 保留 `CommandToolHandlers`，导入 Core path validation 和 test command detection。
  - `core_kernel_adapter.py` 补回 `_run_subprocess` 兼容导出，保持既有命令取消测试入口。

验证：

- `py -3.14 -m py_compile core\src\lamtools_core\tool\command.py core\tests\test_command_tools.py members\writer\backend\app\core\writer\command_runner.py members\writer\backend\app\core\writer\command_tools.py members\writer\backend\app\core\writer\core_kernel_adapter.py`
- `py -3.14 -m pytest core\tests\test_command_tools.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_tool_contracts.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_agent_runtime.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_command_cancel.py -q`
- `rg -n "class CommandExecution|class _CommandExecution|def format_command_output|def _format_command_output|def format_running_command_output|def _format_running_command_output|def validate_command_paths|def _validate_command_paths|def detect_test_command|def _detect_test_command" core\src\lamtools_core\tool members\writer\backend\app\core\writer -g "*.py"`
- `git diff --check`

验证备注：

- Core command tests 9 passed。
- Writer Core kernel adapter tests 172 passed。
- Writer tool contracts tests 33 passed。
- Writer agent runtime tests 21 passed。
- Writer command cancel test 1 passed。
- `git diff --check` 只有 CRLF warning，无 whitespace error。
- 跨包混合运行 `core\tests\test_command_tools.py` 与 Writer 测试时，pytest 对 `tests.test_command_tools` 产生包名解析冲突；按包边界分别运行通过。

当前收缩：

- command result model、输出格式、路径边界、默认测试命令探测已进入 Core。
- Writer command runtime 不再持有这些纯 helper 的实现。

当前遗留：

- 完整 `run_command` / `run_tests` handler 仍在 Writer。
- 后台 server probe、PowerShell shell contract、runtime progress event、skill path rewrite、权限 metadata 仍需后续切片设计 Core contract 后迁移。

下一步：

- Step 7 第五切片：审计 permission / approval 等待恢复链路，先抽 Core `ApprovalGate` contract，再决定 command handler 是否可以整体迁移。

### 11.16 执行记录：2026-07-02 Step 7 第五切片

目标：

- 抽出通用 tool permission / approval gate，不触碰当前有无关脏改动的 Core loop。
- 保留 Writer tool spec 作为成员策略来源，但让通用命令风险分类、路径 gate、敏感路径阻断进入 Core。

已完成：

- `core/src/lamtools_core/tool/approval.py`
  - 新增 `ApprovalGate` 和 `ToolApprovalDecision`。
  - 承接 `classify_command()`、`command_permission_decision()`、命令策略归一、默认高危命令识别、默认敏感文件模式。
  - 支持按成员传入 `tool_permissions`、`work_root`、`auto_approve_read`、`blocked_file_patterns`。
- `core/tests/test_tool_approval.py`
  - 覆盖常规/高危命令分类、高危命令需要审批、读工具自动允许、路径逃逸阻断、写工具需要确认、命令策略执行。
- `members/writer/backend/app/core/writer/permission.py`
  - 收缩为 Writer 适配层。
  - `TOOL_PERMISSIONS` 仍来自 Writer declarative tool specs。
  - `PermissionChecker` 改为调用 Core `ApprovalGate`。
  - 保留旧的 `classify_command()`、`command_permission_decision()`、`DEFAULT_COMMAND_POLICIES`、`BLOCKED_FILE_PATTERNS` 导入/常量兼容面。

验证：

- `py -3.14 -m py_compile core\src\lamtools_core\tool\approval.py core\tests\test_tool_approval.py members\writer\backend\app\core\writer\permission.py`
- `py -3.14 -m pytest core\tests\test_tool_approval.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_permission.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_tool_contracts.py members\writer\backend\tests\test_writer_tool_specs.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_mcp.py members\writer\backend\tests\test_schemas.py -q`
- `rg -n "class ApprovalGate|class PermissionChecker|def classify_command|def command_permission_decision|DANGEROUS_COMMAND_RE|DEFAULT_COMMAND_POLICIES|BLOCKED_FILE_PATTERNS|DEFAULT_BLOCKED_FILE_PATTERNS" core\src\lamtools_core\tool members\writer\backend\app\core\writer -g "*.py"`
- `git diff --check`

验证备注：

- Core approval tests 6 passed。
- Writer permission tests 22 passed。
- Writer tool contract/spec tests 44 passed。
- Writer Core kernel adapter tests 172 passed。
- Writer MCP/schema tests 43 passed。
- `git diff --check` 只有 CRLF warning，无 whitespace error。
- 额外探测 `members\writer\backend\tests\test_writer_app_approvals.py::test_runtime_approval_creates_request_row_and_snapshot_request` 当前失败：测试期望 app snapshot `idle`，当前实现返回 `waiting`。本切片未触碰 app-server projection / runtime bridge，记录为既有 approval snapshot 语义漂移，留到后续 approval 等待恢复切片单独处理。

当前收缩：

- 通用 permission gate 和 command approval policy 已进入 Core。
- Writer permission 模块不再维护命令风险正则、命令策略归一、路径审批 gate 主逻辑。

当前遗留：

- Core loop 的 approval waiting/resume 元数据仍在 `kernel/loop.py`，当前文件有无关脏改动，未在本切片触碰。
- App-server approval row / snapshot / transcript continuation 仍在 Writer 服务层。
- `run_command` 整体 handler 仍在 Writer，待审批恢复 contract 稳定后再迁移。

下一步：

- Step 7 第六切片：单独处理 approval waiting/resume contract。先复核 `test_runtime_approval_creates_request_row_and_snapshot_request` 的 `idle` vs `waiting` 语义，再决定是修 projection 还是更新测试与文档。

### 11.17 执行记录：2026-07-02 Step 7 第六切片

目标：

- 处理第五切片暴露的 approval snapshot 语义漂移。
- 判断 `runtime.approval_request` 后 app snapshot 顶层状态应为 `idle` 还是 `waiting`。

已完成：

- 复核 Core snapshot reducer：
  - `approval_request` 会写入 `core.requests[request_id].status = open`。
  - Core thread `status` 明确变为 `waiting`。
- 复核 Writer app reducer：
  - `core/runItem` 进入后会调用 Core snapshot reducer。
  - app 顶层 `status` 会同步 Core `idle/running/waiting/completed`。
- 更新 `members/writer/backend/tests/test_writer_app_approvals.py`：
  - `test_runtime_approval_creates_request_row_and_snapshot_request` 的 app 顶层状态断言从 `idle` 改为 `waiting`。
  - 保持 `snapshot["requests"] == {}` 不变，外层 Writer request 列表仍不承载运行审批事实；审批事实由 `snapshot.core.requests` 表达。

验证：

- `py -3.14 -m pytest members\writer\backend\tests\test_writer_app_approvals.py members\writer\backend\tests\test_writer_app_runtime_bridge.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_app_server_protocol.py -q`
- `git diff --check`

验证备注：

- Writer app approval / runtime bridge tests 29 passed。
- Writer app server protocol tests 55 passed。
- 测试中出现 Windows asyncio proactor unclosed transport warning，不影响断言通过；本切片未触碰相关 transport。
- `git diff --check` 只有 CRLF warning，无 whitespace error。

当前收缩：

- approval request 的当前真相进一步收口为 Core snapshot：`core.requests` 表达审批请求，Core status 驱动 app 顶层 waiting。
- Writer app 外层 `requests` 不再被测试误认为运行审批主线。

当前遗留：

- approval response 后的继续执行、已批准工具重放、等待块关闭仍在 Writer service 层。
- Core 还没有统一的 resumable approval continuation contract。

下一步：

- Step 7 第七切片：审计 `runtime_waiting_request.py`、`runtime_approved_tool.py`、`writer_service.respond_waiting_request()`，把可通用的 approval continuation result / approved tool replay contract 下沉 Core。

### 11.18 执行记录：2026-07-02 Step 7 第七切片

目标：

- 审计 approval continuation 和 approved tool replay 链路。
- 只抽可通用 contract，不搬 Writer DB / transcript / service 调度。

已完成：

- `core/src/lamtools_core/tool/approval_continuation.py`
  - 新增 `ResolvedWaitingRequest`。
  - 新增 `ApprovedToolExecution`，统一批准后工具执行结果结构和 `completed` 判断。
  - 新增 `normalize_waiting_action()`、`resolve_waiting_decision()`。
  - 新增通用 continuation prompt builder：
    - guidance continuation：用户未批准原动作，而是给出新引导。
    - approved tool continuation：用户已批准，后端已执行等待中的工具调用。
- `core/tests/test_approval_continuation.py`
  - 覆盖 waiting action alias、guide 必须带引导文本、approved tool completed 判断、两类 continuation prompt 内容。
- Writer 服务层改为复用 Core contract：
  - `runtime_waiting_request.py` 使用 Core waiting decision resolver。
  - `runtime_approved_tool.py` 使用 Core `ApprovedToolExecution`。
  - `runtime_continuation_prompts.py` 变为 Writer transcript wrapper，只负责从 turn/block 取原始任务、工具名、参数。

验证：

- `py -3.14 -m py_compile core\src\lamtools_core\tool\approval_continuation.py core\tests\test_approval_continuation.py members\writer\backend\app\services\runtime_waiting_request.py members\writer\backend\app\services\runtime_approved_tool.py members\writer\backend\app\services\runtime_continuation_prompts.py`
- `py -3.14 -m pytest core\tests\test_approval_continuation.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_app_approvals.py members\writer\backend\tests\test_writer_app_server_protocol.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_transcript_service.py members\writer\backend\tests\test_writer_app_runtime_bridge.py -q`
- `rg -n "resolve_waiting_request_response|approved_tool_continuation_prompt|guidance_continuation_prompt|ApprovedToolExecution|normalize_waiting_action" members\writer\backend\tests members\writer\backend\app core\tests -g "*.py"`
- `git diff --check`

验证备注：

- Core approval continuation tests 5 passed。
- Writer app approval/server protocol tests 58 passed。
- Writer transcript/runtime bridge tests 31 passed。
- 测试中仍有 Windows asyncio proactor unclosed transport warning，不影响断言通过；本切片未触碰 transport。
- `git diff --check` 只有 CRLF warning，无 whitespace error。

当前收缩：

- waiting decision 归一、approved tool result contract、continuation prompt 模板进入 Core。
- Writer continuation prompt 文件只保留 transcript wrapper。

当前遗留：

- approval continuation 的 DB 持久化、waiting block 关闭、tool replay 调度仍在 Writer。
- `APPROVABLE_TOOL_NAMES` 和实际 `ReadWriteToolExecutor` 选择仍是 Writer 策略。
- Core 尚未接管完整 resumable approval continuation runner。

下一步：

- Step 7 第八切片：回到 Tool 下沉主线，审计 Web / Browser / MCP / SubAgent 工具中哪些是通用执行能力，哪些是 Writer 策略或产品集成。

### 11.19 执行记录：2026-07-02 Step 7 第八切片

目标：

- 审计 Web / Browser / MCP / SubAgent 工具边界。
- 先迁移低耦合的通用 HTTP 工具，不把 MCP registry 或 SubAgent 策略混入同一切片。

已完成：

- 审计结论：
  - Web / Browser：只依赖 HTTP client、URL 校验、HTML 文本提取、ToolResult/ToolArtifact，属于 Core 通用工具。
  - MCP：当前路由在 `core_kernel_adapter.py`，依赖 Writer MCP registry、MCP permission 和 runtime resource，暂不与 Web 同切。
  - SubAgent：当前依赖 Writer agent definition、LLM route、isolated workspace、write_scope、handoff delivery 和 product metadata，暂不与 Web 同切。
- `core/src/lamtools_core/tool/web_tools.py`
  - 承接 `web_search`、`web_fetch`、`browser_check` handler factory。
  - 承接 DuckDuckGo HTML search、file:// 阻断、HTML readable text extraction、browser expected text check。
- `core/tests/test_web_tools.py`
  - 覆盖 web search structured metadata/artifact、file:// 阻断、HTML fetch artifact、browser expected text。
- `members/writer/backend/app/core/writer/web_tools.py`
  - 收缩为 thin compatibility wrapper。
  - 保留旧 `_HTTP_CLIENT` monkeypatch 兼容：创建 handler 前同步到 Core web tools。
- `core/pyproject.toml`
  - 将 `httpx>=0.28.1` 提升为 Core runtime dependency，因为 Core Web 工具运行时直接导入 `httpx`。

验证：

- `py -3.14 -m py_compile core\src\lamtools_core\tool\web_tools.py core\tests\test_web_tools.py members\writer\backend\app\core\writer\web_tools.py members\writer\backend\app\core\writer\core_kernel_adapter.py`
- `py -3.14 -m pytest core\tests\test_web_tools.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_tool_contracts.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_agent_runtime.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_core_kernel_adapter.py -q`
- `rg -n "def make_web_search_handler|def make_web_fetch_handler|def make_browser_check_handler|def _extract_readable_text|_WEB_SEARCH_URL|_HTTP_CLIENT" core\src\lamtools_core\tool members\writer\backend\app\core\writer -g "*.py"`
- `git diff --check`

验证备注：

- Core Web tests 4 passed。
- Writer tool contracts tests 33 passed。
- Writer agent runtime tests 21 passed。
- Writer Core kernel adapter tests 172 passed。
- 扫描显示 Web / Browser handler 实现在 Core；Writer 仅保留兼容 wrapper。
- `git diff --check` 只有 CRLF warning，无 whitespace error。

当前收缩：

- 通用 Web search/fetch/browser check 工具进入 Core。
- Writer 不再维护通用 HTTP 工具执行逻辑。

当前遗留：

- MCP tool dispatch 仍在 Writer `core_kernel_adapter.py`，因为它绑定 Writer MCP registry 和 runtime resource。
- SubAgent runtime 仍在 Writer `agent_runtime.py` / `core_kernel_adapter.py`，因为它绑定成员 agent definition、模型路由、workspace 交付和产品 metadata。

下一步：

- Step 7 第九切片：审计 MCP registry / MCP tool dispatch，先抽通用 MCP call result / dispatch contract，再判断 registry 是否可下沉 Core。

### 11.20 执行记录：2026-07-02 Step 7 第九切片

目标：

- 审计 MCP registry / MCP tool dispatch。
- 先抽通用 MCP call result / dispatch contract，不迁移 Writer MCP config 和 client 生命周期。

已完成：

- 审计结论：
  - `app.core.mcp.config` / `MCPClient` / `MCPToolRegistry.load()` 仍依赖 Writer 配置来源、builtin Playwright 开关和 stdio client 生命周期，暂留 Writer。
  - `mcp_tool` 与 `mcp__*` 的调用形状、参数清洗、错误映射、结果格式化属于通用 tool contract，可下沉 Core。
- `core/src/lamtools_core/tool/mcp_tools.py`
  - 新增 `MCPToolCaller` protocol。
  - 新增 `mcp_call_args()`，统一解析 `mcp_tool` 和 direct `mcp__server__tool` 两种调用。
  - 新增 `execute_mcp_tool_call()`，统一 unavailable / missing tool_name / exception / ok 的 ToolResult 映射。
  - 新增 `clean_mcp_arguments()`，过滤 `_` 开头的 runtime 参数。
  - 新增 `format_mcp_result()`，统一 MCP text content / error content / fallback JSON 格式化。
- `core/tests/test_mcp_tools.py`
  - 覆盖 generic/direct 调用解析、ToolResult 映射、registry 缺失错误、runtime 参数清洗、MCP result 格式化。
- Writer 侧接入：
  - `members/writer/backend/app/core/mcp/registry.py` 改为复用 Core `clean_mcp_arguments()` 和 `format_mcp_result()`。
  - `members/writer/backend/app/core/writer/core_kernel_adapter.py` 的 `_execute_mcp_tool()` 改为调用 Core `execute_mcp_tool_call()`，仅注入 Writer MCP registry 和 unavailable 文案。

验证：

- `py -3.14 -m py_compile core\src\lamtools_core\tool\mcp_tools.py core\tests\test_mcp_tools.py members\writer\backend\app\core\mcp\registry.py members\writer\backend\app\core\writer\core_kernel_adapter.py`
- `py -3.14 -m pytest core\tests\test_mcp_tools.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_mcp.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_tool_contracts.py -q`
- `rg -n "def format_mcp_result|def clean_mcp_arguments|def mcp_call_args|def execute_mcp_tool_call|async def _execute_mcp_tool" core\src members\writer\backend\app -g "*.py"`
- `git diff --check`

验证备注：

- Core MCP tests 5 passed。
- Writer MCP tests 5 passed。
- Writer Core kernel adapter tests 172 passed。
- Writer tool contracts tests 33 passed。
- 扫描显示 MCP 通用 dispatch / formatting 在 Core；Writer 保留 adapter 方法和 registry 生命周期。
- `git diff --check` 只有 CRLF warning，无 whitespace error。

当前收缩：

- MCP 调用 contract、参数清洗和结果格式化进入 Core。
- Writer MCP registry 不再维护通用 result formatter。
- Writer kernel adapter 不再手写 `mcp_tool` / `mcp__*` ToolResult 映射。

当前遗留：

- MCP server config、builtin Playwright MCP、stdio/json-lines client 生命周期仍在 Writer。
- MCP permission 与 runtime resource prewarm / close 仍在 Writer。

下一步：

- Step 7 第十切片：审计 SubAgent runtime，先抽 sub-agent definition / write_scope / tool allowlist 的通用 contract，保留 Writer 模型路由和 workspace delivery。

### 11.21 执行记录：2026-07-02 Step 7 第十切片

目标：

- 审计 SubAgent runtime 中可先下沉 Core 的低耦合边界。
- 先迁移 write_scope 安全 contract，不触碰 Writer LLM 路由、workspace delivery、内置 agent 文案。

已完成：

- 审计结论：
  - write_scope 解析、路径归一、路径允许判断、并行写入冲突判断是通用子代理安全边界。
  - SubAgent definition 文件加载、builtin agent 定义、Writer 模型路由、isolated workspace、handoff delivery、产品 metadata 仍是 Writer 策略或集成。
- `core/src/lamtools_core/tool/sub_agent.py`
  - 新增 `AgentWriteScope`。
  - 新增 `is_write_capable()`、`write_scope_error()`。
  - 新增 `write_scope_from_options()`，支持 `write_scope` / `write_paths` / `allowed_paths` 及 dict aliases。
  - 新增 `normalize_scope_path()`、`scope_allows_path()`、`scopes_conflict()`、`scope_paths_conflict()`。
- `core/tests/test_sub_agent_tools.py`
  - 覆盖 alias shapes、路径逃逸拒绝、目录/Glob 放行、scope 冲突、写入型 agent 必须声明 write_scope。
- `members/writer/backend/app/core/writer/agent_runtime.py`
  - 删除本地 `AgentWriteScope` 实现，改用 Core。
  - `_is_write_capable()`、`_write_scope_error()`、`_write_scope_for_call()`、`_normalize_scope_path()`、`_scope_allows_path()`、`_scopes_conflict()`、`_scope_paths_conflict()` 保留兼容入口并转调 Core。

验证：

- `py -3.14 -m py_compile core\src\lamtools_core\tool\sub_agent.py core\tests\test_sub_agent_tools.py members\writer\backend\app\core\writer\agent_runtime.py members\writer\backend\app\core\writer\core_kernel_adapter.py`
- `py -3.14 -m pytest core\tests\test_sub_agent_tools.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_agent_runtime.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_tool_contracts.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_core_kernel_adapter.py -q`
- `rg -n "class AgentWriteScope|def write_scope_from_options|def normalize_scope_path|def scope_allows_path|def scopes_conflict|def scope_paths_conflict|def write_scope_error|def _write_scope_for_call|def _normalize_scope_path|def _scope_allows_path|def _scopes_conflict|def _scope_paths_conflict" core\src members\writer\backend\app\core\writer -g "*.py"`
- `git diff --check`

验证备注：

- Core sub-agent tool tests 5 passed。
- Writer agent runtime tests 21 passed。
- Writer tool contracts tests 33 passed。
- Writer Core kernel adapter tests 172 passed。
- 扫描显示 write_scope 实现在 Core；Writer 仅保留兼容转调方法。
- `git diff --check` 只有 CRLF warning，无 whitespace error。

当前收缩：

- SubAgent 写入范围安全边界进入 Core。
- Writer agent runtime 不再维护 write_scope path/scope 冲突算法。

当前遗留：

- SubAgentDefinition、definition file 解析、builtin agent set 仍在 Writer。
- AgentRuntime 调度、LLM client factory、isolated workspace、workspace delivery、sub-agent result projection 仍在 Writer。

下一步：

- Step 7 第十一切片：继续审计 SubAgent definition contract，判断 definition parsing/rendering 是否可下沉 Core，同时保留 Writer builtin definitions 和 routing 策略。

### 11.22 执行记录：2026-07-02 Step 7 第十一切片

目标：

- 审计 SubAgent definition parsing/rendering 边界。
- 将 Claude-style / Writer-style sub-agent definition 文件 contract 下沉 Core，同时保留 Writer builtin definitions 和路由策略。

已完成：

- `core/src/lamtools_core/tool/sub_agent.py`
  - 新增 `SubAgentDefinition`。
  - 新增 `definition_map()`。
  - 新增 `parse_sub_agent_definition()`，解析 frontmatter + developer instructions。
  - 新增 `validate_project_sub_agent_name()`、`project_sub_agent_definition_path()`。
  - 新增 `render_sub_agent_definition()`、`write_project_sub_agent_definition()`、`delete_project_sub_agent_definition()`。
  - 新增 YAML scalar / frontmatter / list parsing helper。
- `core/tests/test_sub_agent_tools.py`
  - 增补 definition frontmatter parsing。
  - 增补 project definition write/delete roundtrip。
  - 增补 name validation 和 render quoting。
- `members/writer/backend/app/core/writer/agent_runtime.py`
  - 删除本地 `SubAgentDefinition` dataclass 和 definition parse/render/write/delete helper。
  - `load_sub_agent_definitions()` 仍保留 Writer 目录策略和 builtin definitions，但使用 Core parser。
  - `sub_agent_definition_map()` 改为使用 Core `definition_map()`。
  - 继续从该模块 re-export `SubAgentDefinition` / project definition helpers，保持现有 Writer imports 兼容。

验证：

- `py -3.14 -m py_compile core\src\lamtools_core\tool\sub_agent.py core\tests\test_sub_agent_tools.py members\writer\backend\app\core\writer\agent_runtime.py members\writer\backend\app\services\subagent_config.py members\writer\backend\app\routers\config.py`
- `py -3.14 -m pytest core\tests\test_sub_agent_tools.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_agent_runtime.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_tool_contracts.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_core_kernel_adapter.py -q`
- `rg -n "class SubAgentDefinition|def parse_sub_agent_definition|def render_sub_agent_definition|def write_project_sub_agent_definition|def delete_project_sub_agent_definition|def validate_project_sub_agent_name|def _parse_sub_agent_definition|def _split_frontmatter|def _parse_simple_frontmatter" core\src members\writer\backend\app\core\writer -g "*.py"`
- `git diff --check`

验证备注：

- Core sub-agent tool tests 8 passed。
- Writer agent runtime tests 21 passed。
- Writer tool contracts tests 33 passed。
- Writer Core kernel adapter tests 172 passed。
- 扫描显示 SubAgentDefinition / definition parser / render / write / delete 在 Core；Writer `skills.py` 的 `_split_frontmatter` 属于 skill index parsing，不是 sub-agent definition。
- `git diff --check` 只有 CRLF warning，无 whitespace error。

当前收缩：

- SubAgent definition 文件契约进入 Core。
- Writer agent runtime 不再维护 definition parser / renderer / project definition write-delete 实现。

当前遗留：

- Writer builtin sub-agent definitions 仍在 Writer，因为它们包含成员角色和工具策略。
- AgentRuntime 调度、模型路由、workspace delivery、result projection 仍在 Writer。

下一步：

- Step 7 第十二切片：评估 Step 7 当前完成度，扫描 Writer 中剩余通用 tool/permission 实现；若只剩成员策略，记录 Step 7 完成边界并转入 Step 8。

### 11.23 执行记录：2026-07-02 Step 7 第十二切片

目标：

- 完成 Step 7 收尾审计，确认 Writer 中剩余 tool / permission 代码是否仍包含应下沉的通用执行能力。
- 把 `run_command` 中可独立复用的纯 subprocess 执行层下沉 Core，Writer 只保留成员运行策略。

已完成：

- `core/src/lamtools_core/tool/command.py`
  - 新增 `run_subprocess()`、`run_subprocess_blocking()`、`run_subprocess_streaming_blocking()`。
  - 新增 `terminate_process_tree()`。
  - Core command contract 现在覆盖命令输出、超时、取消、流式进度回调和进程树终止。
- `members/writer/backend/app/core/writer/command_runner.py`
  - 删除 Writer 本地同步/流式 subprocess 实现。
  - 保留兼容导出名，但实际指向 Core command contract。
  - 保留 Writer 特有的后台本地服务探针、readiness URL 校验、端口占用分类、skill script path rewrite、Windows PowerShell argv 包装。
- `members/writer/backend/app/core/writer/command_tools.py`
  - 主路径直接使用 Core `run_subprocess()` / command output formatter / command execution model。
  - 继续只从 Writer command runner 使用本地服务探针和 shell 策略。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - 测试兼容入口 `_run_subprocess` 改为直接指向 Core。
- `core/tests/test_command_tools.py`
  - 增补 Core command subprocess 普通输出、超时、取消终止子进程测试。

验证：

- `py -3.14 -m pytest core\tests\test_command_tools.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_command_cancel.py members\writer\backend\tests\test_tool_contracts.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_core_kernel_adapter.py -q`
- `rg -n "def _run_subprocess|def _terminate_process_tree|subprocess\.Popen|CREATE_NEW_PROCESS_GROUP|communicate\(|run_subprocess" members/writer/backend/app/core/writer/command_runner.py core/src/lamtools_core/tool/command.py`

验证备注：

- Core command tests 12 passed。
- Writer command cancel + tool contracts tests 34 passed。
- Writer Core kernel adapter tests 172 passed。
- 扫描显示纯 subprocess / 取消 / 超时 / 流式执行主实现位于 Core；Writer command runner 中剩余 `subprocess.Popen` 只服务后台长期进程和本地 HTTP readiness 探针。

当前收缩：

- 通用 Shell 执行层进入 Core。
- Writer 不再维护纯命令执行、取消和超时实现。

Step 7 完成边界：

- 已进入 Core：workspace path / file tools、git handlers、command execution contract、subprocess execution、web/browser handlers、MCP dispatch / result contract、ApprovalGate、approval continuation contract、SubAgent write scope、SubAgent definition contract。
- 保留 Writer：工具启用清单、权限分级配置、command 的本地服务探针和 shell 包装策略、runtime progress event 注入、MCP registry / client lifecycle、Writer builtin sub-agent roles、AgentRuntime 调度、workspace delivery、result projection、tool feedback / verification / outcomes。
- 保留原因：这些剩余项要么依赖 Writer 配置、产品提示词、运行事件投影和交付策略，要么属于成员工具策略，不是可复用 Core toolkit 主体。

下一步：

- 进入 Step 8：Prompt / Memory / Verification 收敛。优先审计 Writer 当前 prompt assembler、session recall/memory、verification result，把通用 prompt/context/verification contract 向 Core 收敛。

### 11.24 执行记录：2026-07-02 Step 8 第一切片

目标：

- 启动 Step 8：Prompt / Memory / Verification 收敛。
- 先选择最小通用面：把写入工具结果的基础验收 contract 下沉 Core，不触碰 Writer 产品级完成验收。

已完成：

- `core/src/lamtools_core/tool/verification.py`
  - 新增 `verify_written_tool_results()`。
  - 新增 `written_file_issues()`、`html_reference_issues()`、`path_from_write_result()`。
  - Core 现在负责基础写入结果验收：写入后文件存在、明显 stub/TODO、HTML 本地引用缺失 warning。
- `core/tests/test_tool_verification.py`
  - 覆盖 write/edit 内容路径解析。
  - 覆盖缺失文件失败。
  - 覆盖 stub code 失败。
  - 覆盖 HTML 本地引用 warning。
- `members/writer/backend/app/core/writer/tool_verification.py`
  - 删除本地实现，改为 Core verification wrapper，保留旧导入兼容名。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - WriterKit 主路径改为直接使用 Core `verify_written_tool_results()`。

验证：

- `py -3.14 -m pytest core\tests\test_tool_verification.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_tool_contracts.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_core_kernel_adapter.py -q`

验证备注：

- Core tool verification tests 4 passed。
- Writer tool contracts tests 33 passed。
- Writer Core kernel adapter tests 172 passed。

当前收缩：

- 通用写入工具验收从 Writer 进入 Core。
- Writer 不再维护基础 write/edit result verification 实现。

当前保留：

- `CompletionVerifier` 仍在 Writer，因为它包含 Writer 对“可交付完成”的产品级判断：项目扫描、Python/JS/HTML/浏览器验收、mock 策略、runnable artifact 约束、repair prompt 文案。
- Prompt/persona、skill index、project instruction、Novel memory 仍在 Writer，下一刀再分解。

下一步：

- Step 8 第二切片：审计 `CompletionVerifier`，优先抽出通用 verification result/check 数据结构或命令运行 helper；若发现判断规则带强 Writer 策略，则只记录保留边界。

### 11.25 执行记录：2026-07-02 Step 8 第二切片

目标：

- 审计 `CompletionVerifier` 中的通用命令运行 helper。
- 复用 Core command contract，避免 Writer 在完成验收里继续维护一套 subprocess / timeout / output decoding。

已完成：

- `members/writer/backend/app/core/writer/completion_verifier.py`
  - 删除本地 `_run_command_blocking()`、`_decode_timeout_output()`、`_exception_summary()`。
  - 删除直接 `subprocess.run()` / `asyncio.to_thread()` 执行路径。
  - `_run_command()` 改为调用 Core `run_subprocess()`。
  - 保留 Writer 的完成验收规则、artifact scan、Python/JS/HTML/browser 检查和 repair prompt 文案。

验证：

- `py -3.14 -m pytest members\writer\backend\tests\test_completion_verifier.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_core_kernel_adapter.py -q`

验证备注：

- Writer completion verifier tests 24 passed。
- Writer Core kernel adapter tests 172 passed。

当前收缩：

- CompletionVerifier 不再复制通用 command execution helper。
- Writer 完成验收继续复用 Core 的超时、输出、错误和进程执行语义。

当前保留：

- `CompletionVerifier` 的数据结构和规则暂留 Writer：其中的完成定义、mock 策略、zero-install MVP、浏览器页面非空、repair prompt 文案都带 Writer 产品判断。

下一步：

- Step 8 第三切片：审计 prompt assembly / static prompt messages，先判断可下沉的是通用 prompt part ordering / prompt file loading contract，还是仅记录 Writer persona / platform / skill index 保留边界。

### 11.26 执行记录：2026-07-02 Step 8 第三切片

目标：

- 审计 prompt assembly / static prompt messages。
- 将通用 prompt part ordering / message metadata contract 下沉 Core；Writer 继续只决定自己的 persona、执行协议、平台提示、项目规则和 skill index 内容。

已完成：

- `core/src/lamtools_core/prompt/__init__.py`
  - 新增 `prompt_parts_to_messages()`。
  - `BasePromptAssembler` 改为复用该 helper。
  - Core 负责将 `PromptPart` 按 priority 排序，并转换为带 `key/kind` metadata 的 `ChatMessage`。
- `core/tests/test_prompt.py`
  - 增补 `prompt_parts_to_messages()` 的排序和 metadata 保留测试。
- `members/writer/backend/app/core/writer/runtime_resources.py`
  - 新增 `_static_prompt_parts()`，Writer 只构造 `PromptPart`。
  - `_build_static_prompt_messages()` 改为调用 Core `prompt_parts_to_messages()`。
  - 保留 Writer 的具体 prompt 来源：persona、execution discipline、platform、project instructions、skill index。

验证：

- `py -3.14 -m pytest core\tests\test_prompt.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_prompt_assembler.py members\writer\backend\tests\test_tool_contracts.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_hook_context_contract.py -q`

验证备注：

- Core prompt tests 12 passed。
- Writer prompt assembler + tool contracts tests 42 passed。
- Writer hook context contract tests 15 passed。

当前收缩：

- 通用 prompt part ordering 和 ChatMessage metadata contract 进入 Core。
- Writer static prompt 不再手写 ChatMessage assembly。

当前保留：

- Writer prompt 文件加载、persona / platform 文案、project instruction 选择规则、skill index 内容仍在 Writer，因为它们是成员策略。

下一步：

- Step 8 第四切片：审计 session recall / memory prompt injection，优先判断 Core `mem` 现有接口能否接管 session memory index / prompt part conversion；若 Writer 仅有产品记忆策略，则记录保留边界。

### 11.27 执行记录：2026-07-02 Step 8 第四切片

目标：

- 审计 session recall / memory prompt injection。
- 复用 Core `mem` 现有能力，先下沉轻量 session memory summary prompt 文本格式。

已完成：

- `core/src/lamtools_core/mem/__init__.py`
  - 新增 `format_session_memory_summary()`。
  - Core 现在负责轻量 session memory stats 的 prompt context 文本格式。
- `core/tests/test_mem.py`
  - 增补 session memory summary 稳定格式测试。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - hook context 中的 `session_memory_summary` 改为使用 Core formatter。

验证：

- `py -3.14 -m pytest core\tests\test_mem.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_hook_context_contract.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_core_kernel_adapter.py -q`

验证备注：

- Core memory tests 12 passed。
- Writer hook context contract tests 15 passed。
- Writer Core kernel adapter tests 172 passed。

当前收缩：

- session memory summary 的 prompt 文本格式进入 Core。
- Writer 不再手写该片段格式。

审计发现：

- Core `mem` 已有 `MemoryEntry` / `MemoryHit` / `hits_to_prompt_parts()`。
- Writer 当前生产代码没有 `recall_session` executor 主路径；`recall_session` 主要仍是 schema、tool spec 和权限声明。
- 因此本切片不迁移不存在的 recall 执行器；后续应在 Step 9 工具清单收缩时判断 `recall_session` 是补齐执行器、移出模型工具，还是归入 Core session memory contract。

当前保留：

- Novel memory writeback、章节状态、领域实体记忆仍在 Writer Novel 模块。
- Writer runtime state 存储在 Writer session memory 中的 `_core_runtime_state` 仍属 Writer DB persistence adapter。

下一步：

- Step 8 收尾审计：逐项核对 Prompt / Memory / Verification 是否已经形成 Core contract；记录 Step 8 完成边界后进入 Step 9 Writer Thin Member 化。

### 11.28 执行记录：2026-07-02 Step 8 收尾审计

目标：

- 补齐最后一个通用 prompt 拼接点。
- 核对 Step 8：Prompt / Memory / Verification 是否已经形成 Core contract，记录完成边界。

已完成：

- `core/src/lamtools_core/prompt/__init__.py`
  - 新增 `format_prompt_sections()`。
  - Core 负责稳定的 heading + sections prompt 拼接规则。
- `core/tests/test_prompt.py`
  - 增补 section prompt formatting 测试。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - hook context system message 改为使用 Core `format_prompt_sections()`。

验证：

- `py -3.14 -m pytest core\tests\test_prompt.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_hook_context_contract.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_core_kernel_adapter.py -q`
- `rg -n "prompt|PromptPart|prompt_parts_to_messages|VerificationResult|CompletionVerifier|verify_written_tool_results|MemoryEntry|hits_to_prompt_parts|session_memory_summary|recall_session|NovelMemoryWriteback" core/src members/writer/backend/app/core members/writer/backend/app/services -g "*.py"`

验证备注：

- Core prompt tests 13 passed。
- Writer hook context contract tests 15 passed。
- Writer Core kernel adapter tests 172 passed。
- 扫描显示：
  - Core 已持有 `PromptPart`、prompt ordering、prompt section formatting、token budget/truncation。
  - Core 已持有 memory protocol、memory budget、memory hit → prompt part、session memory summary formatting。
  - Core 已持有 `VerificationResult` 和通用 write/edit tool result verification。
  - Writer 剩余 prompt 代码是 persona / prompt file loading / platform / project instructions / skill index。
  - Writer 剩余 memory 代码是 Novel 领域记忆和 Writer DB persistence adapter。
  - Writer 剩余 verification 代码是 CompletionVerifier 的产品级完成判断。

Step 8 完成边界：

- 已进入 Core：
  - prompt part ordering、prompt message metadata contract、section formatting、prompt budget/truncation；
  - memory protocol、recall result type、budget、memory prompt part conversion、session memory summary formatting；
  - verification result contract、write/edit tool result verification、completion verifier 的命令执行复用 Core command contract。
- 保留 Writer：
  - Writer persona / execution discipline / platform prompt / prompt file override 策略；
  - project instruction 文件选择；
  - skill index 内容和 `load_skill` 工具；
  - Novel memory writeback / Novel state extraction；
  - CompletionVerifier 的产品级完成定义、browser E2E、mock 策略和 repair prompt；
  - `recall_session` 目前只有 schema/tool spec/permission 声明，没有生产 executor 主路径，后续 Step 9 处理工具清单时应补齐或删除。

下一步：

- 进入 Step 9：Writer Thin Member 化。先审计 Writer backend runtime 文件形态和行数，识别 `adapter.py` / `kit.py` / `tools.py` / `verification.py` / `prompts/` 等薄入口重组的最小安全切片。

### 11.29 执行记录：2026-07-02 Step 9 第一切片

目标：

- 启动 Step 9：Writer Thin Member 化。
- 先做低风险减法：删除 Writer 目录中只转发 Core toolkit 的无价值兼容壳。

基线审计：

- 最大运行文件仍是 `members/writer/backend/app/core/writer/core_kernel_adapter.py`，约 1856 行。
- `completion_verifier.py`、`tool_specs.py`、`agent_runtime.py` 仍是主要 Writer runtime 文件。
- 发现 4 个纯 Core wrapper：`tool_verification.py`、`write_tools.py`、`git_tools.py`、`web_tools.py`。

已完成：

- 删除：
  - `members/writer/backend/app/core/writer/tool_verification.py`
  - `members/writer/backend/app/core/writer/write_tools.py`
  - `members/writer/backend/app/core/writer/git_tools.py`
  - `members/writer/backend/app/core/writer/web_tools.py`
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - write/edit file handlers 改为直接从 Core workspace file toolkit 导入。
  - git handlers 改为直接从 Core git toolkit 导入，并显式注入 Core command runner。
  - web/browser handlers 改为直接从 Core web toolkit 导入。
- `members/writer/backend/tests/test_tool_contracts.py`
  - web tool monkeypatch 改为直接指向 Core web toolkit。

验证：

- `rg -n "app\.core\.writer\.(tool_verification|write_tools|git_tools|web_tools)|from app\.core\.writer import web_tools|from app\.core\.writer\.web_tools|from app\.core\.writer\.git_tools|from app\.core\.writer\.write_tools|from app\.core\.writer\.tool_verification" members/writer/backend/app members/writer/backend/tests -g "*.py"`
- `py -3.14 -m pytest members\writer\backend\tests\test_tool_contracts.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest core\tests\test_git_tools.py core\tests\test_web_tools.py core\tests\test_workspace_files.py -q`

验证备注：

- 旧 Writer wrapper 导入扫描无匹配。
- Writer tool contracts tests 33 passed。
- Writer Core kernel adapter tests 172 passed。
- Core git/web/workspace file tests 11 passed。

当前收缩：

- Writer runtime 目录减少 4 个无业务 wrapper。
- 通用 file/git/web/verification 主路径直接使用 Core。

下一步：

- Step 9 第二切片：继续收缩 Writer runtime 文件形态，优先审计 `core_kernel_adapter.py` 内可移动到薄入口模块的 Writer-specific block，避免一次性大拆。

### 11.30 执行记录：2026-07-02 Step 9 第二切片

目标：

- 继续 Writer Thin Member 化。
- 从 `core_kernel_adapter.py` 中拆出一个语义独立、低风险的 Writer-specific block，减少 Kernel adapter 文件体量。

已完成：

- `members/writer/backend/app/core/writer/llm_bridge.py`
  - 新增 `WriterLLMClientAdapter`。
  - 新增内部 `_WriterToCoreBridge`。
  - 承载 Writer `.chat_full()` / OpenAI-compatible stream 到 Core `LLMClient` / `LLMStreamEvent` 的桥接逻辑。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - 删除原 LLM bridge 实现。
  - 仅从 `llm_bridge.py` 导入 `WriterLLMClientAdapter`，保留旧模块导入兼容路径。
  - 文件行数从约 1856 行降到 1683 行。
- `members/writer/backend/tests/test_writer_core_kernel_adapter.py`
  - streaming tests 的 HTTP client monkeypatch 从旧 `core_kernel_adapter.httpx.AsyncClient` 改到 `runtime_resources.httpx.AsyncClient`，匹配实际 stream client 生命周期入口。

验证：

- `py -3.14 -m py_compile members\writer\backend\app\core\writer\llm_bridge.py members\writer\backend\app\core\writer\core_kernel_adapter.py members\writer\backend\tests\test_writer_core_kernel_adapter.py`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_tool_contracts.py members\writer\backend\tests\test_prompt_assembler.py -q`
- `rg -n "core_kernel_adapter\.httpx|WriterLLMClientAdapter|_WriterToCoreBridge|build_openai_payload|merge_tool_call_deltas|normalize_usage|resolve_tool_calls|build_profiled_openai_request|normalize_stream_chunk_with_profile|resolve_adapter_profile" members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/app/core/writer/llm_bridge.py members/writer/backend/tests/test_writer_core_kernel_adapter.py`

验证备注：

- Writer Core kernel adapter tests 172 passed。
- Writer tool contracts + prompt assembler tests 42 passed。
- 扫描显示 provider payload / stream chunk 相关桥接逻辑已从 `core_kernel_adapter.py` 移到 `llm_bridge.py`；旧测试仍可从 `core_kernel_adapter` 导入 `WriterLLMClientAdapter`。

当前收缩：

- `core_kernel_adapter.py` 少一个大块 LLM bridge 逻辑。
- Writer LLM bridge 成为独立薄入口，后续可继续和 provider/config 代码收敛。

下一步：

- Step 9 第三切片：继续拆 `core_kernel_adapter.py`，优先处理 `ReadWriteToolExecutor` / tool assembly 或 sub-agent dispatch helper，保持每刀可验证。

### 11.31 执行记录：2026-07-02 Step 9 第三切片

目标：

- 继续 Writer Thin Member 化。
- 将 `ReadWriteToolExecutor` / default tool assembly 从 `core_kernel_adapter.py` 拆到薄入口模块。

已完成：

- `members/writer/backend/app/core/writer/tools.py`
  - 新增 `ReadWriteToolExecutor`。
  - 新增 `resolve_tool_executor()`。
  - 集中 Writer 默认工具组合：Core file/git/web toolkit、Writer command tools、management tools。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - 删除原 `ReadWriteToolExecutor` 实现。
  - 删除原 `_resolve_tool_executor()` 实现。
  - 从 `tools.py` 导入并 re-export `ReadWriteToolExecutor`，保留旧测试和服务导入兼容。
  - 文件行数从约 1683 行降到 1519 行。

验证：

- `py -3.14 -m py_compile members\writer\backend\app\core\writer\tools.py members\writer\backend\app\core\writer\core_kernel_adapter.py members\writer\backend\tests\test_writer_core_kernel_adapter.py members\writer\backend\tests\test_tool_contracts.py`
- `py -3.14 -m pytest members\writer\backend\tests\test_tool_contracts.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_core_kernel_adapter.py -q`

验证备注：

- Writer tool contracts tests 33 passed。
- Writer Core kernel adapter tests 172 passed。
- 旧 `core_kernel_adapter.ReadWriteToolExecutor` 导入路径仍可用。

当前收缩：

- Writer default tool assembly 成为独立 `tools.py` 薄入口。
- `core_kernel_adapter.py` 更接近只保留 WriterKit / run_core_kernel 主线。

下一步：

- Step 9 第四切片：继续拆 `core_kernel_adapter.py` 中 sub-agent dispatch / tool result formatting / writeback 之一，优先选择无状态 helper 或可独立测试的 Writer-specific block。

### 11.32 执行记录：2026-07-02 Step 9 第四切片

目标：

- 继续 Writer Thin Member 化。
- 优先拆低风险的工具结果反馈逻辑：失败提示、结构化错误摘要、sub-agent 结果事实、tool-role message 组装。

已完成：

- `members/writer/backend/app/core/writer/tool_feedback.py`
  - 承接 `agent_failure_reason()`。
  - 承接 `agent_tool_facts_for_model()`。
  - 承接 `format_tool_result_for_model()`。
  - 与既有 `tool_error_hint()` / `tool_structured_error_summary()` 放在同一反馈边界内。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - 删除 WriterKit 内部的 sub-agent 失败原因、sub-agent 事实拼装、tool-role message 组装实现。
  - 保留 `WriterKit.format_tool_result_for_model()` 公开签名，内部只委托给 `tool_feedback.py`，避免影响 Core loop contract 和旧测试导入。

验证：

- `py -3.14 -m py_compile members\writer\backend\app\core\writer\tool_feedback.py members\writer\backend\app\core\writer\core_kernel_adapter.py`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_tool_contracts.py -q`

验证备注：

- Writer Core kernel adapter tests 172 passed。
- Writer tool contracts tests 33 passed。
- 本切片没有改变工具执行、权限、MCP、sub-agent dispatch 主路径，只移动给模型看的反馈格式化边界。

当前收缩：

- `core_kernel_adapter.py` 继续向 WriterKit / run entry 靠拢。
- 工具失败反馈和 sub-agent 结果事实不再散落在主 adapter 内。
- 本切片为结构归位，净代码量接近持平；收益主要是让后续 writeback / verifier / dispatch 拆分时不再和反馈文案混在一起。

下一步：

- Step 9 继续：评估 `writeback()`、`execute_tool()`、completion verifier wrapper 是否仍有小切片净收益；若剩余拆分只会制造浅 wrapper，则转入 Step 9 阶段性结构验收并准备 Step 10 Artist thin member 接入。

### 11.33 执行记录：2026-07-02 Step 9 第五切片

目标：

- 继续 Writer Thin Member 化。
- 拆出重复工具失败熔断判断，让 WriterKit 不再承载工具失败保护细节。

已完成：

- `members/writer/backend/app/core/writer/tool_failure.py`
  - 新增 `should_stop_repeated_failure()`。
  - 复用既有 `tool_failure_signature()`，集中管理重复失败签名、历史状态计数、`drift_warning` 写入。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - `_should_stop_repeated_failure()` 改为薄委托。
  - 保留 `WriterKit._tool_failure_signature()` / `_tool_failure_context()` / `_looks_like_test_assertion_failure()` 静态兼容路径，避免破坏旧测试和外部调用。

验证：

- `py -3.14 -m py_compile members\writer\backend\app\core\writer\tool_failure.py members\writer\backend\app\core\writer\core_kernel_adapter.py`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_tool_contracts.py -q`

验证备注：

- Writer Core kernel adapter tests 172 passed。
- Writer tool contracts tests 33 passed。
- 熔断行为仍由现有重复失败测试覆盖，未改变对模型、工具或 Core loop 的外部契约。

当前收缩：

- 工具失败签名、失败上下文、断言失败识别、重复失败熔断已集中在 `tool_failure.py`。
- `core_kernel_adapter.py` 中失败保护逻辑进一步变薄，只保留 RuntimeKit 决策入口。

下一步：

- Step 9 进入阶段性结构验收：重点判断剩余 `execute_tool()`、`writeback()`、completion verifier wrapper 是否仍值得拆，避免为了行数制造浅 wrapper。

### 11.34 执行记录：2026-07-02 Step 9 阶段验收

目标：

- 对 Writer Thin Member 化当前成果做阶段性验收。
- 明确哪些拆分已经完成，哪些剩余职责暂不继续细碎拆分。

验收结论：

- `members/writer/backend/app/core/writer/core_kernel_adapter.py` 当前约 1409 行，已经从早期大而全 adapter 收缩为 WriterKit / run entry 主线。
- 旧 Writer Core wrapper 已删除：
  - `tool_verification.py`
  - `write_tools.py`
  - `git_tools.py`
  - `web_tools.py`
- LLM bridge 已移入 `llm_bridge.py`。
- 默认工具组合已移入 `tools.py`。
- 工具失败提示、结构化错误摘要、sub-agent 结果事实、tool-role message 组装已集中在 `tool_feedback.py`。
- 工具失败签名、失败上下文、断言失败识别、重复失败熔断已集中在 `tool_failure.py`。

保留边界：

- `execute_tool()` 暂留 WriterKit：
  - 仍承担 Agent / MCP / approval / pending test repair / injected executor 的 RuntimeKit 调度入口。
  - 继续拆分容易变成浅 wrapper，短期净收益不足。
- `writeback()` 暂留 WriterKit：
  - 当前只做 task plan 写回和 active plan 同步，体量较小。
  - 后续若 task plan 状态机继续扩张，再迁入 `task_plan.py`。
- completion verifier wrapper 暂留 WriterKit：
  - Writer 的“可交付完成”定义仍是产品级验收，不能下沉 Core。
  - 当前 wrapper 只负责触发条件和 repair prompt 接入，不再继续拆。

验证：

- `rg -n "from app\.core\.writer\.(tool_verification|write_tools|git_tools|web_tools)|core_kernel_adapter\.(httpx|_tool_error_hint|_tool_structured_error_summary)|def _agent_failure_reason|def _agent_tool_facts_for_model" members/writer/backend/app members/writer/backend/tests -g "*.py"`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_core_kernel_adapter.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_tool_contracts.py -q`

验证备注：

- 旧 wrapper / 旧反馈 helper 扫描无残留。
- Writer Core kernel adapter tests 172 passed。
- Writer tool contracts tests 33 passed。

下一步：

- 不继续为了行数拆 WriterKit。
- 总计划应回到 Step 10 之后的主线缺口：OperationCatalog / MemberKit / scaffold / 最终验收，优先确认当前文档中 Step 10 已完成记录与实际代码状态一致。

### 11.35 执行记录：2026-07-02 Step 11 第一切片

目标：

- 开始 Step 11：Scaffold 更新。
- 新 member scaffold 从生成时就是薄 member 包，不复制 Writer runtime、provider parser、SSE manager 或模板运行产物。

已完成：

- `scripts/scaffold-member.ps1`
  - 复制模板时跳过 `__pycache__` 和 `.pyc`。
  - 更新完成提示：优先填写 `backend/app/member/` 下的 prompts、tools、verification；业务 router 只用于产品 API。
- `core/templates/member/backend/app/member/`
  - 新增 `manifest.py`，集中 `MemberManifest`。
  - 新增 `kit.py`，使用 Core `StaticMemberKit`。
  - 新增 `prompts.py`，提供 `PromptFragment` 示例。
  - 新增 `tools.py`，提供空 `ToolSpec` 列表作为产品工具入口。
  - 新增 `verification.py`，提供 `VerificationPolicy` 示例。
- `core/templates/member/backend/app/main.py`
  - 改为从 `app.member` 导入 manifest，不再在 app 入口内直接内联 manifest。
- `core/templates/member/backend/tests/test_member_kit.py`
  - 新 member 默认带 manifest / kit 一致性测试。
- `core/tests/test_member_template.py`
  - 覆盖模板必须包含薄 member package。
  - 覆盖模板不得包含 `__pycache__` / `.pyc`。
  - 覆盖 `main.py` 必须使用 member manifest module。
- 模板文档同步：
  - `core/templates/member/AGENTS.md`
  - `core/templates/member/README.md`
  - `core/templates/member/docs/onboarding.md`

验证：

- `py -3.14 -m pytest core\tests\test_member_template.py -q`
- `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\scaffold-member.ps1 -Id codexprobe -Name LamCodexProbe -DisplayName LamCodexProbe -Capabilities code -DryRun`
- 真实 probe：
  - `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\scaffold-member.ps1 -Id codexprobe -Name LamCodexProbe -DisplayName LamCodexProbe -Capabilities code`
  - `PYTHONPATH=E:\LamTools\core\src;E:\LamTools\members\codexprobe\backend py -3.14 -m py_compile ...`
  - `PYTHONPATH=E:\LamTools\core\src;E:\LamTools\members\codexprobe\backend py -3.14 -m pytest members\codexprobe\backend\tests\test_member_kit.py -q`
- probe 验证后已删除 `members/codexprobe` 和 `codexprobe.cmd`。

验证备注：

- Core member template tests 3 passed。
- scaffold dry-run 输出包含 `backend/app/member/kit.py`、`manifest.py`、`prompts.py`、`tools.py`、`verification.py`。
- 临时生成 member 后端编译通过。
- 临时生成 member 默认测试 1 passed。

当前收缩：

- 新 member 模板不再把 manifest、kit、prompt、tool、verification 当作后续人工补丁。
- scaffold 已具备防运行产物复制的脚本保护。
- Step 11 的第一条验收“新 member scaffold 不生成 runtime、provider parser、SSE manager”有模板结构和测试保护。

下一步：

- 继续 Step 11：决定是否让 scaffold 同步注册 `scripts/dev.ps1` / `build.ps1` / `test.ps1`，或进入 Step 12 最终验收扫描，按旧事件族、TaskManager SSE、Writer SSE 反向适配、Core 产品名污染逐项出证据。

### 11.36 执行记录：2026-07-02 Step 12 第一切片

目标：

- 开始 Step 12 最终验收扫描。
- 先处理当前扫描中最明确的 Core 产品名污染，避免 Core contract 中继续出现 Writer 专有命名。

扫描发现：

- `core/src/lamtools_core/llm/profiles.py` 注释仍提到 Writer。
- `core/src/lamtools_core/tool/mcp_tools.py` 使用 `writer_name` 表示 MCP tool name。
- `core/src/lamtools_core/tool/sub_agent.py` 的项目 sub-agent 定义默认写入 `.writer/agents`。

已完成：

- `core/src/lamtools_core/llm/profiles.py`
  - 注释改为 product members。
- `core/src/lamtools_core/tool/mcp_tools.py`
  - `writer_name` 改为 `tool_name`，保持 MCP call 行为不变。
- `core/src/lamtools_core/tool/sub_agent.py`
  - 项目 sub-agent 定义默认路径改为 `.lamtools/agents`。
- `members/writer/backend/app/core/writer/agent_runtime.py`
  - 项目 sub-agent 读取顺序改为 `.lamtools/agents` 优先。
  - 保留 `.writer/agents` 和 `.claude/agents` 读取兼容。
- 测试同步：
  - `core/tests/test_mcp_tools.py`
  - `members/writer/backend/tests/test_agent_runtime.py`
  - `members/writer/backend/tests/test_writer_app_server_protocol.py`

验证：

- `py -3.14 -m pytest core\tests\test_mcp_tools.py core\tests\test_sub_agent_tools.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_agent_runtime.py -q -k "project_sub_agent_definition or legacy_writer_project_sub_agent or runtime_uses_project_sub_agent"`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_app_server_protocol.py -q -k "subagent"`
- `rg -n "Writer|Artist|LamWriter|LamArtist|writer|artist|\.writer" core/src/lamtools_core --glob "*.py"`

验证备注：

- Core MCP / sub-agent tests 13 passed。
- Writer agent runtime targeted tests 4 passed，18 deselected。
- Writer app-server subagent tests 2 passed，53 deselected。
- Core 产品名扫描无命中。

当前遗留：

- App Server 仍保留 `WriterAppEvent*` 命名；需要在后续 Step 12 判断它是产品 app-server envelope 合理命名，还是旧 Writer SSE / CoreEvent 反向适配残留。
- Writer/Artist targeted tests、真实 smoke 和最终历史维护标注仍未完整跑完。

下一步：

- 继续 Step 12：对 App Server `WriterAppEvent*` / ledger / hub / reducer 做专项审计，判断是否需要重命名或记录为产品 app-server 边界；随后跑 Core / Writer / Artist targeted tests。

### 11.37 执行记录：2026-07-02 Step 12 第二切片

目标：

- 继续 Step 12 最终验收。
- 对 Writer App Server 事件命名做专项审计。
- 跑 Core / Writer / Artist targeted tests，形成当前验收证据。

专项审计结论：

- `WriterAppEventEnvelope` / `WriterAppEventHub` / `WriterAppEvent` 当前属于 Writer app-server 的 JSON-RPC envelope / DB row / websocket fan-out 边界。
- Writer runtime 主载荷已经通过 `CORE_RUN_ITEM_METHOD = "core/runItem"` 写入 app-server ledger。
- `runtime_bridge.py` 当前接收的是 Core `RunItemEvent`，并调用 `append_run_item_event_and_apply_snapshot()`；没有把 Writer-local runtime event 反向适配成 CoreEvent。
- 前端 app-server client 消费 websocket JSON-RPC notification，不是旧 SSE endpoint。
- 因此本切片不重命名 `WriterAppEvent*`；将它记录为 Writer 产品 app-server envelope 命名，而不是旧 Writer SSE 产品链路。

扫描：

- `rg -n "WriterRuntimeEvent|AppEvent|TaskManager|SessionEventHub|publish_artist_event|publish_task_event|WriterAppEvent|Writer SSE|CoreEvent" members/writer/backend/app members/writer/frontend/src members/artist/backend/app members/artist/frontend/src core/src/lamtools_core --glob "*.py" --glob "*.ts" --glob "*.vue"`
- `rg -n "build_openai_payload|normalize_stream_chunk_with_profile|normalize_response_with_profile|build_profiled_openai_request|resolve_adapter_profile|provider parser|response path" members/writer/backend/app members/artist/backend/app core/src/lamtools_core --glob "*.py"`
- `rg -n "EventSource|text/event-stream|/events/live|sessions/.*/events|WriterAppEvent|core/runItem|snapshot.core" members/writer/frontend/src members/writer/backend/app -g "*.py" -g "*.ts" -g "*.vue"`

扫描备注：

- Core 产品名扫描在上一切片已清零。
- Writer `WriterAppEvent*` 命中集中在 app-server envelope / ledger / hub / reducer / DB row。
- Writer tests 明确断言 runtime envelope method 为 `core/runItem`。
- Artist `TaskManager` / `SessionEventHub` / `publish_artist_event` / `publish_task_event` 生产路径未重新出现。
- `event_type/payload` 这类通用词仍不能作为失败条件；Artist event 输出已用 `name/data`，大量 provider / image / debug payload 是合法业务数据。

Targeted tests：

- `py -3.14 -m pytest core\tests\test_agent_app_contract.py core\tests\test_member_template.py core\tests\test_mcp_tools.py core\tests\test_sub_agent_tools.py core\tests\test_runtime_event_hub.py -q`
- `py -3.14 -m pytest core\tests\test_runtime_projection.py core\tests\test_run_item_snapshot.py core\tests\test_http_routes.py -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_writer_app_server_protocol.py members\writer\backend\tests\test_writer_core_kernel_adapter.py members\writer\backend\tests\test_tool_contracts.py -q`
- `py -3.14 -m pytest members\artist\backend\tests\test_artist_core_kernel_adapter_unit.py members\artist\backend\tests\test_core_http_artist_unit.py members\artist\backend\tests\test_session_event_hub_unit.py members\artist\backend\tests\test_task_events_unit.py members\artist\backend\tests\test_task_progress_unit.py members\artist\backend\tests\test_artist_cli_unit.py -q`
- `py -3.14 -m pytest members\artist\backend\tests\test_artist_pipeline.py -q -k "sse_event_payload_integrity"`

验证备注：

- Core contract / scaffold / runtime event hub tests 22 passed。
- Core runtime projection / snapshot / HTTP route tests 49 passed。
- Writer app-server / core kernel adapter / tool contracts tests 260 passed，1 unraisable transport warning。
- Artist core kernel / Core HTTP / event hub / task events / CLI tests 113 passed。
- Artist pipeline SSE payload integrity targeted test 1 passed，13 deselected。

当前遗留：

- Step 12 的真实 smoke 尚未执行：CLI run、GUI turn、approval、refresh、tool call。
- 历史审计文档维护标注尚未系统更新。
- 最终完成不能只靠 targeted tests，需要至少一次当前环境真实启动/交互验证或明确记录不可运行原因。

下一步：

- Step 12 第三切片：启动 Writer/Artist 可运行面，跑最小真实 smoke；若环境已有服务，先检查原因和端口，再复用或启动。

### 11.38 执行记录：2026-07-02 Step 12 第三切片

目标：

- 补 Step 12 真实 smoke。
- 覆盖 Writer 可运行面、approval 响应链路、Artist CLI mock turn 和图片工具链。

Writer smoke：

- 启动临时 Writer 后端：`py -3.14 -m uvicorn app.main:app --port 6173`。
- 启动临时 Writer 前端：`npm run dev -- --host 127.0.0.1 --port 6174`。
- `Invoke-WebRequest http://127.0.0.1:6173/api/health` 返回 200，body 为 `{"status":"ok","app":"LamWriter","writer_service":"ok"}`。
- `Invoke-WebRequest http://127.0.0.1:6174` 返回 200。
- `py -3.14 scripts\member_cli.py writer health` 返回同一健康检查 JSON。
- `py -3.14 scripts\member_cli.py writer session new codex-smoke-session` 创建会话 `8d3f4c4871f64b80963da301a65f5d6c`。
- `py -3.14 scripts\member_cli.py writer session show 8d3f4c4871f64b80963da301a65f5d6c` 显示会话存在，初始 `idle`。

Approval smoke：

- 使用 `members\writer\backend\scripts\seed_app_server_approval.py` 注入 approval request `codex-smoke-approval`。
- 注入后：
  - `py -3.14 scripts\member_cli.py writer session status 8d3f4c4871f64b80963da301a65f5d6c` 显示 `status waiting phase=waiting`。
  - `py -3.14 scripts\member_cli.py writer session result 8d3f4c4871f64b80963da301a65f5d6c` 显示 `status waiting phase=waiting`。
- 通过 app-server websocket 调用 `approval.respond`，decision 为 `approve_once`。
- 数据库 `writer_app_events` 回读确认：
  - seq 5：method `core/runItem`，kind `approval_response`，status `completed`。
  - seq 6：method `serverRequest/resolved`，status `resolved`，decision `approve_once`。

Approval 备注：

- 人工 seed 的 approval 没有完整 runtime continuation 上下文；响应后会话状态落到 `failed`。
- 本次只把它作为 app-server approval 响应、Core run item 落库、resolved event 回放链路验证，不把它当作完整模型 turn 成功证据。

Artist smoke：

- 先用临时 `LAMARTIST_DATA_DIR=.codex-smoke-logs\artist-data` 和 dummy provider 跑 `py -3.14 scripts\member_cli.py artist run "codex smoke image" --mock all --image-count 1 --compact`。
- 首次结果：命令 120s 超时；临时数据库只写入 user message，没有 agent/image 消息。
- 根因：Artist CLI mock 只识别旧 `runtime_state.visible_artifacts`，Step 10 以后 Core tool writeback 给模型的是 tool message，内容包含 `Generated image URLs:`；mock 没识别到已生成图片，于是持续要求下一轮生成。

已完成修复：

- `members/artist/backend/app/cli.py`
  - `_mock_messages_have_visible_output()` 增加 Core tool result 识别：tool message 中出现 `Generated image URLs:` 即视为已有可见输出。
- `members/artist/backend/tests/test_artist_cli_unit.py`
  - 新增回归测试，锁定 Core tool result 识别。

验证：

- `py -3.14 -m pytest members\artist\backend\tests\test_artist_cli_unit.py -q`
- 使用临时 `LAMARTIST_DATA_DIR=.codex-smoke-logs\artist-data-3` seed dummy provider 后执行：
  - `py -3.14 -m app.cli --mock all --image-count 1 --compact "codex smoke image"`

验证备注：

- Artist CLI unit tests 14 passed。
- Artist mock turn 5s 内完成。
- 输出包含：
  - `tool generate_image`
  - `image_response`
  - `verify passed`
  - `done ✓`
  - `completed images=1`
  - artifact URL：`http://127.0.0.1:6171/generated/mock_d61f723322ae.png`

当前收缩：

- Step 12 的真实启动面已覆盖 Writer backend/frontend health、Writer CLI session、Writer approval response、Artist mock image direct command、Artist full mock turn。
- Artist CLI mock 已重新对齐 Core tool writeback，不再依赖旧 runtime payload 形态。

当前遗留：

- Writer GUI 只验证了前端可加载，未通过浏览器人工/自动点击跑完整真实模型 turn。
- Writer approval smoke 是 seed 场景，不等同于真实模型触发审批后的 continuation 成功。
- 真实 LLM provider 环境未作为本轮验收前提；当前烟测以本地 mock/seed 链路为主。

下一步：

- 清理临时 Writer 服务和 `.codex-smoke-logs`。
- 跑本切片受影响测试与 diff check。
- 提交本切片：Artist mock 修复 + Step 12 smoke 记录。

### 11.39 执行记录：2026-07-02 Step 12 第四切片

目标：

- 补最终历史审计文档维护标注。
- 明确哪些旧图示/审计结论已不再代表当前实现。

已完成：

- `docs/complexity-and-loc-review-2026-06-30.md`
  - 增加 2026-07-02 Step 12 后维护标注。
  - 明确本文主体仍是历史复审；旧 TaskManager SSE、Writer SSE -> CoreEvent 反向适配、Artist 旧生命周期事件、Writer provider parser 主线不再全部代表当前实现。
- `docs/agent-architecture-north-star-2026-06-30.md`
  - 增加 2026-07-02 Step 12 后维护标注。
  - 明确 North Star 仍有效，但当前实现状态以本设计文档 Step 12 记录为准。
- `docs/writer-full-chain.md`
  - 增加 2026-07-02 Step 12 后维护标注。
  - 明确下方 Mermaid 是历史链路，不再代表当前运行主线。
- `members/writer/docs/writer-sse-presentation-map.md`
  - 增加 2026-07-02 Step 12 后维护标注。
  - 明确旧 Writer SSE 入口和 canonical Writer SSE 事件族已经不是生产主线。
- `members/artist/docs/architecture.md`
  - 增加 2026-07-02 Step 12 后维护标注。
- `members/artist/docs/architecture.zh-CN.md`
  - 增加 2026-07-02 Step 12 后维护标注。

验证：

- `rg -n "旧事件族|Writer SSE|provider parser|TaskManager|SessionEventHub|runtime_fact|维护标注|CoreEvent|WriterRuntimeEvent|core-member|architecture refactor|架构重构" docs core members -g "*.md"`
- 人工核对高命中文档，优先维护仍会误导当前架构判断的文档。

验证备注：

- 多数历史文档已存在 2026-06-30 / 2026-07-01 维护标注。
- 本切片补的是仍在顶部或入口处容易误导读者的总审计 / 全链路 / Writer SSE / Artist 架构文档。
- `members/artist/docs/architecture*.md` 使用 UTF-8 读写在文件头插入英文维护标注，避免 PowerShell 中文正文编码污染。

当前收缩：

- 历史文档不再静默声称旧 TaskManager/SSE/CoreEvent 反向适配是当前事实。
- 当前实现状态集中指向本设计文档 Step 12 记录。

当前遗留：

- 未重写所有历史 Mermaid 和旧表格；这些内容保留为历史上下文。
- Writer GUI 真实模型 turn、真实 approval continuation 仍需在有可用 provider / 人工浏览器条件时补验。

下一步：

- 跑文档切片 diff check。
- 提交 Step 12 第四切片。
- 做最终完成判定：若以当前环境验收为准，可标记“代码/文档计划完成，真实 provider GUI 验收待人工补测”；若必须包含真实模型 GUI turn，则目标不能标记 complete。

### 11.40 执行记录：2026-07-02 Step 12 完成判定

目标：

- 对 Step 12 做最终要求对照。
- 明确当前能宣称完成的范围和不能伪装完成的验收项。

最终扫描：

- `rg -n "Writer|Artist|LamWriter|LamArtist|writer|artist|\.writer" core/src/lamtools_core --glob "*.py"`
  - 无命中。
- `rg -n "WriterRuntimeEvent|WriterStepEvent|writer_git_|writer_part_updated|core_adapter|TaskManager|SessionEventHub|publish_artist_event|publish_task_event|/api/sessions/events|runtime-events" members/writer/backend/app members/writer/frontend/src members/artist/backend/app members/artist/frontend/src core/src/lamtools_core -g "*.py" -g "*.ts" -g "*.vue"`
  - 无命中。

已完成范围：

- 执行计划已成文：`docs/core-member-architecture-refactor-execution-plan-2026-07-01.md`。
- 执行计划已链接目标设计文档。
- 每个主要切片已追加执行记录到本设计文档。
- Step 1-12 的核心代码迁移、删除、scaffold 更新、Writer thin member、Artist thin member、Core 产品名清理已完成。
- Core / Writer / Artist targeted tests 已形成记录。
- 本地 smoke 已覆盖：
  - Writer backend health 200。
  - Writer frontend HTTP 200。
  - Writer CLI session create/show/status/result。
  - Writer app-server approval response -> `core/runItem` approval_response -> `serverRequest/resolved`。
  - Artist direct image mock command。
  - Artist full mock turn：tool call、image_response、verify passed、done、artifact。
- 历史审计文档已加当前状态维护标注。

未完成 / 待外部条件补验：

- Writer GUI 没有跑真实浏览器点击后的完整模型 turn。
- Writer approval smoke 使用 seed request，验证了响应/落库/回放链路，但没有验证真实模型触发审批后的 continuation 成功。
- 真实 provider 环境没有纳入本轮自动验收；当前验收以本地 mock/seed 和 targeted tests 为准。

完成判定：

- Core/Member 架构重构的代码收敛、文档计划、执行记录、scaffold、targeted tests、本地 smoke：完成。
- 真实 provider GUI turn 和真实 approval continuation：待人工或有 provider 环境时补测。
- 因此本目标可以标记为“当前环境下完成”，但后续验收清单必须保留上述两个外部条件项，不能把它们写成已验证。

### 11.41 执行记录：2026-07-02 Step 7/9/12 补充收缩

目标：

- 按重新审查后的职责边界修正 Step 7 / Step 9 遗留问题。
- Core 提供通用 tool 能力；Writer 决定怎么启用、怎么授权、怎么用于编码任务。
- `sub_agent` 属于 Core 能力，但调度策略属于 member。
- Git 不再被归类为 Core 通用工具；它是编码/VCS 场景能力，不能混入基础 agent 最小骨架。
- Writer 不再保留独立 command runtime，也不继续保留 Novel / architecture agent 这类非编码适配能力。

已完成：

- 将 Writer 私有 command runner / command handlers 下沉到 `core/src/lamtools_core/tool/`：
  - `command_runner.py`
  - `command_tools.py`
- Writer 原路径保留薄兼容 shim，当前生产工具装配从 Core command handlers 引入。
- 归档并从 active tree 删除 Writer Novel 能力：
  - `members/writer/backend/app/core/writer/novel/`
  - `members/writer/backend/app/routers/novel.py`
  - `members/writer/backend/app/services/novel_service.py`
  - 对应 Novel 测试。
- 归档并从 active tree 删除 Writer architecture agent 能力：
  - `members/writer/backend/app/core/writer/agents/`
  - `architecture_handoff.py`
  - `design_scoring.py`
  - `runtime_feasibility.py`
  - 对应 architecture/design pipeline 测试。
- 清理生产引用：
  - Writer app manifest 不再声明 `novel` capability / route。
  - 模型路由只保留 `writer` 与 `sub_agent`。
  - `architecture_agent` 不再出现在工具 schema、权限表、model tool order、agent registry、Core adapter handoff 注入路径。
  - sub-agent workspace 不再复制 architecture handoff 专用上下文。
- 测试同步为新的边界：
  - 默认 agent registry 只暴露 `sub`。
  - `architecture_agent` 在 action type / permission / registry 中明确不可见。
  - Core HTTP manifest 测试不再期待 Novel route。

验证：

- `py -3.14 -m compileall core\src\lamtools_core members\writer\backend\app -q`
- `py -3.14 -m pytest members\writer\backend\tests\test_agent_runtime.py members\writer\backend\tests\test_model_routing_config.py members\writer\backend\tests\test_schemas.py members\writer\backend\tests\test_core_http_writer_unit.py members\writer\backend\tests\test_tool_contracts.py members\writer\backend\tests\test_permission.py -q`
- 结果：140 passed。

验证备注：

- Windows pytest 结束时仍出现一次 asyncio closed pipe unraisable warning；断言全部通过，暂不归因到本切片。
- active production 扫描中 `novel_router`、`app.core.writer.novel`、`ArchitectureAgent`、`architecture_handoff`、`design_scoring`、`runtime_feasibility` 已无命中。

当前收缩：

- Writer 删除了两个非编码适配能力面：Novel 与 architecture agent。
- Writer 的 command 执行实现不再是 member 私有 runtime，已下沉到 Core tool 层。
- Writer 保留的是“编码任务如何使用 Core 工具和 sub_agent”的 member 决策层，不再复制底层运行实现。

下一步：

- 继续将 Writer `core_kernel_adapter.py` 中通用 tool assembly / prompt assembly / verification wrapper 拆向 Core，保留 WriterKit 领域策略。
- 单独审查 Git：保留为 coding member / VCS 能力，不放入 Core 最小通用 agent 骨架。
