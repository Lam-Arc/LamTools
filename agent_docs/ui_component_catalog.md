# UI 组件目录与治理

本目录记录实际可复用的基础控件。设计规范以 `.agents/skills/lam-design-spec/SKILL.md` 为准，主题变量以 `core/ui/src/styles/variables.css` 和 `core/ui/src/helpers/theme.ts` 为准；设置类页面统一使用 `core/ui/src/helpers/settingsTheme.ts` 生成区域变量；不要另建一套主题或控件配方。

## 组件展厅

在 `core/ui` 运行 `npm run dev`，访问终端输出地址下的 `/design-system.html`。展厅直接加载生产组件，也可运行 `npm run build:design-system` 生成独立展厅。展厅可搜索、按分类筛选、切换浅暗主题、操作组件、调整滑条范围、下拉菜单参数与输入框行数并查看真实源码。开关展示标准与小尺寸；禁用状态适用于支持该属性的控件。下表列出可操作的组件或样式（大型组合组件默认按需加载，搜索时直接展示，也可点击加载预览；源码按需加载）；“源码目录”可按文件名、源码线索或静态引用方搜索，并按线索和预览状态筛选，已有预览可跳转。主组件和组合预览中的组件均可按名称或项目相对路径搜索；展项及源码目录可复制路径，复制失败时可手动选择。静态引用可能只是导出，也可能遗漏动态入口，索引不代表组件一定可达或适合复用。

