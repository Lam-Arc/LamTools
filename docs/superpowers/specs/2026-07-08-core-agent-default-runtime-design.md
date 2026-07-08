# Core Agent Default Runtime Design

## 目标

让 `core/` 从“可装配的 Agent 能力集合”升级为“可独立运行的基础 Core Agent”。Writer 继续作为产品 member 存在，但通过字段化配置接入 Core Agent 链路，不再重复实现 Core 已经拥有的会话、事件、快照、授权和通用入口能力。

## 验收标准

- Core Agent 可以在没有 Writer 的情况下独立运行一轮任务。
- Core Agent 有默认工具包、权限门、会话、事件、快照和可替换存储。
- Core Agent 的持久化链路与 Writer app-server 当前事实源相对一致：事件按线程递增，快照由事件归约，刷新读快照。
- Writer 通过配置字段指定自己的 member id、数据目录、工作目录、表模型或表名前缀、提示词和专用工具。
- Writer 原有功能继续可用：项目、附件、队列、审批、命令、模型配置、快照刷新。
- Writer 不再复制 Core 能力；允许保留 Writer 专属投影和业务能力。

## 成熟方案对齐

OpenAI Agents SDK 的成熟形态是：Agent 定义 instructions/tools/model，Runner 执行，sessions 保存上下文，工具调用和 handoff 是运行时事实。Claude Code 的成熟形态是：工具和权限在执行前拦截，设置与权限集中管理，产品能力通过配置和 hooks 扩展。LamTools 的设计对齐这两点：

- Core 管默认 Agent 运行、工具注册、权限、事件、快照和入口。
- Member 只提供业务字段和产品能力，不复制运行时主链路。
- 审批状态必须进事件和快照，不能只停留在 UI 或临时变量里。

参考：

- OpenAI Agents SDK: https://openai.github.io/openai-agents-python/
- OpenAI Agents concepts: https://platform.openai.com/docs/guides/agents
- Anthropic Claude Code settings and permissions: https://docs.anthropic.com/en/docs/claude-code/settings
- Anthropic Claude Code hooks: https://docs.anthropic.com/en/docs/claude-code/hooks

## 方案

推荐方案：**Core Default Agent + Member Adapter**。

新增 Core 默认装配层，但不让 Core 认识 Writer：

- `CoreAgentSpec`：默认 Agent 身份、模型、提示词、member id、工作目录、数据目录。
- `CoreAgentStores`：会话、事件、快照、usage 的统一接口，默认内存，正式态可接 SQLite/SQLAlchemy。
- `CoreAgentEventLedger`：负责按 thread 分配 seq、保存 app event、把 `RunItemEvent` 包成 `core/runItem`。
- `CoreAgentSnapshotStore`：负责 load/apply/rebuild 快照，内部复用 `lamtools_core.snapshot`。
- `CoreAgentRuntime`：把 spec、kit、模型、工具、权限、store 组合成 `turn.start` 和 `approval.respond`。
- `CoreAgentOperationCatalog`：注册 CLI/GUI/HTTP 共用操作名。

Writer 的接入方式：

- Writer 填写 `CoreAgentMemberConfig`：
  - `member_id="writer"`
  - `data_dir=settings.data_dir`
  - `work_root=session.work_root`
  - `event_model=WriterAppEvent`
  - `snapshot_model=WriterThreadSnapshot`
  - `protocol_version="writer.app_server.v1"`
  - `member_snapshot_defaults={"queue": []}`
  - `member_event_handlers` 处理 queue、rollback、project 等 Writer 专属事件
- Writer 保留专属业务：项目、附件、检查点、队列、写作 prompt、写作工具、模型路由 UI。
- Writer 删除或改成薄转发：RunItem event 入账、snapshot core 区归约、core 状态同步、approval 事件形状。

## 非目标

- 不把 Writer 业务迁进 Core。
- 不一次性删除 Writer 的项目、附件、队列、检查点。
- 不重写前端视觉层。
- 不引入新的大型框架或数据库。
- 不让 Core 出现 Writer/Artist 产品名。

## 数据流

1. UI/CLI/HTTP 调 `turn.start`。
2. Core Agent 确保 thread/session 存在。
3. Core Agent 调 `CoreLoopKernel` 或轻量 `AgentApp` 执行一轮。
4. 工具调用前过 Core 权限门。
5. 需要用户确认时写入 `approval_request` 事件并暂停。
6. 每个 `RunItemEvent` 进入 Core event ledger。
7. Snapshot store 从事件归约出线程状态。
8. Writer UI 刷新时读取同一快照，只叠加 Writer 专属视图。

## 错误处理

- 事件 seq 冲突重试，保持现有 Writer 行为。
- 已存在 event id 时返回已有事件，保证幂等。
- 路径越界和敏感文件由 Core 权限门 hard block。
- 需要审批的工具不能绕过 waiting-gate；绕过时返回 Core 统一错误事件。
- 快照损坏时允许从事件重建。

## 测试策略

- Core 单元测试先红后绿：
  - Core Agent 可用内存 store 跑一轮。
  - SQLAlchemy event ledger 能分配 seq、幂等追加、包装 `RunItemEvent`。
  - Snapshot store 能 load/apply/rebuild。
  - Operation catalog 暴露 `turn.start`、`approval.respond`。
- Writer 回归测试：
  - Writer app-server 继续保存 `writer_app_events` 和 `writer_thread_snapshots`。
  - Writer snapshot 仍含 `queue` 和 `core`。
  - Writer 审批请求和响应仍能刷新到前端状态。
  - Writer CLI 和 app-server happy path 不退化。

## 风险

- Writer app-server 当前 `operations.py` 很大，不能一次性全删；先抽 Core 能力，再逐步压缩。
- Writer snapshot 同时有外层状态和 `core` 子状态，迁移要保留兼容。
- 当前工作树已有 Artist 删除和其他脏改；实现必须精确限定路径，不回滚无关改动。
