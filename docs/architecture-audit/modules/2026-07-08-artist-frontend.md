# Artist 前端

## 一句话结论

Artist 前端主入口已经切到 `core/ui` 共享工作台，这是可靠主线。主要债务是旧 Artist 会话状态链、旧 SSE/运行进度投影、设置页主题/设置 shell 自建实现仍留在 member，形成“主线已迁移、旧层未删除”的并行维护压力。

## 路径覆盖

- `members/artist/frontend/src`
- `members/artist/frontend/package.json`
- 必要核对：`members/artist/frontend/src/views/CoreWorkbenchView.vue`
- 共享依赖核对：`core/ui/src/index.ts`、`WorkspaceShell.vue`、`SessionSidebar.vue`、`RuntimePanel.vue`、`SettingsShell.vue`、`ThemeEditor.vue`、`useCoreWorkbenchController.ts`
- 后端边界核对：`members/artist/backend/app/routers/core_http.py`、`session.py`、`billing.py`、`settings.py`
- 计划文档核对：`docs/architecture-audit/2026-07-08-structure-organization-plan.md`

## 主要职责和入口

- `main.ts`：挂载 Vue、Pinia、Router，并引入 `@lamtools/ui` 共享样式。
- `router/index.ts`：当前只有 `/` 和 `/settings`。`/` 指向 `CoreWorkbenchView.vue`，没有暴露旧会话页面入口。
- `CoreWorkbenchView.vue`：Artist 前端主线。复用 `WorkspaceShell`、`SessionSidebar`、`ChatThread`、`RuntimePanel`，用 `useCoreWorkbenchController` 管会话选择、消息加载、发送、provider 数量。
- `api/core.ts`：共享工作台适配层。读会话、消息、事件、provider、usage 走 `/api/core/...`；发送任务映射到 `/api/sessions/{id}/artist-turn`，这是关键业务入口。
- `views/SettingsView.vue` + `views/ApiManage.vue`：设置、provider/vendor、默认模型、下载目录、UI 主题配置。
- `stores/provider.ts`：设置页 provider/vendor 状态源，边界相对清楚。
- `stores/session.ts`：旧 Artist 会话、消息、运行进度、事件翻译、谱系抽屉状态源；当前主工作台未引用。
- `components/session/LineageDrawer.vue`、`Lightbox.vue`：Artist 图片谱系和图片查看，属于产品专用能力，但当前主线未接入。
- `package.json`：Vue 3 + Pinia + Vue Router + Axios + `@lucide/vue`；没有把 `@lamtools/ui` 作为包依赖，而是 Vite/TS alias 指到 `../../../core/ui/src`。

## 可靠

- 主页面复用 `core/ui` 工作台，不再在 Artist member 复制产品无关 shell。
- `CoreWorkbenchView.vue` 把通用聊天发送改为 Artist 业务动作 `/artist-turn`，符合真实任务启动链路。
- `/api/core/...` 作为共享工作台读模型，`/api/sessions/{id}/artist-turn` 作为产品业务写入口，方向正确。
- Provider/vendor/settings 的设置页边界基本清楚：配置归 settings/provider，主工作台只读 provider 数量和 usage。
- `SessionSidebar` 的分组复用比复制侧栏更合理；Artist 没有后端 project 概念，当前用本地分组适配两级侧栏，短期可接受。
- `LineageDrawer` 这类图片谱系展示是 Artist 专用，不应下沉到 core/ui。

## 存疑

- `CoreWorkbenchView.vue` 的会话改名使用 `sessionApi.update`，而其他工作台读写会话走 `api/core.ts`；同一页面混用 core 口径和原生 session 口径，边界不够统一。
- 本地 `sessionGroups` 按 `localStorage` 保存 session id，后端删除、跨设备、重建数据后可能产生脏引用；但目前没有后端 project 概念，不能直接判为必须改。
- `api/core.ts` 同时叫 “Core API”，但 `startCoreArtistTurn` 直接写 Artist persona 和 `/artist-turn`，实际是“Core 工作台适配器 + Artist 业务动作”混合。
- `SettingsView.vue` 约 807 行，包含设置壳、主题编辑、默认模型、下载目录、缓存清理；能用，但不是深模块。
- `lamtools-ui.d.ts` 是手写的 `@lamtools/ui` 声明，同时 tsconfig 已直接 include `core/ui/src`。这份声明有漂移风险。
- `core/ui` 内部仍有 `writer-shell`、`writer-main` 类名，以及少量 Writer/Artist 注释。这不是 Artist 前端本身的问题，但会影响“Core 不认产品名”的整洁度。

## 债务

