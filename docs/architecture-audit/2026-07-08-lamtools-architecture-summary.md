# LamTools 架构整理总报告

日期：2026-07-08

维护标注（2026-07-08）：本报告写于非 Writer 成员下线之前。后续已将未验证成员从当前产品面移除；当前活跃结构应按 Core + Writer 理解，Artist/Imager 相关结论仅保留为历史审计证据。未来绘图成员应基于当前 Core 从干净脚手架重做。

## 一句话结论

LamTools 的主线架构已经成立：`CoreLoopKernel + RuntimeKit` 是共享运行骨架，Writer/Artist 的业务留在各自 member，Core UI 提供共享工作台。当前最该做的不是加新架构，而是减法：删除残留入口、收敛重复事实源、拆过宽页面/操作目录、标注历史文档，避免旧层继续和新主线并行维护。

## 本轮工作范围

本轮只做结构审计和报告落盘，不修改业务代码，不提交，不处理当前已有用户改动。

当前工作树已有非本轮改动：

- `members/writer/frontend/src/views/CoreWorkbenchView.vue`
- `docs/prototypes/`
- `members/writer/frontend/tests/runtime/runtimeResourceWidget.test.ts`

新增报告目录：

- `docs/architecture-audit/2026-07-08-structure-organization-plan.md`
- `docs/architecture-audit/modules/*.md`
- `docs/architecture-audit/2026-07-08-lamtools-architecture-summary.md`

## 统计底表

统计口径：Git 已跟踪的活跃源码和测试；排除运行产物、打包产物、历史截图、临时目录。

| 范围 | 文件数 | 总行数 | 非空行 |
| --- | ---: | ---: | ---: |
| 生产源码 | 398 | 80,438 | 71,089 |
| 测试 | 131 | 40,484 | 34,100 |
| 合计 | 529 | 120,922 | 105,189 |

主要区域非空行：

| 区域 | 非空行 | 判断 |
| --- | ---: | --- |
| Writer 后端 | 20,037 | 最大业务复杂度来源，主线可靠但操作目录和状态投影过宽 |
| Artist 后端 | 12,090 | 主线可靠，member 编排和图片上下文分叉是主要风险 |
| Core 后端 | 11,393 | 共享主线成立，需收口历史协议和产品名残留 |
| Core UI | 10,167 | seam 可用，内部实现和样式过宽 |
| Writer 前端 | 8,942 | 快照主线可靠，页面协调和桌面路线并行压力大 |
| Artist 前端 | 4,324 | 已接入 Core UI，旧状态链未删 |

当前最大热点：

- `core/ui/src/components/ChatThread.vue`
- `members/writer/frontend/src/views/CoreWorkbenchView.vue`
- `core/ui/src/styles/layout.css`
- `members/writer/frontend/src/views/SettingsView.vue`
- `members/writer/backend/app/app_server/operations.py`
- `core/src/lamtools_core/kernel/loop.py`
- `members/artist/backend/app/services/artist_service.py`

## 模块报告

| 模块 | 报告 |
| --- | --- |
| Core 后端协议与运行骨架 | `docs/architecture-audit/modules/2026-07-08-core-backend.md` |
| Core UI 共享工作台 | `docs/architecture-audit/modules/2026-07-08-core-ui.md` |
| Writer 后端、运行时与 CLI | `docs/architecture-audit/modules/2026-07-08-writer-backend.md` |
| Writer 前端、桌面与 app-server 客户端 | `docs/architecture-audit/modules/2026-07-08-writer-frontend.md` |
| Artist 后端、运行时与桌面 | `docs/architecture-audit/modules/2026-07-08-artist-backend.md` |
| Artist 前端 | `docs/architecture-audit/modules/2026-07-08-artist-frontend.md` |
| 脚本、根入口与成员脚手架 | `docs/architecture-audit/modules/2026-07-08-scripts-entrypoints.md` |
| 文档、测试、样例与历史资产 | `docs/architecture-audit/modules/2026-07-08-docs-tests-assets.md` |

## 可靠主线

- Core 后端：`CoreLoopKernel + RuntimeKit` seam 清楚，Kernel 管流程，Kit 管业务。
- Writer：app-server 后端快照已经是主线，前端可只连接和投影。
- Artist：`/artist-turn -> CoreLoopKernel + ArtistKit -> generate_images_core` 主链明确。
- Core UI：共享 Shell、会话栏、线程、输入条、运行面板的外部 seam 仍值得保留。
- CLI：Writer CLI 已经更接近 GUI 同接口，走 app-server 操作而不是独立 side-channel。
- 文档：`AGENTS.md`、`README.md`、现有架构底图和代码 inventory 能支撑继续减法。

## 跨模块问题

### 1. 主线已迁移，旧层未删

典型位置：

- Writer 旧 HTTP 路由与 app-server 并行。
- Writer 前端 `/api/core` 与 app-server 并行。
- Artist 前端旧 `stores/session.ts`、旧 SSE 状态链仍在。
- Artist 后端 `ExecutionEngine` 仍像历史计划执行路径。
- `writer_tui`、`start.bat`、部分桌面/E2E 旧入口仍在主视野。

判断：这是当前第一类债务。优先删残留和标主从，不要再加桥接层。

### 2. 事实源和投影重复

典型位置：

