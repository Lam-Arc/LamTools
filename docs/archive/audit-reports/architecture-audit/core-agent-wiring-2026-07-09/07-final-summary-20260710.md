# Core-first 最终汇总与自审（2026-07-12）

## 当前结论

Core 已成为可独立运行的基础 Agent。Writer 通过 Core host、Kernel、实时协议、事件/快照、工具、权限、配置和共享 UI 工作台运行，只保留项目、附件、Transcript、AGENTS.md、Git、Review、Checkpoint、Rollback、persona 等 Writer 特化。

Core CLI、HTTP、WebSocket、存储和 UI 契约均已通过，Core 与 Writer CLI/GUI/WS 均已完成真实 Kimi 验收。独立审计发现的 Writer 模型 fallback、平行 approval/request continuation、重复 reducer 终态计算和官方测试入口缺口均已整改；第三次独立终审结论为 `PASS`。

## 已完成的架构收口

1. Core host 直接拥有 36/36 个通用 Workbench operation。Writer catalog 只能追加 Writer overlay，不能 fallback 或覆盖 Core operation。
2. Core 统一拥有 turn start/steer/cancel、queue create/update/delete/guide、approval、事件、快照、terminal、live connection、CLI 与 HTTP/WS 骨架。
3. Core queue 支持文本、Skill 和附件输入。附件 ID、可见输入和 runtime 输入随事件及快照持久化，并在 dispatch 时恢复。
4. Writer 旧 `WriterQueuedInput`、`queued_input_service`、`WriterAppRequest` 和审批 mutation API 已删除；旧数据库中已存在的历史表不主动破坏。
5. Writer runtime 的投影失败不再被吞掉，而是上抛给 Core，由 Core 生成唯一 failed terminal。Writer transcript/session 终态只由已持久化 Core terminal 事件派生。
6. 实时 Core 事件只写入一次；Kernel summary 不再重复回放已实时持久化事件，消除了伪 tool 块和矛盾终态。
7. LLM、工具、approved tool、checkpoint、restore、commit review、rollback 和 Git init 均在 SQLite 写锁外执行；数据库阶段使用 claim、锁外副作用、条件持久化的短事务。
8. Writer REST、HTTP Core adapter 与 app-server 共用可注入的 Writer write coordinator；隔离数据库、多实例和测试不再绕回全局 Writer DB。
9. Core UI 是 `@lamtools/ui` 公共包。Writer 不再相对导入 `core/ui/src`，不再实现通用 app-server store、controller、send/stop、queue、approval、模型/thinking/shallow 状态机。
10. Core UI 已清除 Writer/Artist 产品语义和旧 `writer-shell`/`writer-main` 标记；Writer 只保留产品页面组合、项目栏、Transcript 与右栏特化。
11. `approval.respond` 统一经过 Core operation catalog，并以 Core runtime state 的 `pending_approval` 为唯一真相源。Writer 不再查询 Transcript waiting block、不再拥有 member approval lifecycle hook，只注入专用工具、模型/Kernel continuation 与 Transcript 单向投影。
12. Writer 子 Agent 不再在鉴权失败后隐式切回 Writer 模型；路由后的模型失败直接进入 Core failure lifecycle。
13. Core snapshot projector 统一处理 thread、turn、item、request、queue、terminal 和 rollback 通用清理；Writer reducer 只解析 Writer rollback payload，其余通用事件直接委派 Core。

## 数据库边界

| 数据库 | 所有权 | 内容 |
|---|---|---|
| `data/lamtools.db` | Shared config | Provider、API Key、Model、通用配置与 Writer 路由配置 |
| `data/core.db` / `LAMTOOLS_CORE_DB` | Core | Core runtime session、event、snapshot |
| `members/writer/data/lamwriter.db` / `LAMWRITER_DATA_DIR` | Writer | Writer project、session、transcript、attachment、artifact 与 member projection |

Provider/Model 不写入 Core runtime DB 或 Writer runtime DB。Core 与 Writer runtime DB 相互独立，配置只填写一次并共享。

## Writer 合理保留项

- Writer persona、业务 prompt、专属工具及产品文案。
- Project、Writer session 领域字段、附件、Transcript、AGENTS.md。
- Git diff、branch、checkpoint、review、rollback 与文件变更右栏。
- Writer 模型路由选择和旧库/旧环境变量迁移适配。
- 将 Core 通用事件投影为 Writer Transcript 的 member adapter。

这些均是 Core 的增量 patch，不拥有 Agent lifecycle 或通用 Workbench 编排。

## 自动化验证

