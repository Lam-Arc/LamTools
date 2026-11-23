# Sunday 桌面 UI 入口与覆盖记录

本表按实际入口组织盘点，而不是把源码文件数量当作覆盖率。静态引用、测试和展厅证据只证明所列场景；没有列出的状态仍需核对。源码清单和静态调用方分别见 `ui_inventory.md`、`ui_component_usage.md`，详细差异见 `ui_governance_audit.md`。本表不包含 website、移动端和归档。

## 工作区及整版页面

| 入口或区域 | 实际源码 | 当前证据与尚需处理 |
| --- | --- | --- |
| 工作区、消息、输入、分屏、侧栏 | `core/ui/src/app/LamToolsApp.vue`、`ChatThread.vue`、`CoreSplitWorkspace.vue`、`RightSidebarHost.vue` | 共享发送/停止、确认队列（含断线草稿）、附件托盘、侧栏进度及部分加载动效有展厅和测试；附件托盘展示本地图片、文档、上传中、失败重试及移除，并核对浅暗主题；进程面板预览隔离本地数据，日志切换、键盘导航和错误状态已测试；真实分屏及文本编辑器以不持久化的内存数据接入展厅，标签切换、拖动、合并、关闭确认和模拟保存已通过浏览器验证；真实文件预览以本地数据覆盖 Markdown、文本、图片缩放和读取失败重试；表格工作表支持共享键盘切换；真实用户与助手消息及问题卡已接入展厅，长消息展开、问题只读、工具过程运行／完成状态及浅暗主题已验证；消息其他状态、输入、分屏及侧栏其余状态仍需按入口核对。 |
| 资料库：资料、记忆、方案 | `LibraryHomeView.vue` → `MaterialsView.vue`、`MemoryView.vue`、`PlanLibraryView.vue` | 移除、删除、放弃修改、命名表单、搜索框和网格／列表切换已共享并有交互测试；三个页面均接入隔离数据展厅，标签建议支持键盘选择；卡片内菜单的回车不会误打开卡片，深浅主题浏览器验证菜单可打开；分区标签支持键盘移动焦点并保留草稿保护；其他浏览和编辑状态仍需核对。 |
| 设置 | `CoreSettings.vue`、`settingsSections.ts`、`SettingsShell.vue` | 分区为模型、通用、桌宠、界面、工具模式、权限、上下文、Sub agent、关于与更新；模型、工具模式搜索、桌宠、主题、开关及部分输入有专项测试，工具模式、上下文与权限设置展厅操作仅作用于内存，零优先级、审批模式、目录边界和撤销信任已验证；其他状态仍需核对。 |
| 插件、技能、钩子 | `PluginsShell.vue` → `CorePluginSystemEditor.vue`、`CoreSkillsEditor.vue`、`CoreHooksEditor.vue` | 插件、技能和钩子页面已接入展厅；模拟搜索、启停、分组、信任、安装、配置及授权，所有写入均隔离；其他权限、安装和失败状态仍需核对。 |
| 调用台、任务、编排 | `DirectCallView.vue`、`CoreSuperAgentPanel.vue`、`CoreArrangeManager.vue` | 任务与定时任务共用按钮配方，权限复选框和调用台加载动效已共享；三个真实页面均可隔离预览；调用台测试模型切换、调用、历史及异步状态，定时任务页签与调用历史筛选使用统一键盘导航；其他操作和状态仍需核对。 |
| 搜索、连接、项目设置 | `SearchShell.vue`、`AccountShell.vue`、`CoreProjectSettings.vue` | 整版页面共用设置主题映射；全局搜索、桌面连接和项目设置已接入展厅，以本地数据验证搜索、配对码、失败、名称规则及未保存草稿切换；文件互传和发送菜单可以独立预览，验证共享进度条、取消、重试、离线禁用和示例发送；启动偏好复用共享复选框。真实设备连接及传输未进行宿主验收。 |
| 随附工作流 | `core/src/lamtools_core/plugins/bundled/workflow/ui/WorkflowView.vue` | 触发器、策略、输入、节点表单部分控件和确认语义已核对；节点运行详情和工具栏已接入展厅，验证运行、保存、冲突、浅暗主题及减少动态效果的对应场景；队列与历史可在展厅隔离操作，标签键盘导航和清理确认已验证；标题标签使用手动键盘导航并保留草稿切换保护；草稿确认框已接入展厅，焦点循环、Escape 和返回焦点已验证；真实画布以本地示例预览，网格、节点拖拽同步、连线删除与重建、复制粘贴隔离、运行锁定和容器删除警告经浏览器验证；完整工作流切换流程及画布其他操作和运行状态仍需核对。 |
| 随附学习应用 | `core/ui/src/plugins/bundled.ts` → `study/StudyView.vue` | 实际随附入口已确认；主视图、笔记、图谱和标记部分按钮使用共享配方，笔记放弃草稿使用共享确认框；源码含减少动态效果处理。侧栏、笔记树、笔记工作区、两种图谱、标记面板及选区助手已接入展厅，覆盖导航、编辑保存、草稿保护、图谱和标记操作；其余交互状态仍需核对。 |
| 随附网络工具 | `core/src/lamtools_core/plugins/bundled/network-exploration/ui/src/NetworkApp.vue` | 九个实际页面均已接入展厅，以内存模拟开关、订阅、选线、下载、搜索、报告、DNS、防护及计划；页面其他状态和真实服务仍需核对。 |

