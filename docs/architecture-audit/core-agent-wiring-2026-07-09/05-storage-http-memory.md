# 05 - 存储 / HTTP / Usage / Memory 审计

## 主验收结论

Core 已有 session、runtime event、SQL app event、snapshot、usage、memory 协议等基础设施；Writer 已经开始复用 Core SQL event/snapshot 适配器。但 Core CLI、AgentApp、HTTP 管理面没有统一写入同一条运行事实链。

## Core 已有存储能力

| 能力 | 现状 | 持久化 |
|---|---|---|
| Session | 会话和消息 store 协议 + 内存实现。 | 内存。 |
| Runtime Event | 运行事件协议、内存 store、SSE hub。 | 内存。 |
| App Event | SQLAlchemy 通用 app event store。 | SQL，宿主提供表模型。 |
| Snapshot | RunItemEvent reducer、内存 snapshot、SQL snapshot store。 | 内存 + SQL。 |
| Usage | usage ledger 协议和内存实现。 | 内存。 |
| Memory | Memory store/adapter/budget 协议和 prompt 格式化。 | 无具体 store。 |

## 证据

- `InMemorySessionStore`：`core/src/lamtools_core/session/__init__.py:76`。
- `InMemoryUsageLedger`：`core/src/lamtools_core/usage/__init__.py:72`。
- `MemoryStoreProtocol`：`core/src/lamtools_core/mem/__init__.py:103`。
- `SqlAlchemyAppEventStore`：`core/src/lamtools_core/app/event_store.py:75`。
- `SqlAlchemyThreadSnapshotStore`：`core/src/lamtools_core/app/snapshot_store.py:89`。
- Writer 已复用 Core event store：`members/writer/backend/app/app_server/ledger.py:8`、`members/writer/backend/app/app_server/ledger.py:14`。

## Core CLI 现状

Core CLI 走真实 Kernel，但运行状态和事件是临时的：

- 状态 store 是 `InMemoryRuntimeStateStore`：`core/src/lamtools_core/cli.py:387`。
- 输出 `events-redacted.json` 和 `summary.json`：`core/src/lamtools_core/cli.py:404`、`:405`。
- 不写 Core SQL app event。
- 不写 SQL snapshot。
- 不写 UsageLedger。

## AgentApp 现状

AgentApp 可以注入 session/snapshot/event sink，但默认是内存：

- default agent 使用 `InMemorySessionStore`：`core/src/lamtools_core/app/default_agent.py:74`。
- `turn.start` 是 operation，但走 AgentApp，不走 Kernel。
- SQL event/snapshot 适配器没有接入 default agent。

## HTTP `/api/core` 现状

`/api/core` 是管理面，不是运行面：

- router 入口：`core/src/lamtools_core/http/routes.py:94`。
- 默认内存 session：`core/src/lamtools_core/http/routes.py:109`。
- 默认内存 usage：`core/src/lamtools_core/http/routes.py:124`。
- factory 挂 router：`core/src/lamtools_core/app/factory.py:111`、`:113`。

它能管理 session、message、event、provider、usage；不能触发真实 Agent run，不能恢复 SQL snapshot，不能访问 memory store。

## 统一链路建议

目标链路：

`CoreLoopKernel/CoreAgentRuntime -> CoreEvent -> RunItemEvent -> core/runItem app event -> thread snapshot`

具体建议：

1. 以 `RunItemEvent -> core/runItem -> snapshot` 为唯一展示/恢复事实链。
2. CLI Kernel 发出的 `CoreEvent` 先通过已有 runtime projection 转成 RunItemEvent，再写 app event/snapshot。
3. AgentApp 若保留，也要把 RunItemEvent 交给同一持久化 sink。
4. HTTP 增加 operation endpoint，触发真实 `turn.start`，不要只允许手工创建 event。
5. Usage 先从 run summary/snapshot 聚合，不急着扩 SQL ledger。
6. Memory 先不宣称持久化；等有真实召回需求再接具体 store。

## 验收用例

- `core run` 后能查到 app events、thread snapshot、summary 三者 session/run 对齐。
- `/api/core` 能发起真实 `turn.start`。
- 刷新后能从 SQL snapshot 恢复 Core Agent 展示状态。
- Writer `writer_app_events` / `writer_thread_snapshots` 仍通过 Core SQL 适配器写入。
- CLI、HTTP、AgentApp 不再各自产生不可互相恢复的临时事件流。

