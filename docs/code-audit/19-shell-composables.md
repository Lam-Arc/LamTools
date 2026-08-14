# 19 外壳/会话/组合式 审计报告

审计时间：2026-08-13　审计区：19（应用外壳 / 会话侧栏 / composables / 样式体系）　方式：静态只读审计
严重度定义：S1=严重缺陷/安全隐患；S2=中等（功能失效/数据丢失/契约断裂）；S3=轻微；S4=建议

## 1. 概况

本区覆盖 WorkspaceShell 三卡布局外壳、SessionSidebar 会话侧栏、TitleBar/CoreSessionTitleEditor、文件树（FileTreePanel/FileTreeNode/FbTreeItem）、FolderBrowserDialog、ComposerBar/AutoTextarea/CommandPalette/AttachmentTray/CoreQueuedInputTray，composables 目录全部 18 个文件，composer/ 语法解析 3 个文件，styles 4 个 CSS 文件，以及 helpers/theme.ts、ThemeEditor/ThemeAreaEditor、demo/App.vue 集成层与 member 模板 WorkbenchView。

总体印象：composables 层工程质量高——竞态防护（generation token、activeThreadId 校验、seq 自增）、乐观消息、滚动跟随控制器（易错点清单 A–E）都设计得相当扎实，注释与实现一致。主要问题集中在**样式体系在主干仓库与 sage worktree 之间发生了合并丢失**（移动端抽屉整段 CSS 缺失，直接导致桌面端出现浮动移动导航条、移动端左抽屉不可用），以及两个生命周期/契约类问题（停止宽限定时器无卸载清理、member 模板与当前 shell API 失配）。

问题统计：S1=0，S2=3，S3=15，S4=6，共 24 条。

## 2. 问题清单

### 2.1 样式体系（layout.css 合并丢失）

- **[S2] 移动端抽屉整套 CSS 在主干 layout.css 中丢失：桌面端渲染出无样式的移动导航条，移动端左抽屉宽度为 0 不可用**
  位置：`core/ui/src/styles/layout.css:16-77`（shell 段）、`core/ui/src/components/WorkspaceShell.vue:7-42`（`.mobile-shell-nav` / `.mobile-drawer-backdrop` / `.mobile-shell-button` 标记）
  问题：`git log -p -S"mobile-shell-nav"` 显示 commit `cd12f8f` 删除了 `.mobile-shell-nav, .mobile-drawer-backdrop { display: none; }`，且主干 layout.css 中再无任何这两类选择器的规则（全仓库 grep 仅剩 WorkspaceShell.vue 模板里的类名）；对比 worktree `.worktrees/sage-agent-local/core/ui/src/styles/layout.css:62` 与 `:2296-2345` 可看到完整的桌面隐藏 + ≤640px 抽屉滑入/滑出（translateX ±102%）、fixed 定位移动导航、44px 触控目标等规则在主干全部缺失。同时主干 `layout.css:2424-2425` 在 ≤640px 把 `--left-card-width` 设为 `0px`，而 `.workspace-drawer` 宽度即 `var(--left-card-width)`（`layout.css:110`）——左抽屉在移动端变成 0 宽不可见；worktree 同位置为 `min(86vw, 320px)` + 抽屉 sheet 化。
  影响：桌面端每个产品外壳顶部都会渲染出一个无样式、无定位的"产品名 + 汉堡按钮 + 面板按钮"浮动条，叠在抽屉头/主卡上方；移动端（≤640px）左"会话与导航"抽屉打开后宽度为 0，完全不可用；右抽屉虽为 100vw 但没有滑入动画与遮罩层级（z-index 仍是 background-info 层）。`tests/workspace-shell.test.ts:90-98` 只断言 scoped style 不含 `display:none`、把责任推给"shared responsive stylesheet"，而该样式表已丢失规则，测试形成虚假信心。
  影响级别：S2（功能失效 + 可见视觉回归）
  修复建议：把 worktree 版本的 `.mobile-shell-nav`/`.mobile-drawer-backdrop`/≤640px 抽屉规则完整合并回主干 layout.css（含桌面 `display:none`、`--left-card-width: min(86vw, 320px)`、抽屉 translateX 滑入、遮罩与层级）；并在 workspace-shell.test.ts 中补充对 layout.css 源码的断言（如移动端左抽屉宽度非 0）。