| 组件 | 适用场景 | 主要接口 | 源码 |
| --- | --- | --- | --- |
| MaterialsView | 资料浏览、标签和筛选 | `projectId`、`requestRpc`、`transport`、`uploadFiles`，可通过 `copyPath` 接管路径复制；标签补全与评分支持键盘；卡片内操作不会打开文件；条目右键菜单提供三个动作：预览（交给灯箱，走统一解析链路）、转换成 Markdown（复用 `document_normalize`，产物登记为「转换/」层条目）、使用默认应用打开；失败落在就近的错误行上；展厅中的上传、打开、复制、收藏、归档和移除均为本地模拟 | `core/ui/src/components/MaterialsView.vue`；样式 `core/ui/src/styles/library-styles.css`；转换后端 `core/src/lamtools_core/artifact/convert.py` |
| LocalFilesView | Library「本机文件」：全盘搜索、目录浏览、预览、资产编辑、集合与文件操作 | `requestRpc`（`libraryfs.*`）、可选 `transport`（媒体取流）；搜索输入 260ms 防抖，类型/范围/排序/视图切换保留结果；列表/网格/瀑布三视图；选中后出现批量工具栏；窄窗把位置/资产/集合收进抽屉；坏引擎时显示明确状态条，浏览与资产仍可用 | `core/ui/src/components/LocalFilesView.vue`；挂载 `core/ui/src/components/LibraryHomeView.vue`；后端 `core/src/lamtools_core/library/service.py`、`core/src/lamtools_core/library/operations.py` |
| CoreProjectSettings | 项目名称、外观与项目规则 | `project`、`theme`、`requestRpc`、保存与更新事件；展厅仅修改内存示例，可测试草稿切换保护 | `core/ui/src/components/CoreProjectSettings.vue` |
| SearchShell | 全局搜索、分类与结果操作 | `requestRpc`、`sessions`、`onJump`、可选 `autoFocus` 与打开回调；输入变化时丢弃旧结果；展厅只操作本地示例 | `core/ui/src/components/SearchShell.vue` |
| AccountShell / RemoteConnectionPanel | 桌面设备连接状态、配对及可信设备 | `theme`、`appRuntime`；可选 `remoteServices` 供隔离预览，展厅不连接真实设备或修改剪贴板 | `core/ui/src/components/AccountShell.vue`、`core/ui/src/components/RemoteConnectionPanel.vue` |
| TransferPanel | 文件互传面板：传输进度（方向/文件名/进度/状态）、取消、重试、打开所在文件夹；收到的文件可预览与定位 | props `invoke`（宿主命令通道，可注入替身）、`sendSources`（本窗口发起的传输→源文件）、`now`（新文件提示判定）；事件 `retry`。进度使用 `SundayProgress` 和宿主 `p2p-state` 推送；界面不可见时停动画。展厅可取消、重试和预览示例文件 | `core/ui/src/components/TransferPanel.vue`；整形与错误码在 `core/ui/src/transfer/shape.ts`、`core/ui/src/transfer/codes.ts`、`core/ui/src/transfer/received.ts` |
| SendToDeviceMenu | 「发送到设备」的设备清单：可信名单 + 在线名册 + 本机票据合成，选中即开始传输 | props `path`、`name`、`size`、`invoke`；事件 `sent`、`close`。展厅只模拟发送，不读取实际配对记录；不能发的行当场写明原因（未配对/离线/无票据/超 8 GiB/非本机路径）；资格判定在 `core/ui/src/transfer/send.ts`，宿主命令在 `core/ui/src/transfer/dispatch.ts` | `core/ui/src/components/SendToDeviceMenu.vue` |
| SpeedChart | 随附网络工具的实时网速趋势和等待采样 | `history`、`traffic`、`compact`；展厅使用本地示例，不访问网络服务 | `core/src/lamtools_core/plugins/bundled/network-exploration/ui/src/SpeedChart.vue`；样式 `ui/src/style.css` |
| NetworkHome / HomeView | 随附网络工具的网络数据、加速、代理与下载快捷操作 | `session`、`navigate`；展厅以本地数据模拟开关、订阅、处理中和下载失败，不访问网络服务 | `core/src/lamtools_core/plugins/bundled/network-exploration/ui/src/HomeView.vue`；样式 `ui/src/style.css` |
| NetworkDashboard / DashboardView | 随附网络工具的加速状态、趋势与网站检查 | `session`、`navigate`、`diagnostic`；展厅与首页复用隔离数据，不检查真实网站 | `core/src/lamtools_core/plugins/bundled/network-exploration/ui/src/DashboardView.vue`；图表 `SpeedChart.vue` |
| NetworkTransfer / TransferView | 随附网络工具的下载设置、任务和详情 | `session`；展厅在内存模拟下载、暂停、继续和限速失败，成功后才显示新限速 | `core/src/lamtools_core/plugins/bundled/network-exploration/ui/src/TransferView.vue`；样式 `ui/src/style.css` |
| NetworkProxy / ProxyView | 随附网络工具的订阅、连接及线路选择 | `session`；展厅模拟订阅取消、连接、选线和测速，不发送真实订阅 | `core/src/lamtools_core/plugins/bundled/network-exploration/ui/src/ProxyView.vue`；子组件 `ImportProfile.vue`、`NodePicker.vue` |
| NetworkConnections / ConnectionsView | 随附网络工具的连接搜索和列表 | `session.read`；只展示最新查询结果，展厅仅搜索示例数据 | `core/src/lamtools_core/plugins/bundled/network-exploration/ui/src/ConnectionsView.vue` |
| NetworkDiagnose / DiagnoseView | 随附网络工具的网站检查、报告和历史 | `session`、可选 `report`；展厅模拟检查和详情，不访问真实网站 | `core/src/lamtools_core/plugins/bundled/network-exploration/ui/src/DiagnoseView.vue` |
| NetworkSettings / NetworkSettings | 随附网络工具的网络接口、DNS 和规则 | `session`；展厅使用内存接口及查询结果，不修改系统设置 | `core/src/lamtools_core/plugins/bundled/network-exploration/ui/src/NetworkSettings.vue` |
| NetworkSecurity / SecurityView | 随附网络工具的应用联网限制和设置恢复 | `session`；展厅只模拟应用及恢复记录 | `core/src/lamtools_core/plugins/bundled/network-exploration/ui/src/SecurityView.vue` |
| NetworkAdvanced / AdvancedView | 随附网络工具的定时检查、设备和采样设置 | `session`；展厅只修改内存计划，不读取实际设备或导出文件 | `core/src/lamtools_core/plugins/bundled/network-exploration/ui/src/AdvancedView.vue` |
| CoreSettings | Sunday 设置页面；展厅展示上下文与权限设置 | `section`、`theme`、`requestRpc` 等；展厅仅保存本地示例 | `core/ui/src/components/CoreSettings.vue`；信任列表 `core/ui/src/components/OperationTrustSettings.vue` |
| PluginRegionBlocks | 插件区域状态、进度、参数表单与授权操作 | `regions`、`requestRpc`、`fill`；支持字段必填声明，失败保留参数，卸载时关闭待处理确认；展厅只模拟授权和执行 | `core/ui/src/components/PluginRegionBlocks.vue`；授权流程 `core/ui/src/plugins/consent.ts` |
| PluginConfigPanel | 插件配置字段、枚举及保存反馈 | `pluginName`、`version`、`description`、`requestRpc`；展厅只读写本地示例，不加载自定义插件面板 | `core/ui/src/components/PluginConfigPanel.vue` |
| PluginMarket | 插件市场目录、安装与错误状态 | `requestRpc`、可选 `openRepository`、`changed`；展厅模拟安装和链接，不访问网络或安装插件 | `core/ui/src/components/PluginMarket.vue` |
| OpticalGlass | 承载面板与浮层菜单的共享材质 | 一套玻璃底板，按用途切换透光量；消息气泡不再叠加光学玻璃，改用 CoreMessageSurface | `core/ui/src/styles/optical-glass.css` |
| CoreMessageSurface | 消息气泡外壳：用户与助手共用 | props `shape`（`card` 卡片 / `capsule` 胶囊）、`fill`（任意 CSS 颜色，空则用角色色）、`glass`（玻璃 / 实色）、`surface`（关闭时只做普通容器）；尺寸与间距可用 `--message-surface-*` 覆盖，角色色与过程区紧凑间距在 message-bubbles.css；界面入口：设置 → 通用 → 气泡外观（形状、玻璃、用户/助手填充色，存 `core.assistantDisplay`） | `core/ui/src/components/CoreMessageSurface.vue`；材质 `core/ui/src/styles/message-surface.css`；角色色 `core/ui/src/styles/message-bubbles.css` |
| CoreBubbleAppearance | 设置 → 界面 → 气泡外观 | `requestRpc`；形状（卡片/胶囊）、玻璃开关、用户与助手填充色，读写 `core.assistantDisplay`，改动即时生效 | `core/ui/src/components/CoreBubbleAppearance.vue`；材质 `core/ui/src/styles/message-surface.css` |
| MessageView | 用户、助手消息、工具过程、长文本折叠及问题卡 | `msg`、`transport`、`messageActions`、运行与决策状态；展厅只使用本地示例，不接入会话 | `core/ui/src/components/MessageView.vue`；问题卡 `core/ui/src/components/CoreQuestionGroup.vue`（`disabled` 控制只读）；会话样式 `core/ui/src/styles/chat-thread-*.css` |
| WorkflowControlBar | 工作流运行、调试、保存与冲突处理 | `running`、`dirty`、`conflict`、`canUndo`、`canRedo` 和操作事件；展厅仅记录本地操作 | `core/src/lamtools_core/plugins/bundled/workflow/ui/WorkflowControlBar.vue` |
| WorkflowCanvas | 工作流节点、连线及画布元素 | `definition`、`nodeStates`、`locked`、选择和运行事件；锁定时禁止修改；`isolatedClipboard` 供展厅隔离复制粘贴，实际应用默认使用共享剪贴板 | `core/src/lamtools_core/plugins/bundled/workflow/ui/WorkflowCanvas.vue` |
| CoreSplitWorkspace | 工作区分屏布局、标签和分隔线；三态（正常／紧凑／折叠条）与指针拖拽；对称槽位（主槽／辅助槽）与主辅互换；工作区级浮层集合；区域移动与重新停靠 | `controller`、`workRoot`、`dirty`、内容插槽及几何／可见性事件；标签拖动走 pointer 状态机（按下 4px 后才算拖），命中判定由覆盖工作区的 overlay 统一算，分隔条 12px 命中／吸附 25·50·75（4px 阈值，Alt 关闭）／Home·End 到极值·Enter 复位／拖到 <8% 折叠；放不下时辅助屏收成 32px 折叠条；键盘 Ctrl+反斜杠 右分屏·Ctrl+Shift+反斜杠 下分屏·Ctrl+Shift+W 关屏·Ctrl+W 仅辅助屏关标签·Alt+1..9 切屏·Ctrl+Tab 切标签·Ctrl+Shift+Enter 聚焦·Esc 退出；空屏给「打开内容」主按钮、「辅助对话」次按钮与最近 3 项；**主槽位**：`state.mainTab` 非空时在主区矩形上画不透明 `split-main-slot`（同一套插槽内容，聊天只被盖住不卸载），左上角 `Agent ▾`（`data-split-main-switch`）打开内容实例清单，切换只改槽位指向；**浮层外壳**：浏览器自带外壳，其余内容共用 `.split-float-bar`（标题栏拖动、双击铺满、右下角 `.split-float-resize` 缩放、置顶／固定／收起／关闭四个按钮，`data-split-float-*`），层级只读 `controller.floatOrder`（z-index = `--z-stage` + 序号）；**对称槽位与主辅互换（P1）**：`mainTab` 与辅助槽共用「槽位 = `{area, surfaceId, mode, tab}`」模型（`controller.slots`、`surfaces.surfaceSlots/slotAt`），分屏右键「与主区互换」（`controller.swapMain`）只改指向，不重建内容；**浮层移出 panes（P1）**：浮层是 `state.floats` 集合 + `state.floatOrder` z 序，不再挂在任何分屏下（没有分屏也能开），`controller.tabs` 把浮层以 `pane='float'` 混进同一条扁平内容层，三态切换统一走 `controller.setSurfaceMode`（`surfaces.applySurfaceMode`）；**布局保存与恢复（P1）**：存档版本 3，`mainTab`／`floats`（矩形与 z 序）／`parkedFloats`／分屏树与比例／每个内容的形态一起进档，读档先 `parseSplitArchive` 判有效性，坏档或未知版本回落到 `<key>.prev` 备份；**区域移动与重新停靠（P1）**：从角柄拖到别的区域边缘 = 整块区域搬过去（`controller.movePanePlan/movePaneCommit`，预览与提交共用 `layout.performPaneMove`），拖到中间仍是合并，拖动期间沿用 overlay 命中与「先隐藏网页再显示」；**浮层层级与焦点（P1）**：点击浮层即 `controller.focusFloat`（置顶 + 焦点），`Alt+\`` 轮转焦点（`controller.nextFloat`），`Esc` 让焦点回主区（`controller.blurFloat`），浮层外壳描一圈焦点高亮，关闭浮层走 `controller.collapseFloat`（进 parked，不销毁内容）；**固定预览**：`beginPin` → `.split-preview--pin` 描矩形 + `.split-pin-bar`（固定／取消，Esc 收回）；**收起不销毁**：浮层「收起」进 `controller.parkedFloats`，「分屏」菜单里「收起的窗口 (N)」原样唤回；展厅使用不持久化的内存控制器 | `core/ui/src/components/CoreSplitWorkspace.vue`；控制器 `core/ui/src/split/useSplitWorkspace.ts`；内容实例／主槽位／浮层层级／固定解除固定 `core/ui/src/split/surfaces.ts`；拖拽状态机与命中表 `core/ui/src/split/splitDrag.ts`；布局纯函数（`hitZone`／`snapRatio`／`dividerLimits`）`core/ui/src/split/layout.ts` |
| CoreSplitPane | 辅助分屏标签栏（标签、关闭、角柄、溢出遮罩） | `pane`、`active`、`dirty`、`screenSwitch`、`draggingTabId`、`insertIndex`；只上报 `tab-drag`（pointerdown）与 `tabbar-dblclick`，自身不声明 `draggable`，拖动与排序由工作区统一处理 | `core/ui/src/components/CoreSplitPane.vue` |
| CoreContentRoot | 左上角布局选择器 | 只能选择 Agent 或 Browser，当前布局写入工作区。文件、库、插件与已打开网页通过标签条、标签页抽屉或各自入口管理 | `core/ui/src/components/CoreContentRoot.vue`、`core/ui/src/workspace/useWorkspace.ts` |
| CoreWorkspace | 当前桌面工作区，分屏、主区、浮层与收起 | 同一标签的内容持续挂载，切换落点只换宿主及矩形。各类辅助分屏及空分屏都有独立关闭键；关闭标签和分屏前处理未保存确认；布局存档保留文件类型、项目范围及浏览器当前地址。原生网页浮窗覆盖的分隔条片段随网页矩形裁切，露出的部分可继续拖动 | `core/ui/src/components/CoreWorkspace.vue`、`core/ui/src/components/CoreWorkspaceContentHost.vue`、`core/ui/src/workspace/useWorkspace.ts` |
| CoreWorkspaceTabs | 工作区标签条 | 横向按可用宽度显示标题、图标和翻页键。图标模式的选中标签显示关闭键，浏览器图标优先复用站点图标。展厅在 CoreWorkspace 的「预览标签溢出」里可交互验证 | `core/ui/src/components/CoreWorkspaceTabs.vue` |
| CoreWorkspaceTabDrawer | 右上角标签页抽屉（替换原分屏键）：汇总工作区主区/分屏标签、浮层及已收起浮层，支持切页、浮起/固定/恢复/关闭与快速新建浮层/分屏 | `controller`；触发器是窗口控件簇里的圆形键（直径与三键胶囊等高），点击展开卡片，数量显示在抽屉标题，支持 Esc/外部点击关闭、自动登记 `browserOverlays` | `core/ui/src/components/CoreWorkspaceTabDrawer.vue` |
| SessionFusion（`.session-fusion` + `.conversation.is-fused`） | 选中会话与右侧内容区的连接处（Agent 纵向融合）：两侧面板同底色，连接处跨过中间的缝、盖住两边描边，四角用 radial-gradient 挖出内凹圆角 | 纯 CSS + 三个几何变量 `--session-fusion-top` / `--session-fusion-height` / `--session-fusion-row-bleed`（由 `useSessionFusion` 量出来写在外壳上，不写死侧栏内边距）；几何纯函数 `fusionGeometry`；装饰令牌 `--session-fusion-fill` / `-indicator` / `-indicator-width` / `-radius` / `-inset` / `-plate-display`（设 `none` 即整条连接处不画）；窄窗（≤640px）抽屉态不画 | `core/ui/src/styles/workspace-shell.css`、`core/ui/src/styles/session-sidebar.css`；测量 `core/ui/src/composables/useSessionFusion.ts`、`core/ui/src/composables/sessionFusion.ts`；挂载点 `core/ui/src/components/WorkspaceShell.vue`、`core/ui/src/components/SessionSidebar.vue` |
| SessionSidebar | 项目和会话侧栏，支持筛选、折叠和拖动排序 | 仅当可见条目或排列改变时测量位移，使用 `--dur-base` / `--ease-out`，遵循减少动态效果偏好。分屏工作区展厅使用本地会话演示拖动 | `core/ui/src/components/SessionSidebar.vue`、`core/ui/src/directives/reorderMotion.ts`、`core/ui/src/design-system/SplitWorkspacePreview.vue` |
| CoreSplitTextEditor | 分屏文本编辑、保存与未保存确认 | `tab`、`root`、`controller`、`documents`、`visible`，通过 `dirty` 汇报修改；展厅使用隔离的内存文档，不写真实文件 | `core/ui/src/components/CoreSplitTextEditor.vue`；文档管理 `core/ui/src/split/documents.ts` |
| PreviewSurface | 预览器统一浏览器表面 | `document`、可选 `interactive`、`canOpenWithDefaultApp`、`canHandOff`、`loadTimeoutMs`、`annotating`、`loadOriginal`、`loadBytes`；三态（native / rendered / unsupported）。**按类型分派到原生查看器**：图片 → `PreviewImageViewer`，音视频 → `PreviewMediaPlayer`，PDF → `PreviewPdfViewer`，纯文本/JSON/CSV → `PreviewTextViewer`；只有「转换出来的 HTML」还用 iframe（`sandbox=""`，不给同源）。暴露 `reload()` 与各查看器实例；展厅随灯箱展示本地示例 | `core/ui/src/preview/PreviewSurface.vue`；契约 `core/ui/src/preview/resolve.ts`；**唯一分派表** `core/ui/src/preview/route.ts`（`resolvePreviewRoute` 决定 native/text/markdown/local/unsupported，灯箱与分屏都只读它；TIF/TIFF 走 native 且 `raster: true`） |
| PreviewImageViewer | 灯箱里的图片查看器（缩放、拖动、标注） | `src`、`name`、`annotating`（由灯箱头部控制）、`loadOriginal`（合成标注图时重新解码，避免跨源画布污染）、`loadTimeoutMs`；默认自适应（大图装下、小图 1:1）、滚轮直接以光标为锚缩放（不需要 Ctrl）、滚轮平移、左键拖动、双击切「适应 / 1:1」、`+ - 0` 快捷键；底部缩放条与标注工具坞；暴露 `hasAnnotations()`、`exportBlob()`、`fit()`、`zoomBy()`、`reload()`、`focusStage()`；纯数学在 `imageView.ts` | `core/ui/src/preview/PreviewImageViewer.vue`、`core/ui/src/preview/imageView.ts` |
| PreviewMediaPlayer | 灯箱里的音视频播放器 | `src`、`mime`、`title`、`loadTimeoutMs`；视频 `<video controls playsinline preload="metadata">`、音频卡片式 `<audio>`；加载中/失败（按 `MediaError.code` 给格式、读取、解码三类人话）/重试；暴露 `reload()`。**不再用 iframe 的媒体文档**——沙箱里既不出播放器也没有加载反馈 | `core/ui/src/preview/PreviewMediaPlayer.vue` |
| PreviewPdfViewer | 灯箱里的 PDF 查看器（pdfjs 画布） | `loadBytes`（预览通道字节）、`title`、`loadTimeoutMs`；翻页/缩放/适应宽度、失败可重试；文档对象必须放 `shallowRef`（pdfjs 6 的私有字段经 Vue 代理会抛 `#pagesNumber`），卸载用加载任务的 `destroy()`；cMap/标准字体走 `pdfjsAssets.ts`（`/pdfjs/` 下的离线副本） | `core/ui/src/preview/PreviewPdfViewer.vue`、`core/ui/src/preview/pdfjsAssets.ts`、`core/ui/public/pdfjs/` |
| PreviewTextViewer | 灯箱里的只读文本查看器 | `loadBytes`、`title`、`maxBytes`（默认 4 MB）；等宽正文、UTF-8 解码、超限与读取失败都给人话；替代原来的 sandbox iframe（CSV 会被浏览器当下载、WebView 里可能空白） | `core/ui/src/preview/PreviewTextViewer.vue` |
| AnnotationToolbar | 共用标注工具条（Ping 截图编辑器与灯箱同一份） | `tool`、`color`、`disabled`、`canUndo`、`canRedo`、`clearable`、`active`；事件 `update:tool`、`update:color`、`undo`、`redo`、`clear`；插槽 `extra`（宿主自己的按钮）与 `end`（取消等）；换皮只改 CSS 变量（`--annotation-fg/-hover/-active/-divider/-menu-*`），Ping 保持深色玻璃、灯箱跟随会话主题；工具：箭头、问号、叹号、文字块、画笔 + 8 色盘 | `core/ui/src/annotation/AnnotationToolbar.vue`；模型与绘制 `core/ui/src/annotation/model.ts`、`core/ui/src/annotation/draw.ts`、`core/ui/src/annotation/export.ts` |
| PreviewLightbox | 单例灯箱预览（媒体类默认宿位） | 应用根部挂载一次，`transport` 与可选 `resolver`（展厅/测试注入本地示例）由根传入；通过 `openInLightbox(target)` 打开，Teleport 到 body、`--z-modal`、ESC/Tab 焦点陷阱与焦点恢复；图片头部动作：标注（模式开关）、复制（未标注复制原图、标注后复制合成 PNG）、引用（经 `PREVIEW_COMPOSER_KEY` 注入的输入框通道；**未标注的原图只交绝对路径**走 `/attachments/reference`，标注图才交字节，成功后关闭且不抢输入框焦点）、外部打开；**左右切换**：同目录同类文件（`preview/siblings.ts`，族别分开），两侧圆钮 + `←`/`→`（window 级监听，到头绕回，标注中不切），头部显示 `3 / 11`；`关闭` 支持跳过焦点归还 | `core/ui/src/preview/PreviewLightbox.vue`；状态 `core/ui/src/preview/usePreviewLightbox.ts`；引用通道 `core/ui/src/preview/composerBridge.ts`、`core/ui/src/preview/imageClipboard.ts` |
| FirstRunChecklist | 首次使用进度和示例提示 | `visible`、模型、项目、会话及消息完成状态；通过事件交给宿主处理，完成态显示后自动收起；展厅可调整内存示例 | `core/ui/src/components/FirstRunChecklist.vue`；阶段逻辑 `core/ui/src/firstRun/firstRun.ts` |
| CoreSplitPreview | 分屏文件预览（与灯箱同一条解析链路） | `tab`、`root`、`transport`、可选 `pane` 和 `controller`；**不自行按扩展名分派**：经 `resolvePreviewDocument` 拿三态，native 直接用解析层给的本机地址（图片/音视频不再搬字节进 blob），unsupported 显示与灯箱同一句原因 + 「使用默认应用打开」，docx/xlsx/pptx/md 由本地渲染器承担；展厅的 Markdown、文本、图片、错误重试和打开操作均使用本地示例 | `core/ui/src/components/CoreSplitPreview.vue`；解析层 `core/ui/src/preview/resolve.ts`；分派表 `core/ui/src/preview/route.ts` |
| CoreSplitBrowser | 分屏和浮窗的浏览器，包含导航、地址栏、页内查找和网页缩放 | 以网页宿主实际矩形为准，经 DPR 单次转换后传给 WebView2。默认缩放下，横向超出视口的网页自动缩放，窗口变宽后重新适配。手动缩放会覆盖自动适配。展厅通过隔离服务模拟浏览器动作 | `core/ui/src/components/CoreSplitBrowser.vue`、`core/ui/src/split/native.ts`、`core/desktop/src-tauri/src/browser/compositor.rs` |
| 浏览器页眉（`.split-browser-header`）+ `browserOverlays` | 页眉只留五个槽位：返回、前进、刷新（加载中变停止）、地址栏、`更多 ▾`；其余入口按「页面 / 标签 / 呈现 / 下载 / 诊断(仅 dev)」分组收进菜单 | `data-browser-slot` 标识五个槽位，`data-browser-more-item` 标识菜单项；每项都调原有动作函数（`openFind`/`zoomStep`/`openExternal`/`clearSiteData`/`forgetCertificateMemory`/`newTab`/`newTabWithProfile`/`reopenClosed`/`setSurface`/`toggleDownloads`/`runDiagnostics`），不可用项置灰并在小字里写原因；窄窗用容器查询（`@container browser-header (max-width:300px)`）折掉三个导航图标，入口仍在菜单里；菜单与所有浮层经 `openOverlay()/closeOverlay()` 登记嵌套计数，`CoreSplitBrowser.options()` 读 `overlayActive()`，可见性判定仍只走 `split/browserVisibility.ts::resolveBrowserBounds`（原生 webview 永远在 DOM 之上，只能让它让位） | `core/ui/src/components/CoreSplitBrowser.vue`；登记表 `core/ui/src/split/browserOverlays.ts`；判定 `core/ui/src/split/browserVisibility.ts`、`core/ui/src/split/browserOverlay.ts` |
| BrowserHomeView | 浏览器首页：空标签时 pane 内的落地页（可选问候语 + 中央大输入栏 + 可选快捷入口 + 自定义卡片扩展位） | `controller`（可选）、`pane`（可选）、`busy`；事件 `submit`；插槽 `cards`。**显隐只有一条判据**：`browserHome.browserHomeVisible({resource, created, failed})` —— 这个标签有活着的网页就一律不画（原生 webview 永远盖在 DOM 之上）；中央输入栏**不自己解析地址**，只把原话 emit 给 `CoreSplitBrowser` 走地址栏那条唯一的 `resolveAddress`（像网址直开、否则搜索）；Enter 提交、Esc 清空、进入/切回标签自动聚焦；问候语按时段（早/下午/晚）且可关闭，问候语与快捷入口的开关都记在 localStorage 并可从「首页设置」恢复；快捷入口只放真入口（Web=聚焦输入栏；Workspace/Media 需要 `controller`+`pane` 才出现，分别打开分屏文件树与资料库页），Saved 因资料库收藏/最近项无可深链入口而**不实现**；参考图里的 Explore/Quick actions/Weather/Notes 卡片不做，改由 `cards` 插槽外挂 | `core/ui/src/components/BrowserHomeView.vue`；判据与偏好存储 `core/ui/src/split/browserHome.ts`；宿主接入时序 `core/ui/src/components/CoreSplitBrowser.vue` |
| LibraryHomeView | 统一资料库入口 | 项目文件、资料、记忆、方案和 Wiki 共用一组分区。项目文件复用 CoreSplitFileTree，切换分区保留目录展开状态。窄分屏优先保留分区栏高度，分区横向滚动，正文纵向滚动。应用导航和浏览器首页都可进入资料库 | `core/ui/src/components/LibraryHomeView.vue` |
| CoreSplitFileTree | 分屏项目文件树 + 文件检索入口 | `root`、可选 `listFiles`、`transport`、`open`；方向键展开、收起及导航，Home / End 跳转首尾；顶部检索条按「文件名 / 内容」查工作区，结果明示命中数、扫描条目数与「预算用完 / 只显示前 N 条」，点结果走同一条 `open` 通道；无 `transport` 时不显示检索框（不假装能搜）；切换项目时丢弃旧结果，失败可重试原目录；展厅可模拟读取错误 | `core/ui/src/components/CoreSplitFileTree.vue`；后端 `core/src/lamtools_core/tool/workspace_search.py`（复用 `workspace_files.py` 的匹配与扫描预算） |
| ContextMenuHost | 共享上下文菜单及子菜单 | 应用根部挂载一次，通过 `openContextMenu` 提供条目与动作；菜单内滚动不会关闭，页面滚动会关闭；展厅动作仅记录本地结果 | `core/ui/src/components/context-menu/ContextMenuHost.vue`；入口 `core/ui/src/components/context-menu/context-menu.ts` |
| WorkflowSwitchGuard | 工作流草稿保存、放弃或取消 | `open`、`choice`；焦点循环、Escape 与焦点恢复；展厅仅操作本地示例 | `core/src/lamtools_core/plugins/bundled/workflow/ui/WorkflowSwitchGuard.vue` |
| WorkflowQueuePanel | 工作流队列、历史、详情与清理确认 | `items`、`history`、`selectedItem` 和操作回调；展厅操作仅影响本地示例 | `core/src/lamtools_core/plugins/bundled/workflow/ui/WorkflowQueuePanel.vue` |
| WorkflowNodeRuntimeDock | 工作流节点运行、等待、完成和失败详情 | `nodeId`、`title`、`kind`、`state`、`detail`、人工任务回调；展厅使用本地示例 | `core/src/lamtools_core/plugins/bundled/workflow/ui/WorkflowNodeRuntimeDock.vue` |
| AttachmentTray | 输入区附件缩略图、文件、上传中、失败及重试 | `attachments`、`transport`、`preview` / `open` / `retry` / `remove`；展厅仅操作本地示例 | `core/ui/src/components/AttachmentTray.vue` |
| InlineFileComposer / ComposerBar | 输入区编辑器与输入栏 | `v-model`、文件建议、禁用状态与输入事件；输入栏通过插槽组合工具和操作；展厅补全与发送仅使用本地示例，引用右键菜单禁用 | `core/ui/src/components/InlineFileComposer.vue`、`core/ui/src/components/ComposerBar.vue` |
| CommandPalette | 输入区命令、文件和上下文建议 | `commands`、`activeIndex`、`select`；每个实例独立滚动，读屏标签区分 `/`、`@` 和 `#`；展厅随真实输入组件预览 | `core/ui/src/components/CommandPalette.vue` |
| CoreQueuedInputTray | 输入区目标及待发送队列 | `items`、`goal`、`editingId`、`draft`、`canGuide` 与编辑、排序、删除、引导事件；展厅只操作内存示例 | `core/ui/src/components/CoreQueuedInputTray.vue` |
| CoreExecutionControls | 输入区模型、思考等级、运行模式与权限 | `modelValue`、`thinkingMode`、`permissionPreset`、各选项与更新事件；禁用时收起已打开菜单；运行模式和权限支持方向键、首尾跳转与 Escape；展厅仅修改内存示例 | `core/ui/src/components/CoreExecutionControls.vue`，菜单 `CoreRuntimeMenu.vue`、`CoreModelThinkingMenu.vue` |
| CoreWorkspaceMenu | 输入区工作环境选择 | `activeId`、`options`、`disabled`、`select`；支持方向键和首尾键，禁用或无选项时收起菜单；展厅展示本地示例 | `core/ui/src/components/CoreWorkspaceMenu.vue` |
| CoreSuperAgentPanel | 目标任务列表、权限与详情 | `requestRpc`；展厅为隔离示例，不创建真实任务 | `core/ui/src/components/CoreSuperAgentPanel.vue`；按钮配方 `core/ui/src/styles/full-area-buttons.css` |
| CoreArrangeManager | 定时任务列表、模板与表单 | `requestRpc`；展厅为隔离示例，不创建真实任务 | `core/ui/src/components/CoreArrangeManager.vue`；按钮配方 `core/ui/src/styles/full-area-buttons.css` |
| RightSidebarProcesses | 右侧栏后台进程、日志和状态操作 | `requestRpc`、`sessionId`、`processSignal`；展厅使用本地示例，不访问或终止系统进程 | `core/ui/src/components/RightSidebarProcesses.vue` |
| CorePluginSystemEditor | 插件管理、筛选及配置 | `requestRpc`、可选 `openWindow`；窗口在插件卡片中显示，未匹配卡片的窗口显示在补充区域；展厅仅使用本地示例 | `core/ui/src/components/CorePluginSystemEditor.vue`；补充窗口入口 `core/ui/src/components/PluginWindowLauncher.vue` |
| CoreSkillsEditor | 技能列表、启停、分组和创建 | `requestRpc`、`changed`；展厅模拟启停及分组，其他写入明确拒绝 | `core/ui/src/components/CoreSkillsEditor.vue` |
| CoreHooksEditor | 钩子列表、事件筛选和信任管理 | `requestRpc`；同一钩子信任变更期间禁止重复操作，展厅仅模拟信任变更 | `core/ui/src/components/CoreHooksEditor.vue` |
| DirectCallView | 模型调用台、参数、结果与历史 | `requestRpc`、`projectId`、`embedded`；`persistParameters=false` 用于隔离预览，模型和历史丢弃旧响应；展厅可模拟历史读取失败 | `core/ui/src/components/DirectCallView.vue` |
| CoreLoadToolsEditor | 工具模式、工具清单及保存 | `requestRpc`；展厅使用内存示例，保存不访问真实设置 | `core/ui/src/components/CoreLoadToolsEditor.vue` |
| SundaySpinner | 加载图标的旋转反馈 | `.sunday-spin`；可选 `.sunday-spin--fast` / `.sunday-spin--slow` / `.sunday-spin--task`；自动遵循减少动态效果，需搭配状态文字或无障碍标签 | `core/ui/src/styles/sunday-spinner.css`；组件独立加载时显式引入样式 |
| StudySidebar | 学习应用的课程树、置顶与导航 | `courses`、`active`、`select`、`loadChildren`、`openNode`、`notesEnabled`；加载失败可重试，展厅仅使用本地示例 | `core/ui/src/study/StudySidebar.vue`；依赖 `core/ui/src/styles/workspace-shell.css` 的导航样式 |
| StudyNoteTree | 学习笔记目录、选择及读取状态 | `tree`、`activeId`、`loading`、`error`、选择和刷新回调；支持方向键和首尾跳转；展厅仅使用本地示例 | `core/ui/src/study/StudyNoteTree.vue`；样式 `core/ui/src/study/study.css` |
| NotesManager | 学习笔记全文预览、编辑、保存和草稿保护 | `notes`、`selected`、`onSelect`、`onSaveDocument` 等；保存期间继续输入不会丢失，较新版本不会覆盖未保存草稿；展厅可模拟远程更新 | `core/ui/src/study/NotesManager.vue`；引用 `core/ui/src/study/StudyNoteReferences.vue` |
| StudyGraph | 学习知识图谱、课程进度、节点和关系 | `net`、`nodes`、`viewport` 及打开、焦点、布局事件；展厅仅使用本地示例 | `core/ui/src/study/StudyGraph.vue`；样式 `core/ui/src/study/study.css` |
| StudyNoteRelationGraph | 笔记节点和关系、空状态及导航 | `graph`、`activeId`、`loading`、`error`、`onOpenNote`；展厅仅使用本地示例 | `core/ui/src/study/StudyNoteRelationGraph.vue` |
| MarksPanel | 学习标记的定位、解释、翻译和删除 | 默认使用共享标记及事件；可选 `items`、`onShow`、`onJump`、`onDelete` 供隔离预览 | `core/ui/src/study/MarksPanel.vue`；共享状态 `core/ui/src/study/annotations.ts` |
| SelectionAssistant | 选中文本的解释、翻译和追问弹层 | `sessionId`、`mode`、`themeMode`、`jump`；依赖插件上下文；展厅模拟回答与失败，不访问真实服务 | `core/ui/src/study/SelectionAssistant.vue`；标记状态 `core/ui/src/study/annotations.ts` |
| RuntimeChecklistCard | 当前计划、进度和步骤 | `stepGroups`；点击展开，支持减少动态效果；展厅对照右侧栏步骤 | `core/ui/src/components/RuntimeChecklistCard.vue`；步骤标记与 `RightSidebarChecklist.vue` 共用 `core/ui/src/styles/sunday-task-indicator.css`，状态文案见 `core/ui/src/helpers/runtimeStepStatus.ts` |
| ComputerUseCapsule | 电脑操作状态与结束入口 | `label`、`paused`、`stop`；支持减少动态效果 | `core/ui/src/computerUse/ComputerUseCapsule.vue` |
| CoreSystemEventRow | 子代理、记忆续跑等系统事件行 | `event.kind`、`text`、`entries` | `core/ui/src/components/CoreSystemEventRow.vue` |
| PingRing | Ping 圆环和子环展示 | `ping`；支持减少动态效果 | `core/ui/src/pet/ui/PingRing.vue` |
| TrayPanel | 桌面托盘面板 | 复用 SundaySwitch；展厅以隔离服务演示开关、打开和退出，不操作宿主 | `core/ui/src/tray/TrayPanel.vue` |
| CaptureEditor | 截图框选、标注及本地导出 | `frame`、`sandbox`、`busy`、`cancel`、`send`；拖出画布可结束标注，编码期间防止重复发送；翻译语言复用 `UiSelect`；展厅可本地取字、翻译，并切换发送中和错误状态 | `core/ui/src/pet/ui/CaptureEditor.vue` |
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
| SundayButton | 普通操作的四种语义 | `.btn--primary` 主操作（保存）、`.btn--secondary` 次操作（取消）、`.btn--quiet` 轻量操作（刷新）、`.btn--danger` 危险操作（删除），均与 `.btn` 组合。尺寸和材质为独立变体；旧 `.btn--ghost` 兼容现有紧凑布局，新用法选 `.btn--quiet` | `core/ui/src/styles/sunday-button.css` |
| SundayProgress | 进度反馈 | `value`、`max`、`label`、`valueText`、`indeterminate`；未知总量提供动态反馈并支持减少动态效果 | `core/ui/src/components/SundayProgress.vue`；数值规范化见 `core/ui/src/helpers/progressMetrics.ts`，样式见 `core/ui/src/styles/sunday-controls.css` |
| CoreSendStopButton | 主输入栏的会话控制 | 待发送时短按发送，运行中短按「停止运行」暂停，暂停后短按继续，运行或暂停时长按弹出终止确认。宿主通过 `actionMode`、`holdEnabled`、`terminate` 等接入，展厅只操作示例回合 | `core/ui/src/components/CoreSendStopButton.vue` |
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
| CoreUpdateCard | 更新提示、下载进度、安装与失败状态 | `state`、`received`、`total`、`confirm` / `cancel` / `closed`；关闭只收卡片、下载留在后台继续（`cancel` 仅由「取消下载」发出），下载完成再打开卡片显示「立即安装」；展厅仅模拟 | `core/ui/src/components/CoreUpdateCard.vue` |
| CoreProjectCreate | 项目创建与目录选择 | `transport`、`loading`、`submit` / `cancel`；`useNativePicker=false` 时使用传入的目录服务，展厅为本地模拟 | `core/ui/src/components/CoreProjectCreate.vue` |
| CoreProjectPicker | 选择已登记项目 | `projects`、`select` / `cancel`；展厅使用本地示例 | `core/ui/src/components/CoreProjectPicker.vue` |
| ProjectVisualPicker | 项目创建与设置中的图标和颜色选择 | `iconKey`、`colorKey`、`disabled`、对应更新事件；支持键盘单选 | `core/ui/src/components/ProjectVisualPicker.vue` |
| ProjectVisualIcon | 项目图标及颜色标识 | `iconKey`、`colorKey`、`size`、`iconSize`、`swatch` | `core/ui/src/components/ProjectVisualIcon.vue` |
| FileTypeBadge | 文件类型图标 | `name`、`size`、`failed` | `core/ui/src/components/FileTypeBadge.vue` |
| ProcessIcon | 会话内过程行（工具调用、推理、系统事件）的语义图标 | `import ProcessIcon from '@/components/process/ProcessIcon.vue'`；props `kind`、`partType`、`toolName`、`label`、`args`、`result`、`status`、`size`（默认 16）、`strokeWidth`（不传则按语义类别取 1.5~1.75）；语义类别与图标映射见 `core/ui/src/helpers/processIcons.ts`，认不出走 `generic`，不回退扳手。状态语义：`running` 外圈细环旋转、`pending` 降透明、`completed` 静态 `opacity .72`、`failed` / `error` 警戒红并在右下角加 4px 标点；`prefers-reduced-motion` 下环不旋转 | `core/ui/src/components/process/ProcessIcon.vue`；映射 `core/ui/src/helpers/processIcons.ts`；依赖主题变量 `--theme-process-icon-color`、`--theme-main-text`、`--red` |
| ProcessChevron | 过程行折叠态的展开指示箭头 | `import { ProcessChevron } from '@/components/process/ProcessIcon.vue'`（与 `ProcessIcon` 同一文件具名导出，一处 import 可同时拿到两者）；props `expanded`（默认 `false`）、`size`（默认 16）；`expanded` 为真时挂 `.is-expanded` 旋转 90°，过渡 `transform 160ms ease-out`，`prefers-reduced-motion` 下关闭过渡；颜色跟随 `currentColor` | `core/ui/src/components/process/ProcessIcon.vue`；样式为同文件非 scoped 块，靠 `.process-chevron` 前缀限定 |