- `stores/session.ts` 是最大债务：旧状态源维护 sessions/messages/runtimeProgress/runtimeActivity/SSE 事件翻译，但当前 `CoreWorkbenchView` 不用它。它和 `useCoreWorkbenchController` 是重复状态源。
- `composables/useSessionEvents.ts`、`api/sse.ts` 当前未被主入口引用，且和 `/api/core/.../events/live`、core 工作台事件读取职责重叠。
- `stores/billing.ts` + `api/billing.ts` 当前未被主线引用；主工作台只用 `/api/core/usage/total`。
- `api/download.ts`、`useDownload.ts`、`useMarkdown.ts`、`Lightbox.vue`、`ErrorBoundary.vue` 当前未被主路由或主工作台引用，疑似旧页面残留。
- `SettingsView.vue` 复制了 `core/ui` 已有的 `SettingsShell`、`ThemeEditor`、theme helper 逻辑，属于样式/组件重叠。
- `UiSelect.vue`、`ConfirmDialog.vue` 是通用 UI 基础件，但留在 Artist member；如果 Writer 或 core/ui 已有等价能力，应合并。
- `CoreWorkbenchView.vue` 对新建会话后“sessions[0] 就是新会话”的假设偏脆弱，属于顺序耦合。

## 重构/优化建议

### P0

- 先确认并删除断入口旧层：`stores/session.ts`、`useSessionEvents.ts`、`api/sse.ts`、未引用的 billing/download/markdown/lightbox/error-boundary。删除前只需核对是否被未来计划或桌面壳动态引用。
- 把 `CoreWorkbenchView.vue` 的会话更新也收敛到 `api/core.ts`，优先使用 `/api/core/sessions/{id}` patch，避免同页混用两套 session 接口。

### P1

- 把 `SettingsView.vue` 改为复用 `core/ui` 的 `SettingsShell` 和 `ThemeEditor`；Artist 只保留具体 section 内容和保存逻辑。
- 删除或生成化 `lamtools-ui.d.ts`。既然 tsconfig 已 include `core/ui/src`，优先让真实导出类型成为唯一事实源。
- 把 `api/core.ts` 改名或内部整理为 workbench adapter，明确哪些是 core-shaped read，哪些是 Artist action write。

### P2

- 评估 `UiSelect`、`ConfirmDialog` 是否下沉 core/ui；只有 Writer/Artist 都需要时再下沉，避免为了抽象而抽象。
- 如果 Artist 分组需要长期保留，再设计后端轻量分组；短期不要为了 localStorage 脏引用新增复杂同步层。
- 清理 core/ui 里的产品名类名/注释，但应归 Core UI 模块报告处理，不建议混在 Artist 前端改造里。

## 不建议现在做

- 不建议重写 Artist 工作台。当前主线已经接入共享工作台，优先删旧层和收敛接口。
- 不建议把 Artist 图片谱系强行下沉 core/ui；它是产品语义，不是共享 shell。
- 不建议新增状态管理抽象。先删除旧 `session store`，再看剩余复杂度。
- 不建议把本地分组立即做成完整项目系统；Artist 后端没有 project 概念，贸然新增会扩大范围。
- 不建议在设置页大改视觉设计；先复用已有 `SettingsShell` / `ThemeEditor`，减少重复代码。

## 需要主线程核对的证据

- `router/index.ts` 只注册 `/` 和 `/settings`，旧 session 页面未暴露。
- `CoreWorkbenchView.vue` 使用 `WorkspaceShell`、`SessionSidebar`、`ChatThread`、`RuntimePanel`，并把发送映射到 `startCoreArtistTurn`。
- `api/core.ts` 读 `/core/sessions`、`/core/messages`、`/core/events`、`/core/providers`、`/core/usage/total`，但发送走 `/sessions/{id}/artist-turn`。
- `session.py` 后端显示 `/messages` 只是消息写入，`/artist-turn` 才启动后台生成并写 `generating/idle/error`。
- `rg` 显示 `useSessionStore`、`useSessionEvents`、`parseSSEStream`、`useBillingStore`、`Lightbox`、`ErrorBoundary` 当前没有主线引用。
- `SettingsView.vue` 自建设置壳和主题编辑；core/ui 已有 `SettingsShell.vue`、`ThemeEditor.vue`、theme helpers。
- `lamtools-ui.d.ts` 手写声明与 `core/ui/src/types.ts` 存在字段差异风险，且 tsconfig 已 include `../../../core/ui/src/**/*.ts` 和 `.vue`。
- `core/ui/src/components/WorkspaceShell.vue` 仍有 `writer-shell` / `writer-main` 类名，建议交给 Core UI 报告统一处理。
