# 会话 / 事件 / 持久化架构发现

分析基线：`https://github.com/Lam-Arc/LamTools.git`，revision `5c1371e717dfa86e125665f7669526d758ad5bce`。本页回答“状态由谁拥有、如何持久化和恢复”。

## 边界

持久化 不是一个单一表或单一 Store，而是三层：

1. 运行时 侧的 ***运行时状态存储***（`RuntimeStateStore`） / ***运行时检查点存储***（`RuntimeCheckpointStore`） 协议，承接执行状态、历史、审批 和 检查点。
2. 应用层 侧的 ***应用持久化宿主***（`AppPersistenceHost`）、***核心会话存储***（`CoreSessionStore`） 与 恢复 编排，组合事件、快照、会话 和运行状态的用例。
3. 基础设施 侧的 ***SQLAlchemy 运行时状态存储***（`SqlAlchemyRuntimeStateStore`）、***SQLAlchemy 应用事件存储***（`SqlAlchemyAppEventStore`）、***SQLAlchemy 线程快照存储***（`SqlAlchemyThreadSnapshotStore`） 和 `CoreAppDb / SQLite`。

***应用持久化宿主***（`AppPersistenceHost`） 将 ***事件存储*** 追加 与 ***快照存储*** 投影 组合在统一的 write/保存点 逻辑中；***核心应用数据库***（`CoreAppDb`） 则把多种具体 Store 聚合成一个应用句柄。

## 职责

- ***运行时状态***：当前运行的 session/run/状态/阶段/loop 状态 与 元数据，是活动执行的状态所有者。
- ***事件存储***：按 thread/sequence 保存 `AppEventEnvelope` 与 `RunItemEvent`，是运行事实和协议事件的追加记录。
- ***快照存储***：把事件折叠成可快速读取的 thread 投影，服务 会话 列表、恢复和客户端 装载。
- 检查点：保存某个可继续执行的边界，不等同于完整历史或全量快照。
- ***核心会话存储***：以 thread 快照 为资源适配，负责 SessionRecord、元数据、visibility、project/runtime preferences 的读写。
- ***恢复协调器***：启动时处理 过期 活动轮次，并从 ***运行时状态***、快照、事件/History 恢复可继续的执行上下文。

这说明当前系统不是严格的 事件溯源。它同时拥有事件记录、物化 快照、RuntimeSession/History/检查点 等可变持久化模型；***事件存储*** 更准确地是事实日志与 流式传输/重放 基础设施。

## 依赖

运行时 到 ***运行时状态存储***（`RuntimeStateStore`） 是端口依赖，具体 SQL adapter 在 应用层/基础设施。***应用持久化宿主***（`AppPersistenceHost`） 依赖 ***事件存储***、***快照存储*** 和 SQLite write coordinator；***核心应用数据库***（`CoreAppDb`） 在启动时创建这些实现并注入 `CoreLiveOperationHost`、SessionStore 与 智能体 operations。

这条方向总体合理，但 ***核心会话存储***（`CoreSessionStore`） 直接依赖 ***核心应用数据库***（`CoreAppDb`） 和 ORM 快照 model，导致资源域与 storage model 绑定；恢复逻辑也仍由 `http_agent_app.py`、`live_operations.py` 和多个 Store 协同完成。

## 耦合

1. ***核心应用数据库***（`CoreAppDb`） 同时暴露 事件、快照、runtime 状态、project、goal、arrange、memory 和 persistence host，是便利的 聚合体，但也是跨域依赖入口。
2. ***核心会话存储***（`CoreSessionStore`） 在 快照 JSON、runtime preferences、plugin visibility、legacy 迁移 与 SessionRecord 之间做多种业务转换，职责超过纯 adapter。
3. 运行时 状态、CoreThreadSnapshot 和 事件/Projection 都可能携带 状态、turn、历史 或 元数据；如果没有明确写入顺序，调用方容易把 投影 当作 权威源。
4. ***应用持久化宿主***（`AppPersistenceHost`） 已经集中 write coordination，这是正确方向，但低延迟 流式传输、批量 追加、快照 投影 与 客户端 broadcast 仍需要由 应用层 明确编排。

## 风险

- P1：全局不存在单一 真实状态源；活动执行、会话 元数据、事件事实和客户端 投影 分属不同 拥有者，恢复语义需要靠约定维持。
- P1：***核心会话存储***（`CoreSessionStore`） / ***核心应用数据库***（`CoreAppDb`） 把领域 会话、快照 JSON 与 ORM 模式 绑定，模式 演进会波及 运行时 和 UI。
- P1：运行状态写入、事件追加、快照 投影、Hub publish 和 过期-turn 恢复 若从多个入口调用，可能产生重复、乱序或恢复竞态。
- P2：legacy 历史 blob、runtime preferences 迁移 与 快照 重建 增加了兼容路径，长期会提高恢复测试成本。

## 建议

1. 写下显式 状态所有权 contract：***运行时状态*** 是 active execution 权威源；***事件存储*** 是事实记录；快照 是 投影；UI 是 cache；插件 状态 由插件自身拥有。
2. 以 ***会话仓储***（`SessionRepository`）、***运行时状态仓储***（`RuntimeStateRepository`）、***事件仓储***（`EventRepository`）、***快照仓储***（`SnapshotRepository`） 和 ***恢复服务***（`RecoveryService`） 作为 应用层 ports，逐步隐藏 ***核心应用数据库***（`CoreAppDb`） 和 ORM model。
3. 将 已接受轮次 的状态保存、事件 追加、快照 投影、Hub publish 和 terminal convergence 纳入一个可测试的 应用层 transaction protocol。
4. 为 恢复 建立固定顺序和幂等键：先读 durable 已接受轮次 / 检查点，再按 seq 重放，最后恢复 ***运行时状态*** 和 实时 subscription。

## 证据

- `core/src/lamtools_core/runtime/__init__.py`
- `core/src/lamtools_core/app/core_db.py`
- `core/src/lamtools_core/app/persistence_host.py`
- `core/src/lamtools_core/app/event_store.py`
- `core/src/lamtools_core/app/snapshot_store.py`
- `core/src/lamtools_core/app/core_session_store.py`
- `core/src/lamtools_core/app/live_operations.py`
- `core/src/lamtools_core/app/http_agent_app.py`
- `core/src/lamtools_core/checkpoint.py`
- `core/src/lamtools_core/snapshot/__init__.py`
