# UI 组件目录与治理

本目录记录实际可复用的基础控件。设计规范以 `.agents/skills/lam-design-spec/SKILL.md` 为准，主题变量以 `core/ui/src/styles/variables.css` 和 `core/ui/src/helpers/theme.ts` 为准；设置类页面统一使用 `core/ui/src/helpers/settingsTheme.ts` 生成区域变量；不要另建一套主题或控件配方。

## 组件展厅

在 `core/ui` 运行 `npm run dev`，访问终端输出地址下的 `/design-system.html`。展厅直接加载生产组件，也可运行 `npm run build:design-system` 生成独立展厅。展厅可搜索、按分类筛选、切换浅暗主题、操作组件、调整滑条范围、下拉菜单参数与输入框行数并查看真实源码。开关展示标准与小尺寸；禁用状态适用于支持该属性的控件。下表列出可操作的组件或样式（大型组合组件默认按需加载，搜索时直接展示，也可点击加载预览；源码按需加载）；“源码目录”可按文件名、源码线索或静态引用方搜索，并按线索和预览状态筛选，已有预览可跳转。主组件和组合预览中的组件均可按名称或项目相对路径搜索；展项及源码目录可复制路径，复制失败时可手动选择。静态引用可能只是导出，也可能遗漏动态入口，索引不代表组件一定可达或适合复用。