SundaySegmented、项目图标及颜色、主题外观、填充和玻璃材质单选组使用 `core/ui/src/composables/radioGroupKeyboard.ts` 提供方向键和首尾键操作；工作流队列、进程日志、定时任务、调用历史筛选、分屏标签和分屏工作表标签通过同一模块提供键盘导航；资料库分区和工作流标题使用手动激活模式，保留编辑保护。共享确认框、命名框和项目／目录弹窗使用 `core/ui/src/composables/trapDialogTab.ts` 将 Tab 焦点保持在可操作控件内；确认框关闭后恢复原焦点。

使用前先搜索现有组件和样式；优先组合已有组件，只有交互或语义确实不同时才保留专用实现。这些控件依赖 `sunday-controls.css` 或组件自身样式与主题变量。对组件增加功能时同步更新展厅、目录和针对实际行为的测试。

## 2026-11-18 展厅按用途统计

按能打开和操作的展项计数，一个展项可能包含多个真实组件，变体、按钮状态、源码索引文件不重复计入。

| 类别 | 展项 |
| --- | ---: |
| 页面与组合 | 61 |
| 状态反馈 | 13 |
| 选项选择 | 5 |
| 内容展示 | 5 |
| 输入 | 4 |
| 按钮 | 2 |
| 数值 | 2 |
| 开关 | 1 |
| 基础 | 1 |
| 材质 | 1 |
| 动效（新增共享展项） | 1 |
| 设计令牌 | 1 |
| 合计 | 97 |