- **[S3] `.drawer-left:not(.open) { pointer-events: auto; }` 与右抽屉相反，且无视觉隐藏手段，仅靠模板的 inert 兜底**
  位置：`core/ui/src/styles/layout.css:132`（对比 `:143` `.drawer-right:not(.open) { opacity: 0; pointer-events: none; }`）
  问题：左抽屉关闭态没有 opacity/transform 隐藏规则（`.drawer-left` 恒为 `transform:none; opacity:1`，`layout.css:123-131`），关闭后只靠 WorkspaceShell 模板的 `:inert`（`WorkspaceShell.vue:75`）屏蔽交互；而 CSS 却显式声明关闭态 `pointer-events: auto`。
  影响：一旦有消费方不按 WorkspaceShell 模板使用（如仅用 useShellLayout 自建外壳，或注释掉 inert），关闭的左抽屉会持续拦截左侧 244px 的点击；两条规则语义自相矛盾，误导后续维护。
  修复建议：删除该行，或为关闭态补 `opacity: 0; pointer-events: none;` 与右侧一致（并保留 inert 作为双保险）。

- **[S4] base.css 全局移除所有输入框的 focus-visible 轮廓**
  位置：`core/ui/src/styles/base.css:45-46`
  问题：`input:focus-visible, select:focus-visible, textarea:focus-visible { outline: none; }` 注释称"输入框不做聚焦态：光标闪动即聚焦指示"，但对纯键盘用户（以及 readonly/disabled 之外的选择框）会丢失全部可见聚焦指示，与 `button:focus-visible`（`base.css:47-52`）保留轮廓的决策不一致。
  影响：键盘可达性退化；无障碍审计项。
  修复建议：至少为 `select` 保留 outline，或为输入框提供等价的 border 聚焦态。

### 2.2 composables 生命周期

- **[S2] useCoreLiveComposerController 停止宽限定时器（stopGraceTimer）无作用域清理，卸载后可能对错误线程执行强制重置**
  位置：`core/ui/src/composables/useCoreLiveComposerController.ts:72`（声明）、`:230-234`（`stop()` 中 `setTimeout(..., 3000)` 升级 force reset）
  问题：`clearStopGraceTimer()` 仅在 `stop()`、status watcher（`:109-114`）和 `resetForThreadChange()`（`:146-155`）中调用；整个文件没有任何 `onScopeDispose`/`onUnmounted`。若组件在使用该 composable 期间点击"停止"后立即卸载（产品把 Workbench 做成可销毁视图时），3 秒后定时器仍会触发 `escalateForceReset()`（`:238-247`），而 `activeThreadId` 此时可能已指向另一会话或为空——强制重置会发往错误的线程，或对空线程报错；同时 `setStatusText` 等回调作用于已卸载状态。这是全区唯一一处"定时器未随作用域清理"的生命周期缺口。
  影响：错误线程被 force reset（功能影响），以及悬空回调/潜在泄漏。
  修复建议：在 composable 内加 `onScopeDispose(() => { clearStopGraceTimer(); stopPending = false })`（或由调用方在卸载前调用 `resetForThreadChange()`，但建议前者，防御所有消费方）。

- **[S3] useShellLayout 全局快捷键（Ctrl+Tab / Ctrl+E / Escape）无输入焦点豁免**
  位置：`core/ui/src/composables/useShellLayout.ts:186-213`
  问题：document 级 `keydown` 直接处理 `Ctrl+Tab`（preventDefault + 切换左抽屉）、`Ctrl+E`（切换右抽屉）、`Escape`（关闭抽屉）。无 `event.repeat` 判断、无对 `input/textarea/contenteditable` 焦点或 `isComposing` 的豁免，也不检查当前是否有模态框打开。
  影响：用户在输入框/命令面板中按 Escape（如 CoreSessionTitleEditor 的取消、命令面板关闭）会同时把抽屉关掉；Ctrl+Tab/Ctrl+E 在 Tauri 桌面与浏览器 devtools 等场景可能与宿主快捷键冲突；模态打开时 Escape 也会连带关抽屉。
  修复建议：按目标元素过滤（`closest('input, textarea, [contenteditable]')` 时跳过，Escape 例外可保留但需模态优先），并加 `event.repeat` 守卫。

