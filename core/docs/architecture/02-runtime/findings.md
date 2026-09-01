# 运行时 / 智能体架构发现

分析基线：`https://github.com/Lam-Arc/LamTools.git`，revision `5c1371e717dfa86e125665f7669526d758ad5bce`。本页回答“LamTools 如何执行一次 智能体 轮次”，节点按架构责任组织，代码文件仅作为证据。

## 边界

运行时 的清晰边界是 `CoreLoopKernel + RuntimeKit`。***核心循环内核***（`CoreLoopKernel`） 负责通用执行骨架：加载或创建 ***运行时状态***（`RuntimeState`）、维护 run/turn、构建请求、调用模型、解析输出、执行工具、验收、决定 `continue / wait / done / failed`、写回和终态事件。***运行时工具包***（`RuntimeKit`） / ***核心基础智能体工具包***（`CoreBaseAgentKit`） 负责成员或应用特有的 context、请求、parse、tool-result formatting、verify、decide_next 和 writeback。

入口和装配属于 应用层：`default_agent.py` 绑定 LLM、Toolbox、StateStore、***事件输出端口***、插件 生命周期和 检查点；`http_agent_app.py` 维护 FastAPI、Live Hub、***运行时任务注册表***（`RuntimeTaskRegistry`）、会话 Store 与启动/关闭。内核 设计明确不绑定 FastAPI、SQLite、WebView 或具体产品业务。

## 职责

- `Session` 是跨多次用户输入的资源边界；`Task` 是一次响应用户输入的工作单元；`Turn` 是 任务 内的一次模型/工具/验收迭代。
- ***核心循环内核***（`CoreLoopKernel`） 是执行控制面，拥有通用的 loop 阶段、决策、取消、重试、超时、检查点 和终态收敛。
- ***核心基础智能体工具包***（`CoreBaseAgentKit`） 是能力适配面，提供项目上下文、工具规格、模型请求、输出解析和业务验收。
- ***运行时状态存储***（`RuntimeStateStore`） 是 运行时 侧的状态端口；***事件输出端口***（`EventSink`） 是事件输出端口；***大语言模型客户端***（`LLMClient`） 与 Toolbox 是外部能力端口。

因此 运行时 的核心抽象不是某个 HTTP 处理器，也不是某个数据库表，而是“带有可注入 Kit 和端口的通用 轮次 执行器”。

## 依赖

当前依赖方向总体合理：HTTP/CLI → 应用装配 → 内核；内核 → ***运行时工具包***（`RuntimeKit`） / ***大语言模型客户端***（`LLMClient`） / ***运行时状态存储***（`RuntimeStateStore`） / ***事件输出端口***（`EventSink`）；具体 SQLite、提供方、工具 处理器 由装配层注入。`core/docs/core-loop-kernel-design.md` 还明确把 Artist / Writer 的业务差异留在 Kit。

需要持续守住的边界是：

- 运行时 不应反向依赖 Vue、WebSocket 或 FastAPI 类型。
- 内核 不应按工具名、产品名或 提供方 SDK 分支。
- 应用层 可以知道具体 adapter，但不应把 adapter 细节泄漏到 内核 和 Kit 协议。

## 耦合

1. `core/src/lamtools_core/app/default_agent.py` 同时完成 智能体装配、内核 构造、Toolbox/LLM/插件/持久化 绑定和多个运行入口，是当前最明显的装配 上帝对象 信号。
2. ***核心循环内核***（`CoreLoopKernel`） 的可选依赖已经包含 hook、检查点、completion gate、memory、tracer、model-context sink 和外部 cancel 来源。它没有越过 HTTP/SQLite 边界，但构造面偏宽，新增横切能力容易继续堆入 内核。
3. ***核心基础智能体工具包***（`CoreBaseAgentKit`） 同时持有配置、项目上下文、Toolbox、验证策略和 sub-agent guide。它是有效的 Kit 聚合，但应避免继续吸收应用编排或持久化职责。
4. ***运行时任务注册表***（`RuntimeTaskRegistry`） 的取消、审批和 guidance 通过 应用层 注入 运行时；这个方向是对的，但全局默认 registry 与请求级 registry 并存时，容易形成隐式共享状态。

## 风险

- P1：装配职责集中在 `default_agent.py` / `http_agent_app.py`，会使 运行时、传输层、插件 和 持久化 的改动互相触发。
- P1：运行时 状态、会话 快照、事件/Projection 的写入路径如果由多个 应用层 处理器 自行组合，可能造成恢复顺序、重复事件或 活动轮次 状态不一致。
- P2：内核 的可选依赖面继续扩大后，***核心循环内核***（`CoreLoopKernel`） 会从稳定骨架退化为横切关注点聚合器。

## 建议

1. 先抽出 ***核心应用层***（`CoreApplication`） / ***核心运行时工厂***（`CoreRuntimeFactory`），让 HTTP、CLI、Tauri 入口只调用用例，不直接拼装 内核 依赖。
2. 固化 ***运行时工具包***（`RuntimeKit`）、***大语言模型端口***（`LLMPort`）、***工具执行器***（`ToolExecutor`）、***事件输出端口***（`EventSink`）、`StatePort` 的 contract tests；内核 只依赖这些协议。
3. 将 cancellation、审批、检查点、memory、tracing 变成明确的 port 或 middleware 组合，而不是继续增加 内核 构造参数。
4. 为一次 已接受轮次 建立单一的 应用层 execution boundary，统一 状态 save、事件 追加、快照 投影 和终态广播的顺序。

## 证据

- `core/src/lamtools_core/kernel/loop.py`
- `core/src/lamtools_core/kernel/kit.py`
- `core/src/lamtools_core/runtime/__init__.py`
- `core/src/lamtools_core/app/base_agent.py`
- `core/src/lamtools_core/app/default_agent.py`
- `core/src/lamtools_core/app/http_agent_app.py`
- `core/docs/core-loop-kernel-design.md`