| 组件 | 适用场景 | 主要接口 | 源码 |
| --- | --- | --- | --- |
| MaterialsView | 资料浏览、标签和筛选 | `projectId`、`requestRpc`、`transport`、`uploadFiles`，可通过 `copyPath` 接管路径复制；标签补全与评分支持键盘；卡片内操作不会打开文件；展厅中的上传、打开、复制、收藏、归档和移除均为本地模拟 | `core/ui/src/components/MaterialsView.vue`；样式 `core/ui/src/styles/library-styles.css` |
| CoreProjectSettings | 项目名称、外观与项目规则 | `project`、`theme`、`requestRpc`、保存与更新事件；展厅仅修改内存示例，可测试草稿切换保护 | `core/ui/src/components/CoreProjectSettings.vue` |
| SearchShell | 全局搜索、分类与结果操作 | `requestRpc`、`sessions`、`onJump`、可选 `autoFocus` 与打开回调；输入变化时丢弃旧结果；展厅只操作本地示例 | `core/ui/src/components/SearchShell.vue` |
| SpeedChart | 随附网络工具的实时网速趋势和等待采样 | `history`、`traffic`、`compact`；展厅使用本地示例，不访问网络服务 | `core/src/lamtools_core/plugins/bundled/network-exploration/ui/src/SpeedChart.vue`；样式 `ui/src/style.css` |
| CoreSettings | Sunday 设置页面；展厅展示上下文与权限设置 | `section`、`theme`、`requestRpc` 等；展厅仅保存本地示例 | `core/ui/src/components/CoreSettings.vue`；信任列表 `core/ui/src/components/OperationTrustSettings.vue` |
| PluginRegionBlocks | 插件区域状态、进度、参数表单与授权操作 | `regions`、`requestRpc`、`fill`；支持字段必填声明，失败保留参数，卸载时关闭待处理确认；展厅只模拟授权和执行 | `core/ui/src/components/PluginRegionBlocks.vue`；授权流程 `core/ui/src/plugins/consent.ts` |
| PluginConfigPanel | 插件配置字段、枚举及保存反馈 | `pluginName`、`version`、`description`、`requestRpc`；展厅只读写本地示例，不加载自定义插件面板 | `core/ui/src/components/PluginConfigPanel.vue` |
| PluginMarket | 插件市场目录、安装与错误状态 | `requestRpc`、可选 `openRepository`、`changed`；展厅模拟安装和链接，不访问网络或安装插件 | `core/ui/src/components/PluginMarket.vue` |
| MessageView | 用户、助手消息、工具过程、长文本折叠及问题卡 | `msg`、`transport`、`messageActions`、运行与决策状态；展厅只使用本地示例，不接入会话 | `core/ui/src/components/MessageView.vue`；问题卡 `core/ui/src/components/CoreQuestionGroup.vue`（`disabled` 控制只读）；会话样式 `core/ui/src/styles/chat-thread-*.css` |
| WorkflowControlBar | 工作流运行、调试、保存与冲突处理 | `running`、`dirty`、`conflict`、`canUndo`、`canRedo` 和操作事件；展厅仅记录本地操作 | `core/src/lamtools_core/plugins/bundled/workflow/ui/WorkflowControlBar.vue` |
| WorkflowCanvas | 工作流节点、连线及画布元素 | `definition`、`nodeStates`、`locked`、选择和运行事件；锁定时禁止修改；`isolatedClipboard` 供展厅隔离复制粘贴，实际应用默认使用共享剪贴板 | `core/src/lamtools_core/plugins/bundled/workflow/ui/WorkflowCanvas.vue` |
| CoreSplitWorkspace | 工作区分屏布局、标签和分隔线 | `controller`、`workRoot`、`dirty`、内容插槽及几何／可见性事件；展厅使用不持久化的内存控制器 | `core/ui/src/components/CoreSplitWorkspace.vue`；控制器 `core/ui/src/split/useSplitWorkspace.ts` |
| CoreSplitTextEditor | 分屏文本编辑、保存与未保存确认 | `tab`、`root`、`controller`、`documents`、`visible`，通过 `dirty` 汇报修改；展厅使用隔离的内存文档，不写真实文件 | `core/ui/src/components/CoreSplitTextEditor.vue`；文档管理 `core/ui/src/split/documents.ts` |
| CoreSplitPreview | 分屏文件预览 | `tab`、`root`、`transport`、可选 `pane` 和 `controller`；按文件类型显示内容；展厅的 Markdown、文本、图片、错误重试和打开操作均使用本地示例 | `core/ui/src/components/CoreSplitPreview.vue` |
| CoreSplitBrowser | 分屏浏览器地址、导航和状态 | `tab`、`visible`、可选 `services`；默认使用桌面浏览器服务，展厅仅模拟导航和外部打开 | `core/ui/src/components/CoreSplitBrowser.vue` |
| CoreSplitFileTree | 分屏项目文件树 | `root`、可选 `listFiles`、`open`；方向键展开、收起及导航，Home / End 跳转首尾；切换项目时丢弃旧结果，失败可重试原目录；展厅可模拟读取错误 | `core/ui/src/components/CoreSplitFileTree.vue` |
| ContextMenuHost | 共享上下文菜单及子菜单 | 应用根部挂载一次，通过 `openContextMenu` 提供条目与动作；菜单内滚动不会关闭，页面滚动会关闭；展厅动作仅记录本地结果 | `core/ui/src/components/context-menu/ContextMenuHost.vue`；入口 `core/ui/src/components/context-menu/context-menu.ts` |
| WorkflowSwitchGuard | 工作流草稿保存、放弃或取消 | `open`、`choice`；焦点循环、Escape 与焦点恢复；展厅仅操作本地示例 | `core/src/lamtools_core/plugins/bundled/workflow/ui/WorkflowSwitchGuard.vue` |
| WorkflowQueuePanel | 工作流队列、历史、详情与清理确认 | `items`、`history`、`selectedItem` 和操作回调；展厅操作仅影响本地示例 | `core/src/lamtools_core/plugins/bundled/workflow/ui/WorkflowQueuePanel.vue` |
| WorkflowNodeRuntimeDock | 工作流节点运行、等待、完成和失败详情 | `nodeId`、`title`、`kind`、`state`、`detail`、人工任务回调；展厅使用本地示例 | `core/src/lamtools_core/plugins/bundled/workflow/ui/WorkflowNodeRuntimeDock.vue` |
| AttachmentTray | 输入区附件缩略图、文件、上传中、失败及重试 | `attachments`、`transport`、`preview` / `open` / `retry` / `remove`；展厅仅操作本地示例 | `core/ui/src/components/AttachmentTray.vue` |
| InlineFileComposer / ComposerBar | 输入区编辑器与输入栏 | `v-model`、文件建议、禁用状态与输入事件；输入栏通过插槽组合工具和操作；展厅补全与发送仅使用本地示例，引用右键菜单禁用 | `core/ui/src/components/InlineFileComposer.vue`、`core/ui/src/components/ComposerBar.vue` |
| CommandPalette | 输入区命令、文件和上下文建议 | `commands`、`activeIndex`、`select`；每个实例独立滚动，读屏标签区分 `/`、`@` 和 `#`；展厅随真实输入组件预览 | `core/ui/src/components/CommandPalette.vue` |
| CoreQueuedInputTray | 输入区目标及待发送队列 | `items`、`goal`、`editingId`、`draft`、`canGuide` 与编辑、排序、删除、引导事件；展厅只操作内存示例 | `core/ui/src/components/CoreQueuedInputTray.vue` |
| CoreExecutionControls | 输入区模型、思考等级、运行模式与权限 | `modelValue`、`thinkingMode`、`permissionPreset`、各选项与更新事件；禁用时收起已打开菜单；展厅仅修改内存示例 | `core/ui/src/components/CoreExecutionControls.vue`，菜单 `CoreRuntimeMenu.vue`、`CoreModelThinkingMenu.vue` |
| CoreWorkspaceMenu | 输入区工作环境选择 | `activeId`、`options`、`disabled`、`select`；支持方向键和首尾键，禁用或无选项时收起菜单；展厅展示本地示例 | `core/ui/src/components/CoreWorkspaceMenu.vue` |
| CoreSuperAgentPanel | 目标任务列表、权限与详情 | `requestRpc`；展厅为隔离示例，不创建真实任务 | `core/ui/src/components/CoreSuperAgentPanel.vue`；按钮配方 `core/ui/src/styles/full-area-buttons.css` |
| CoreArrangeManager | 定时任务列表、模板与表单 | `requestRpc`；展厅为隔离示例，不创建真实任务 | `core/ui/src/components/CoreArrangeManager.vue`；按钮配方 `core/ui/src/styles/full-area-buttons.css` |
| RightSidebarProcesses | 右侧栏后台进程、日志和状态操作 | `requestRpc`、`sessionId`、`processSignal`；展厅使用本地示例，不访问或终止系统进程 | `core/ui/src/components/RightSidebarProcesses.vue` |
| CorePluginSystemEditor | 插件管理、筛选及配置 | `requestRpc`；展厅只模拟搜索和启停，不访问已安装插件，未实现的操作提示不支持 | `core/ui/src/components/CorePluginSystemEditor.vue` |
| CoreLoadToolsEditor | 工具模式、工具清单及保存 | `requestRpc`；展厅使用内存示例，保存不访问真实设置 | `core/ui/src/components/CoreLoadToolsEditor.vue` |
| SundaySpinner | 加载图标的旋转反馈 | `.sunday-spin`；可选 `.sunday-spin--fast` / `.sunday-spin--slow` / `.sunday-spin--task`；自动遵循减少动态效果，需搭配状态文字或无障碍标签 | `core/ui/src/styles/sunday-spinner.css`；组件独立加载时显式引入样式 |
| StudySidebar | 学习应用的课程树、置顶与导航 | `courses`、`active`、`select`、`loadChildren`、`openNode`、`notesEnabled`；加载失败可重试，展厅仅使用本地示例 | `core/ui/src/study/StudySidebar.vue`；依赖 `core/ui/src/styles/workspace-shell.css` 的导航样式 |
| RuntimeChecklistCard | 当前计划、进度和步骤 | `stepGroups`；点击展开，支持减少动态效果；展厅对照右侧栏步骤 | `core/ui/src/components/RuntimeChecklistCard.vue`；步骤标记与 `RightSidebarChecklist.vue` 共用 `core/ui/src/styles/sunday-task-indicator.css`，状态文案见 `core/ui/src/helpers/runtimeStepStatus.ts` |
| ComputerUseCapsule | 电脑操作状态与结束入口 | `label`、`paused`、`stop`；支持减少动态效果 | `core/ui/src/computerUse/ComputerUseCapsule.vue` |
| CoreSystemEventRow | 子代理、记忆续跑等系统事件行 | `event.kind`、`text`、`entries` | `core/ui/src/components/CoreSystemEventRow.vue` |
| PingRing | Ping 圆环和子环展示 | `ping`；支持减少动态效果 | `core/ui/src/pet/ui/PingRing.vue` |
| CaptureEditor | 截图框选、标注及本地导出 | `frame`、`sandbox`、`busy`、`cancel`、`send` | `core/ui/src/pet/ui/CaptureEditor.vue` |
| CoreSubmissionStatus | 输入区提交状态与失败处理 | `submissions`、`canEdit`、`busy`、`retry`、`edit` | `core/ui/src/components/CoreSubmissionStatus.vue` |
| CoreSubAgentActivityIndicator | 子代理运行状态与占位 | `active`、`names`；支持减少动态效果 | `core/ui/src/components/CoreSubAgentActivityIndicator.vue` |
| HistoryLoadingIndicator | 历史消息加载反馈 | `active`；支持减少动态效果 | `core/ui/src/components/HistoryLoadingIndicator.vue` |
| CoreModelCatalog | 模型目录、筛选与详情 | `models`、`providers`、`catalogView`、本地示例数据 | `core/ui/src/components/CoreModelCatalog.vue` |
| WorkflowTriggersPanel | 工作流触发器与激活 | `workflowDefinition`、`activationBusy`、`onUpdateDefinition`、`onActivate`；展厅保存仅修改本地示例 | `core/src/lamtools_core/plugins/bundled/workflow/ui/WorkflowTriggersPanel.vue` |
| ThemeAreaEditor | 主题区域的填充、玻璃材质与透明度 | `stops`、`fillMode`、`glassLevel`、`opacity` 等更新事件；展厅示例仅存内存 | `core/ui/src/components/ThemeAreaEditor.vue`；样式 `core/ui/src/styles/theme-editor.css` |
| CorePendingDecisionPanel | 输入区确认队列、选项与自由回复 | `items`、`channelReady`、`decision-select`；展厅使用本地示例 | `core/ui/src/components/CorePendingDecisionPanel.vue` |
| SettingsShell | 设置、插件和项目设置的导航与内容框架 | `sections`、`title`、`hideNav`、`activeSection`、`beforeSectionChange`、内容插槽 | `core/ui/src/components/SettingsShell.vue`；样式 `core/ui/src/styles/layout.css` |
| CorePetEditor | 桌宠设置、Ping 配置与快捷键 | `preview` 开启本地隔离预览；正常模式读写桌面配置 | `core/ui/src/components/CorePetEditor.vue` |
| CoreAgentsEditor | AGENTS 内容编辑 | `content`、`loading`、`error`、`save`、`close`；展厅保存仅影响内存中的示例 | `core/ui/src/components/CoreAgentsEditor.vue` |
| DesignTokens | 四个主题区域、语义色、间距与圆角；桌宠设置输入跟随输入区配色 | `variables.css`、`themeToCSSVars` | `core/ui/src/styles/variables.css` |
| SundayButton | 各类操作按钮 | `.btn` 与 `.btn--primary` / `secondary` / `quiet` / `ghost` / `danger`；可选 `.btn--sm`、主按钮 `.btn--material`；工作流节点、条件编辑器和触发器面板使用紧凑按钮 | `core/ui/src/styles/sunday-button.css` |
| SundayProgress | 进度反馈 | `value`、`max`、`label`、`valueText`、`indeterminate`；未知总量提供动态反馈并支持减少动态效果 | `core/ui/src/components/SundayProgress.vue`；数值规范化见 `core/ui/src/helpers/progressMetrics.ts`，样式见 `core/ui/src/styles/sunday-controls.css` |
| CoreSendStopButton | 输入区发送、停止与继续 | `actionMode`、`disabled`、`holdEnabled`、`terminate` | `core/ui/src/components/CoreSendStopButton.vue` |
| LibrarySearchField | 资料库及设置搜索输入 | `v-model`（支持 `.trim`）、`label`、`placeholder`、`type`、图标尺寸和描边、`inputAttrs`、附加操作插槽及 `focus()`；资料库使用 `.library-surface` 样式，其他区域需提供自身样式 | `core/ui/src/components/LibrarySearchField.vue` |
| LibraryViewToggle | 资料、记忆和方案的网格／列表切换 | `v-model` 为 `grid` 或 `list`；放在 `.library-surface` 内，样式由 `library-surface.css` 提供 | `core/ui/src/components/LibraryViewToggle.vue` |
| LibraryNameDialog | 资料库创建与重命名 | `v-model`、`title`、`fieldLabel`、`placeholder`、`busy`、`error`、`submit` / `cancel`；支持 Escape、焦点恢复及完整遮罩点击取消，拖出弹窗不误关闭；放在 `.library-surface` 内，依赖 `library-surface.css` | `core/ui/src/components/LibraryNameDialog.vue` |
| LibraryConfirmDialog | 资料库多行警告和危险操作确认 | `open`、`title`、`ariaLabel`、`confirmLabel`、`cancelLabel`、默认说明插槽、`confirm` / `cancel`；支持焦点循环与恢复、完整遮罩点击取消，拖出弹窗不误关闭；放在 `.library-surface` 内，依赖 `library-surface.css` | `core/ui/src/components/LibraryConfirmDialog.vue` |
| MemoryView / PlanLibraryView | 记忆与方案浏览页面 | 展厅以隔离内存模拟新增、编辑、删除等操作；卡片和内部菜单分别处理回车，保留网格、列表和文件夹差异 | `core/ui/src/components/MemoryView.vue`、`core/ui/src/components/PlanLibraryView.vue` |
| CoreConfirmDialog | 确认、取消和可选输入 | `open`、`title`、`input`、`loading`、`confirmDisabled`、`confirm` / `cancel`；支持 Escape 与焦点恢复 | `core/ui/src/components/CoreConfirmDialog.vue` |
| SundayCheckbox | 保留原生表单行为的布尔或多项勾选 | 原生 `<input type="checkbox" class="sunday-checkbox">`、可选 `--checkbox-size` | `core/ui/src/styles/sunday-controls.css` |
| SundaySwitch | 布尔设置 | `v-model`、必填 `label`、`size`、`disabled`；异步结果未更新时恢复原状态；更新、钩子和技能设置已接入 | `core/ui/src/components/SundaySwitch.vue`；样式 `core/ui/src/styles/sunday-switch.css` |
| ThinkingIntensitySlider | 思考强度专用竖向控件 | `v-model`、`options`、`label`、`disabled`、`showParticles` | `core/ui/src/components/ThinkingIntensitySlider.vue` |
| SundayRange | 数值范围 | `v-model`、`min`、`max`、`step`、`label`、`suffix`、`disabled`、`inputAttrs`、`valueText`、`change`（松开后提交） | `core/ui/src/components/SundayRange.vue` |
| SundaySegmented | 少量互斥选项 | `v-model`、`options`、必填 `label`；当前值不在选项中时仍可键盘进入并重新选择 | `core/ui/src/components/SundaySegmented.vue` |
| UiSelect | 下拉选项 | `v-model`、`options`、`ariaLabel`、`disabled`、菜单方向及尺寸；打开后禁用会关闭菜单 | `core/ui/src/components/UiSelect.vue`；样式 `core/ui/src/styles/ui-select.css` |
| AutoTextarea | 自动增高的多行输入 | `v-model`、`placeholder`、`minRows`、`maxRows`；宽度变化时重新计算，超过最大行数后滚动 | `core/ui/src/components/AutoTextarea.vue` |
| CoreUpdateCard | 更新提示、下载进度、安装与失败状态 | `state`、`received`、`total`、`confirm` / `cancel` / `closed`；展厅仅模拟 | `core/ui/src/components/CoreUpdateCard.vue` |
| CoreProjectCreate | 项目创建与目录选择 | `transport`、`loading`、`submit` / `cancel`；`useNativePicker=false` 时使用传入的目录服务，展厅为本地模拟 | `core/ui/src/components/CoreProjectCreate.vue` |
| CoreProjectPicker | 选择已登记项目 | `projects`、`select` / `cancel`；展厅使用本地示例 | `core/ui/src/components/CoreProjectPicker.vue` |
| ProjectVisualPicker | 项目创建与设置中的图标和颜色选择 | `iconKey`、`colorKey`、`disabled`、对应更新事件；支持键盘单选 | `core/ui/src/components/ProjectVisualPicker.vue` |
| ProjectVisualIcon | 项目图标及颜色标识 | `iconKey`、`colorKey`、`size`、`iconSize`、`swatch` | `core/ui/src/components/ProjectVisualIcon.vue` |
| FileTypeBadge | 文件类型图标 | `name`、`size`、`failed` | `core/ui/src/components/FileTypeBadge.vue` |
| ProcessIcon | 会话内过程行（工具调用、推理、系统事件）的语义图标 | `import ProcessIcon from '@/components/process/ProcessIcon.vue'`；props `kind`、`partType`、`toolName`、`label`、`args`、`result`、`status`、`size`（默认 16）、`strokeWidth`（不传则按语义类别取 1.5~1.75）；语义类别与图标映射见 `core/ui/src/helpers/processIcons.ts`，认不出走 `generic`，不回退扳手。状态语义：`running` 外圈细环旋转、`pending` 降透明、`completed` 静态 `opacity .72`、`failed` / `error` 警戒红并在右下角加 4px 标点；`prefers-reduced-motion` 下环不旋转 | `core/ui/src/components/process/ProcessIcon.vue`；映射 `core/ui/src/helpers/processIcons.ts`；依赖主题变量 `--theme-process-icon-color`、`--theme-main-text`、`--red` |
| ProcessChevron | 过程行折叠态的展开指示箭头 | `import { ProcessChevron } from '@/components/process/ProcessIcon.vue'`（与 `ProcessIcon` 同一文件具名导出，一处 import 可同时拿到两者）；props `expanded`（默认 `false`）、`size`（默认 16）；`expanded` 为真时挂 `.is-expanded` 旋转 90°，过渡 `transform 160ms ease-out`，`prefers-reduced-motion` 下关闭过渡；颜色跟随 `currentColor` | `core/ui/src/components/process/ProcessIcon.vue`；样式为同文件非 scoped 块，靠 `.process-chevron` 前缀限定 |