普通及会话控制各占一个按钮展项。用户与助手共用一套气泡，玻璃共用一套底板，承载、菜单、阅读是三个用途变体。消息、审批和报错反馈按各自用途展示。

## 页面与组合的用途分组

在「分类」选「页面与组合」，再用「用途」筛选。用途与组件搜索可以同时使用。每个展项按主要用途归一组。

| 用途 | 展项数 | 典型展项 |
| --- | ---: | --- |
| 聊天与输入 | 6 | 消息、输入区、附件、待发送队列 |
| 设置与外观 | 5 | 通用设置、主题区域、模型目录 |
| 文件与资料 | 8 | 资料、记忆、方案、文件树、预览与互传 |
| 工作流与任务 | 7 | 画布、触发器、运行队列、定时任务 |
| 项目与工作区 | 7 | 项目切换、分屏、全局搜索 |
| 插件与工具 | 7 | 插件市场、技能、钩子、模型调用台 |
| 学习与笔记 | 7 | 笔记树、图谱、标记、选区助手 |
| 桌面与设备 | 5 | 设备连接、桌宠、托盘、截图 |
| 网络工具 | 9 | 代理、下载、诊断和网络设置 |
| 合计 | 61 | |

可通过 `?category=组合&group=聊天与输入` 直达用途组。