- **[S3] useShellLayout.onPointerDown 直接操纵全局 DOM 隐藏 .composer-menu，与组件状态脱节**
  位置：`core/ui/src/composables/useShellLayout.ts:157-183`
  问题：点击任意处时用 `document.querySelectorAll('.composer-menu')` 把菜单 `style.display = 'none'`，绕过菜单自身的 open 状态（按钮上的 `.open` class 不会同步），且依赖全局类名 `.composer-menu`/`.composer-pill` 与 CSS 结构耦合；多个 shell 实例并存时会互相影响。
  影响：菜单按钮的视觉"打开"态与真实显示不一致；composable 越权接触 DOM，可测试性差。
  修复建议：改由菜单组件自管理关闭（如共享一个 `closeMenus()` 事件总线/注入），或至少由宿主传入查询选择器。

- **[S3] useShellLayout 主题变量写入 :root 后卸载不清理，且 matchMedia 未兼容旧式 addListener**
  位置：`core/ui/src/composables/useShellLayout.ts:72-83`（:root 写入）、`:234-238`（`narrowMediaQuery.addEventListener`）
  问题：`:root` 上的 `--theme-*` 变量在 onUnmounted 时不会恢复（TitleBar 的 `--titlebar-offset` 有对应 removeProperty，主题变量没有）；旧 Safari/WebView 只支持 `addListener/removeListener`，不支持 `addEventListener('change')`，会静默失效。
  影响：多实例/热切换产品时 :root 残留上一主题变量；旧 WebView 移动端窄屏判定失效。
  修复建议：onUnmounted 时把 `shellStyle` 中写过的 key 从 `document.documentElement` 移除（或记录原值）；`matchMedia` 分支兼容 `addListener`。

- **[S3] useCoreConfigState / useCoreProjectSessionState 共享 loading 标志，并发请求互相清态**
  位置：`core/ui/src/composables/useCoreConfigState.ts:22-29`、`useCoreProjectSessionState.ts:40-43, 67-70`
  问题：`fetchProviders` 与 `fetchModels`（以及 fetchProjects/fetchSessions）共用一个 `loading` ref，先完成的请求会在另一个还在飞行时把 `loading` 置 false；且无 generation 防护，后返回的旧响应可能覆盖新数据。
  影响：设置页快速切换 tab 时出现"加载中"指示提前消失或数据回跳。
  修复建议：拆分 loading 或计数（pending 计数），并加请求代次校验。

- **[S3] useCoreUiPreferences.save 未包裹 try/catch，localStorage 抛错产生未处理 rejection**
  位置：`core/ui/src/composables/useCoreUiPreferences.ts:38-42`
  问题：`save()` 中 `localStorage.setItem` 无 try/catch（同文件 `load()` 有），且所有入口都是 `void save()`（`:47-65`）——在隐私模式/配额满/禁用存储的桌面环境下抛出即成为未处理 Promise rejection；与 `useShellLayout.saveSettings`（`useShellLayout.ts:265-276`，同样无 try/catch）一致。
  影响：硬化环境（本仓库多处注释都在防御这类场景）下控制台报错、主题设置静默失败。
  修复建议：与 `readStoredXxx` 一样包裹 try/catch 并忽略。

- **[S3] useShellLayout 与 useCoreUiPreferences 共用同一 localStorage key 且写入不同 schema，互相覆盖**
  位置：`core/ui/src/demo/App.vue:713`（`settingsStorageKey = 'lamtools.core.ui'`）、`:74`（传给 WorkspaceShell storage-key）、`:861`（传给 useCoreUiPreferences）；写入 schema：`useShellLayout.ts:265-276`（含 stageOpen/stageHeight）vs `useCoreUiPreferences.ts:38-46`（不含）
  问题：demo 把同一个 key 同时给两个 composable 用：shell 保存 `{density, contentWidth, theme, stageOpen, stageHeight}`，uiPreferences 保存 `{density, contentWidth, theme}`。任何一方 save 都会覆盖另一方字段，导致 stageOpen/stageHeight 持久化被静默丢弃（重开后 stage 恢复默认 300px/关闭）。
  影响：stage 高度/开合状态持久化不可靠；两套主题来源（shellTheme vs uiPreferences.theme）存在漂移风险。
  修复建议：统一为一个持久化模型（建议 useShellLayout 作为唯一写者，uiPreferences 读同一 key），或拆分 key。

