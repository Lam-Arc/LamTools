# Writer 前端、桌面与 app-server 客户端

## 一句话结论

Writer 前端主线已经转向“后端快照为事实源、前端只连接和投影”，这是可靠方向。当前最大结构问题是 `CoreWorkbenchView.vue` 和 `SettingsView.vue` 承载过多协调职责，同时 Electron/Tauri、`/api/core`/app-server、Settings 本地壳/core-ui 之间存在并行路线。

## 路径覆盖

- `members/writer/frontend/src`
- `members/writer/frontend/electron`
- `members/writer/frontend/scripts`
- `members/writer/frontend/src-tauri/src`
- `members/writer/frontend/tests`
- 必要的 `core/ui/src`
- `docs/architecture-audit/2026-07-08-structure-organization-plan.md`

本报告只读分析，未运行测试，未改文件。

## 主要职责和入口

- 路由很薄：`/` 到工作台，`/settings` 到设置页，`file:` 下切 hash history。
- 桌面桥统一暴露 `window.lamwriterDesktop`：Tauri 在 `main.ts` 里注入；Electron 在 `preload.cjs` 注入。
- app-server 客户端分层基本清楚：`client.ts` 是 WebSocket JSON-RPC 传输，`store.ts` 管连接、重连、resume、快照水位，`snapshot.ts` 补默认字段，`selectors.ts` 做 UI 投影。
- 工作台使用了 `core/ui` 的 `WorkspaceShell`、`SessionSidebar`、`ChatThread`、`AttachmentTray`、`CommandPalette` 等，但页面内部仍负责会话分组、消息投影、命令、附件、授权、运行指标、Git 审查、项目弹窗和滚动。
- 设置页使用了 `core/ui` 的 `PROVIDER_PRESETS`，但没有使用现成 `SettingsShell.vue`，主题编辑也大量本地实现。
- Electron 是当前一键包主线：`package.json` 的 `desktop:unpacked` 指向 `package-electron-unpacked.ps1`。Tauri 仍保留完整便携包路线。

## 可靠

- app-server 快照权威方向可靠：`store.test.ts` 明确验证“响应快照优先，事件不在前端建状态”。
- 断线恢复位置合理：重连、`lastSeenSeq`、`thread/resume` 在 store，传输层保持薄。
- 协议有 schema 检查入口：`scripts/check-app-server-schema.mjs`。
- 共享 UI 主壳已复用：工作台入口依赖 `core/ui`，不是 Writer 自造整套 shell。
- Provider 预设已下沉 core/ui：`SettingsView.vue` 使用 `PROVIDER_PRESETS`。

## 存疑

- `/api/core` 与 app-server 并行：工作台通过 `api/core.ts` 拉 core session，同时业务 CRUD 通过 `api/index.ts` 临时 WebSocket 调 app-server。短期闭环可用，长期会制造会话事实源分叉。
- `selectors.ts` 已经不是简单选择器：它合并 outer/core item、过滤旧 runtime 投影、归一 legacy 字段、压制 sub-agent 重复输出。这是必要兼容还是后端快照未收敛，需要判定。
- `CoreWorkbenchView.vue` 直接同步 `sessions` 和 `sessionStore.sessions`。这属于前端自建局部事实，容易和后端列表漂移。
- Settings 的“远端设置 + localStorage fallback”闭环可用，但本地/远端双写带来来源不清。
- 桌面两条路线都能跑后端、选目录、找资源，但没有主次标记。

## 债务

- `CoreWorkbenchView.vue` 约 3365 非空行，是页面协调中心，不是薄页面。
- `SettingsView.vue` 约 2066 非空行，且隐藏区仍保留大段源码：`Writer 行为`、`项目默认值`、`工具与 Agent` 都是 `v-if="false && ..."`。
- Electron/Tauri 重复实现后端生命周期、端口、资源路径、目录选择。
- 部分桌面 E2E 脚本仍读取旧 HTTP 会话/消息/步骤接口作为证据。
- 设置页重复 core/ui 已有壳和主题能力，尤其 `SettingsShell.vue`、`ThemeEditor`、`ThemeAreaEditor` 已在 core/ui 导出。

## 重构/优化建议

### P0

- 定主桌面路线。按当前包产物和脚本，建议保留 Electron `desktop:unpacked` 为产品主线；Tauri 标记为实验/冻结，若无近期验收需求则移出默认脚本和报告主线。
- 收敛会话事实源。工作台不要同时维护 `sessions`、`sessionStore.sessions`、app-server snapshot 三套状态；至少先把列表更新集中到一个小模块，页面只调用一个入口。
- 把 app-server 投影规则从页面剥离。`selectChatMessages` 后的 `appServerItemToPart`、运行指标聚合、队列投影应从 `CoreWorkbenchView.vue` 移到独立投影模块，页面只拿 `CoreMessage[]` 和右栏 view model。

### P1

- 清理 Settings 隐藏区。遵守“临时隐藏区不按功能丢失修复”，但可以把隐藏区代码移到隔离文件或历史注释清单，避免继续增加页面负担。
- 复用 `SettingsShell` 和 core/ui 主题编辑能力，先替换壳和公共控件，不新增抽象。
- 将 Electron/Tauri 共用的“后端启动参数、runtime 资源布局、数据目录规则”沉到脚本/配置说明，至少保证两条路线不各自发明路径约定。

### P2

- `api/index.ts` 的一次性 WebSocket RPC 可以保留，但建议后续封装成 app-server operation client，避免每个设置/项目动作都知道传输细节。
- 桌面 E2E 证据迁移到 app-server snapshot/JSON-RPC 口径，旧 HTTP 证据只保留兼容检查。
- `runtimeResourceSummary` 这类右栏展示可以沉到小 helper；当前已有 `runtimeResourceWidget.test.ts`，但测试是源码字符串匹配，后续应改成纯函数输入输出测试。

## 不建议现在做

- 不建议重写 app-server 协议。当前 snapshot-only 主线已有测试保护，问题是重复入口和页面承载过重。
- 不建议恢复隐藏的 Writer 行为、项目默认值、工具与 Agent 设置页。
- 不建议同时优化 Electron 和 Tauri 两条桌面路线；先定主线再谈完善。
- 不建议把 Writer 专用运行指标直接下沉 core/ui；先抽成 Writer 投影模块，确认 Artist 也需要时再共享。

## 需要主线程核对的证据

- 是否确认 Electron 是当前发布主线：`desktop:unpacked`、`package-electron-unpacked.ps1`、历史一键包都指向 Electron。
- 是否允许把 Tauri 从默认维护面降级为实验路线。
- `/api/core/sessions` 是否仍是必须入口，还是可以由 app-server `session.list` 统一承接。
- `selectors.ts` 中 outer/core 合并和 legacy 字段归一化，哪些是后端仍会产生的当前事实，哪些只是历史兼容。
- Settings 隐藏区是否只保留历史源码，还是后续要独立重做。
