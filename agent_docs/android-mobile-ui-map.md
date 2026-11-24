# Android 移动端 UI 功能清单（快速定位）

> user:“随时记功能清单方便后续快速定位修改”  
> 本表只记「哪个能力在哪个文件、由谁触发」，改之前先看这里，避免重复实现。

## 层级与归属（不可破坏）

`运行环境 → 项目 → 会话 → 消息/任务`。项目必须属于一个环境，会话必须属于一个项目；切环境不迁移数据。

| 规则 | 落点 |
|---|---|
| L1 只列当前项目的会话 | `LamToolsApp.vue`：`:groups="currentProjectGroup ? [currentProjectGroup] : []"` |
| 环境/项目上下文一行 | `MobileChatList.vue` 的 `[data-mobile-chat-context]` → `MobileContextPicker.vue` |
| 新建会话必须有项目 | `createMobileSession`：没有项目时先开新建项目 |
| 返回逐层退 | `handleSystemBack`：重命名弹窗 → L3 会话信息 → 环境/项目面板 → L1 → 分屏 → 整版页 → 宿主 |

## 一级导航与外壳

| 能力 | 实现 | 说明 |
|---|---|---|
| 底部四入口（对话/工作区/任务/设置） | `core/ui/src/components/MobileBottomNav.vue`；`LamToolsApp.vue` 的 `onMobileNavSelect` | 常驻；重复点同一入口不退出（底栏不是开关）；插件与远程收进设置 |
| 手机端抽屉退役 | `LamToolsApp.vue`：`:collapse-left-sidebar="platform==='mobile' ? true : ..."`、`:show-drawer-toggle="... && platform!=='mobile'"`；`WorkspaceShell.vue`：`<LeftSidebarShell v-if="props.platform !== 'mobile'">` | 手机不再生成抽屉 DOM；桌面端侧栏完全不变 |
| 底部导航高度与让位 | `core/ui/src/styles/workspace-shell.css`（`--mobile-bottom-nav-height` / `--composer-bottom-offset`）、`styles/layout.css`（移动端主区 padding） | 输入栏与内容都不压在导航条下 |
| 手机 L1/L2/L3 状态 | `LamToolsApp.vue`：`mobileChatSurface`、`mobileChatListOpen`、`mobileSessionSettingsOpen` | 默认 L1；进会话 L2；`··· → 会话信息` 进 L3 |

## L1 会话列表

| 能力 | 实现 | 说明 |
|---|---|---|
| 列表与卡片 | `core/ui/src/components/MobileChatList.vue` | 置顶段 + 全部会话；头像/名称/状态/时间/运行中圆点 |
| 顶部环境/项目上下文 | 同上：`[data-mobile-chat-context]` → `@pick-context` | 显示 `本机 Android / 项目名 ▾` |
| 搜索 | 同上：`[data-mobile-chat-search]` | 本地按标题过滤（消息正文搜索待后端） |
| 新建会话 | 同上：`[data-mobile-chat-new]` → `createMobileSession` | 当前项目下建会话；建成功直接进 L2，失败留在列表；无项目时先建项目 |
| 长按会话菜单（450ms） | 同上：`@session-menu` → `openMobileSessionMenu` | 重命名 / 置顶（取消置顶）/ 导出 Markdown / 删除（二次确认） |
| 置顶列表来源 | `LamToolsApp.vue`：`pinnedSessionIds` + `:pinned-session-ids` | 与桌面共用 `lamtools-core.sidebar.pinned-projects.sessions`；列表只展示，不自己写存储 |

## 环境与项目

| 能力 | 实现 | 说明 |
|---|---|---|
| 选择面板（先环境、再项目） | `core/ui/src/components/MobileContextPicker.vue`；`LamToolsApp.vue` 的 `mobileContextOpen` | 本机 Android 为当前环境；远程设备接入后在同一面板列出 |
| 切换项目 | `selectMobileProject` → `selectRegisteredProject` | 切换后 L1 列表随项目变化 |
| 新建项目 | `openMobileProjectCreate` → `openProjectCreate` | 项目必须归属环境（当前只有本机） |
| 项目管理（长按 450ms） | `MobileContextPicker.vue` 的 `@project-menu` → `openMobileProjectMenu` | 项目设置 / 重命名项目 / 删除项目；沿用 `openProjectActions`、`openProjectRename`、`deleteProject` |