SundaySegmented、项目图标及颜色、主题外观、填充和玻璃材质单选组使用 `core/ui/src/composables/radioGroupKeyboard.ts` 提供方向键和首尾键操作；工作流队列、进程日志、定时任务、调用历史筛选、分屏标签和分屏工作表标签通过同一模块提供键盘导航；资料库分区和工作流标题使用手动激活模式，保留编辑保护。共享确认框、命名框和项目／目录弹窗使用 `core/ui/src/composables/trapDialogTab.ts` 将 Tab 焦点保持在可操作控件内；确认框关闭后恢复原焦点。

使用前先搜索现有组件和样式；优先组合已有组件，只有交互或语义确实不同时才保留专用实现。这些控件依赖 `sunday-controls.css` 或组件自身样式与主题变量。对组件增加功能时同步更新展厅、目录和针对实际行为的测试。

## 初步盘点与后续工作

2026-11-15 的规范检查覆盖 `core/ui/src/styles/*.css` 和 `core/ui/src/components/*.vue` 共 175 个文件，报告 29 处候选差异；最初报告为 37 处。它不覆盖所有子目录，也不能判断差异是否有意保留。运行 `node .agents/skills/lam-design-spec/scripts/audit.mjs` 可重新生成结果。必须逐项核对场景和行为，不能机械替换数值。