## 实际页面共用的样式

- `core/ui/src/styles/page-surfaces.css` 提供页面标题、内容面板、筛选标签和状态提示。页面保留自己的布局和行为。项目设置通过现有 `settings-surface--stack` 共享分区式面板。
- 调用台、插件管理与市场、配对和互传、任务卡适用内容面板。搜索、资料库分区和任务列表共用筛选标签。错误样式与「重试」操作分开，工作流队列沿用主按钮和危险按钮。
- 主输入框展开与胶囊共用输入区描边，聚焦时加强描边。聊天、分屏和工作流仍各用合适的停靠布局。

## 动效

在展厅选择「动效」，可重播浮层与入场，查看加载等待，并模拟共享 CSS 动效减少后的效果。专用组件仍保留原有归类，在「动效」下也能找到。

- `sunday-motion.css`：浮层入场、退场，以及设置页、列表和消息入场。缩放仅作用于菜单内容，定位和键盘操作留给真实组件。
- `sunday-spinner.css`：共享加载旋转，聊天与侧栏沿用原有尺寸和状态语义。未知总量进度保留「处理中」提示。
- 发送键变形、模型与思考菜单、历史消息骨架继续由对应组件维护，使用系统的减少动态效果偏好。

## 复用和维护

按钮可在展厅选择「按钮」分类直达普通操作和主输入栏会话控制；也可通过 `/design-system.html?category=%E6%8C%89%E9%92%AE` 直接打开。

