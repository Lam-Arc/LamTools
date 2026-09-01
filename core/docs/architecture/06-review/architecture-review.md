# LamTools Core 架构评审

分析基线：`https://github.com/Lam-Arc/LamTools.git`，revision `5c1371e717dfa86e125665f7669526d758ad5bce`。本评审综合四张 Level 2 子系统图，不把当前工作树未提交改动当作架构事实。

## 8.1 执行摘要

LamTools Core 当前是一个“分层 + 六边形倾向 + 插件 + 事件驱动”的混合架构：Vue/Tauri 位于 表示层，FastAPI/JSON-RPC/WebSocket 位于 传输层，`http_agent_app.py` 与 `default_agent.py` 负责 应用装配，***核心循环内核***（`CoreLoopKernel`） 与 ***核心基础智能体工具包***（`CoreBaseAgentKit`） 构成 运行时，插件/工具 是扩展面，SQLite/事件/快照 是 持久化。

最大优势是 运行时 已经有真实的端口意识：***核心循环内核***（`CoreLoopKernel`） 通过 ***运行时工具包***（`RuntimeKit`）、***大语言模型客户端***（`LLMClient`）、***运行时状态存储***（`RuntimeStateStore`） 和 ***事件输出端口***（`EventSink`） 工作，设计文档明确不绑定 FastAPI、SQLite、WebView。其次，事件、快照、WebSocket 增量和 快照 装载 已形成可用的运行协议。

最大风险不是某一条调用链，而是边界在 应用装配 处重新汇聚：`http_agent_app.py`、`default_agent.py`、***核心应用数据库***（`CoreAppDb`）、***核心工具箱***（`CoreToolbox`） 和 ***插件上下文***（`PluginContext`） 都知道过多的上下文。状态也不是单一来源：活动 ***运行时状态***、会话 快照、***事件存储***、快照 投影、UI 投影 各自拥有不同切片，恢复正确性依赖跨模块约定。

优先级建议：先抽离 应用层/传输层 装配并锁定状态所有权，再收窄 ***插件上下文*** 与 Toolbox 扩展 API，最后拆解 持久化 门面 和 UI 投影 语义。静态证据没有确认一个必须立即止损的 P0 缺陷；但“单一 已接受轮次 执行边界”和“一个 活动轮次 的状态写入顺序”应作为 P0 级不变量守护。

## 8.2 架构模型

### 分层架构

代码和运行路径表现出明显层次：表示层 → 传输层 → 应用层 → 运行时 → 基础设施。`core/desktop/src/main.ts` 不负责 智能体 业务，`core/ui/src/appServer/client.ts` 负责协议，`http_agent_app.py` 负责 FastAPI 装配，内核 负责执行骨架，SQLite/提供方/插件 由装配层注入。

### 六边形架构（部分形成）

运行时 已有 ports：***运行时工具包***（`RuntimeKit`）、***运行时状态存储***（`RuntimeStateStore`）、***运行时检查点存储***（`RuntimeCheckpointStore`）、LLM 客户端、Toolbox 和 ***事件输出端口***。`core/docs/core-loop-kernel-design.md` 对“内核 不绑定 FastAPI / SQLite / WebView”有明确约束。因此依赖方向接近 Hexagonal，但 应用装配 和 ***核心应用数据库***（`CoreAppDb`） 仍把多个 adapter 绑定在一起，端口尚未覆盖 会话、Recovery、权限、事件/协议 的全部边界。

### 插件架构

清单、***插件注册表***、后端 生命周期、***插件上下文***、工具/操作 目录、***钩子引擎***、MCP registry、UI 扩展 和 ***核心工具箱*** 构成显式扩展模型。插件能力不是直接改 内核，而是以 工具/操作/事件/上下文 进入 宿主；问题在于 上下文 的宽字段和 `services: dict[str, Any]` 仍允许绕过稳定 API。

### 事件驱动架构（混合形态）

***事件存储***、***快照存储***、CoreAppEventHub、`live_router.py` 和 UI 事件 投影 形成事件传播链。但 ***运行时状态***、会话 快照、检查点 和关系型表仍是独立的可变存储，所以当前不是严格 事件溯源，而是“命令/状态执行 + 事实事件 + 物化 投影 + 流式传输”的混合架构。

