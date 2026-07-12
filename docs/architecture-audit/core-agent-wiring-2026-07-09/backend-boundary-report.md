# Core/Writer 后端接缝审计报告

审计日期：2026-07-09  
范围：只读审计后端 Core/Writer 接缝；未修改业务代码。

## 结论

总体结论：后端已经完成一部分基础能力下沉，但还没有达到“基础设施全部走 Core，member 只做增量补丁/mode”的目标。

已下沉较明确的部分：

- live WebSocket 连接框架已在 Core：连接握手、发送队列、订阅、通用操作分发接口由 `core/src/lamtools_core/app/live_router.py` 提供，Writer 的 `WriterAppServerConnection` 继承该连接。
- CLI live client 已在 Core：WebSocket pending request、事件队列、事件去重在 `core/src/lamtools_core/app/live_client.py`；Writer CLI 的 `members/writer/backend/writer_cli/app_server_client.py` 只是改路径、client 名和业务便捷方法。
- 工具、权限、技能、MCP、hook 基础能力大多已在 Core：`CoreToolbox`、`ApprovalGate`、`SkillRegistry`、`MCPToolRegistry`、plugin/hook engine 都在 Core，Writer 多数是包装或资源路径增量。
- DB/config 分库方向符合目标：共享 LLM/config 默认进入 `data/lamtools.db`；Core standalone runtime DB 独立；Writer runtime DB 独立，且启动迁移会从 Writer DB 删除共享配置表。
- 指定 Core active 范围内没有发现 `Writer` / `LamWriter` / `writer` / `lamwriter` 产品名残留。

主要缺口：

- Writer 仍保留自己的 live operation 状态机、queue 接收、thread/turn 处理和 snapshot reducer。连接层复用了 Core，但运行语义还没有完全由 Core 承担。
- Provider/config CRUD 仍在 Writer app_server operations 中实现，虽然数据模型和 DB 已下沉到 Core shared config。
- Writer app_server 仍有 hub/protocol/envelope 兼容层和重复投影逻辑，短期可接受，长期应减少为 member adapter。

## 证据

### 1. runtime/live WebSocket/operation dispatch/queue/snapshot

Core 侧已有基础能力：

- `core/src/lamtools_core/app/live_router.py`：`CoreLiveConnectionAdapter`、`CoreLiveConnection`、通用 WebSocket run loop、operation catalog 分发、内置 thread/turn/queue 分发。
- `core/src/lamtools_core/app/live_operations.py`：通用 `thread.resume`、`thread.read`、`turn.start`、`turn.cancel`、`queue.create/update/delete`，并能启动 runtime task。
- `core/src/lamtools_core/app/operation_groups.py`：定义 Core workbench 操作名，并禁止 member overlay 覆盖 Core 操作名。
- `core/src/lamtools_core/app/snapshot_store.py`：通用 thread snapshot projector，处理 seen_event_ids、turn、queue、core/runItem。
- `core/src/lamtools_core/app/event_store.py`：通用 app event store、client_message 去重、run item 持久化。

Writer 侧现状：

- `members/writer/backend/app/app_server/connection.py` 继承 `CoreLiveConnection`，通过 adapter 注入 Writer operation catalog、runtime start、approval continuation。这说明 WebSocket 骨架已走 Core。
- `members/writer/backend/app/app_server/operations.py` 仍实现大量 Core 同名操作：thread resume/read/start、turn start/cancel/steer、queue create/update/delete、approval respond、settings/config、command/artifact。
- `members/writer/backend/app/app_server/queue.py` 仍实现 `turn/accepted`、`queue/itemAccepted`、`queue/itemUpdated`、`queue/itemDispatched` 的接收、去重和派发逻辑，其中一部分属于通用 live queue 状态机。
- `members/writer/backend/app/app_server/reducer.py` 复用 `CoreAppSnapshotProjector` 处理 `core/runItem`，但仍自己处理 thread、turn、queue、request、rollback 和 status。
- `members/writer/backend/app/app_server/snapshot.py` 使用 Core 的 `SqlAlchemyThreadSnapshotStore`，但挂了 Writer 自定义 projector。

