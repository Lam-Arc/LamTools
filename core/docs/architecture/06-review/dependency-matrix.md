# LamTools Core 依赖矩阵

基线 revision：`5c1371e717dfa86e125665f7669526d758ad5bce`。判断同时考虑当前实现和 target architecture；“合理”表示方向可以保留，不表示当前耦合已经足够小。

| From | To | 当前判断 | 证据 / 说明 | 目标动作 |
|---|---|---|---|---|
| Vue UI | App Server Client | 合理 | `core/ui/src/appServer/client.ts` 是协议 客户端；UI 不直接 import 内核 | 保持 |
| Tauri Shell | API Base / local host | 合理 | `core/desktop/src/main.ts` 调 `get_api_base` 并注入 `/api/core` | 只保留 host 能力 |
| App Server Client | FastAPI / Live Router | 合理 | HTTP/WS 与 JSON-RPC 是 传输层 contract | 提取版本化 DTO/夹具 |
| FastAPI factory | 应用层 services | 合理但过重 | `http_agent_app.py` 同时 挂载 路由、启动/关闭、DB、插件、会话、operations | 只保留 adapter + host wiring |
| 应用层 services | ***核心循环内核*** | 合理 | `default_agent.py` / `live_operations.py` 组装并启动 内核 | 通过 ***核心应用层***（`CoreApplication`） 用例接口 |
| ***核心循环内核*** | ***运行时工具包*** | 合理 | 内核 docs 将业务 context/parse/verify/decide 留在 Kit | 保持稳定 protocol |
| ***核心循环内核*** | LLM / 工具 / 状态 / 事件 ports | 合理 | 内核 constructor 注入 `llm_client`、`state_store`、`event_sink` 等 | 收窄为明确 port/middleware |
| ***核心循环内核*** | SQLite implementation | 当前间接合理 | ***运行时状态存储***（`RuntimeStateStore`） 由 ***SQLAlchemy 运行时状态存储***（`SqlAlchemyRuntimeStateStore`） 实现，内核 不直接 import SQLAlchemy | 禁止直接化 |
| 运行时 | Vue UI | 不应存在直接依赖 | 运行时 通过 ***事件输出端口***/应用层 Hub 出口，当前没有直接 UI 类型依赖 | 用 protocol/事件 adapter 保持隔离 |
| ***插件注册表*** | ***插件上下文*** / 目录 | 合理 | 注册表 发现 清单，上下文/目录 提供能力入口 | 分离 discover 与 register |
| 插件 | ***核心循环内核*** 私有 状态 | 高风险 | 上下文 已避免直接给 内核，但 broad fields 与 `services: Any` 提供绕行空间 | 类型化能力 + deny-by-默认 |
| 插件 | ***运行时任务注册表*** / LLM / EventBus | 需要收敛 | ***插件上下文***（`PluginContext`） 显式暴露这些服务，生命周期与权限边界容易被插件感知 | 通过最小 能力 门面 |
| ***核心工具箱*** | 插件/MCP/Durable 处理器 | 合理但过宽 | Toolbox 统一 spec、处理器、权限、mode、timeout 和 conflict | 拆 目录 / 权限 / Executor |
| ***钩子引擎*** | 权限 / 事件 / MCP / command execution | 需要收敛 | ***钩子引擎*** 支持多种 处理器、审计、阻断与 权限 决策 | 钩子 runner 与 策略 决策 分离 |
| 持久化 adapter | 运行时 protocols / 领域 状态 | 合理 | SQL adapter 把 ORM row 转换为 ***运行时状态***（`RuntimeState`） | 保留 adapter → port 方向 |
| ***核心会话存储*** | ***核心应用数据库*** / ORM 快照 | 当前可用但耦合 | SessionStore 直接依赖 ***核心应用数据库***（`CoreAppDb`）、`CoreThreadSnapshot` 和 JSON 迁移 | 通过 ***会话仓储*** 隐藏 模式 |
| ***应用持久化宿主*** | ***事件存储*** + ***快照存储*** | 合理 | 追加/应用/重建/write coordinator 已集中在 宿主 | 固化 transaction protocol |
| ***事件存储*** | ***快照存储*** | 合理 | 事件 追加 后投影 快照，支持 seq/重放 | 明确 事件=fact, 快照=读取模型 |
| UI 投影 store | Core 快照/事件 protocol | 合理 | `store.ts` / `workbenchProjection.ts` 消费 事件/快照 | 不复制完成/权限语义 |
| UI 投影 store | Core DB tables | 不合理 | UI 不应理解 ORM 字段或 SQL 模式 | 只消费 protocol DTO |
| 领域 / 运行时 | HTTP / WebSocket / Tauri | 不合理 | 违反 内核 docs 的独立性目标 | 通过 inbound/出口适配器s |
| Config env / 全局 registry | 应用装配 | 隐式耦合 | `LAMTOOLS_*`、默认 task registry、`app_state`、callbacks 影响生命周期 | 显式 请求-限定范围 dependencies |

## 循环依赖观察清单

当前最需要监控的潜在环不是 Python import cycle，而是运行时 ownership cycle：

`Runtime → EventHub → WebSocket → UI projection → reconnect/resume → Application → Runtime`

这条链作为事件闭环是必要的，但 UI 投影 不得回写 ***运行时状态***；恢复 只能通过 应用层 command 重新进入 运行时。另一个高风险闭环是：

`PluginContext → OperationCatalog → Plugin handler → PluginContext`

它允许能力组合，但必须通过 类型化能力、调用上下文和权限边界阻止插件拿到 宿主 内部可变对象。