## 8.3 核心领域

### 核心领域对象

- ***运行时状态***（`RuntimeState`）：一次 会话 的活动执行状态、阶段、决策、turn_count、元数据。
- `RuntimeTurnInput`、`KernelTurn`、`KernelStep`、`KernelResult`：一次 轮次 的输入、模型结果、工具步骤、验收与终态。
- `LoopPhase` 与 `LoopDecision`：通用生命周期语义，区别于 Writer/Artist 的产品业务状态。
- ***运行时工具包***（`RuntimeKit`） / ***核心基础智能体工具包***（`CoreBaseAgentKit`）：把业务上下文、模型请求、工具结果、验收和下一步决策接入通用 内核。
- ***核心循环内核***（`CoreLoopKernel`）：执行这些对象的通用领域控制面。

### 核心服务与生命周期

活动生命周期是：load/create 状态 → running → build context → model → parse → tool → verify → decide → writeback/save → continue/wait/done/failed/cancelled。会话 跨多次 任务；任务 是一次用户输入的工作单元；轮次/步骤 是 任务 内的循环迭代。

### 不属于 核心领域

Vue/Tauri、FastAPI/WebSocket、SQLite/SQLAlchemy、提供方 SDK、插件 文件扫描、具体文件/Git/图像工具和 UI 投影 都是适配器或基础设施事实。它们可以实现端口，但不应改变 内核 的通用生命周期语义。

## 8.4 架构边界

| 边界 | 当前 拥有者 | 应保持的方向 |
|---|---|---|
| 表示层 | Vue UI、UI 投影 store、Tauri shell | 只产生用户意图并渲染 投影 |
| 传输层 | App Server Client、HTTP 路由、Live WebSocket Router | 只做协议、连接、背压和 DTO 适配 |
| 应用层 | `http_agent_app.py`、`default_agent.py`、Live 操作 宿主、会话 编排 | 组织用例、装配依赖、控制事务 |
| 运行时 | ***核心循环内核***（`CoreLoopKernel`）、***运行时工具包***、运行时 状态/LLM/tool/事件 ports | 只定义执行与状态转移 |
| Extension | ***插件注册表***、生命周期、***插件上下文***、目录、钩子/MCP/UI 扩展 | 通过稳定 能力 接入，不穿透内部实现 |
| 持久化 | 状态/事件/快照/会话 repositories、持久化 宿主、SQLite adapters | 事实、投影、运行状态 拥有者 分离 |

最需要修复的不是边界名称，而是 拥有者 的可执行性：目前 应用层 组件同时拥有启动、注册、恢复、持久化、插件和路由知识，导致“理论上的六层”在实现中通过装配对象互相连接。

## 8.5 关键执行流程

1. **User Action**：Vue composer 或 CLI 产生用户意图；Vue 不直接调用 内核。
2. **UI / 传输层 Client**：***核心应用服务器客户端***（`CoreAppServerClient`） 通过 `__LAMTOOLS_API_BASE__` 组装 HTTP/WS 地址，使用 JSON-RPC `initialize`、请求/notify 和事件回调。
3. **App Server**：FastAPI 挂载 `/api/core` 路由 和 `/api/core/app-server` 实时 路由器；传输层 校验 origin、消息大小、连接和队列压力。
4. **应用层**：Live operations 根据 会话、项目、任务 registry 和 请求 元数据 创建/恢复执行上下文，选择 model、Toolbox、插件 和 持久化 实现。
5. **会话 / 运行时**：内核 通过 ***运行时状态存储***（`RuntimeStateStore`） 加载或创建 状态，调用 Kit build context / 请求。
6. **模型 / 工具**：内核 通过 LLM 客户端 获取 流式传输 响应，解析为 `KernelTurn`，把 ToolCall 交给 Toolbox/权限/审批，接收 ToolResult。
7. **Verify / Decide**：Kit 验收并给出 `continue / wait / done / failed`，内核 写回 历史、状态 和终态。
8. **事件 / 持久化**：运行时 ***事件输出端口***/应用层 PersistenceHost 将 生命周期/runItem 事件追加到 ***事件存储***，必要时应用 快照 投影，并保存 运行时 检查点/状态。
9. **Streaming / UI**：***事件中心*** 发布 实时 信封，WebSocket Router 广播；UI 客户端 合并 事件/快照，投影 store 再交给 Vue 渲染。