- **[S4] useCoreGoals 节流窗口在空 threadId 下也被占用**
  位置：`core/ui/src/composables/useCoreGoals.ts:19-29`
  问题：`throttledUntil = now + GOAL_REFRESH_THROTTLE_MS` 在 `if (!tid) return` 之前执行；会话未选中时频繁调用会白白消耗 2s 节流窗口。
  影响：切换到会话后的首次刷新可能被节流跳过（延迟最多 2s，`force=true` 可绕过）。
  修复建议：把 `if (!tid) return` 提到设置节流之前。

### 2.3 文件树与目录浏览

- **[S3] 文件树懒加载存在竞态且错误全静默：快速切项目/目录时旧响应覆盖新数据**
  位置：`core/ui/src/components/FileTreePanel.vue:47-58`（loadRoot）、`:70-72`（watch projectId）；`FileTreeNode.vue:94-104`（loadChildren）；`FbTreeItem.vue:112-124`
  问题：三个加载点都没有请求代次/取消（fetch 无 AbortController）：FileTreePanel 切换 projectId 后，先前请求晚返回会覆盖新项目的根目录；FileTreeNode/FbTreeItem 展开目录时 catch 一律 `children.value = []`，无错误提示无重试；点击折叠再展开的加载中状态没有 in-flight 去重（loading 期间再点会再次发起）。
  影响：切换项目后文件树显示错乱（数据错配）；网络错误时用户看到空目录却不知道原因。
  修复建议：为每次加载生成代次号，响应返回时校验代次才写入；FileTreePanel/FileTreeNode 复用 AbortController 或在卸载/换 key 时作废；错误状态显示错误信息并提供重试。

- **[S3] FolderBrowserDialog 无焦点管理：无自动聚焦、无焦点圈禁、Escape 监听落点不可聚焦**
  位置：`core/ui/src/components/FolderBrowserDialog.vue:6`（`@keydown.escape="cancel"` 挂在 backdrop div 上）、`:82-107`（无 focus 逻辑）、`:186-195`
  问题：Escape 处理器挂在不可聚焦的 backdrop 上——除非焦点恰好在其子树内，否则按键不生效（`role="dialog"` 无 `autofocus` 目标、无 Tab 循环、关闭后焦点不归还触发按钮）。对比 CoreProjectCreate 有 `workRootInput` 聚焦，本对话框没有。
  影响：键盘用户无法用 Escape 关闭、Tab 会逃出对话框、关闭后焦点丢失（a11y 与可用性）。
  修复建议：打开时把焦点移到对话框标题或首控件，实现焦点圈禁（Tab 循环）与关闭归还；Escape 监听移到 `role="dialog"` 元素或 document 捕获阶段。

- **[S3] FolderBrowserDialog / CoreProjectCreate 的 `Teleport defer to=".workspace-shell"` 与外壳强耦合**
  位置：`core/ui/src/components/FolderBrowserDialog.vue:2`、`CoreProjectCreate.vue:1-2`；demo `App.vue:101`
  问题：两个组件把内容 teleport 到 CSS 选择器 `.workspace-shell`；一旦在无 WorkspaceShell 的宿主（如设置页、member 产品未挂 shell）中使用，目标不存在，内容永不渲染且 Vue 告警。
  影响：组件复用面被静默收窄；脚手架产品容易踩坑。
  修复建议：提供 `teleport-target` prop（默认回退 `document.body`），或改用 `useId` 定位的显式挂载点。

### 2.4 Composer / 输入