实际页面入口与覆盖记录见 `agent_docs/ui_page_coverage.md`；完整源码索引见 `agent_docs/ui_inventory.md`，静态组件调用方见 `agent_docs/ui_component_usage.md`，可用 `node scripts/ui-inventory.mjs` 更新；该索引是搜索线索，不代表每个文件都是已验证的可复用组件。

项目已有 `core/ui/src/demo/` 中多个专门实验页和 `core/ui/src/uiRegistry/` 的运行时注册机制；前者不是完整组件目录，后者用于应用扩展，不应直接当作展厅组件清单。尚需盘点所有前端及插件界面、交互和动效，识别相似实现及实际调用方；按页面逐项迁移并验证主题、键盘操作和既有行为；扩充展厅至可复用组件，补齐参数、变体和源码定位。现有展厅只提供基础参数操作，不代表上述工作已经完成。

已核实的复用选择、迁移记录与尚未解决的差异见 `agent_docs/ui_governance_audit.md`。

独立加载的随附插件若使用 `SundaySwitch`、`UiSelect` 或共享按钮，须分别将 `sunday-switch.css`、`ui-select.css` 或 `sunday-button.css` 随插件注入；主应用通过 `sunday-controls.css` 引入，不复制控件规则。网络工具使用此方式并保持原有操作、禁用及失败回退。