## L2 聊天

| 能力 | 实现 | 说明 |
|---|---|---|
| 顶部栏（返回/标题/设备/···） | `core/ui/src/components/MobileChatHeader.vue`；`LamToolsApp.vue` 的 `mobileChatHeaderOpen` | 只在会话详情出现；标题居中，次级行 `项目 · 设备`；`data-mobile-chat-*` 供测试定位 |
| 设备状态 | `LamToolsApp.vue`：`mobileDeviceLabel` / `mobileDeviceState` | 本机 Android / 电脑 · 已连接 / 电脑离线；复用 `remoteLinkDown` |
| 顶栏让位 | `styles/layout.css`：`.workspace-shell--mobile-chat-detail` 下的 `.workspace-main` 与 `.thread` | 顶栏自己处理 `--native-safe-area-top`；消息区独立滚动，首条消息不再被渐隐遮罩吃掉 |
| `···` 菜单 | `openMobileChatMenu` | 会话信息 / 导出（Markdown）/ 删除；搜索聊天记录、任务记录、文件与资源等后端聚合能力未接，不摆空按钮 |
| 返回列表 | 顶栏返回键 → `backToMobileChatList`；系统返回同样先回 L1 | 线程保持挂载，滚动与草稿不丢 |
| 线程与输入栏 | `LamToolsApp.vue` 主内容区 + `ComposerBar.vue` | 列表打开时隐藏输入栏 |

## L3 会话信息（会话设置）

| 能力 | 实现 | 说明 |
|---|---|---|
| 页面本体 | `core/ui/src/components/MobileSessionSettings.vue`；`LamToolsApp.vue` 的 `mobileSessionSettingsOpen` | 全屏页，盖住底栏；`data-mobile-session-*` 供测试定位 |
| 基础信息 | 同上 | 会话名称、项目、执行设备、创建时间 |
| 重命名 | 名称行 → `openMobileRename` → `CoreConfirmDialog`（输入形态） | 两种入口共用：L3 名称行、L1 长按菜单 |
| 置顶开关 | 同上 `[data-mobile-session-pin]` → `toggleMobileSessionPin` | `role="switch"`，写入同一份置顶存储 |
| 导出 / 删除 | 同上 → `exportMobileActiveSession` / `deleteMobileSession` | 删除前二次确认；删除当前会话后回 L1 |

## 设置

| 能力 | 实现 | 说明 |
|---|---|---|
| 插件/技能/钩子入口 | `core/ui/src/components/CoreSettings.vue` 的 `plugins` 分区；`useCorePageBindings.ts` 的 `onOpenPlugins` | 仅手机宿主传 `onOpenPlugins`（桌面清单不变）；返回落在设置 |
| 远程连接 | 设置分区 `account` → `RemoteConnectionPanel` | 手机端已有 |
| 主体设置 | `CoreSettings.vue`（`hideNav = platform !== 'mobile'`） | 手机上不显示内置左导航 |

## 数据与缺口（后端/宿主）

| 项 | 现状 |
|---|---|
| 环境实体 | 前端暂无；远程只有 p2p 连接状态，没有按环境隔离的项目/会话命名空间 |
| 默认项目 | Core 未提供「每个环境一个默认项目」，无项目时走新建项目 |
| 会话摘要/未读/待审批数 | 后端缺口，L1 用状态文案占位 |
| 按消息正文搜索 | 后端缺口 |
| 静音 / 归档 | 服务端无会话状态字段，长按菜单与 L3 暂不提供 |
| 任务记录 / 文件与资源（会话内） | 后端无会话→任务/资源聚合接口，L2 `···` 暂不提供 |
| x86_64 安装包 | 本地缺 x86_64 运行时资产，需 WSL 重建或用 arm64 真机验证 |

## 测试锚点

- `core/ui/tests/mobile-chat-list.test.ts`：上下文、打开、置顶分段、长按不误触。
- `core/ui/tests/mobile-chat-header.test.ts`：L2 顶栏与 L3 页面的展示与事件。
- `core/ui/tests/mobile-context-picker.test.ts`：项目轻点切换、长按弹管理菜单。
- `core/ui/tests/full-area-views.test.ts`：整版界面与设置分区清单（含手机插件分区约束）。