- **[S3] ComposerBar 与 WorkspaceShell 的默认 textarea 按 Enter 直接提交，无 IME（isComposing）守卫**
  位置：`core/ui/src/components/ComposerBar.vue:25`（`@keydown.enter.exact.prevent="$emit('submit')"`）、`components/WorkspaceShell.vue:157`
  问题：核心产品 demo 用自绘 textarea + `useCoreLiveComposerController.handleKeydown`（`demo/App.vue:346`，有 `!event.isComposing` 守卫），但 ComposerBar/WorkspaceShell 自带的兜底 textarea 直接 emit submit——中文/日文输入法选词回车（composition confirm）会误发消息。
  影响：member 产品若直接用默认 textarea（member 模板 WorkbenchView 正是如此），IME 用户每选一次词就误发一条消息。
  修复建议：默认 textarea 增加 `@keydown.enter` 处理器并检查 `event.isComposing && !event.repeat` 后再提交。

- **[S3] useCoreQueuedInputController.save 无提交中防重：Enter + blur 可并发触发两次更新**
  位置：`core/ui/src/composables/useCoreQueuedInputController.ts:47-66`；`components/CoreQueuedInputTray.vue:48-50`（blur 与 Enter 都 emit save）
  问题：编辑态按 Enter 会先触发 `emit('save')` 再触发 input 的 blur（`@blur="emit('save', item)"`），`save()` 里 `editingId` 要到 `finally` 才清空，两次调用都能通过 `editingId.value !== item.id` 与 `submittingItemIds` 检查（save 不占 submitting 集合），从而并发执行两次 `updateQueueInput`。对比 `guide()` 有 submitting 集合防重（`:81-107`）。
  影响：同一编辑内容重复写队列（后端幂等性依赖其实现），竞态下可能以旧值覆盖新值。
  修复建议：save 进入时也把 item.id 加入 submittingItemIds（或引入 saveGeneration），复用 guide 的防重模式。

- **[S3] useCoreWorkbenchController.sendMessage 失败后乐观消息不回滚，且无错误提示**
  位置：`core/ui/src/composables/useCoreWorkbenchController.ts:97-151`
  问题：先追加乐观 user/assistant 消息（`:106-124`），`startTurn`/`createMessage` 抛错时仅 `console.error`（`:144-150`），乐观占位（空 assistant 内容）永远留在列表里，也没有 `loadError`/`lastError` 回传。
  影响：发送失败时用户看到"已发送但没响应"的幽灵消息，只能刷新；与 demo 层（composerErrorText 由 live 控制器负责）行为不一致。
  修复建议：catch 中按 `optimisticId` 过滤掉乐观消息（或回滚到发送前快照），并通过返回值/回调上报错误。

- **[S4] CommandPalette 键盘导航不把选中项滚入视口**
  位置：`core/ui/src/components/CommandPalette.vue:63-67`（`.command-list` max-height 320px + overflow-y auto）
  问题：`activeIndex` 变化（↑↓）没有 `scrollIntoView` 联动，12 条命令超出可视区后，箭头移动会把选中项移到视口外。
  影响：命令多时键盘选择"看不见选中项"。
  修复建议：在 activeIndex 变化时对 `.command-item.active` 做 `scrollIntoView({ block: 'nearest' })`。

- **[S4] AutoTextarea 的 minH 在 setup 时静态计算，props.minRows 变化不更新**
  位置：`core/ui/src/components/AutoTextarea.vue:32`
  问题：`const minH = \`calc(${props.minRows} * 1.55em + ...)\`` 只在初始化时求值一次，后续 minRows/maxRows 变化不会反映到样式（maxH 在 autoGrow 内实时读取，min 高度不会）。
  影响：动态切换 minRows 的宿主（本仓库未见使用方，风险低）。
  修复建议：改为 computed 并 watch 后重新 autoGrow。

### 2.5 会话侧栏与外壳集成

- **[S2] member 模板 WorkbenchView 与当前外壳 API 全面失配：槽名与 SessionSidebar props 全部对不上**
  位置：`core/templates/member/frontend/src/views/WorkbenchView.vue:9-24`
  问题：模板使用 `<template #sidebar>`、`<template #chat>` 两个槽，而 WorkspaceShell（`core/ui/src/components/WorkspaceShell.vue:81-158`）只提供 `sidebar-body`/`sidebar-header-action`/`main-content`/`thread-content` 等槽，**没有 `#sidebar`/`#chat`**——未知命名槽内容被静默丢弃；同时 `SessionSidebar` 用法（`:sessions`/`:groups`/`:active-id`/`@select`，`:10-15`）与当前组件 API（`projectGroups`/`activeSessionId`/`select-session`，`SessionSidebar.vue:197-240`）完全不符，TS 类型检查必然报错。
  影响：用该模板脚手架出的 member 产品渲染出空外壳（聊天区直接消失），且编译期报错；说明模板已随外壳 2.0 重构过时。
  修复建议：按当前 WorkspaceShell 槽契约与 SessionSidebar props/emits 重写模板（`#sidebar-body` + `#thread-content` + `project-groups` + `@select-session`），并加一个"模板与组件契约"的对比测试（slot-contract 测试已有先例）。

