# LamTools Core 重构路线图

目标是从当前可运行的混合架构演进到 [target-architecture.html](target-architecture.html) 所示的“薄适配器 + 应用层 用例 + Core 运行时 + 稳定 Ports + 可替换 适配器”。每一阶段都应保持现有 HTTP/WS 协议和用户体验可回归。

## R0 — 建立边界不变量

### 当前结构

同一执行链由 HTTP、CLI、arrange、plugin 和恢复入口装配；状态、事件、快照和 实时 broadcast 的顺序主要由调用约定维持。

### 问题

新入口可能绕过现有协调器，造成 活动轮次 竞争、重复事件或恢复时旧状态覆盖新状态。

### 目标架构

所有入口调用同一个 `CoreApplicationHost.start_turn / resume_turn / cancel_turn`；该服务拥有 已接受轮次 的幂等键、状态写入、事件追加、投影 和 terminal convergence 协议。

### 迁移路径

1. 先不移动业务代码，新增 contract tests 覆盖 `turn_id`、`client_message_id`、seq、cancel、审批 continuation、重启/恢复。
2. 把现有 HTTP、CLI、arrange 和 plugin turn entry point 逐个接到同一 wrapper。
3. 记录并监测绕过 wrapper 的直接 `state_store` / `event_store` 写入。

### 影响

`http_agent_app.py`、`live_operations.py`、`cli.py`、arrange runner、persistence tests 和 恢复 tests。

### 优先级

P0（不变量；先加测试和入口护栏，避免大范围行为变化）。

## R1 — 抽离应用宿主与运行时工厂

### 当前结构

`http_agent_app.py` 和 `default_agent.py` 同时负责 FastAPI 启动/关闭、DB、插件 生命周期、会话、LLM、Toolbox、内核、operations 和 实时 context。

### 问题

传输层 变化会牵动 运行时/持久化；依赖装配隐藏在 `app_state`、闭包和大量可选参数中，难以替换或单测。

### 目标架构

***核心应用宿主***（`CoreApplicationHost`） 管理 app-限定范围 dependencies 和 生命周期；***核心运行时工厂***（`CoreRuntimeFactory`） 只构造 `CoreLoopKernel + RuntimeKit + ports`；FastAPI/CLI/Tauri 只调用 类型化 用例。

### 迁移路径

1. 从现有 `startup_core_agent` 提取纯装配函数，保留原调用结果。
2. 将 `live_context()`、会话 store、operations 和 恢复 coordinator 移入 宿主。
3. 把 FastAPI route 挂载 与 宿主 生命周期分开；CLI 复用同一 宿主 factory。
4. 最后删除重复闭包和 `app_state` key string。

### 影响

`http_agent_app.py`、`default_agent.py`、`factory.py`、`live_operations.py`、CLI 和启动/关闭测试；外部协议不应变化。

### 优先级

P1。

## R2 — 收窄运行时端口

### 当前结构

内核 已依赖 ***运行时工具包***（`RuntimeKit`）、LLM、StateStore、***事件输出端口***，但可选依赖继续增加；***核心基础智能体工具包*** 同时持有 Toolbox、配置、项目上下文、验证与 sub-agent 资料。

### 问题

横切能力可能继续成为 内核 构造参数，导致 内核 从稳定执行骨架变为关注点聚合器。

### 目标架构

以 ***运行时工具包***（`RuntimeKit`）、***大语言模型端口***（`LLMPort`）、***工具执行器***（`ToolExecutor`）、`PermissionPort`、`StatePort`、`EventPort`、`CheckpointPort` 组成最小端口；tracing、memory、cancel、审批 通过 middleware/策略 composition 注入。

### 迁移路径

1. 为现有构造参数建立 protocol wrapper，不改变 内核 行为。
2. 将 hook/检查点/completion/memory/tracing 逐项移到 wrapper 或 middleware。
3. 为 内核 运行 contract 添加 fake ports 和 contract tests。
4. 只在确认无调用方依赖后删除旧的 optional kwargs。

### 影响

`kernel/loop.py`、`kernel/kit.py`、`runtime/__init__.py`、`base_agent.py`、sub-agent runner、内核 tests。

### 优先级

P1。

## R3 — 稳定插件 / 工具扩展 API

### 当前结构

注册表、生命周期、***插件上下文***、操作 目录、***钩子引擎***、MCP 和 ***核心工具箱*** 共同把 plugin spec、处理器、权限、mode、timeout、UI 扩展 和 runtime service 组装起来。

### 问题

`PluginContext.services` 与宽字段暴露 宿主 内部；工具 注册、冲突、权限和执行在 Toolbox 汇聚；***钩子引擎*** 同时承担多种 处理器 与 策略 决策。

### 目标架构

***插件描述符注册表***（`PluginDescriptorRegistry`） 只发现；***插件生命周期管理器***（`PluginLifecycleManager`） 只管理 start/stop；***能力注册器***（`CapabilityRegistrar`） 只注册；***权限服务***（`PermissionService`） 只判定；***工具执行器***（`ToolExecutor`） 只执行。`PluginContext v1` 只暴露 类型化, 限定范围 capabilities。

