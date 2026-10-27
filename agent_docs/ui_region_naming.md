# 界面区域命名规范

> 2026-10-24 与用户共同确定。本文档只定名字，不改任何代码。
> 旧代码里的旧名字不用专门清理；写新代码、改到相关文件时，按本规范使用新名。

## 七个区域

| 中文名 | 英文名 | 管什么 |
|---|---|---|
| 底板 | Backdrop | 最底层的整个工作台背景，所有卡片都浮在它上面 |
| 左竖栏 | App Rail | 最左边那条常驻的小图标栏（导航入口、账号、更新） |
| 左侧栏 | Left Sidebar | 左竖栏右边那条会话列表栏（可展开/收起/钉住） |
| 主界面 | Main Area | 中间的大卡片：聊天正文、整版界面（设置/搜索/资料库等）都在这里 |
| 右侧栏 | Right Sidebar | 右边滑出的信息面板（运行状态等） |
| 输入栏 | Composer | 主界面底部悬浮的输入框条 |
| 标题栏 | Header | 主界面顶部的标题条（会话标题、整版界面的页名和动作位）。注意：不是系统窗口的标题栏 |

## 分屏（主界面的第二块屏）

| 中文名 | 英文名 | 管什么 |
|---|---|---|
| 分屏 | Split Pane | 主界面内通过左右 / 上下拆分得到的辅助内容屏，可继续拆分并承载多个标签。它属于主界面，不是与左竖栏/右侧栏平级的独立区域 |

分屏打开时主界面（含输入栏）按布局缩放，辅助分屏占据其余区域，可左右 / 上下自由组合；主界面不添加标签栏，辅助分屏支持多个标签。窄窗放不下时临时聚焦当前屏，保留原布局，空间恢复后还原。沟通时说"打开分屏""关掉分屏"即可。

### 分屏承载什么

分屏是通用的第二块屏，按承载的内容区分叫法：

| 承载内容 | 中文叫法 | 说明 |
|---|---|---|
| 子代理对话 | 子代理分屏 | 分屏的第一个租户，现状已实现 |
| 内置浏览器 | 浏览器分屏 | 桌面原生子 WebView |
| 内置文本编辑器 | 编辑器分屏 | 项目内 UTF-8 文本编辑，包含草稿与保存保护 |
| 内置文件树 | 文件树分屏 | 项目内目录与文件浏览 |
| 左竖栏其他入口的界面（资料库、设置等） | 界面分屏 | "多界面分屏"指主聊天进行的同时能在分屏里打开其他入口界面的能力，各屏独立导航 |

### 英文命名

通用名 **Split Pane**。通用布局宿主为 `CoreSplitWorkspace.vue`，单屏标签栏为 `CoreSplitPane.vue`，样式使用 `.split-*` 与 `.workspace-shell--split`。子代理过程内容为 `CoreSubAgentView.vue`；`CoreSubAgentPane.vue` 仅保留旧导入的兼容适配。旧单屏 CSS 名称不再代表通用分屏入口。

另：右侧栏里还有一块"子代理运行清单"小部件（`CoreSubAgentPanel.vue`），那是子代理分屏的入口列表，不是分屏本身。

## 英文命名对照（写代码用）

| 中文名 | 组件名 | CSS 类名 | 区域标识（data-region / region） |
|---|---|---|---|
| 底板 | `WorkspaceShell.vue` 的外壳 | `.workspace-shell` | — |
| 左竖栏 | `AppRail.vue` | `.app-rail` | `rail` |
| 左侧栏 | `LeftSidebarShell.vue` | `.sidebar-left` | `left` |
| 主界面 | `WorkspaceShell.vue` 的 `<main>` | `.workspace-main` | `main` |
| 右侧栏 | `WorkspaceShell.vue` 的 `<aside>` | `.sidebar-right` | `right` |
| 输入栏 | `ComposerBar.vue` | `.composer-*` | `composerSide`（侧边扩展位） |
| 标题栏 | 各界面自带的 header 元素 | `.thread-header` / `.full-area-header` | `titlebar` |
| 分屏 | `CoreSplitWorkspace.vue` / `CoreSplitPane.vue` | `split-*`（状态类 `.workspace-shell--split`） | `split`，属于主界面布局 |

## 使用规则

1. 和用户沟通、写注释、写文档时，一律用中文表中文名（底板 / 左竖栏 / 左侧栏 / 主界面 / 右侧栏 / 输入栏 / 标题栏），不再说"抽屉（Drawer）""会话栏""右侧面板"这些旧叫法。
2. 写新 CSS、新组件时，英文按上表取名；其中 `.sidebar-left` / `.sidebar-right` 是新名，现有代码里的 `.drawer-left` / `.drawer-right` 是旧名，遇到时知道是同一个东西即可。
3. 底板的主题色变量沿用现有代码里的 `--theme-backdrop-background` / `--theme-backdrop-text`（"backdrop"即底板），新变量也按 `--theme-backdrop-*` 这族取名。
4. 右侧栏在界面上的标题文字目前写的是"运行状态"，这属于界面文案，不在本次改名范围内，保持原样。

## 历史背景

旧架构把左右两条侧栏都叫"抽屉"（drawer），但两者行为其实不同：左侧栏可以常驻钉住，更接近固定的侧栏；右侧栏才是真正滑出滑入的。所以这次统一改叫 Sidebar，"Drawer"一词废弃。