- Core 后端全量：`764 passed`。
- Writer 后端全量：`742 passed`。
- Core UI contract：`16 files / 110 assertions passed`，包含 Vite WebSocket proxy 防回归契约。
- Core UI build：通过，`dist/index.d.ts` 与 `dist/lamtools-ui.css` 存在。
- Writer frontend：`53 passed`，lint、typecheck、build 通过。
- 官方 `scripts/test.ps1 all`：通过；统一覆盖 Core 后端 `764`、Core UI `110`、Writer 后端 `742` 和 Writer frontend `53`，不再把脚手架模板示例测试当作产品测试收集。
- Writer 真实 FastAPI/Uvicorn WebSocket E2E：通过；覆盖 initialize、thread.start、queue CRUD、断线重连、thread.read 和 SQLite 持久化。
- Writer SQLite lifecycle：`19 passed`；覆盖真实 runtime + terminal command + 12 路 steer，以及 Git 阻塞时并发数据库写入。
- `git diff --check`：通过；仅有工作区 CRLF 提示。

已知测试噪声：Windows Proactor/aiosqlite 在事件循环关闭后的 transport 清理 warning；不影响断言，但后续可单独治理。Writer production build 仍有既有的大 chunk warning。

## 真实 Kimi K2.6 验收

### Core CLI

- 模型：`Kimi-K2.6`，model record `906d775ffa9f489e86c74b3d42451631`。
- 思考：开启，budget `10000`。
- 结果：`decision=done`，2 轮模型调用，有 reasoning、text、`write_file` tool call/result。
- 文件：`E:\LamTools\.acceptance\core-kimi-final\core-proof.md`，20 行。
- Core DB：`E:\LamTools\.acceptance\core-kimi-final\core.db`，包含 Core event/snapshot/runtime 表。
- 证据：`E:\LamTools\tmp\core-cli-run-20260712-003126\summary.json` 与 `events-redacted.json`。

### Writer CLI / WS

- 模型：同一 Kimi K2.6，共享配置读取，思考开启。
- Session：`0c995f6110694b9b94ac6c2f8b9c3eaa`。
- 结果：completed；数据库含 thinking、message、tool_call、tool_result、usage、running/completed；模型调用不少于 2 次。
- 工具：`write_file`。
- 文件：`E:\LamTools\members\writer\backend\.acceptance\writer-kimi-final\work\writer-proof.md`，21 行，UTF-8 正常。
- Writer DB：`E:\LamTools\.acceptance\writer-kimi-final\data\lamwriter.db`。

### Writer GUI

- 页面真实连接隔离 Writer backend 与 app-server WebSocket。
- 可见 Kimi-K2.6、Max 思考、Shallow、附件、Send、Diff 和资源统计。
- 历史过程可展开查看 reasoning、`write_file` 和最终正文。
- GUI 发送后 100ms 内显示“请求中”，Send 切换为“停止运行”；完成后恢复“发送”。
- 最终 follow-up 正文正确显示，中文无乱码。

### Core GUI

- 页面真实连接隔离 Core backend 与 Core app-server WebSocket；Vite `/api` proxy 已启用 WebSocket 转发。
- 可见 Kimi-K2.6、Max/High/Medium/Low/No thinking、Shallow、Send 与运行状态面板。
- 发送后立即显示“请求中”，Send 切换为“停止运行”；完成后恢复“发送”。
- 首个真实任务完成 2 轮模型调用、2 段 reasoning、`write_file` 和最终正文；文件 `E:\LamTools\.acceptance\core-gui-final\work\core-gui-proof.md` 共 22 行。
- 第二个真实任务先使用不兼容的命令失败，随后 Agent 根据工具结果自主修正为 PowerShell 命令并再次调用 `run_tests`；成功输出 `core-gui-stop-proof`，最终正文返回 `exit_code: 0`。该任务覆盖流式思考、失败工具结果、多轮纠错、成功工具结果、无工具调用即停止和 completed terminal。

### 独立终审

- 前两次审计发现的 fallback、approval/request、reducer 和官方测试入口阻断均已逐项整改。
- 第三次 Sol 独立审计最终结论：`PASS`，无阻断项。

## 自审结论

“Core Agent 独立 CLI/HTTP/WS/存储/GUI 可用”“Writer 复用 Core 且原功能可用”“共享配置与 runtime DB 分离”“通用能力不在 Writer 重复实现”已有当前代码、自动化测试与真实 Kimi 运行证据。

最终独立审计、自动化门禁和真实 Core/Writer 验收均已完成，当前目标可以关闭。