判断：

- WebSocket 传输层：Core 承担，Writer 是 adapter。
- operation dispatch：连接调度由 Core 承担，但 Writer 仍自建 Core 同名操作 catalog 和 handler，未完全由 Core live operations 承担。
- queue/snapshot：Core 有基础实现，Writer 仍有重复状态机；其中附件、transcript、rollback 是产品 overlay，普通 turn/queue/status 应继续下沉。

### 2. CLI live client

Core 侧：

- `core/src/lamtools_core/app/live_client.py` 包含 pending request、事件队列、WebSocket 读循环、resume、start_turn、steer、approval、cancel、thread read、command execute 和事件去重。

Writer 侧：

- `members/writer/backend/writer_cli/app_server_client.py` 继承 Core client，只设置 `/api/app-server`、`lamwriter_cli`，并把 `message` 包成文本 input。
- `members/writer/backend/writer_cli/__main__.py` 使用 `AppServerClient.connect()`、`start_turn()`、`events()`；未发现另一套 WebSocket/pending/event queue/dedupe。

判断：

- CLI live client 基础能力已由 Core 承担。
- Writer CLI 仍有大量展示/业务命令格式化，这是 member 可接受范围；不是 WebSocket 基础逻辑重复。

### 3. tool/permission/skill/hooks/MCP

Core 侧：

- `core/src/lamtools_core/tool/default_toolbox.py`：默认工具定义、权限、工具分类、失败模式、模型工具 schema、执行器、MCP tool、sub-agent tool。
- `core/src/lamtools_core/tool/approval.py`：命令风险分类、文件边界、敏感路径、审批门。
- `core/src/lamtools_core/skills.py`：技能发现、索引、加载。
- `core/src/lamtools_core/mcp/client.py`、`core/src/lamtools_core/mcp/registry.py`、`core/src/lamtools_core/tool/mcp_tools.py`：MCP client、registry、tool call 适配。
- `core/src/lamtools_core/kernel/loop.py` 和 `core/src/lamtools_core/plugins/*`：hook engine 和 PreToolUse hook 接入。

Writer 侧：