- Writer 同时有 transcript、app events、thread snapshots、session lifecycle 字段。
- Writer 前端同时维护本地 sessions、store sessions、app-server snapshot。
- Core 后端有多套事件形态：`CoreEvent`、`RunItemEvent`、`RuntimeEventRecord`、SSE payload。
- Core UI `ChatThread` 内部用工具名启发式解释 runtime 过程。

判断：先明确“事实源、投影、索引、展示模型”的主从关系，再拆文件。

### 3. 大文件不是根因，但已经影响维护

优先拆内部实现，不扩大外部接口：

- `ChatThread.vue`
- `CoreWorkbenchView.vue`
- `SettingsView.vue`
- `operations.py`
- `artist_service.py`
- `generate_service.py`
- `layout.css`

判断：这些模块外部 seam 多数还能用，问题是内部职责没有 locality。

### 4. 脚本入口说“all”，实际不全

典型位置：

- `scripts/build.ps1 all` 只构建前端，不含桌面包。
- `scripts/test.ps1 all` 不含 Core UI、Writer 前端、E2E smoke。
- `lamtools doctor` 仍检查旧 AppData Writer 数据库。
- 新成员脚手架生成后还要手工更新 dev/build/test。

判断：入口语义和执行范围必须先对齐，否则后续自动化和文档都会漂。

### 5. 文档和样例资产污染主视野

典型位置：

- `docs/superpowers/**`、`docs/plans/**`、`docs/stages/**` 是实施档案，不应作为当前事实入口。
- `e2e/test-apps`、根 `test-*`、`kbtool-task` 更像 fixtures/archive。
- Writer 文档内存在 Artist 历史内容。

判断：保留历史，但加维护标注和索引分类；不重写历史，不把样例当产品模块。

## 优先级路线

### P0：先清理会误导主线的残留

- Core：修正 member 模板与 Core HTTP 路由契约；清理 `core/src/lamtools_core/appserver` 缓存残留；把 `writer_message_id` 迁出 Core。
- Core UI：清理 `writer-shell/writer-main` 等产品命名；收窄 `index.ts` 暴露；合并重复类型。
- Writer 后端：删除/归档 `writer_tui`；删除 Core 命令重导出层；给旧 HTTP 路由标主从；列 CLI parity 缺口。
- Writer 前端：确定 Electron 为当前发布主线，Tauri 降级为实验/冻结；收敛会话事实源；把 app-server 投影从页面剥离。
- Artist 后端：收敛图片上下文到一个入口；改名/合并 Hook 语义测试；拆 `artist_orchestrate()` 的桥接职责。
- Artist 前端：删除旧 session store/SSE/billing/download 等断入口旧层；会话更新收敛到 workbench adapter。
- 脚本入口：降级 `start.bat`；修正 `lamtools doctor` Writer 数据库检查；处理未注册 `members/imager`。
- 文档测试：更新 `docs/documentation-inventory.md`；给 Writer 历史文档加维护标注；修正 test/build 入口口径。

### P1：再拆大文件和统一协议

- 拆 `operations.py` 为 session/project/config/runtime/artifact 操作模块，保留 catalog 组装点。
- 缩 `connection.py`，合并重复 JSON-RPC 分发逻辑。
- `ChatThread` 拆私有投影层和私有渲染块，对外仍吃 `CoreMessage[]`。
- `layout.css` 按 shell/sidebar/composer/runtime/thread/settings 拆分所有权。
- Writer/Artist 设置页复用 `core/ui` 的 `SettingsShell` 和主题编辑能力。
- 建最小成员注册表，让 `lamtools_cli.py`、ps1、脚手架读同一份事实。
- 明确事件协议：哪个是运行事实、哪个是持久化 DTO、哪个是展示快照。

### P2：最后做体验和长期治理

- 为文档加轻量状态标记：current / historical / plan / preview / fixture。
- 样例资产建索引：用途、引用方、删除条件。
- 桌面构建入口拆成 frontend / desktop / all。
- 测试入口拆成 backend / frontend / e2e / all，默认轻量，显式全量才跑重测试。
- 将 WriterGitManager、workspace file tools、provider profiles 等内部再细分，但保持外部接口稳定。

## 不建议现在做

- 不要恢复 HookSet 或新增平行 Hook 层。
- 不要把 Writer/Artist 业务下沉 Core。
- 不要重写 CoreLoopKernel。
- 不要新增“统一状态管理器”盖在旧状态上。
- 不要同时优化 Electron 和 Tauri 两条桌面路线。
- 不要把所有历史文档合成一本巨型文档。
- 不要为文档系统先做复杂生成器。

## 后续建议

下一步最适合拆成 4 个独立减法任务：

1. 入口与脚手架收敛：`start.bat`、doctor DB、成员注册表、PowerShell UTF-8、build/test 口径。
2. Writer 事实源收敛：旧 HTTP 主从标注、CLI parity 缺口、前端会话源和页面投影下沉。
3. Core/Core UI 清洁：产品名残留、模板契约、事件协议主从、`ChatThread` 内部拆分准备。
4. 文档/样例资产治理：文档索引、历史标注、fixtures/archive 清单、test 入口对齐。

这些任务都应先写小计划，再按模块做 TDD 或最小验证；涉及 OpenAI/Claude 对齐或具体实现时，再单独做官方资料核对。
