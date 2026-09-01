# LamTools Core 架构风险

基线 revision：`5c1371e717dfa86e125665f7669526d758ad5bce`。这是静态架构评审，不把风险描述为已发生事故；P0 表示必须建立的止损不变量，P1 表示扩展或并发压力下的主要结构性风险，P2 表示可持续观察项。

## P0 — 不变量 / 发布闸门

### R0.1 已接受轮次的单一执行边界

- **状态**：没有从 pinned revision 证实一个现存 P0 correctness defect。
- **必须守住**：同一 会话 同时只能有一个 活动轮次；已接受轮次 的 ***运行时状态*** 保存、事件 追加、快照 投影、terminal convergence 和 实时 publish 必须有明确顺序与幂等键。
- **触发器**：任何新入口绕开 `CoreLiveOperationHost` / ***应用持久化宿主***（`AppPersistenceHost`） 自行写 状态、事件 或 broadcast。
- **控制措施**：把不变量写成 应用层 contract test；所有 HTTP、CLI、arrange、plugin 入口都走同一个 execution boundary。

## P1 — 近期结构性风险

### R1. 应用装配上帝对象

**证据**：`core/src/lamtools_core/app/http_agent_app.py` 同时管理 FastAPI、app 状态、DB、会话、插件 生命周期、operations、启动/关闭、路由、实时 context；`default_agent.py` 同时绑定 内核、Kit、Toolbox、LLM、持久化、插件 和 检查点。

**影响**：新增一个能力会修改入口、装配、运行和持久化多个区域；测试边界不清，生命周期问题容易被误判为 传输层 或 运行时 问题。

**应对**：抽出 ***核心应用宿主***（`CoreApplicationHost`）、***核心运行时工厂***（`CoreRuntimeFactory`） 和 类型化 use-case services；入口只 挂载/分发。

### R2. 多源状态与恢复竞态

**证据**：***运行时状态存储***、***核心会话存储***、***事件存储***、***快照存储***、检查点 和 UI 投影 各自保存状态切片；***应用持久化宿主***（`AppPersistenceHost`） 已协调部分写入，但恢复由多个 应用层/Live 路径共同参与。

**影响**：状态、turn、历史、snapshot_seq 或 活动轮次 在重启、重连、取消、审批继续时出现次序差异；可能表现为重复事件、旧快照或无法继续。

**应对**：书面化 状态 ownership；建立 ***恢复服务*** 和 单一已接受轮次事务协议；用 seq、client_message_id、turn_id 做幂等。

### R3. 扩展契约泄漏

**证据**：***插件上下文***（`PluginContext`） 暴露 operation 目录、权限、事件 bus、task registry、LLM 客户端 和 `services: dict[str, Any]`；***核心工具箱*** 聚合 plugin/MCP/durable/tool 权限/处理器/mode/timeout。

**影响**：插件实际依赖 宿主 内部对象，API 变更需要同步插件；权限和生命周期可能从多个入口解释。

**应对**：类型化/versioned 能力 门面；拆 DescriptorRegistry、LifecycleManager、***能力注册器***、***权限服务***、***工具执行器***；默认 deny。

### R4. 跨语言协议耦合

**证据**：Python `live_protocol.py` / `live_router.py` 与 TypeScript `protocol.ts` / `client.ts` / 投影 同时消费 JSON-RPC、事件 信封、快照、服务端 请求。

**影响**：协议改动需要 服务端/客户端 同步；流式传输、快照 trigger、重放 与 UI semantics 可能在不同版本漂移。

**应对**：独立 protocol package、模式 夹具、兼容性 matrix，先兼容再迁移；UI 只做 投影 不做领域决策。

## P2 — 观察并收敛

### R5. 界面投影语义重复

`selectors.ts`、`messageParts.ts`、`workbenchProjection.ts` 为性能和兼容性做 normalization。它们应保持为 transport 投影；若开始决定 completion、审批、权限 或 恢复，就会产生多客户端不一致。

### R6. 核心应用数据库 / 会话存储门面过宽

***核心应用数据库***（`CoreAppDb`） 聚合 runtime 状态、事件、快照、project、goal、arrange、memory 等 Store；***核心会话存储***（`CoreSessionStore`） 还处理 visibility、legacy 迁移、runtime preferences。短期可用，长期会使 模式 演进穿透 应用层。

### R7. 隐式可变上下文

`app_state: dict[str, Any>`、默认 ***运行时任务注册表***（`RuntimeTaskRegistry`）、环境变量、plugin `services` 和 回调 链 都会让依赖不完全由函数签名表达。优先在 application host 收敛为 请求/app 限定范围 object，并为 关闭/重启 做生命周期测试。

## 优先级规则

先确保 R0.1 的 execution boundary 和状态顺序，再做 R1/R2；R3/R4 可并行推进；R5–R7 在边界重构时顺手收敛，不建议为了“全局纯净”一次性重写。