- 先用展厅或本目录查找相同用途的组件，再查静态调用索引，确认真实页面、布局与状态。颜色和常用尺寸统一取自 `core/ui/src/styles/variables.css`，用所在区域的主题变量映射。
- 同一交互优先使用现有组件或共享样式。尺寸、禁用、加载等差异用已有变体或小范围样式处理，业务规则留在页面。保留截图覆盖层、专用发送控件等需要独特对比度或交互的设计。
- 增改共享组件时同步此目录和展厅示例。用本地数据演示实际操作与可比较的状态，避免连接生产服务。修改后运行 `node scripts/ui-inventory.mjs` 同步源码目录和调用索引。
- 实际入口与已验证场景见 [页面覆盖记录](ui_page_coverage.md)，保留差异和审核线索见 [治理审计](ui_governance_audit.md)。自动盘点索引范围限定为 Sunday 桌面与随附界面。

独立加载的随附插件若使用 `SundaySwitch`、`UiSelect` 或共享按钮，须分别将 `sunday-switch.css`、`ui-select.css` 或 `sunday-button.css` 随插件注入；主应用通过 `sunday-controls.css` 引入，不复制控件规则。网络工具使用此方式并保持原有操作、禁用及失败回退。

### Sunday 桌面窗口与工作区

- **WindowControls**（`core/ui/src/components/TitleBar.vue`）是右上角一簇深灰底：左侧拖拽空白、中间标签页抽屉的圆形键、右侧三键胶囊（描边 1px 半透渐变，左上为图标色、右下稍暗；填充暗色墨黑/亮色石英白）。展厅搜索 **WindowControls** 查看实物预览。
- **WorkspaceShell / AppRail**。主界面铺满窗口（背景层不再露出衬边），左栏常驻并与右侧图标栏共用同一套底色/悬停/选中令牌；浏览器与悬浮浏览器不再占用竖栏位。Agent 项目侧栏默认展开，左上角按钮、`Ctrl+B` 或左栏右缘热区可收起或打开。
- **Agent 项目侧栏**。点选会话会把主区切回聊天，文件等标签和已有分屏仍保留在工作区。
- **CoreWorkspace / CoreWorkspaceArea / CoreWorkspaceFloat**。三者共用 `workspace/composition.ts` 的网页裁切逻辑。桌面前端构建后可用 `node core/desktop/scripts/verify-workspace-build.mjs` 验证 Browser 标签栏和地址栏。
- **CoreWorkspaceTabDrawer** 用圆形底，与最小化/最大化/关闭的胶囊同处一层深灰底、同一套描边与填充。固定浮窗时保留已有分屏内容。窗口确实太小时，只有分屏或固定操作失败才弹出错误。