上述整版页面映射来自 `CoreAppPage.vue`；具体分区来自 `settingsSections.ts`、`LibraryHomeView.vue` 和 `PluginsShell.vue`。部分页面可能也由分屏或运行时插件入口复用，不能只按入口数量判断覆盖。

## 独立桌面窗口

| 入口 | 源码入口 | 当前证据与尚需处理 |
| --- | --- | --- |
| 主窗口 | `core/desktop/index.html` → `src/main.ts` | 承载上述工作区和整版页面。 |
| 桌宠与 Ping | `pet.html` → `src/pet.ts`；`ping.html` → `src/ping.ts`；`card.html` → `src/pingCard.ts` | 桌宠设置、部分 Ping 圆环、截图和确认已测试；其余窗口状态和布局仍需核对。 |
| 截图与标注 | `capture.html` → `src/capture.ts`；`overlay.html` → `src/overlay.ts` | 截图编辑器在展厅覆盖框选、画布外松开、撤销、重做、清空、发送防重及忙碌和错误状态，并以本地示例验证取字、语言选择、Escape 和翻译；准备失败可恢复，准备或上传期间 Escape 可退出并阻止后续步骤；独立窗口尺寸和状态胶囊部分动效已测试；真实截图与发送链路仍需核对。 |
| 电脑操作状态与托盘 | `computer-use.html` → `src/computer-use.ts`；`tray.html` → `src/tray.ts` | 状态胶囊已在展厅预览并核对减少动态效果；托盘面板已接入隔离展厅，桌宠开关、键盘操作和退出操作已验证；真实宿主状态和其他状态仍需核对。 |
| 实验入口 | `bar-preview.html`、`pet-animlab.html`、`pet-navlab.html` | 用于实验或预览；`pet-navlab` 有已记录的最简无样式要求，不机械套用生产配方。 |

工作区专项检查使用真实控制器、真实工作区外壳和浏览器组件的模拟宿主，覆盖文件标签恢复、最后一次导航的保存、关闭保护及移动不重复创建网页实例。真实系统网页的位置、焦点和滚动状态仍需桌面核对。

## 维护方式

新增入口时先核对是否实际随 Sunday 桌面交付，再加入本表；把迁移和测试写到具体场景，不将纯静态搜索、源码文件存在或构建成功写成完整视觉验收。修改通用组件时同步展厅与 `ui_component_catalog.md`，运行 `node scripts/ui-inventory.mjs` 刷新源码及调用索引。