- **[S3] SessionSidebar visibleSessions 每次渲染全量排序；折叠/展开状态与持久化键语义混杂**
  位置：`core/ui/src/components/SessionSidebar.vue:393-402`（visibleSessions 每渲染全量 sort）、`:245-248`（groupExpanded 不持久化）
  问题：`visibleSessions` 是模板直接调用的函数（非 computed），渲染时对整组会话做稳定排序 + pin 判定；项目会话量大（数百条）时每次渲染 O(n log n)。另外"展开全部"（groupExpanded）不持久化，刷新即失效，与 groupCollapsed（持久化）语义不对称。
  影响：大项目侧栏渲染性能；"展开全部"状态刷新丢失（轻微）。
  修复建议：把排序结果提升为 computed（依赖 projectGroups/pins），或在组件内缓存；groupExpanded 也写入 `${pinStorageKey}.collapsed` 同一存储。

- **[S4] WorkspaceShell 双 watcher 同步 stageOpen 无环风险但依赖父组件配合；leftPinned/rightPinned 状态不持久化**
  位置：`core/ui/src/components/WorkspaceShell.vue:325-341`（stageOpen/theme/density/contentWidth 三组同步 watcher）
  问题：每个 prop 都有双向同步 watcher（prop→state、state→emit），虽都有相等守卫不会死循环，但三组 watcher 重复同一模式、模板与 useShellLayout 状态各持一份；另外 useShellLayout 的持久化不含 left/right pin（`useShellLayout.ts:265-276`），重启后抽屉回到默认开/关，桌面用户固定偏好丢失。
  影响：低——重启后 pin 偏好不保留；三处同步 watcher 增加心智负担。
  修复建议：pin 状态纳入 loadSettings/saveSettings（注意与 2.2 的 key 冲突问题一并解决）。

### 2.6 主题编辑器

- **[S3] ThemeAreaEditor 用 v-model 直接改写 props 嵌套对象，绕过 emits 契约**
  位置：`core/ui/src/components/ThemeAreaEditor.vue:11-19`（`v-model="stop.color"` / `v-model.number="stop.position"` 绑定的是 props.stops 数组元素）、`:31-32`（angleModel computed 的 set 走 emit，另一条路径）
  问题：`stops` 是父组件传入的 prop 数组，元素级 `v-model` 直接原地修改父组件 reactive 状态；颜色/位置改变只靠 `@change="$emit('sort-stops')"` 触发保存，中间态（输入过程中）不保存且父组件无感知。同一文件里 angle/opacity/textColor 走 computed setter→emit，两条更新路径并存，语义不一致。
  影响：主题编辑过程中父组件（useCoreUiPreferences）的 save 时机依赖 change 事件，若某字段只改不退（颜色 input 一直处于 focus）则变更不持久化；直接改 prop 违反单向数据流，vue 严格模式会告警。
  修复建议：统一走 `update:stops` emit（用本地 draft computed + `@input`/`@change` emit 新数组），去掉对 props 的原地修改。

- **[S4] useTheme 与 useCoreUiPreferences 主题逻辑双实现**
  位置：`core/ui/src/composables/useTheme.ts`（全套 loadTheme/saveTheme/applyPreset/渐变编辑）vs `core/ui/src/composables/useCoreUiPreferences.ts:44-72`（同样一套）
  问题：两份几乎相同的主题编辑/持久化实现并存；demo 实际只用 useCoreUiPreferences（`demo/App.vue:861`），useTheme 只在测试/旧调用方中存在（`grep` 显示 demo 未 import），存在过期代码。
  影响：维护成本与行为漂移风险。
  修复建议：确认 useTheme 消费方后删除或改为 useCoreUiPreferences 的薄封装。