Streaming 与 持久化 在实现中不是严格的串行单线：低频事件可以先以 实时 delta 传播，快照 在 turn boundary 或触发事件时更新。评审应把它视为“同一事件协议的两个消费路径”，而不是让 UI 把 快照 当作每个 token 的唯一来源。

## 8.6 状态所有权

| 状态切片 | 真实状态源 | 非 拥有者 |
|---|---|---|
| UI interaction | Vue component / UI store 的临时输入与连接状态 | 运行时、SQLite |
| UI 投影 | Core 事件/快照 的客户端投影缓存 | 不得重算 Core completion/审批 |
| Active execution | ***运行时状态***（`RuntimeState`） + ***运行时状态存储***（`RuntimeStateStore`） | UI、普通 会话 JSON |
| 会话 resource | ***核心会话存储***（`CoreSessionStore`） / thread 快照 的 元数据、visibility、project 范围 | 内核 私有 状态 |
| 事实 | ***事件存储*** 的按 seq 事件 信封 / runItem | 快照 投影 |
| 读取 model | ***快照存储*** 的物化 thread 快照 | ***事件存储*** 原始事实 |
| Resume boundary | ***运行时检查点存储*** / 检查点 data | 完整 会话 历史 |
| 插件-owned 状态 | 插件自己的 config/后端 状态，经 上下文 访问 | Core 全局 app 状态 |

结论是：系统没有一个覆盖所有语义的单一 真实状态源，但可以有清晰的分片 拥有者。需要把“活动执行状态”“事件事实”“会话 资源”“客户端 投影”写成协议，避免同名的 状态/turn/历史/元数据 在多个模块间互相覆盖。

## 8.7 扩展模型

| 新能力 | 推荐扩展点 | 不应改动 |
|---|---|---|
| 工具 | 清单 → ToolSpec/处理器 → ***能力目录*** → ***工具执行器***/Toolbox | 内核 不按工具名分支 |
| LLM 提供方 | provider/model config → LLM adapter → LLM port | 内核 不接 提供方 SDK 类型 |
| 插件 | ***插件注册表***/生命周期 → 类型化 ***插件上下文*** → 目录/事件/权限 | 不直接访问 ***核心应用数据库***、会话 internals、内核 私有 状态 |
| 运行时 能力 | ***运行时工具包*** 或明确 port/middleware 注入 ***核心循环内核*** | 不把产品业务 if/else 塞进 内核 |
| UI feature | UI registry / protocol DTO / 前端 component | 不让 UI 反向拥有 运行时 状态 |
| 持久化 后端 | 状态/事件/快照 repository adapter → ***应用持久化宿主*** | 领域 不依赖 ORM/SQLite |

标准接入规则是“声明 能力、通过版本化 contract 注册、由 宿主 统一权限与生命周期、由 运行时 只消费抽象”。

## 8.8 架构风险

详细分级见 [architecture-risks.md](architecture-risks.md)。静态评审的结论如下：

- **P0**：没有从 pinned revision 证实的现存 P0 缺陷；但 已接受轮次 的单一执行边界、活动轮次 互斥和 状态/事件/投影 顺序是必须守住的 P0 级不变量。
- **P1**：应用装配上帝对象；多源状态与恢复竞态；***插件上下文***/Toolbox 扩展契约泄漏；Python/TypeScript protocol 演进耦合。
- **P2**：UI 投影 语义重复、***核心应用数据库***（`CoreAppDb`） 门面 过宽、legacy 迁移、默认 registry/环境变量/回调链带来的隐式共享状态。

## 评审结论

LamTools 不需要重新发明 运行时；应沿现有 `CoreLoopKernel + RuntimeKit` 方向继续。下一阶段的目标不是增加总图细节，而是把已有的隐式端口变成显式 contract：应用层 负责用例与事务，运行时 负责执行语义，Extension 负责能力注册，持久化 负责事实/投影/恢复，表示层 负责交互与渲染。