### 迁移路径

1. 先为现有 上下文 字段定义 公开/内部 清单与版本号。
2. 在旧 上下文 外包一层 类型化 门面，兼容旧插件并记录使用情况。
3. 把 Toolbox 内的注册/权限/execute 函数拆为服务，但保留旧 ***核心工具箱***（`CoreToolbox`） 门面。
4. 对新插件默认 deny 未声明 能力，旧 escape hatch 进入 deprecation window。

### 影响

`plugins/*`、`tool/default_toolbox.py`、`tool/approval.py`、MCP registry、bundled plugins、UI plugin registry 和 plugin tests。

### 优先级

P1。

## R4 — 明确持久化所有权与恢复

### 当前结构

***核心应用数据库***（`CoreAppDb`） 聚合 ***运行时状态***、事件、快照、项目 等 Store；***应用持久化宿主***（`AppPersistenceHost`） 协调 追加/应用；***核心会话存储***（`CoreSessionStore`） 直接理解 快照 ORM/JSON；恢复逻辑位于 Live/应用层 启动。

### 问题

***运行时状态***、会话 快照、事件 事实、检查点 和 UI 投影 的 权威源 容易混淆；模式/迁移 细节会穿透 会话/应用层。

### 目标架构

应用层 只依赖 ***会话仓储***（`SessionRepository`）、***运行时状态仓储***（`RuntimeStateRepository`）、***事件仓储***（`EventRepository`）、***快照仓储***（`SnapshotRepository`）、`CheckpointRepository` 和 ***恢复服务***（`RecoveryService`）。事件=fact、快照=读取模型、***运行时状态***=active execution 权威源、UI=cache。

### 迁移路径

1. 先写 状态所有权 contract 与 事件/快照/恢复 夹具。
2. 在现有 Store 外加 repository ports；让 ***核心会话存储*** 迁移到 ***会话仓储*** 门面。
3. 将 恢复 顺序集中到 ***恢复服务***，统一 seq/turn/客户端 idempotency。
4. 最后再把 ***核心应用数据库***（`CoreAppDb`） 从 公开 聚合体 降为 infrastructure composition detail。

### 影响

`core_db.py`、`persistence_host.py`、`core_session_store.py`、事件/快照 stores、runtime store、实时 恢复 和 SQLite tests。

### 优先级

P1。

## R5 — 协议与表示层解耦

### 当前结构

Python 实时 protocol/路由器、TypeScript App Server Client/store/投影 和 Tauri API Base 注入共同维护 HTTP/WS 模式；UI 已通过 事件/快照 做增量投影。

### 问题

服务端/客户端 版本演进容易同步失败；UI 若重复解释 completion/审批/恢复，会与 运行时 产生第二套语义。

### 目标架构

独立的 versioned protocol DTO/夹具；传输层 只翻译；UI store 只维护 connection/投影/cache；Tauri 只提供 boot/file/window/external URL host capabilities。

### 迁移路径

1. 从 `live_protocol.py` 与 `protocol.ts` 抽取 模式 夹具 和 兼容性 tests。
2. 为 快照 trigger、runItem delta、服务端 请求、恢复/重连 建立 golden cases。
3. 把 UI semantic normalization 标注为 投影-only，并删除不必要的 Core 决策 duplication。
4. 新 Web UI 复用同一 protocol，不复制 desktop-specific paths。

### 影响

`live_protocol.py`、`live_router.py`、`live_hub.py`、UI `client.ts`/`store.ts`/`selectors.ts`/`workbenchProjection.ts`、Tauri main 和相关测试。

### 优先级

P1（协议变更前优先；不要求立即重写 UI）。

## R6 — 清理隐式共享状态

### 当前结构

环境 变量、默认 ***运行时任务注册表***（`RuntimeTaskRegistry`）、`app_state: dict[str, Any]`、插件 `services` 和 回调 链 共同传递运行上下文。

### 问题

依赖不完全出现在 API 签名中，测试隔离、并发和 关闭/重启 行为难以推理。

### 目标架构

显式的 app-限定范围/请求-限定范围 dependency object；全局默认值只作为 CLI convenience，不能成为 服务端 runtime 权威源；插件 能力 有 拥有者 和生命周期。

### 迁移路径

1. 建立 dependency inventory，先标记 全局/env/回调 的 拥有者。
2. 将 服务端 路径迁移到显式 宿主 context。
3. 为 singleton/默认 registry 增加隔离测试，再决定是否删除。
4. 保留环境变量作为配置输入，但在 启动 解析成不可变 config object。

### 影响

`runtime/__init__.py`、`http_agent_app.py`、config root、plugin context、CLI、关闭/重启 tests。

### 优先级

P2；随 R1–R4 一起收敛。

## 顺序摘要

`R0 invariants → R1 Application Host → R2 Runtime Ports → R3 Extension API + R4 Persistence → R5 Protocol → R6 cleanup`

每阶段都应保留现有 JSON-RPC/HTTP/WS 兼容测试；任何阶段若需要修改对外协议，应先更新 夹具 和 迁移 note，再改实现。