## 3. 该区 Top 3 问题

1. **移动端抽屉 CSS 整套丢失（S2）**：主干 layout.css 与 worktree 相比少了 `.mobile-shell-nav`/`.mobile-drawer-backdrop` 的全部规则与 ≤640px 抽屉滑入动画，导致桌面端每个外壳顶部悬浮一个无样式移动导航条、移动端左抽屉宽度 0 不可用，且现有测试只查 scoped style 无法拦截。`core/ui/src/styles/layout.css:16-77, 2424-2425`。
2. **停止宽限定时器无作用域清理（S2）**：useCoreLiveComposerController 的 3 秒 force-reset 升级定时器在卸载后仍会触发，可能对错误线程强制重置。`core/ui/src/composables/useCoreLiveComposerController.ts:230-234`。
3. **member 模板与外壳契约全面失配（S2）**：模板 WorkbenchView 的 `#sidebar`/`#chat` 槽与 SessionSidebar 旧 props 均不存在于当前组件，脚手架产品直接渲染空壳。`core/templates/member/frontend/src/views/WorkbenchView.vue:9-24`。

## 4. 亮点

- **滚动跟随控制器（useCoreAutoFollowScroll）**：20 条易错点清单全部落实——token 竞态防护、单写 scrollTop + 帧后二次校正、程序化滚动防误伤标志、reduceMotion 尊重，是全区文档最完整的控制器。
- **useCoreLiveComposerController 提交防护**：`submitting` 防重入、IME 组合期 Enter 忽略、keydown/keyup 双通道 + 时间戳去重、stop 后 3s 升级 force reset 的注释解释了真实场景的卡死状态，设计意图清晰。
- **会话切换竞态防护**：useCoreWorkbenchController.selectSession、useCoreGoals.refreshGoal、useCoreWorkbenchProjectionController 全部用 activeThreadId/代次校验防止旧响应覆盖新会话，一致性很好。
- **useShellLayout 生命周期清理完整**（监听器/定时器/媒体查询都在 onUnmounted 释放），是全区 composable 清理的样板；TitleBar 的 `--titlebar-offset` 设置/移除对称。
- **样式 token 收敛**：variables.css 提供统一半径/间距/阴影/alpha 标尺，组件普遍用 color-mix + `--theme-*` 派生，暗/亮主题在 themeToCSSVars 里按相对亮度自动切换派生色，思路清晰。

## 5. 审计范围与方法

- 组件（12）：WorkspaceShell.vue、SessionSidebar.vue、TitleBar.vue、CoreSessionTitleEditor.vue、FileTreePanel.vue、FileTreeNode.vue、FbTreeItem.vue、AttachmentTray.vue、ComposerBar.vue、AutoTextarea.vue、CommandPalette.vue、FolderBrowserDialog.vue、CoreQueuedInputTray.vue，另核 ThemeEditor.vue / ThemeAreaEditor.vue / CoreProjectCreate.vue（Teleport 关联）。
- composables（18 个文件全读）：useShellLayout、useTheme、useCoreLiveTurnController、useCoreWorkbenchController、useCoreApprovalController、useCoreConfigState、useCoreExecutionControlsState、useCoreGoals、useCoreQueuedInputController、useCoreUiPreferences、useCoreUpdateState、useCoreLiveComposerController、useComposerCommandPalette、useCoreAutoFollowScroll、useCoreProjectSessionState、useCoreWorkbenchProjectionController、usePendingAttachments、index.ts。
- composer/：syntax.ts、inputItems.ts、execution.ts；helpers/theme.ts、data/theme-presets 关联。
- styles 4 个：variables.css、base.css、layout.css（3058 行分段全读）、theme-editor.css。
- 集成层：demo/App.vue（关键段落）、core/ui/src/index.ts（导出契约）、core/templates/member/frontend/src/views/WorkbenchView.vue、tests/workspace-shell.test.ts、tests/session-sidebar.test.ts 抽样。
- 方法：只读静态审计；git log/-S 溯源 layout.css 移动端规则丢失；与 `.worktrees/sage-agent-local` 的 layout.css 逐段对比确认合并丢失；grep 验证定时器/监听器/onScopeDispose 覆盖情况。