- `members/writer/backend/app/core/writer/tools.py` 通过 `build_core_toolbox()` 组装默认工具，只排除 MCP/sub-agent 后增加 Writer 管理工具、设计检查、项目检查。
- `members/writer/backend/app/core/writer/permission.py` 包装 Core `ApprovalGate`，权限表来自 Writer tool_specs。
- `members/writer/backend/app/core/writer/skills.py` 继承 Core `SkillRegistry`，只增加 Writer/Core 资源根和提示文案。
- `members/writer/backend/app/core/mcp/client.py`、`registry.py` 基本是 Core MCP 的 re-export/轻包装，`config.py` 保留 Writer 环境变量。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py` 通过 Core plugin assembly 和 hook engine 接入 hook。

判断：

- 工具执行、权限判断、技能加载、MCP client/registry、hook 引擎基础能力已在 Core。
- Writer 仍有包装层，但多数是产品资源根、工具 overlay、兼容命名。可清理，但不是最高风险。

### 4. DB/config

符合项：

- 共享 config schema 在 `core/src/lamtools_core/config/shared_database.py`：`llm_providers`、`llm_models`、`app_settings`。
- Writer shared config DB 默认路径在 `members/writer/backend/app/shared_config_database.py`：无 `LAMTOOLS_LLM_CONFIG_DB` 时使用 repo `data/lamtools.db`。
- Core standalone runtime DB 在 `core/src/lamtools_core/app/core_db.py`：`core_app_events`、`core_thread_snapshots`。
- Writer runtime DB 在 `members/writer/backend/app/config.py`：默认 `members/writer/backend/data/lamwriter.db`，显式 `LAMWRITER_DATA_DIR` / `LAMWRITER_DATABASE_URL` 优先。
- Writer runtime tables 在 `members/writer/backend/app/database.py` / `members/writer/backend/app/models/app_server.py`：`writer_app_events`、`writer_thread_snapshots`、`writer_app_requests` 等。
- Writer 迁移和启动会删除 Writer runtime DB 中的共享配置表：`members/writer/backend/app/config.py` 和 `members/writer/backend/app/database.py` 都处理 `llm_models`、`llm_providers`、共享 app_settings 清理。
- Core HTTP provider adapter 不暴露原始 API Key：`members/writer/backend/app/routers/core_http.py` 返回 `api_key_ref`。

风险项：

- `members/writer/backend/app/app_server/operations.py` 的 Provider/Model CRUD 仍在 Writer operations 层实现，数据写入 shared config session；这符合“Provider/API Key 不在 Writer runtime DB”，但不符合“共享配置基础设施全部走 Core”的最终形态。
- `members/writer/backend/app/services/config_write.py` 仍从 `LAMWRITER_` 环境默认值导入 provider/model；这是 Writer 启动兼容逻辑，长期应收敛到 shared config 初始化策略。

### 5. Core active code 产品语义

检查范围：

- `core/src/lamtools_core/app/*`
- `core/src/lamtools_core/cli.py`
- `core/src/lamtools_core/kernel/*`
- `core/src/lamtools_core/tool/*`
- `core/src/lamtools_core/mcp/*`
- `core/src/lamtools_core/skills.py`
- `core/src/lamtools_core/config/*`

结果：

- 未发现 `Writer`、`LamWriter`、`writer`、`lamwriter` 产品名。
- Core active code 中存在 provider、agent、app-server、workbench 等通用语义，未见 Writer 产品语义侵入。

## 缺口清单

### P0：Writer app_server 仍承载 Core live operation 状态机

证据：

- `members/writer/backend/app/app_server/operations.py`
- `members/writer/backend/app/app_server/queue.py`
- `members/writer/backend/app/app_server/connection.py`
- Core 对应基础能力：`core/src/lamtools_core/app/live_operations.py`

问题：

- Core 已有通用 `turn.start`、`turn.cancel`、`queue.create/update/delete`，但 Writer 仍维护同名操作的接收、去重、事件生成、snapshot 加载。
- Writer 的 turn start 同时创建 transcript turn/user message，这是产品 overlay；但 client_message 去重、turn accepted、queue accepted、running status 这些是通用 live 语义。

建议动作：

- 把 Core live operations 扩展成可注入 member hooks/adapters：例如“创建用户消息/附件校验/运行前上下文”作为 member callback。
- Writer 只保留 transcript、attachment、rollback、project/session 展示等 overlay。
- 删除或缩减 Writer 自己的 `accept_turn_start`、`accept_queue_item`、普通 queue update/delete 基础流程。

### P1：Writer snapshot reducer 仍重复通用 turn/queue/status reducer

证据：

- `members/writer/backend/app/app_server/reducer.py`
- `members/writer/backend/app/app_server/snapshot.py`
- Core 对应基础能力：`core/src/lamtools_core/app/snapshot_store.py`

问题：

- Writer reducer 已把 `core/runItem` 交给 Core projector，但仍自己维护 seen_event_ids、turn accepted/interrupted、queue accepted/updated/dispatched、thread status。
- 这会让 live 刷新、历史回放、queue 派发在 Core 和 Writer 两边继续漂移。

建议动作：

- 让 `CoreAppSnapshotProjector` 接管通用事件。
- Writer projector 只处理产品事件：transcript 扩展、rollback、attachment/artifact 投影、兼容旧事件。
- 把“队列项取消后是否删除”“status 从 core 同步”等规则放到 Core，Writer 不再另写。

### P1：共享 config 操作还在 Writer operations 层

证据：

- `members/writer/backend/app/app_server/operations.py`
- `members/writer/backend/app/services/config_read.py`
- `members/writer/backend/app/services/config_write.py`
- Core schema：`core/src/lamtools_core/config/shared_database.py`

问题：

- DB/schema 已经在 Core，默认 DB 也对了，但 CRUD operation、SQLite lock retry、导入 env 默认值、settings get/update 仍在 Writer operations。
- 这会导致未来其他 member 复用 Provider/API Key 时继续复制 Writer operations。

建议动作：

- 在 Core 增加 shared config operation catalog：provider/model/settings CRUD、masked read、env import、lock retry。
- Writer 只保留 `lamwriter.modelRouting` 或 member-specific routing/default 选择。
- Core operation 输出保持中性，不返回原始 api_key，只返回 masked 或 api_key_ref。

### P1：Writer hub/protocol/envelope 仍是重复兼容层

证据：

- `members/writer/backend/app/app_server/hub.py`
- `members/writer/backend/app/app_server/protocol.py`
- Core 对应基础能力：`core/src/lamtools_core/app/live_hub.py`、`live_protocol.py`、`event_store.py`

问题：

- Writer hub 与 Core hub 形态高度重复。
- Writer protocol 复用 Core JsonRPC 类型，但仍维护 Writer envelope/version。

建议动作：

- 将 hub 替换为 Core hub 或 typed alias。
- 保留 Writer protocol version 仅作为兼容字段；事件 envelope 尽量使用 Core `AppEventEnvelope`，在边缘做版本映射。

### P2：Writer MCP wrapper 和 permission wrapper 可继续瘦身

证据：

- `members/writer/backend/app/core/mcp/client.py`
- `members/writer/backend/app/core/mcp/registry.py`
- `members/writer/backend/app/core/mcp/schemas.py`
- `members/writer/backend/app/core/writer/permission.py`

问题：

- MCP client/schema 基本是 Core re-export。
- permission wrapper 已复用 Core `ApprovalGate`，但还暴露旧 `PermissionChecker` 和私有方法转调。

建议动作：

- 删除只做 re-export 的 MCP 文件，调用方直接用 Core；只保留 Writer MCP config loader。
- 将旧 PermissionChecker 调用迁到 CoreToolbox/ApprovalGate，保留兼容 shim 到无调用后删除。

### P2：Writer CLI 展示逻辑偏厚，但不属于 live client 重复

证据：

- `members/writer/backend/writer_cli/__main__.py`
- `members/writer/backend/writer_cli/app_server_client.py`
- Core live client：`core/src/lamtools_core/app/live_client.py`

问题：

- CLI 展示分组、snapshot message 提取、approval prompt 判断都在 Writer CLI。
- 这不是 WebSocket/pending/dedupe 重复，但如果未来多个 member 都要 CLI streaming，会重复展示投影。

建议动作：

- 暂不作为基础能力下沉优先项。
- 等第二个 member CLI 出现后，再把 event-to-display formatter 下沉 Core，Writer 只保留标签和文案。

## 建议动作顺序

1. 先下沉 live operation core path：把 `turn.start/cancel`、`queue.create/update/delete`、`thread.resume/read` 的通用部分从 Writer operations 迁到 Core live operations，通过 member adapter 插入 transcript/attachment。
2. 再收敛 snapshot projector：Core projector 处理通用 turn/queue/status，Writer projector 只处理产品投影和历史兼容。
3. 下沉 shared config operation catalog：Provider/Model/Settings CRUD、lock retry、masked read、env import 进入 Core。
4. 替换 Writer hub/protocol/envelope 重复层：先 alias，再删除重复实现。
5. 清理 MCP/permission re-export 和兼容 shim。

## 没把握的点

- 本次只审计后端指定范围；未审计前端 store 是否仍有独立 queue/status 规则。
- `members/writer/backend/app/app_server/reducer.py` 中 rollback、legacy turn started、approval request 状态是否仍需长期兼容，需要结合历史 DB 和迁移策略确认。
- `turn.start` 中 transcript turn/user message 创建是否必须发生在 operation 接收阶段，还是可改为 Core 接收后调用 member pre-run adapter，需要一次小型设计验证。
- `LAMWRITER_` 环境变量导入 provider/model 是兼容入口还是产品默认配置策略，需确认是否仍要支持旧安装包。
