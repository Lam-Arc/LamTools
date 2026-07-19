# Writer 后端、运行时与 CLI

## 一句话结论

Writer 后端主线已经收敛到 `CoreLoopKernel + WriterKit + backend-only app snapshot`，方向可靠。当前最大问题不是 Core 主线，而是 Writer 侧入口、状态投影、HTTP/app-server/CLI 适配层过宽并行，应该先删残留和合并入口，再拆大文件。

## 路径覆盖

- `members/writer/backend/app`
- `members/writer/backend/writer_cli`
- `members/writer/backend/writer_tui`
- `members/writer/backend/tests`
- `members/writer/AGENTS.md`
- 必要 Core 接口：`core/src/lamtools_core/kernel`、`app`、`snapshot`、`tool`
- 结构计划：`docs/architecture-audit/2026-07-08-structure-organization-plan.md`

规模证据：

- `members/writer/backend/app/app_server/operations.py`：约 2041 非空行，注册 64 个操作，76 个顶层函数。
- `members/writer/backend/app/app_server/connection.py`：约 845 非空行，79 个方法。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`：约 1275 非空行。
- `members/writer/backend/writer_cli/__main__.py`：约 908 非空行，17 个 CLI 命令。
- `members/writer/backend/writer_tui`：没有 Git 跟踪源码，只剩目录和 `__pycache__`。

## 主要职责和入口

App-server 是 GUI/CLI 的统一操作入口：`/api/app-server` WebSocket 接收 JSON-RPC，`OperationCatalog` 注册 `session.*`、`project.*`、`turn.*`、`config.*`、`command.execute` 等操作；事件进入 `writer_app_events`，再落 `writer_thread_snapshots`。

运行时入口是 app-server 的 `turn.start`，进入 `WriterRuntimeLifecycle` 后异步调用 Writer 服务，再由 `WriterRuntimeRunner` 进入 `run_core_kernel`。

WriterKit 是业务注入点：负责 persona、项目规则、工具目录、权限、模型输出解析、验证、writeback、子 agent。Core 只管循环骨架，符合“Kernel 管流程，Kit 管业务”。

工具层大体可靠：命令、文件、Git diff/status、Web 工具主要复用 `core/src/lamtools_core/tool`；Writer 只装配权限、业务工具和 sub-agent 语义。

数据库主源在 `members/writer/data/lamwriter.db`；`LAMWRITER_DATA_DIR` 优先；旧 AppData 库只在新库不存在时迁移，和当前规则一致。

CLI 当前通过 `AppServerClient` 连接同一个 app-server WebSocket，不再走独立 side-channel。`run/resume/watch/cancel/list/show/status/result/compact/open-change-file/project create/pick-directory` 已覆盖核心运行链路。

## 可靠

- `CoreLoopKernel + WriterKit` 主线可靠：Core 不认 Writer 产品名，Writer 业务留在 member。
- app-server 后端快照主线可靠：前端可只水合 backend snapshot，不再维护前端 reducer 作为第二套真相。
- 数据目录规则可靠：默认项目内 `members/writer/data`，旧库只迁移。
- 工具执行方向可靠：Writer 复用 Core 命令/文件/快照/投影基础能力，没有明显重写第二套命令执行器。
- CLI 核心运行链路可靠：测试明确约束 session/run/message/status 等命令使用 app-server 操作。
- 删除旧 runtime events endpoint 的方向可靠：测试证明 `/api/sessions/{id}/runtime-events` 不再挂载。

## 存疑

- 状态源偏多：`writer_sessions.status/phase/runtime_state/context_summary`、`writer_transcript_*`、`writer_app_events`、`writer_thread_snapshots` 都在表达运行状态。可接受，但必须明确“transcript/事件是事实，snapshot/session 是投影/索引”。
- `operations.py` 是过宽操作目录：session/project/config/queue/approval/artifact/command 全塞在一个文件，接口深度不足。
- `connection.py` 每个操作都有转发方法，像机械分发表，和 `operations.py` 形成双宽面。
- 旧 HTTP 路由仍与 app-server 并行：`/api/sessions`、`/api/projects`、`/api/config`、`/api/core/*`。可能是兼容入口，但需要标注主从。
- CLI 展示层重复投影：`writer_cli.__main__` 重新解析 `core/runItem`、snapshot、状态标签；短期必要，长期应减少自定义解释。
- 测试很多，但大量使用 fake/monkeypatch，与 `members/writer/AGENTS.md` 的“不使用 mock 测试”冲突。

## 债务

- `members/writer/backend/writer_tui` 是残留目录：无源码、无 Git 跟踪，仅 pycache。
- `members/writer/backend/app/core/writer/command_runner.py` 是 Core 私有命令函数重导出，属于兼容层，应找调用方后删除。
- `hook_context` 命名残留在测试和 WriterKit 语义里，容易误导成 HookSet 平行层。
- `app_server/reducer.py` 仍处理 `turn/started` legacy 事件，说明快照协议还背历史形状。
- CLI 没有完整覆盖 GUI 能力：配置/模型、附件、artifact、队列、版本图、检查点、commit review、agent branch、undo 等没有同接口 CLI。
- `writer_service.writer_orchestrate()` 返回函数字典，接口不够深，调用方必须知道字符串键。
- `WriterGitManager` 过大，Git 图、checkpoint、agent branch、merge/restore 混在一起；它是 Writer 业务，不该下沉 Core，但需要内部拆分。

## 重构/优化建议

### P0

- 删除或归档 `writer_tui` 残留目录；没有源码就不要作为活跃模块统计。
- 查生产调用后删除 `app.core.writer.command_runner` 重导出层，直接引用 Core 命令模块。
- 给旧 HTTP 路由加当前状态标注：app-server 是 GUI/CLI 主入口，HTTP 是兼容/外部适配入口；禁止新 GUI 功能只走 HTTP。
- 把 CLI parity 缺口列成表，至少为设置/模型配置、附件、检查点、commit review、agent branch 增加同 app-server 操作命令或明确暂不支持。

### P1

- 拆 `operations.py`，按业务目录拆成 `session_ops`、`project_ops`、`config_ops`、`runtime_ops`、`artifact_ops`，保留一个 catalog 组装点。
- 缩 `connection.py`：把重复的“调用 handler、发送 response、publish events”合并成统一执行路径，减少 70 多个手写转发方法。
- 明确状态主从文档和测试：事件/transcript 为事实，snapshot/session lifecycle 为投影；状态冲突时统一从 transcript/app event 重建。
- 把 CLI formatter 的 core run item 解释迁到共享投影辅助，CLI 只负责文本展示。

### P2

- 将 `WriterGitManager` 内部拆为 checkpoint、agent branch、graph/query 三个私有模块，外部仍保留一个 Writer Git 门面。
- 将 `writer_orchestrate()` 的函数字典换成小接口对象，先不新增抽象层，只减少字符串键耦合。
- 逐步把 `hook_context` 改名为 `business_context` 或 `runtime_context`，避免 HookSet 历史误导。

## 不建议现在做

- 不要恢复 HookSet 或任何平行 Hook 层。
- 不要把 Writer persona、项目规则、专用工具下沉 Core。
- 不要重写 CoreLoopKernel；当前债务集中在 Writer 适配和投影层。
- 不要现在重建 TUI。先删残留，等 CLI parity 稳定后再判断是否需要 TUI。
- 不要大迁移数据库结构；先把状态主从关系写清，再小步收敛。
- 不要新增一个“统一状态管理器”盖在现有状态上；先删重复投影和旧兼容。

## 需要主线程核对的证据

- 前端是否仍直接调用 `/api/sessions`、`/api/projects`、`/api/config`；如果是，要决定迁到 app-server 还是正式标为 HTTP 兼容入口。
- `writer_tui` 是否可直接清理；当前 Git 没跟踪源码。
- CLI parity 的验收范围：是否要求所有 GUI 能力都有命令，还是只要求用户可见关键能力。
- fake/monkeypatch 测试是否允许作为“外部服务替身”，否则 backend 测试规则和现实测试写法冲突。
- `hook_context` 命名是否要随本轮结构整理统一改名，避免后续 agent 误判为 HookSet 复活。

本轮只做静态只读分析，未修改文件，未运行测试。
