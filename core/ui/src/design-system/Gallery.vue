<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import SundaySwitch from '@/components/SundaySwitch.vue'
import SpeedChart from '../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/SpeedChart.vue'
import AttachmentTray from '@/components/AttachmentTray.vue'
import attachmentSource from '@/components/AttachmentTray.vue?raw'
import type { CoreAttachment } from '@/types.ts'
import SundayRange from '@/components/SundayRange.vue'
import SundayProgress from '@/components/SundayProgress.vue'
import SundaySegmented from '@/components/SundaySegmented.vue'
import UiSelect from '@/components/UiSelect.vue'
import AutoTextarea from '@/components/AutoTextarea.vue'
import FileTypeBadge from '@/components/FileTypeBadge.vue'
// user:“过程行读取文件且 MIME 属于多媒体时，在过程行标题下方直接挂内联预览区”+(三个过程行结果容器直接渲染生产组件)。
import ProcessMediaPreview from '@/components/process/ProcessMediaPreview.vue'
import ProcessResultPills from '@/components/process/ProcessResultPills.vue'
import ProcessKvPill from '@/components/process/ProcessKvPill.vue'
// user:“展品里的图片请用工作区内真实存在的图片文件路径，别用外链、别用 base64 占位”
// +(展厅用项目自带图片资源演示比例与多图，构建时由 Vite 处理成真实地址)。
import galleryMediaIconDark from '@/assets/sunday-app-icon-dark.png'
import galleryMediaIconLight from '@/assets/sunday-app-icon-light.png'
import galleryMediaSkin from '@/pet/assets/sunday-skin.png'
import ProjectVisualIcon from '@/components/ProjectVisualIcon.vue'
import ProjectVisualPicker from '@/components/ProjectVisualPicker.vue'
import CoreProjectPicker from '@/components/CoreProjectPicker.vue'
import CoreProjectCreate from '@/components/CoreProjectCreate.vue'
import CoreUpdateCard from '@/components/CoreUpdateCard.vue'
import type { CoreUpdateCardState } from '@/components/CoreUpdateCard.vue'
import type { LamToolsTransport } from '@/transport/index.ts'
import type { CoreProjectColorKey, CoreProjectIconKey } from '@/projects/types.ts'
import HistoryLoadingIndicator from '@/components/HistoryLoadingIndicator.vue'
import CoreSubAgentActivityIndicator from '@/components/CoreSubAgentActivityIndicator.vue'
import CoreSubmissionStatus from '@/components/CoreSubmissionStatus.vue'
import CorePendingDecisionPanel from '@/components/CorePendingDecisionPanel.vue'
import type { CorePendingDecision } from '@/appServer/pendingDecisions.ts'
import CoreSystemEventRow from '@/components/CoreSystemEventRow.vue'
import RuntimeChecklistCard from '@/components/RuntimeChecklistCard.vue'
import RightSidebarChecklist from '@/components/RightSidebarChecklist.vue'
import sidebarChecklistSource from '@/components/RightSidebarChecklist.vue?raw'
import taskIndicatorSource from '@/styles/sunday-task-indicator.css?raw'
import runtimeStepStatusSource from '@/helpers/runtimeStepStatus.ts?raw'
import fullAreaButtonsSource from '@/styles/full-area-buttons.css?raw'
import CoreAgentsEditor from '@/components/CoreAgentsEditor.vue'
import WorkflowControlBar from '../../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowControlBar.vue'
import workflowCanvasSource from '../../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowCanvas.vue?raw'
import workflowControlsSource from '../../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowControlBar.vue?raw'
import WorkflowSwitchGuard from '../../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowSwitchGuard.vue'
import workflowGuardSource from '../../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowSwitchGuard.vue?raw'
import WorkflowQueuePanel from '../../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowQueuePanel.vue'
import workflowQueueSource from '../../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowQueuePanel.vue?raw'
import type { WorkflowQueueItem } from '../../../src/lamtools_core/plugins/bundled/workflow/ui/types'
import WorkflowNodeRuntimeDock from '../../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowNodeRuntimeDock.vue'
import workflowRuntimeSource from '../../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowNodeRuntimeDock.vue?raw'
import type { NodeStateStatus } from '../../../src/lamtools_core/plugins/bundled/workflow/ui/types'
import WorkflowTriggersPanel from '../../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowTriggersPanel.vue'
import type { WorkflowDef } from '../../../src/lamtools_core/plugins/bundled/workflow/ui/types'
import type { CoreRuntimeStepGroup, CoreMessage, CoreMessageEditRequest } from '@/types.ts'
import type { CorePermissionPreset } from '@/composer/execution.ts'
import ComputerUseCapsule from '@/computerUse/ComputerUseCapsule.vue'
import CoreConfirmDialog from '@/components/CoreConfirmDialog.vue'
import LibraryConfirmDialog from '@/components/LibraryConfirmDialog.vue'
import LibraryNameDialog from '@/components/LibraryNameDialog.vue'
import LibraryViewToggle from '@/components/LibraryViewToggle.vue'
import LibrarySearchField from '@/components/LibrarySearchField.vue'
import SettingsShell from '@/components/SettingsShell.vue'
import ThemeAreaEditor from '@/components/ThemeAreaEditor.vue'
import CoreSendStopButton from '@/components/CoreSendStopButton.vue'
import ThinkingIntensitySlider from '@/components/ThinkingIntensitySlider.vue'
import StudySidebar from '@/study/StudySidebar.vue'
import { LoaderCircle } from 'lucide-vue-next'
import '@/styles/sunday-spinner.css'
import spinnerSource from '@/styles/sunday-spinner.css?raw'
import motionSource from '@/styles/sunday-motion.css?raw'
import MotionPreview from './MotionPreview.vue'
import type { KnowledgeItem } from '@/study/types.ts'
import studySidebarSource from '@/study/StudySidebar.vue?raw'
import { SUNDAY_DARK_THEME, SUNDAY_LIGHT_THEME, themeToCSSVars, type ThemeFillMode, type ThemeGlassPreference, type ThemeImageFit } from '@/helpers/theme'
import { settingsThemeVars } from '@/helpers/settingsTheme.ts'
import switchSource from '@/components/SundaySwitch.vue?raw'
// user:“源码定位”+(开关展厅同时展示组件与共用样式来源)。
import switchStyleSource from '@/styles/sunday-switch.css?raw'
import rangeSource from '@/components/SundayRange.vue?raw'
import segmentedSource from '@/components/SundaySegmented.vue?raw'
import selectSource from '@/components/UiSelect.vue?raw'
// user:“源码定位”+(下拉组件与共用样式一并可查)。
import selectStyleSource from '@/styles/ui-select.css?raw'
import textareaSource from '@/components/AutoTextarea.vue?raw'
import badgeSource from '@/components/FileTypeBadge.vue?raw'
import processMediaPreviewSource from '@/components/process/ProcessMediaPreview.vue?raw'
import processResultPillsSource from '@/components/process/ProcessResultPills.vue?raw'
import processKvPillSource from '@/components/process/ProcessKvPill.vue?raw'
import processMediaStyleSource from '@/styles/process-media.css?raw'
import projectIconSource from '@/components/ProjectVisualIcon.vue?raw'
import projectPickerSource from '@/components/ProjectVisualPicker.vue?raw'
import coreProjectPickerSource from '@/components/CoreProjectPicker.vue?raw'
import coreProjectCreateSource from '@/components/CoreProjectCreate.vue?raw'
import updateCardSource from '@/components/CoreUpdateCard.vue?raw'
import historyLoadingSource from '@/components/HistoryLoadingIndicator.vue?raw'
import activitySource from '@/components/CoreSubAgentActivityIndicator.vue?raw'
import submissionSource from '@/components/CoreSubmissionStatus.vue?raw'
import pendingDecisionSource from '@/components/CorePendingDecisionPanel.vue?raw'
import eventSource from '@/components/CoreSystemEventRow.vue?raw'
import planSource from '@/components/RuntimeChecklistCard.vue?raw'
import agentsEditorSource from '@/components/CoreAgentsEditor.vue?raw'
import petEditorSource from '@/components/CorePetEditor.vue?raw'
import workflowTriggersSource from '../../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowTriggersPanel.vue?raw'
import computerUseSource from '@/computerUse/ComputerUseCapsule.vue?raw'
import captureSource from '@/pet/ui/CaptureEditor.vue?raw'
import traySource from '@/tray/TrayPanel.vue?raw'
import pingRingSource from '@/pet/ui/PingRing.vue?raw'
import type { PingRuntime } from '@/pet/ping/usePingRuntime.ts'
// user:“源码定位”+(展示对话框共用的遮罩交互源码)。
import outsidePointerSource from '@/composables/useOutsidePointerDismiss.ts?raw'
import confirmSource from '@/components/CoreConfirmDialog.vue?raw'
import libraryConfirmSource from '@/components/LibraryConfirmDialog.vue?raw'
import libraryNameSource from '@/components/LibraryNameDialog.vue?raw'
import libraryViewToggleSource from '@/components/LibraryViewToggle.vue?raw'
import librarySearchSource from '@/components/LibrarySearchField.vue?raw'
import settingsShellSource from '@/components/SettingsShell.vue?raw'
import themeAreaSource from '@/components/ThemeAreaEditor.vue?raw'
import radioKeyboardSource from '@/composables/radioGroupKeyboard.ts?raw'
import dialogFocusSource from '@/composables/trapDialogTab.ts?raw'
import sendStopSource from '@/components/CoreSendStopButton.vue?raw'
import thinkingSource from '@/components/ThinkingIntensitySlider.vue?raw'
import checkboxSource from '@/styles/sunday-controls.css?raw'
import progressSource from '@/components/SundayProgress.vue?raw'
import progressMetricsSource from '@/helpers/progressMetrics.ts?raw'
import buttonSource from '@/styles/sunday-button.css?raw'
import tokenSource from '@/styles/variables.css?raw'
import glassSource from '@/styles/optical-glass.css?raw'
import messageBubbleSource from '@/styles/message-bubbles.css?raw'
import messageSurfaceSource from '@/styles/message-surface.css?raw'
import CoreMessageSurface from '@/components/CoreMessageSurface.vue'
import coreMessageSurfaceSource from '@/components/CoreMessageSurface.vue?raw'
import CoreBubbleAppearance from '@/components/CoreBubbleAppearance.vue'
import bubbleAppearanceSource from '@/components/CoreBubbleAppearance.vue?raw'
import settingsThemeSource from '@/helpers/settingsTheme.ts?raw'
import componentInventory from './component-inventory.json'
import { copyText } from '@/helpers/clipboard'

// user:“直接渲染项目真实组件，支持分类、搜索、筛选、实时预览、交互测试、参数调整、变体对比及源码定位”+(展厅直接使用生产组件，提供可操作参数和可查看的实际源码)
// user:“提高前端一致性与开发效率”+(大型组合预览按需加载，避免打开展厅时同时初始化整个模型目录)
// user:“直接渲染项目真实组件”+(消息视图按需加载，预览不接入真实会话)。
const WindowControls = defineAsyncComponent(() => import('@/components/TitleBar.vue'))
const MaterialsView = defineAsyncComponent(() => import('@/components/MaterialsView.vue'))
const WorkflowCanvas = defineAsyncComponent(() => import('../../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowCanvas.vue'))
const SplitWorkspacePreview = defineAsyncComponent(() => import('./SplitWorkspacePreview.vue'))
const SplitFilePreview = defineAsyncComponent(() => import('./SplitFilePreview.vue'))
// user:“直接渲染项目真实组件”+(预览灯箱只展示本地示例)。
const LightboxPreview = defineAsyncComponent(() => import('./LightboxPreview.vue'))
// user:“直接渲染项目真实组件”+(新手清单展示可调的本地进度)。
const FirstRunPreview = defineAsyncComponent(() => import('./FirstRunPreview.vue'))
// user:“直接渲染项目真实组件”+(网络首页只使用本地模拟状态)。
const NetworkHomePreview = defineAsyncComponent(() => import('./NetworkHomePreview.vue'))
// user:“直接渲染项目真实组件”+(下载页面以内存任务预览)。
const NetworkTransferPreview = defineAsyncComponent(() => import('./NetworkTransferPreview.vue'))
// user:“直接渲染项目真实组件”+(代理页面只使用隔离的订阅与节点示例)。
const NetworkProxyPreview = defineAsyncComponent(() => import('./NetworkProxyPreview.vue'))
// user:“直接渲染项目真实组件”+(连接与诊断使用隔离示例)。
const NetworkInspectionPreview = defineAsyncComponent(() => import('./NetworkInspectionPreview.vue'))
// user:“直接渲染项目真实组件”+(网络设置和防护使用隔离示例)。
const NetworkSettingsPreview = defineAsyncComponent(() => import('./NetworkSettingsPreview.vue'))
// user:“直接渲染项目真实组件”+(笔记树使用本地示例)。
const StudyNoteTreePreview = defineAsyncComponent(() => import('./StudyNoteTreePreview.vue'))
// user:“直接渲染项目真实组件”+(笔记工作区仅使用本地示例)。
const StudyNotesPreview = defineAsyncComponent(() => import('./StudyNotesPreview.vue'))
// user:“直接渲染项目真实组件”+(学习图谱使用隔离节点和关系)。
const StudyGraphsPreview = defineAsyncComponent(() => import('./StudyGraphsPreview.vue'))
// user:“直接渲染项目真实组件”+(标记面板使用隔离示例)。
const StudyMarksPreview = defineAsyncComponent(() => import('./StudyMarksPreview.vue'))
// user:“直接渲染项目真实组件”+(选区助手的请求仅使用本地示例)。
const SelectionAssistantPreview = defineAsyncComponent(() => import('./SelectionAssistantPreview.vue'))
// user:“直接渲染项目真实组件”+(技能和钩子仅操作隔离示例)。
const SkillsHooksPreview = defineAsyncComponent(() => import('./SkillsHooksPreview.vue'))
// user:“直接渲染项目真实组件”+(调用台仅使用内存模型和结果)。
const DirectCallPreview = defineAsyncComponent(() => import('./DirectCallPreview.vue'))
// user:“直接渲染项目真实组件”+(设备连接使用隔离的桌面示例)。
const TransferPreview = defineAsyncComponent(() => import('./TransferPreview.vue'))
const AccountPreview = defineAsyncComponent(() => import('./AccountPreview.vue'))
const SplitBrowserPreview = defineAsyncComponent(() => import('./SplitBrowserPreview.vue'))
const LibraryHomeView = defineAsyncComponent(() => import('@/components/LibraryHomeView.vue'))
const CoreSplitFileTree = defineAsyncComponent(() => import('@/components/CoreSplitFileTree.vue'))
const ComposerPreview = defineAsyncComponent(() => import('./ComposerPreview.vue'))
const QueuedInputPreview = defineAsyncComponent(() => import('./QueuedInputPreview.vue'))
const ExecutionControlsPreview = defineAsyncComponent(() => import('./ExecutionControlsPreview.vue'))
const MemoryView = defineAsyncComponent(() => import('@/components/MemoryView.vue'))
const PlanLibraryView = defineAsyncComponent(() => import('@/components/PlanLibraryView.vue'))
import { createLibraryPreviewData } from './libraryPreviewData'
import { createMaterialsPreviewData } from './materialsPreviewData'
import { ContextMenuHost, openContextMenu } from '@/components/context-menu/index.ts'
const CoreProjectSettings = defineAsyncComponent(() => import('@/components/CoreProjectSettings.vue'))
const SearchShell = defineAsyncComponent(() => import('@/components/SearchShell.vue'))
const CoreSettings = defineAsyncComponent(() => import('@/components/CoreSettings.vue'))
const PluginRegionBlocks = defineAsyncComponent(() => import('@/components/PluginRegionBlocks.vue'))
const PluginConfigPanel = defineAsyncComponent(() => import('@/components/PluginConfigPanel.vue'))
const PluginMarket = defineAsyncComponent(() => import('@/components/PluginMarket.vue'))
const MessageView = defineAsyncComponent(() => import('@/components/MessageView.vue'))
const PingRing = defineAsyncComponent(() => import('@/pet/ui/PingRing.vue'))
const TrayPreview = defineAsyncComponent(() => import('./TrayPreview.vue'))
const CaptureEditor = defineAsyncComponent(() => import('@/pet/ui/CaptureEditor.vue'))
const CoreModelCatalog = defineAsyncComponent(() => import('@/components/CoreModelCatalog.vue'))
const CorePetEditor = defineAsyncComponent(() => import('@/components/CorePetEditor.vue'))
const CoreLoadToolsEditor = defineAsyncComponent(() => import('@/components/CoreLoadToolsEditor.vue'))
const CorePluginSystemEditor = defineAsyncComponent(() => import('@/components/CorePluginSystemEditor.vue'))
const RightSidebarProcesses = defineAsyncComponent(() => import('@/components/RightSidebarProcesses.vue'))
const CoreArrangeManager = defineAsyncComponent(() => import('@/components/CoreArrangeManager.vue'))
const entries = [
  // user:“直接渲染项目真实组件”+(资料库使用隔离文件示例)。
  { name: 'MaterialsView', category: '组合', group: '文件与资料', description: '资料浏览与标签补全；操作均模拟在本地', source: '', loadSource: () => Promise.all([import('@/components/MaterialsView.vue?raw'), import('@/styles/library-styles.css?raw'), import('./materialsPreviewData.ts?raw')]).then(([view, style, data]) => ({ default: `${view.default}\n\n/* src/styles/library-styles.css */\n${style.default}\n\n/* src/design-system/materialsPreviewData.ts */\n${data.default}` })) },
  { name: 'MemoryView', category: '组合', group: '文件与资料', description: '记忆浏览与编辑；仅修改本地示例', source: '', loadSource: () => Promise.all([import('@/components/MemoryView.vue?raw'), import('./libraryPreviewData.ts?raw')]).then(([view, data]) => ({ default: `${view.default}\n\n/* src/design-system/libraryPreviewData.ts */\n${data.default}` })) },
  { name: 'PlanLibraryView', category: '组合', group: '文件与资料', description: '方案浏览与编辑；仅修改本地示例', source: '', loadSource: () => Promise.all([import('@/components/PlanLibraryView.vue?raw'), import('./libraryPreviewData.ts?raw')]).then(([view, data]) => ({ default: `${view.default}\n\n/* src/design-system/libraryPreviewData.ts */\n${data.default}` })) },
  // user:“直接渲染项目真实组件”+(项目设置只编辑内存示例)。
  { name: 'CoreProjectSettings', category: '组合', group: '项目与工作区', description: '项目名称、外观和规则；仅修改本地示例', source: '', loadSource: () => import('@/components/CoreProjectSettings.vue?raw') },
  // user:“直接渲染项目真实组件”+(搜索仅使用内存中的任务与结果)。
  { name: 'SearchShell', category: '组合', group: '项目与工作区', description: '全局搜索与分类筛选；仅使用本地示例', source: '', loadSource: () => import('@/components/SearchShell.vue?raw') },
  // user:“直接渲染项目真实组件”+(网速图只使用本地采样示例)。
  { name: 'SpeedChart', category: '反馈', description: '网络工具网速趋势与等待采样；示例数据仅在本地', source: '', sourcePath: '../src/lamtools_core/plugins/bundled/network-exploration/ui/src/SpeedChart.vue', loadSource: () => Promise.all([import('../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/SpeedChart.vue?raw'), import('../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/style.css?raw')]).then(([chart, style]) => ({ default: `${chart.default}\n\n/* network-exploration/ui/src/style.css */\n${style.default}` })) },
  { name: 'NetworkHome', category: '组合', group: '网络工具', description: '网络工具首页快捷操作；加速、代理与下载均为本地模拟', source: '', sourcePath: '../src/lamtools_core/plugins/bundled/network-exploration/ui/src/HomeView.vue', loadSource: () => import('../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/HomeView.vue?raw') },
  { name: 'NetworkDashboard', category: '组合', group: '网络工具', description: '网络工具加速、趋势与网站检查；仅本地模拟', source: '', sourcePath: '../src/lamtools_core/plugins/bundled/network-exploration/ui/src/DashboardView.vue', loadSource: () => import('../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/DashboardView.vue?raw') },
  { name: 'NetworkConnections', category: '组合', group: '网络工具', description: '网络连接搜索与列表；仅使用本地示例', source: '', sourcePath: '../src/lamtools_core/plugins/bundled/network-exploration/ui/src/ConnectionsView.vue', loadSource: () => import('../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/ConnectionsView.vue?raw') },
  { name: 'NetworkDiagnose', category: '组合', group: '网络工具', description: '网站检查、报告与历史；仅使用本地示例', source: '', sourcePath: '../src/lamtools_core/plugins/bundled/network-exploration/ui/src/DiagnoseView.vue', loadSource: () => import('../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/DiagnoseView.vue?raw') },
  { name: 'NetworkSettings', category: '组合', group: '网络工具', description: '网络接口、DNS 与规则；仅本地模拟', source: '', sourcePath: '../src/lamtools_core/plugins/bundled/network-exploration/ui/src/NetworkSettings.vue', loadSource: () => import('../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/NetworkSettings.vue?raw') },
  { name: 'NetworkSecurity', category: '组合', group: '网络工具', description: '应用联网限制与设置恢复；仅本地模拟', source: '', sourcePath: '../src/lamtools_core/plugins/bundled/network-exploration/ui/src/SecurityView.vue', loadSource: () => import('../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/SecurityView.vue?raw') },
  { name: 'NetworkAdvanced', category: '组合', group: '网络工具', description: '定时检查、设备和采样设置；仅本地模拟', source: '', sourcePath: '../src/lamtools_core/plugins/bundled/network-exploration/ui/src/AdvancedView.vue', loadSource: () => import('../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/AdvancedView.vue?raw') },
  { name: 'NetworkTransfer', category: '组合', group: '网络工具', description: '网络工具下载任务、设置与操作；只使用本地模拟', source: '', sourcePath: '../src/lamtools_core/plugins/bundled/network-exploration/ui/src/TransferView.vue', loadSource: () => import('../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/TransferView.vue?raw') },
  { name: 'NetworkProxy', category: '组合', group: '网络工具', description: '网络工具订阅、代理连接与节点选择；仅本地模拟', source: '', sourcePath: '../src/lamtools_core/plugins/bundled/network-exploration/ui/src/ProxyView.vue', alsoPreviews: ['core/src/lamtools_core/plugins/bundled/network-exploration/ui/src/ImportProfile.vue', 'core/src/lamtools_core/plugins/bundled/network-exploration/ui/src/NodePicker.vue'], loadSource: () => Promise.all([import('../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/ProxyView.vue?raw'), import('../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/ImportProfile.vue?raw'), import('../../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/NodePicker.vue?raw')]).then(([view, profile, nodes]) => ({ default: `${view.default}\n\n/* ImportProfile.vue */\n${profile.default}\n\n/* NodePicker.vue */\n${nodes.default}` })) },
  // user:“直接渲染项目真实组件”+(上下文设置使用隔离数据和保存操作)。
  { name: 'CoreSettings', category: '组合', group: '设置与外观', description: '上下文和权限设置；只读写本地示例', alsoPreviews: ['core/ui/src/components/OperationTrustSettings.vue'], source: '', loadSource: () => Promise.all([import('@/components/CoreSettings.vue?raw'), import('@/components/OperationTrustSettings.vue?raw')]).then(([settings, trust]) => ({ default: `${settings.default}\n\n/* src/components/OperationTrustSettings.vue */\n${trust.default}` })) },
  // user:“直接渲染项目真实组件”+(插件动作和授权使用隔离示例)。
  { name: 'PluginRegionBlocks', category: '组合', group: '插件与工具', description: '插件区域、参数与授权操作；仅本地模拟', source: '', loadSource: () => Promise.all([import('@/components/PluginRegionBlocks.vue?raw'), import('@/plugins/consent.ts?raw')]).then(([panel, consent]) => ({ default: `${panel.default}\n\n/* src/plugins/consent.ts */\n${consent.default}` })) },
  // user:“直接渲染项目真实组件”+(插件配置只读写本地示例)。
  { name: 'PluginConfigPanel', category: '组合', group: '插件与工具', description: '插件配置的字段与保存状态；仅操作本地示例', source: '', loadSource: () => import('@/components/PluginConfigPanel.vue?raw') },
  // user:“直接渲染项目真实组件”+(插件市场安装和链接只使用本地模拟)。
  { name: 'PluginMarket', category: '组合', group: '插件与工具', description: '插件市场安装、更新与错误；仅操作本地示例', source: '', loadSource: () => import('@/components/PluginMarket.vue?raw') },
  // user:“直接渲染项目真实组件”+(并列展示真实用户和助手消息，禁止外部操作)。
  { name: 'MessageView', category: '组合', group: '聊天与输入', description: '消息气泡：用户、助手和问题卡，可切换助手气泡和只读状态', alsoPreviews: ['core/ui/src/components/CoreQuestionGroup.vue'], source: '', loadSource: () => Promise.all([import('@/components/MessageView.vue?raw'), import('@/components/CoreQuestionGroup.vue?raw')]).then(([message, question]) => ({ default: `${message.default}\n\n/* src/components/CoreQuestionGroup.vue */\n${question.default}` })) },
  // user:“直接渲染项目真实组件”+(工作流控制操作只记录本地示例)。
  { name: 'WorkflowControlBar', category: '组合', group: '工作流与任务', description: '工作流运行、保存与冲突操作；仅本地模拟', source: workflowControlsSource, sourcePath: '../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowControlBar.vue' },
  { name: 'WorkflowCanvas', category: '组合', group: '工作流与任务', description: '真实工作流画布；节点、布局和复制仅作用于本地示例', source: workflowCanvasSource, sourcePath: '../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowCanvas.vue' },
  { name: 'WindowControls', category: '按钮', description: '桌面右上角的最小化、最大化和关闭；展厅只预览外观', source: '', sourcePath: 'src/components/TitleBar.vue', loadSource: () => import('@/components/TitleBar.vue?raw') },
  { name: 'CoreWorkspace', category: '组合', group: '项目与工作区', description: 'Agent 与 Browser 布局切换、分屏关闭保护和标签溢出；仅使用本地示例', alsoPreviews: ['core/ui/src/components/WorkspaceShell.vue', 'core/ui/src/components/CoreWorkspaceContentHost.vue', 'core/ui/src/components/CoreSplitTextEditor.vue', 'core/ui/src/components/CoreWorkspaceTabDrawer.vue', 'core/ui/src/components/CoreWorkspaceTabs.vue'], source: '', loadSource: () => Promise.all([import('@/components/CoreWorkspace.vue?raw'), import('@/components/CoreWorkspaceContentHost.vue?raw'), import('@/components/CoreSplitTextEditor.vue?raw'), import('@/components/CoreWorkspaceTabDrawer.vue?raw'), import('@/components/CoreWorkspaceTabs.vue?raw'), import('@/workspace/composition.ts?raw'), import('@/styles/split-workspace.css?raw'), import('./SplitWorkspacePreview.vue?raw')]).then(([view, host, editor, drawer, tabs, composition, styles, preview]) => ({ default: [view.default, host.default, editor.default, drawer.default, tabs.default, composition.default, styles.default, preview.default].join('\n\n') })) },
  { name: 'CoreSplitPreview', category: '组合', group: '文件与资料', description: '分屏文件预览、失败和重试；仅使用本地示例', source: '', loadSource: () => Promise.all([import('@/components/CoreSplitPreview.vue?raw'), import('./SplitFilePreview.vue?raw')]).then(([view, preview]) => ({ default: `${view.default}\n\n/* src/design-system/SplitFilePreview.vue */\n${preview.default}` })) },
  { name: 'PreviewLightbox', category: '组合', group: '文件与资料', description: '灯箱和预览表面；图片可缩放拖动标注，只显示本地示例内容', source: '', sourcePath: 'src/preview/PreviewLightbox.vue', alsoPreviews: ['core/ui/src/preview/PreviewSurface.vue', 'core/ui/src/preview/PreviewImageViewer.vue', 'core/ui/src/annotation/AnnotationToolbar.vue'], loadSource: () => Promise.all([import('@/preview/PreviewLightbox.vue?raw'), import('@/preview/PreviewSurface.vue?raw'), import('@/preview/PreviewImageViewer.vue?raw'), import('@/annotation/AnnotationToolbar.vue?raw')]).then(([lightbox, surface, viewer, toolbar]) => ({ default: `${lightbox.default}\n\n/* src/preview/PreviewSurface.vue */\n${surface.default}\n\n/* src/preview/PreviewImageViewer.vue */\n${viewer.default}\n\n/* src/annotation/AnnotationToolbar.vue */\n${toolbar.default}` })) },
  { name: 'FirstRunChecklist', category: '组合', group: '项目与工作区', description: '首次使用清单及各阶段；进度只保存在展厅', source: '', loadSource: () => import('@/components/FirstRunChecklist.vue?raw') },
  { name: 'CoreSplitBrowser', category: '组合', group: '项目与工作区', description: '分屏浏览器地址、导航和错误；不打开真实网页', source: '', loadSource: () => Promise.all([import('@/components/CoreSplitBrowser.vue?raw'), import('./SplitBrowserPreview.vue?raw')]).then(([view, preview]) => ({ default: `${view.default}\n\n/* src/design-system/SplitBrowserPreview.vue */\n${preview.default}` })) },
  { name: 'LibraryHomeView', category: '组合', group: '文件与资料', description: '统一资料库，包含项目文件、资料、记忆、方案和 Wiki；仅使用本地示例', source: '', loadSource: () => import('@/components/LibraryHomeView.vue?raw') },
  { name: 'CoreSplitFileTree', category: '组合', group: '文件与资料', description: '分屏文件树及键盘导航；仅使用本地目录', source: '', loadSource: () => import('@/components/CoreSplitFileTree.vue?raw') },
  { name: 'InlineFileComposer', category: '组合', group: '聊天与输入', description: '输入区文本、文件与上下文补全；发送仅记录本地示例', alsoPreviews: ['core/ui/src/components/ComposerBar.vue', 'core/ui/src/components/CommandPalette.vue'], source: '', loadSource: () => Promise.all([import('@/components/InlineFileComposer.vue?raw'), import('@/components/ComposerBar.vue?raw'), import('@/components/CommandPalette.vue?raw'), import('./ComposerPreview.vue?raw')]).then(([input, bar, palette, preview]) => ({ default: `${input.default}\n\n/* src/components/ComposerBar.vue */\n${bar.default}\n\n/* src/components/CommandPalette.vue */\n${palette.default}\n\n/* src/design-system/ComposerPreview.vue */\n${preview.default}` })) },
  { name: 'CoreQueuedInputTray', category: '组合', group: '聊天与输入', description: '待发送队列的编辑、排序与引导；只操作本地示例', source: '', loadSource: () => Promise.all([import('@/components/CoreQueuedInputTray.vue?raw'), import('./QueuedInputPreview.vue?raw')]).then(([tray, preview]) => ({ default: `${tray.default}\n\n/* src/design-system/QueuedInputPreview.vue */\n${preview.default}` })) },
  { name: 'CoreExecutionControls', category: '组合', group: '聊天与输入', description: '输入区模型、思考等级、权限和工作环境；仅操作本地示例', alsoPreviews: ['core/ui/src/components/CoreRuntimeMenu.vue', 'core/ui/src/components/CoreModelThinkingMenu.vue', 'core/ui/src/components/CoreWorkspaceMenu.vue'], source: '', loadSource: () => Promise.all([import('@/components/CoreExecutionControls.vue?raw'), import('@/components/CoreRuntimeMenu.vue?raw'), import('@/components/CoreModelThinkingMenu.vue?raw'), import('@/components/CoreWorkspaceMenu.vue?raw')]).then(([controls, runtime, model, workspace]) => ({ default: `${controls.default}\n\n/* CoreRuntimeMenu.vue */\n${runtime.default}\n\n/* CoreModelThinkingMenu.vue */\n${model.default}\n\n/* CoreWorkspaceMenu.vue */\n${workspace.default}` })) },
  { name: 'ContextMenuHost', category: '基础', description: '共享菜单、键盘导航和子菜单；操作仅记录在本地', source: '', sourcePath: 'src/components/context-menu/ContextMenuHost.vue', alsoPreviews: ['core/ui/src/components/context-menu/ContextMenuPanel.vue'], loadSource: () => Promise.all([import('@/components/context-menu/ContextMenuHost.vue?raw'), import('@/components/context-menu/ContextMenuPanel.vue?raw'), import('@/components/context-menu/context-menu.ts?raw')]).then(([host, panel, logic]) => ({ default: `${host.default}\n\n/* ContextMenuPanel.vue */\n${panel.default}\n\n/* context-menu.ts */\n${logic.default}` })) },
  // user:“直接渲染项目真实组件”+(草稿选择仅修改展厅示例)。
  { name: 'WorkflowSwitchGuard', category: '反馈', description: '工作流草稿的保存、放弃或取消；仅为本地示例', source: `${workflowGuardSource}\n\n/* src/composables/trapDialogTab.ts */\n${dialogFocusSource}`, sourcePath: '../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowSwitchGuard.vue' },
  // user:“直接渲染项目真实组件”+(工作流队列和清理仅使用本地示例)。
  { name: 'WorkflowQueuePanel', category: '组合', group: '工作流与任务', description: '工作流队列、历史及清理确认；仅操作本地示例', source: `${workflowQueueSource}\n\n/* src/composables/radioGroupKeyboard.ts */\n${radioKeyboardSource}`, sourcePath: '../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowQueuePanel.vue' },
  // user:“直接渲染项目真实组件”+(工作流运行详情只展示本地状态)。
  { name: 'WorkflowNodeRuntimeDock', category: '反馈', description: '工作流节点运行状态和详情；使用本地示例', source: `${workflowRuntimeSource}\n\n/* src/styles/sunday-spinner.css */\n${spinnerSource}`, sourcePath: '../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowNodeRuntimeDock.vue' },
  // user:“直接渲染项目真实组件”+(附件操作只影响本地示例)。
  { name: 'AttachmentTray', category: '组合', group: '聊天与输入', description: '输入区附件、上传失败和重试；使用本地示例', source: attachmentSource },
  // user:“直接渲染项目真实组件”+(定时任务预览只读取空示例，真实提交操作不可用)。
  { name: 'CoreArrangeManager', category: '组合', group: '工作流与任务', description: '定时任务列表与表单；仅使用本地示例', source: '', loadSource: () => import('@/components/CoreArrangeManager.vue?raw').then(module => ({ default: `${module.default}\n\n/* src/styles/full-area-buttons.css */\n${fullAreaButtonsSource}\n\n/* src/composables/radioGroupKeyboard.ts */\n${radioKeyboardSource}` })) },
  // user:“直接渲染项目真实组件”+(进程面板使用纯本地进程与日志，不访问系统进程)。
  { name: 'RightSidebarProcesses', category: '组合', group: '工作流与任务', description: '后台进程与日志；操作仅作用于本地示例，旋转样式见 src/styles/sunday-spinner.css', source: '', loadSource: () => import('@/components/RightSidebarProcesses.vue?raw').then(module => ({ default: `${module.default}\n\n/* src/composables/radioGroupKeyboard.ts */\n${radioKeyboardSource}` })) },
  // user:“直接渲染项目真实组件”+(插件管理使用隔离示例，不访问或变更已安装插件)。
  { name: 'CorePluginSystemEditor', category: '组合', group: '插件与工具', description: '插件管理与搜索；示例操作仅在本地', alsoPreviews: ['core/ui/src/components/PluginWindowLauncher.vue'], source: '', loadSource: () => Promise.all([import('@/components/CorePluginSystemEditor.vue?raw'), import('@/components/PluginWindowLauncher.vue?raw')]).then(([editor, launcher]) => ({ default: `${editor.default}\n\n/* src/components/PluginWindowLauncher.vue */\n${launcher.default}` })) },
  { name: 'CoreSkillsEditor', category: '组合', group: '插件与工具', description: '技能启停和分组；仅操作本地示例', source: '', loadSource: () => import('@/components/CoreSkillsEditor.vue?raw') },
  { name: 'CoreHooksEditor', category: '组合', group: '插件与工具', description: '钩子筛选和信任；仅操作本地示例', source: '', loadSource: () => import('@/components/CoreHooksEditor.vue?raw') },
  { name: 'DirectCallView', category: '组合', group: '插件与工具', description: '模型调用、参数与历史；仅使用本地示例', source: '', loadSource: () => import('@/components/DirectCallView.vue?raw') },
  // user:“直接渲染项目真实组件”+(设备传输列表和发送菜单都可独立检索和操作)。
  { name: 'TransferPanel', category: '组合', group: '文件与资料', description: '文件互传进度、取消和接收记录；仅使用本地示例', source: '', loadSource: () => import('@/components/TransferPanel.vue?raw') },
  { name: 'SendToDeviceMenu', category: '组合', group: '文件与资料', description: '按设备状态发送文件；仅使用本地示例', source: '', loadSource: () => import('@/components/SendToDeviceMenu.vue?raw') },
  { name: 'AccountShell', category: '组合', group: '桌面与设备', description: '桌面设备连接、配对状态与错误；仅使用本地示例', source: '', alsoPreviews: ['core/ui/src/components/RemoteConnectionPanel.vue'], loadSource: () => Promise.all([import('@/components/AccountShell.vue?raw'), import('@/components/RemoteConnectionPanel.vue?raw')]).then(([shell, panel]) => ({ default: `${shell.default}\n\n/* src/components/RemoteConnectionPanel.vue */\n${panel.default}` })) },
  // user:“直接渲染项目真实组件”+(工具模式预览使用内存中的数据和保存结果)。
  { name: 'CoreLoadToolsEditor', category: '组合', group: '设置与外观', description: '工具模式与工具搜索；保存仅修改本地示例', source: '', loadSource: () => import('@/components/CoreLoadToolsEditor.vue?raw') },
  // user:“变体对比”+(直接对照应用使用的三种加载速度和减少动态效果)。
  // user:“做”+(集中展示共享动作，也能在动效分类找到真实业务动作)。
  { name: 'SundayMotion', category: '动效', description: '浮层开合、列表与消息入场、加载等待和减少动效', source: motionSource + '\n\n' + spinnerSource, sourcePath: 'src/styles/sunday-motion.css' },
  { name: 'SundaySpinner', category: '反馈', description: '加载图标旋转及减少动态效果；支持四种速度', source: spinnerSource, sourcePath: 'src/styles/sunday-spinner.css' },
  // user:“直接渲染项目真实组件”+(学习侧栏使用本地数据演示导航，不访问学习资料)。
  { name: 'StudySidebar', category: '组合', group: '学习与笔记', description: '学习导航、课程树和置顶；示例仅保存在本地', source: studySidebarSource, sourcePath: 'src/study/StudySidebar.vue' },
  { name: 'StudyNoteTree', category: '组合', group: '学习与笔记', description: '学习笔记文件树、键盘导航与错误状态；仅使用本地示例', source: '', sourcePath: 'src/study/StudyNoteTree.vue', loadSource: () => import('@/study/StudyNoteTree.vue?raw') },
  { name: 'NotesManager', category: '组合', group: '学习与笔记', description: '学习笔记编辑、保存与草稿保护；仅使用本地示例', source: '', sourcePath: 'src/study/NotesManager.vue', alsoPreviews: ['core/ui/src/study/StudyNoteReferences.vue'], loadSource: () => Promise.all([import('@/study/NotesManager.vue?raw'), import('@/study/StudyNoteReferences.vue?raw')]).then(([notes, references]) => ({ default: `${notes.default}\n\n/* src/study/StudyNoteReferences.vue */\n${references.default}` })) },
  { name: 'StudyGraph', category: '组合', group: '学习与笔记', description: '学习知识图谱、缩放与节点；仅使用本地示例', source: '', sourcePath: 'src/study/StudyGraph.vue', loadSource: () => import('@/study/StudyGraph.vue?raw') },
  { name: 'StudyNoteRelationGraph', category: '组合', group: '学习与笔记', description: '笔记关系图、节点及空状态；仅使用本地示例', source: '', sourcePath: 'src/study/StudyNoteRelationGraph.vue', loadSource: () => import('@/study/StudyNoteRelationGraph.vue?raw') },
  { name: 'MarksPanel', category: '组合', group: '学习与笔记', description: '学习标记、解释、翻译和定位；仅使用本地示例', source: '', sourcePath: 'src/study/MarksPanel.vue', loadSource: () => import('@/study/MarksPanel.vue?raw') },
  { name: 'SelectionAssistant', category: '组合', group: '学习与笔记', description: '选区解释、翻译和追问；仅使用本地示例', source: '', sourcePath: 'src/study/SelectionAssistant.vue', loadSource: () => import('@/study/SelectionAssistant.vue?raw') },
  // user:“直接渲染项目真实组件”+(资料库搜索使用本地示例，筛选不会访问真实资料)。
  { name: 'LibrarySearchField', category: '输入', description: '资料、记忆和方案的搜索输入', source: librarySearchSource },
  // user:“直接渲染项目真实组件”+(更新卡片只模拟状态和进度，不启动实际更新)。
  { name: 'CoreUpdateCard', category: '反馈', description: '更新弹窗及下载、安装和失败状态；仅本地模拟', source: `${updateCardSource}\n\n/* src/composables/trapDialogTab.ts */\n${dialogFocusSource}` },
  // user:“直接渲染项目真实组件”+(项目创建和目录选择只使用本地示例，不写入项目或调用系统选择器)。
  { name: 'CoreProjectCreate', category: '组合', group: '项目与工作区', description: '项目创建弹窗，使用本地示例目录与结果', source: `${coreProjectCreateSource}\n\n/* src/composables/trapDialogTab.ts */\n${dialogFocusSource}\n\n/* src/composables/useOutsidePointerDismiss.ts */\n${outsidePointerSource}` },
  // user:“直接渲染项目真实组件”+(项目选择弹窗只处理本地示例项目)。
  { name: 'CoreProjectPicker', category: '组合', group: '项目与工作区', description: '项目选择弹窗，使用本地示例项目', source: `${coreProjectPickerSource}\n\n/* src/composables/trapDialogTab.ts */\n${dialogFocusSource}\n\n/* src/composables/useOutsidePointerDismiss.ts */\n${outsidePointerSource}` },
  // user:“直接渲染项目真实组件”+(项目图标与颜色选择器仅调整本地示例)。
  { name: 'ProjectVisualPicker', category: '选择', description: '项目图标与颜色选择；支持键盘操作', source: `${projectPickerSource}\n\n/* src/composables/radioGroupKeyboard.ts */\n${radioKeyboardSource}` },
  // user:“直接渲染项目真实组件”+(主题区域编辑只修改本地示例，不改变当前应用主题)。
  { name: 'ThemeAreaEditor', category: '组合', group: '设置与外观', description: '主题区域填充、材质和透明度；只修改本地示例', source: `${themeAreaSource}\n\n/* src/composables/radioGroupKeyboard.ts */\n${radioKeyboardSource}` },
  // user:“直接渲染项目真实组件”+(资料库视图切换使用本地示例状态)。
  { name: 'LibraryViewToggle', category: '选择', description: '资料、记忆和方案的网格/列表切换；样式位于 src/styles/library-surface.css', source: libraryViewToggleSource },
  // user:“直接渲染项目真实组件”+(确认队列、断线和自由回复只使用本地示例)。
  { name: 'CorePendingDecisionPanel', category: '组合', group: '聊天与输入', description: '输入区确认队列、选项与自由回复；仅本地模拟', source: pendingDecisionSource },
  // user:“直接渲染项目真实组件”+(设置、插件与项目共用框架提供本地导航预览)。
  { name: 'SettingsShell', category: '组合', group: '设置与外观', description: '设置页导航与内容框架；共享样式位于 src/styles/layout.css', source: settingsShellSource },
  // user:“直接渲染项目真实组件”+(桌宠设置以本地隔离状态操作，避免读取或修改真实配置)。
  { name: 'CorePetEditor', category: '组合', group: '桌面与设备', description: '桌宠设置；预览只操作本地示例', source: petEditorSource },
  // user:“直接渲染项目真实组件”+(资料库命名表单仅修改本地示例，不访问项目)。
  { name: 'LibraryNameDialog', category: '输入', description: '资料库创建与重命名表单，支持键盘焦点循环', source: `${libraryNameSource}\n\n/* src/composables/trapDialogTab.ts */\n${dialogFocusSource}\n\n/* src/composables/useOutsidePointerDismiss.ts */\n${outsidePointerSource}` },
  // user:“直接渲染项目真实组件”+(完整警告文本的资料库确认框使用本地示例)。
  { name: 'LibraryConfirmDialog', category: '反馈', description: '资料库多行警告与删除确认，支持键盘焦点循环', source: `${libraryConfirmSource}\n\n/* src/composables/trapDialogTab.ts */\n${dialogFocusSource}\n\n/* src/composables/useOutsidePointerDismiss.ts */\n${outsidePointerSource}` },
  // user:“直接渲染项目真实组件”+(工作流触发器展示生产面板，所有示例操作仅作用于内存)。
  { name: 'WorkflowTriggersPanel', category: '组合', group: '工作流与任务', description: '工作流触发器配置；保存仅修改本地示例', source: workflowTriggersSource, sourcePath: '../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowTriggersPanel.vue' },
  // user:“UI 请按语义整理并展示”+(普通按钮和主输入栏会话控制并列展示)。
  { name: 'SundayButton', category: '按钮', description: '普通操作 · 主操作、次操作、轻量操作和危险操作', source: buttonSource, sourcePath: 'src/styles/sunday-button.css' },
  { name: 'CoreSendStopButton', category: '按钮', description: '主输入栏会话控制 · 发送、暂停（停止运行）、继续与长按终止', source: sendStopSource },
  // user:“尤其是气泡和玻璃效果”+(展示生产材质在三种用途下的差异)。
  { name: 'OpticalGlass', category: '材质', description: '同一玻璃材质的三种用途：承载面板、浮层菜单、阅读气泡', source: glassSource + '\n\n' + messageBubbleSource, sourcePath: 'src/styles/optical-glass.css', alsoPreviews: ['core/ui/src/styles/message-bubbles.css'] },
  // user:“全部统一以这个为示例 可复用化，可调参数为胶囊/卡片,填充颜色,是否玻璃”+(气泡材质单列展项，四种组合并排对照)。
  { name: 'CoreMessageSurface', category: '材质', description: '消息气泡材质：卡片/胶囊、填充颜色、玻璃开关；用户与助手共用', source: `${coreMessageSurfaceSource}\n\n/* src/styles/message-surface.css */\n${messageSurfaceSource}`, sourcePath: 'src/styles/message-surface.css', alsoPreviews: ['core/ui/src/components/CoreMessageSurface.vue'] },
  // user:“放进 界面/主题”+(气泡外观卡片在展厅可交互，只改浏览器本地示例偏好)。
  { name: 'CoreBubbleAppearance', category: '输入', description: '气泡外观：形状、玻璃与两侧填充色；示例只改本地偏好', source: bubbleAppearanceSource, sourcePath: 'src/components/CoreBubbleAppearance.vue' },
  { name: 'DesignTokens', category: '令牌', description: '主题区域、语义色与尺寸刻度；桌宠设置文字输入使用输入区配色', source: `${tokenSource}\n\n/* src/helpers/settingsTheme.ts */\n${settingsThemeSource}`, sourcePath: 'src/styles/variables.css' },
  { name: 'ThinkingIntensitySlider', category: '数值', description: '思考强度专用竖向滑条，保留独立动效与等级语义', source: thinkingSource },
  // user:“梳理所有可见的组件、样式、布局、动效及交互”+(展厅展示真实历史加载动画并允许切换状态)。
  // user:“变体对比”+(运行指示直接对照真实组件的启用和停用状态)。
  // user:“实时预览、交互测试、参数调整、变体对比”+(用本地示例展示真实发送状态和重试操作)。
  // user:“直接渲染项目真实组件，支持分类、搜索、筛选、实时预览、交互测试、参数调整、变体对比及源码定位”+(截图编辑使用本地示例并按需载入)。
  // user:“梳理所有可见的组件、样式、布局、动效及交互”+(以本地示例展示真实 Ping 圆环及子环)。
  { name: 'PingRing', category: '组合', group: '桌面与设备', description: 'Ping 圆环与子环；示例仅供预览', source: pingRingSource, sourcePath: 'src/pet/ui/PingRing.vue' },
  // user:“直接渲染项目真实组件”+(托盘使用隔离的本地宿主演示)。
  { name: 'TrayPanel', category: '组合', group: '桌面与设备', description: '托盘面板；操作仅在本地演示', source: traySource, sourcePath: 'src/tray/TrayPanel.vue' },
  { name: 'CaptureEditor', category: '组合', group: '桌面与设备', description: '截图框选、标注、取字、翻译与发送；仅使用本地示例', source: captureSource, sourcePath: 'src/pet/ui/CaptureEditor.vue' },
  // user:“变体对比”+(使用真实系统事件行对照子代理与记忆续跑两类内容)。
  // user:“直接渲染项目真实组件，支持分类、搜索、筛选、实时预览、交互测试、参数调整、变体对比及源码定位”+(状态胶囊用本地事件演示，不调用真实电脑操作)。
  // user:“实时预览、交互测试、参数调整、变体对比”+(用本地步骤演示真实计划卡的状态与展开交互)。
  // user:“直接渲染项目真实组件”+(编辑器只保存本地示例，不写入项目文件)。
  { name: 'CoreAgentsEditor', category: '输入', description: '项目说明文本编辑与保存', source: agentsEditorSource },
  { name: 'RuntimeChecklistCard', category: '组合', group: '工作流与任务', description: '当前计划及侧栏步骤状态对照', alsoPreviews: ['core/ui/src/components/RightSidebarChecklist.vue'], source: `${planSource}\n\n/* src/components/RightSidebarChecklist.vue */\n${sidebarChecklistSource}\n\n/* src/styles/sunday-task-indicator.css */\n${taskIndicatorSource}\n\n/* src/helpers/runtimeStepStatus.ts */\n${runtimeStepStatusSource}` },
  { name: 'ComputerUseCapsule', category: '反馈', description: '电脑操作状态胶囊与结束入口', source: computerUseSource, sourcePath: 'src/computerUse/ComputerUseCapsule.vue' },
  { name: 'CoreSystemEventRow', category: '反馈', description: '子代理和系统事件的消息行', source: eventSource },
  { name: 'CoreSubmissionStatus', category: '反馈', description: '发送状态、失败重试与编辑', source: `${submissionSource}\n\n/* src/styles/sunday-spinner.css */\n${spinnerSource}` },
  { name: 'CoreSubAgentActivityIndicator', category: '反馈', description: '子代理运行指示与静止占位', source: activitySource },
  { name: 'HistoryLoadingIndicator', category: '反馈', description: '历史消息加载状态与减少动态效果', source: historyLoadingSource },
  { name: 'SundayProgress', category: '反馈', description: '已知或未知总量的任务进度，使用主题控制区颜色', source: `${progressSource}\n\n/* src/helpers/progressMetrics.ts */\n${progressMetricsSource}\n\n/* src/styles/sunday-controls.css */\n${checkboxSource}` },
  // user:“建立组件目录、使用说明与复用规范”+(展厅注明紧凑主次按钮的实际使用场景)。
  { name: 'CoreConfirmDialog', category: '反馈', description: '确认、取消与可选输入，支持键盘焦点循环', source: `${confirmSource}\n\n/* src/composables/trapDialogTab.ts */\n${dialogFocusSource}\n\n/* src/composables/useOutsidePointerDismiss.ts */\n${outsidePointerSource}` },
  { name: 'SundayCheckbox', category: '选择', description: '原生复选框，支持表单与多选', source: checkboxSource, sourcePath: 'src/styles/sunday-controls.css' },
  { name: 'SundaySwitch', category: '开关', description: '布尔设置，支持尺寸和禁用状态；用于更新、钩子和技能设置；样式：src/styles/sunday-switch.css', source: `${switchSource}\n\n/* src/styles/sunday-switch.css */\n${switchStyleSource}` },
  { name: 'SundayRange', category: '数值', description: '带标签、单位和数值的范围选择', source: rangeSource },
  { name: 'SundaySegmented', category: '选择', description: '少量互斥选项，支持键盘操作', source: `${segmentedSource}\n\n/* src/composables/radioGroupKeyboard.ts */\n${radioKeyboardSource}` },
  { name: 'UiSelect', category: '选择', description: '选项较多时使用的下拉选择；样式：src/styles/ui-select.css', source: `${selectSource}\n\n/* src/styles/ui-select.css */\n${selectStyleSource}` },
  { name: 'AutoTextarea', category: '输入', description: '自动增高的多行输入框', source: textareaSource },
  // user:“直接渲染项目真实组件，支持分类、搜索、筛选、实时预览、交互测试、参数调整、变体对比及源码定位”+(项目图标以真实组件展示图案与颜色变体)。
  { name: 'ProjectVisualIcon', category: '展示', description: '项目图标、颜色和色块', source: projectIconSource },
  { name: 'FileTypeBadge', category: '展示', description: '按文件类型显示图标，支持失败状态', source: badgeSource },
  // user:“过程行读取文件且 MIME 属于多媒体时，在过程行标题下方直接挂内联预览区”+
  // (预览区各态在展厅直接对照：单图比例、多图轨道、+N、坏图降级、音频波形、视频首帧、PDF 徽章)。
  { name: 'ProcessMediaPreview', category: '展示', description: '过程行多媒体内联预览：单图比例、多图轨道、+N、坏图降级、音频波形、视频首帧与 PDF 徽章', source: `${processMediaPreviewSource}\n\n/* src/styles/process-media.css */\n${processMediaStyleSource}`, sourcePath: 'src/components/process/ProcessMediaPreview.vue' },
  // user:“胶囊式（Pill）列表：横向流式排列多个结果胶囊（Favicon + 截断标题），点击跳转原文”+(结果胶囊的降级与截断在展厅可见)。
  { name: 'ProcessResultPills', category: '展示', description: '搜索与知识库结果胶囊：favicon 首字母降级、标题单行截断、点击打开原文', source: processResultPillsSource, sourcePath: 'src/components/process/ProcessResultPills.vue' },
  // user:“超过 N 个键值折叠成「+N」（展开可看全部）”+(键值胶囊的折叠与三种状态徽章在展厅可切换)。
  { name: 'ProcessKvPill', category: '展示', description: 'API 与状态查询的键值胶囊：折叠 +N、成功/失败/进行中徽章与耗时', source: processKvPillSource, sourcePath: 'src/components/process/ProcessKvPill.vue' },
  // user:“提高前端一致性与开发效率”+(大型源码按需载入并缓存，避免打开整个展厅时先加载)。
  { name: 'CoreModelCatalog', category: '组合', group: '设置与外观', description: '模型目录、筛选与详情；示例数据仅在本地', source: '', loadSource: () => import('@/components/CoreModelCatalog.vue?raw') },
]
// user:“建立统一的 Design Tokens”+(展示四个主题区域，便于核对桌宠和其他页面的输入区配色)。
const colorTokens = ['--theme-backdrop-background', '--theme-backdrop-text', '--theme-main-background', '--theme-main-text', '--theme-composer-background', '--theme-composer-text', '--theme-control-background', '--theme-control-solid', '--theme-control-text', '--green', '--blue', '--orange', '--red', '--purple']
const scaleTokens = ['--space-1', '--space-2', '--space-3', '--space-4', '--space-5', '--space-6', '--radius-sm', '--radius', '--radius-lg', '--radius-xl']
const otherTokens = ['--font-sans', '--font-mono', '--interaction-height-sm', '--interaction-height', '--interaction-height-lg', '--alpha-hover', '--alpha-active', '--alpha-press', '--dur-fast', '--dur-base', '--ease-out', '--shadow-sm', '--shadow-md', '--shadow-lg', '--z-popover', '--z-modal', '--z-toast', '--z-fullscreen']
// user:“建立统一的 Design Tokens”+(展示实际计算值，切换主题时同步更新)
function tokenValue(name: string): string {
  void theme.value
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '未设置'
}
// user:“交互测试、参数调整、变体对比”+(附件示例不读取文件或调用真实服务)。
function initialGalleryAttachments(): CoreAttachment[] {
  return [
    { id: 'gallery-image', filename: 'image.png', mime_type: 'image/png', size: 1, preview_type: 'image', status: 'uploaded' },
    { id: 'gallery-uploading', filename: 'upload.txt', mime_type: 'text/plain', size: 1, preview_type: 'text', status: 'uploading' },
    { id: 'gallery-document', filename: 'report.pdf', mime_type: 'application/pdf', size: 1, preview_type: 'pdf', status: 'uploaded' },
    { id: 'gallery-failed', filename: 'notes.txt', mime_type: 'text/plain', size: 1, preview_type: 'text', status: 'failed', error: '示例上传失败' },
  ]
}
const galleryAttachments = ref(initialGalleryAttachments())
const galleryAttachmentResult = ref('')
const galleryAttachmentTransport = { request: async () => ({ status: 404, headers: {}, body: [] }) } as unknown as LamToolsTransport
function retryGalleryAttachment(id: string) {
  galleryAttachments.value = galleryAttachments.value.map(item => item.id === id ? { ...item, status: 'uploaded', error: undefined } : item)
}
// user:“交互测试”+(队列操作全部在内存中完成，不调用真实工作流)。
function sampleQueueItem(id: string, status: WorkflowQueueItem['status']): WorkflowQueueItem {
  return { queue_id: id, id, workflow_id: 'example', workflow_name: '示例', work_root: '', thread_id: '', run_id: id, inputs: {}, status, priority: 0 }
}
const galleryQueue = ref([sampleQueueItem('示例运行', 'running')])
const galleryHistory = ref([sampleQueueItem('示例历史', 'completed')])
const galleryQueueSelected = ref<WorkflowQueueItem | null>(null)
function resetGalleryQueue() { galleryQueue.value = [sampleQueueItem('示例运行', 'running')]; galleryHistory.value = [sampleQueueItem('示例历史', 'completed')]; galleryQueueSelected.value = null }
function clearGalleryQueue(all: boolean) { galleryHistory.value = []; if (all) galleryQueue.value = []; galleryQueueSelected.value = null }
// user:“变体对比及交互测试”+(固定示例仅用于消息展示，不读取或修改真实会话)。
const galleryMessages: CoreMessage[] = [
  { id: 'gallery-user', role: 'user', content: '示例问题：\n' + Array(9).fill('请说明这个任务的进展。').join('\n'), timestamp: '' },
  { id: 'gallery-assistant', role: 'assistant', content: '示例回答：任务已经整理完成。', timestamp: '', parts: [{ id: 'gallery-answer', partType: 'model_text', status: 'completed', label: '正文', content: '示例回答：任务已经整理完成。' }] },
  { id: 'gallery-question', role: 'assistant', content: '', timestamp: '', parts: [{ id: 'gallery-question-part', partType: 'questionGroup', status: 'pending', content: '', metadata: { question_group_id: 'sample', questions: [{ id: 'sample-question', title: '是否继续？', type: 'single', required: true, options: [{ label: '继续', description: '' }, { label: '稍后', description: '' }] }] } }] },
]
const galleryMessageLive = ref(false)
const galleryAssistantBubbles = ref(true)
const galleryProcessExpanded = ref(new Set<string>())
const galleryProcessMessage = computed<CoreMessage>(() => ({
  id: 'gallery-process', role: 'assistant', content: '示例处理结果', timestamp: '', metadata: { live: galleryMessageLive.value },
  parts: [
    { id: 'gallery-tool', partType: 'tool_call', status: galleryMessageLive.value ? 'running' : 'completed', content: '', label: '读取示例', toolName: 'read_file', toolArgs: { path: 'example.txt' }, toolResult: '示例内容' },
    { id: 'gallery-process-answer', partType: 'model_text', status: galleryMessageLive.value ? 'running' : 'completed', content: '示例处理结果', label: '正文' },
  ],
}))
function toggleGalleryProcess(id: string) { const next = new Set(galleryProcessExpanded.value); if (next.has(id)) next.delete(id); else next.add(id); galleryProcessExpanded.value = next }
const galleryMessageReadonly = ref(true)
const galleryMessageResult = ref('')
const galleryEditRefused = ref(false)
const galleryEditableMessage = ref<CoreMessage>({ id: 'gallery:turn:edit:user', role: 'user', content: '调整这条消息。', timestamp: '' })
const galleryEditBasis = () => ({ threadId: 'gallery', revision: 1 })
function settleGalleryEdit(request: CoreMessageEditRequest): void {
  if (!galleryEditRefused.value) galleryEditableMessage.value = { ...galleryEditableMessage.value, content: request.content }
  request.onSettled?.(!galleryEditRefused.value)
}
const galleryMessageTransport = { request: async () => { throw new Error('展厅不访问真实会话') } } as unknown as LamToolsTransport

/** 展厅里的气泡外观只改本地示例偏好，不写真实设置。 */
const bubbleAppearanceRpc = async () => ({ namespace: 'core.assistantDisplay', value: {} })
const galleryWorkflowRunning = ref(false)
const galleryWorkflowDirty = ref(true)
const galleryWorkflowConflict = ref(false)
const galleryWorkflowControlResult = ref('')
const galleryWorkflowGuardOpen = ref(false)
const galleryWorkflowGuardResult = ref('')
const galleryWorkflowState = ref<NodeStateStatus>('running')
const projectIcon = ref('folder')
const loadToolsRequested = ref(false)
const pluginEditorRequested = ref(false)
const fullAreaPreviewRequested = ref(false)
// user:“交互测试”+(展示只读示例数据，禁止产生真实任务或定时安排)。
async function sampleFullAreaRpc(method: string): Promise<Record<string, unknown>> {
  if (method === 'superagent.ticket.list') return { tickets: [] }
  if (method === 'arrange.list') return { jobs: [] }
  if (method.includes('list') || method.includes('get')) return {}
  throw new Error('展厅示例不支持创建或修改任务')
}
const processPreviewRequested = ref(false)
const processPreviewVersion = ref(0)
function initialSampleProcess() { return { pid: 42, command: 'example-task', alive: true, owned: true, can_terminate: true, persistent: true } }
let sampleProcess: ReturnType<typeof initialSampleProcess> | null = initialSampleProcess()
function resetSampleProcess() { sampleProcess = initialSampleProcess(); processPreviewVersion.value++ }
// user:“交互测试”+(进程列表、日志与终止操作全部使用内存数据)。
async function sampleProcessRpc(method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> {
  if (method === 'process.list') return { processes: sampleProcess ? [structuredClone(sampleProcess)] : [] }
  if (method === 'process.log') return { content: params?.stream === 'stderr' ? '示例错误输出' : '示例标准输出' }
  if (method === 'process.kill') { if (sampleProcess) sampleProcess = { ...sampleProcess, alive: false, can_terminate: false }; return {} }
  if (method === 'process.forget') { sampleProcess = null; return {} }
  throw new Error('展厅示例不支持此操作')
}
// user:“交互测试”+(市场目录、安装和链接操作均隔离在内存中)。
// user:“交互测试”+(不加载自定义插件面板，配置和失败均为本地数据)。
// user:“交互测试”+(权限确认与执行结果只记录在本地，不调用插件)。
// user:“交互测试”+(上下文设置只读写本地内存，其他设置动作不支持)。
// user:“提高前端一致性与开发效率”+(大型示例默认延迟初始化，搜索或手动打开时再加载)。
const deferredPreviewNames = new Set(['LibraryHomeView', 'MaterialsView', 'MemoryView', 'PlanLibraryView', 'WorkflowCanvas', 'CoreWorkspace', 'CoreSplitPreview', 'PreviewLightbox', 'NetworkHome', 'NetworkDashboard', 'NetworkTransfer', 'NetworkProxy', 'NetworkConnections', 'NetworkDiagnose', 'NetworkSettings', 'NetworkSecurity', 'NetworkAdvanced', 'NotesManager', 'StudyGraph', 'StudyNoteRelationGraph', 'SelectionAssistant', 'CoreSkillsEditor', 'CoreHooksEditor', 'DirectCallView', 'AccountShell', 'CoreSplitBrowser', 'CoreSplitFileTree', 'InlineFileComposer', 'CoreProjectSettings', 'SearchShell', 'CoreSettings', 'PluginRegionBlocks', 'PluginConfigPanel', 'PluginMarket', 'MessageView'])
const requestedPreviews = ref(new Set<string>())
function requestPreview(name: string) { requestedPreviews.value = new Set([...requestedPreviews.value, name]) }
const galleryNetworkEmpty = ref(false)
const galleryNetworkHistory = [{ download: 1024, upload: 512 }, { download: 4096, upload: 1536 }, { download: 3072, upload: 2048 }]
// user:“交互测试”+(搜索结果和打开动作只作用于本地示例)。
// user:“交互测试”+(项目名称、外观和规则均为本地状态，不写真实项目)。
// user:“交互测试”+(资料列表和标签仅存于内存，禁止真实文件操作)。
const galleryMaterialTags = ref('')
// user:“交互测试”+(记忆与方案的修改仅作用于本地示例)。
const { memoryRpc: sampleMemoryRpc, client: galleryLibraryClient } = createLibraryPreviewData()
const galleryMaterialRating = ref<number | null>(null)
const galleryMaterialCopied = ref('')
const { rpc: sampleMaterialsRpc, upload: uploadSampleMaterial } = createMaterialsPreviewData(item => { galleryMaterialTags.value = item.tags.join(', '); galleryMaterialRating.value = item.rating })
const galleryProject = ref({ id: 'sample-project', name: '示例项目', workRoot: '', iconKey: 'folder' as CoreProjectIconKey, colorKey: 'gray' as CoreProjectColorKey })
const galleryProjectRules = ref('示例项目规则')
const galleryProjectRulesSaved = ref(false)
async function saveGalleryProjectRules(content: string): Promise<boolean> { galleryProjectRules.value = content; galleryProjectRulesSaved.value = true; return true }
function updateGalleryProjectVisual(iconKey: CoreProjectIconKey, colorKey: CoreProjectColorKey) { galleryProject.value = { ...galleryProject.value, iconKey, colorKey } }
const gallerySearchResult = ref('')
const gallerySearchSessions = [{ id: 'sample-session', title: '示例任务', status: 'idle', updatedAt: '' }]
async function sampleSearchRpc(method: string): Promise<Record<string, unknown>> {
  if (method === 'plugin.system.list') return { plugins: [{ name: 'sample-plugin', description: '示例插件', enabled: true }] }
  if (method === 'skill.list') return { skills: [] }
  if (method === 'hook.list') return { hooks: [] }
  if (['workspace.search', 'rag.sessions.search', 'rag.docs.search', 'study.search'].includes(method)) return { hits: [] }
  throw new Error('展厅示例不支持此操作')
}
const gallerySettingsSection = ref<'agents' | 'permissions'>('agents')
const galleryPermissionPreset = ref<CorePermissionPreset>('ask')
const galleryOutsideWorkdir = ref(false)
let galleryTrustEntries = [{ key: JSON.stringify(['示例操作']), level: 2 }]
let galleryContext = { addition: [{ name: 'RULES.md', priority: 50, kind: 'system' }], except: ['AGENTS.md'] }
const galleryContextResult = ref<number | null>(null)
async function sampleSettingsRpc(method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> {
  if (method === 'permissions.trust.list') return { entries: structuredClone(galleryTrustEntries) }
  if (method === 'permissions.trust.revoke') { galleryTrustEntries = galleryTrustEntries.filter(entry => entry.key !== params?.key); return {} }
  if (method === 'config.load_context.get') return structuredClone(galleryContext)
  if (method === 'config.load_context.set') { galleryContext = structuredClone(params as typeof galleryContext); galleryContextResult.value = galleryContext.addition[0]?.priority ?? null; return {} }
  if (method === 'config.agents_md.get') return { agents_md: { content: '示例规则' } }
  if (method === 'config.agents_md.set' || method === 'settings.update') return {}
  if (method === 'settings.get') return { value: {} }
  throw new Error('展厅示例不支持此操作')
}
const galleryRegionFail = ref(false)
const galleryRegionResult = ref('')
const galleryRegions = [{ plugin: '示例插件', region: 'main', order: 0, mode: '', replace: false, blocks: [{ type: 'progress', label: '示例进度', value: 35, max: 100, text: '', state: '', items: [], detail: '' }], actions: [{ id: 'sample-run', title: '执行示例', operation: 'example.run', input_schema: { required: ['name'], properties: { name: { type: 'string', title: '名称' }, count: { type: 'number', title: '数量' }, enabled: { type: 'boolean', title: '启用' } } } }] }]
async function sampleRegionRpc(method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> {
  if (method === 'example.run') { if (galleryRegionFail.value) throw new Error('示例执行失败'); return { approval: { id: 'local', operation: '示例操作', impact: '仅模拟授权，不修改真实数据' } } }
  if (method === 'plugin.system.operation.respond') { galleryRegionResult.value = String(params?.decision || ''); return {} }
  throw new Error('展厅示例不支持此操作')
}
const galleryConfigFail = ref(false)
let galleryConfig: Record<string, unknown> = { name: '示例', enabled: true, mode: 'standard' }
async function sampleConfigRpc(method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> {
  if (method === 'plugin.system.config.get') return { schema: { properties: { name: { type: 'string', title: '名称' }, enabled: { type: 'boolean', title: '启用' }, mode: { type: 'string', title: '模式', enum: ['standard', 'compact'] } } }, config: structuredClone(galleryConfig), has_panel: false }
  if (method === 'plugin.system.config.update') { if (galleryConfigFail.value) throw new Error('示例保存失败'); galleryConfig = structuredClone(params?.config as Record<string, unknown>); return {} }
  throw new Error('展厅示例不支持此操作')
}
const galleryMarketVersion = ref(0)
const galleryMarketFail = ref(false)
const galleryMarketInstalled = ref(false)
const galleryMarketLink = ref('')
function resetGalleryMarket() { galleryMarketInstalled.value = false; galleryMarketFail.value = false; galleryMarketLink.value = ''; galleryMarketVersion.value++ }
async function sampleMarketRpc(method: string): Promise<Record<string, unknown>> {
  if (method === 'plugin.market.list') return { plugins: [{ id: 'sample', title: '示例插件', description: '本地模拟的市场条目', category: '工具', capabilities: ['示例'], version: '1.0', installed_version: galleryMarketInstalled.value ? '1.0' : '', update_available: false, installable: true, repository_url: 'https://example.invalid/sample' }] }
  if (method === 'plugin.market.install') { if (galleryMarketFail.value) throw new Error('示例安装失败'); galleryMarketInstalled.value = true; return { installed: true } }
  throw new Error('展厅示例不支持此操作')
}
const samplePlugins = [
  { name: 'alpha', version: '1.0', description: '示例插件 Alpha', enabled: true, scope: 'global', root: '/example/alpha' },
  { name: 'beta', version: '1.0', description: '示例插件 Beta', enabled: false, scope: 'global', root: '/example/beta' },
]
// user:“交互测试”+(预览只返回本地示例，不调用真实插件服务)。
async function samplePluginRpc(method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> {
  if (method === 'plugin.system.list') return { plugins: structuredClone(samplePlugins), errors: [] }
  if (method === 'plugin.system.enable' || method === 'plugin.system.disable') {
    const plugin = samplePlugins.find(item => item.name === params?.name)
    if (plugin) plugin.enabled = method === 'plugin.system.enable'
    return {}
  }
  // user:“交互测试”+(窗口入口使用本地样例，浏览器中不会打开桌面窗口)。
  if (method === 'plugin.system.ui') return { windows: [{ plugin: 'alpha', id: 'main', title: '示例插件窗口', url: '/example', width: 400, height: 300 }, { plugin: 'other', id: 'main', title: '其他示例窗口', url: '/example-other', width: 400, height: 300 }] }
  if (['plugin.system.behavior', 'plugin.deps-status', 'plugin.market.list'].includes(method)) return {}
  throw new Error('展厅示例不支持此操作')
}
const loadToolsPreviewResult = ref('')
let sampleToolModes: Record<string, { description: string; tools: string[] }> = {
  consider: { description: '分析和计划', tools: ['read_file'] },
  execute: { description: '执行任务', tools: ['read_file', 'write_file'] },
}
// user:“交互测试”+(工具模式的读取与保存均限制在展厅内存)。
async function sampleToolModesRpc(method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> {
  if (method === 'config.loadtools.set') {
    sampleToolModes = structuredClone(params?.modes as typeof sampleToolModes)
    loadToolsPreviewResult.value = '示例已保存'
    return { modes: structuredClone(sampleToolModes) }
  }
  return { modes: structuredClone(sampleToolModes), catalog: [{ name: 'read_file', category: 'file_read' }, { name: 'write_file', category: 'file_write' }], source: 'builtin' }
}
const studyPreviewActive = ref('manage')
const studyPreviewResult = ref('')
const studyPreviewNotes = ref(true)
const studyPreviewFailure = ref(false)
const studyPreviewCourses = [{ id: 'example-course', name: '示例课程', total: 1, passed: 0 }]
const studyPreviewNodes: KnowledgeItem[] = [{ id: 'example-node', name: '示例知识点', learnable: true, progressRole: 'unit', assessment: 'pass', mastery: null, course_id: 'example-course' }]
// user:“交互测试、参数调整”+(可模拟课程加载失败并重试，不访问真实服务)。
async function loadStudyPreviewChildren() {
  if (studyPreviewFailure.value) throw new Error('示例加载失败')
  return studyPreviewNodes
}
function openStudyPreviewNode(node: KnowledgeItem) { studyPreviewResult.value = node.name }
const projectColor = ref('gray')
const pickerIcon = ref<CoreProjectIconKey>('folder')
const pickerColor = ref<CoreProjectColorKey>('gray')
const projectPickerOpen = ref(false)
const projectPickerResult = ref('')
const sampleProjects = [{ id: 'sample-project', name: '示例项目', workRoot: 'E:/example', iconKey: 'folder' as const, colorKey: 'gray' as const }]
const projectCreateOpen = ref(false)
const projectCreateResult = ref('')
const sampleDirectoryTransport = { request: async () => ({ status: 200, headers: {}, body: new TextEncoder().encode('{"entries":[]}') }) } as unknown as LamToolsTransport
const updatePreviewOpen = ref(false)
const updatePreviewState = ref<CoreUpdateCardState>('idle')
const updatePreviewProgress = ref(45)
const updatePreviewResult = ref('')
const updatePreviewStates = [{ value: 'idle', label: '待更新' }, { value: 'downloading', label: '下载中' }, { value: 'downloaded', label: '已下载' }, { value: 'installing', label: '安装中' }, { value: 'failed', label: '失败' }]
const projectIcons = ['folder', 'code', 'idea', 'design', 'docs', 'work', 'rocket', 'sparkles'].map(value => ({ value, label: value }))
const projectColors = ['gray', 'blue', 'violet', 'pink', 'red', 'orange', 'green', 'cyan', 'sunrise', 'aurora', 'ocean', 'violet-sky', 'berry', 'ember', 'forest', 'prism'].map(value => ({ value, label: value }))
// user:“具体设计参考这个文件，尤其是气泡和玻璃效果”+(链接可直接定位到真实消息或材质展项)。
const query = ref(new URLSearchParams(globalThis.location?.search).get('q') ?? '')
const showInventory = ref(false)
const inventorySignal = ref('all')
const inventoryPreview = ref('all')
const inventorySignals = [{ value: 'all', label: '全部线索' }, ...['button', 'checkbox', 'switch', 'range', 'select', 'dialog', 'event', 'grid', 'flex', 'animation', 'reduced-motion', 'theme', 'tokens'].map(value => ({ value, label: value }))]
const inventoryPreviewOptions = [{ value: 'all', label: '全部状态' }, { value: 'available', label: '已有预览' }, { value: 'pending', label: '待接入预览' }]
// user:“收敛方式按照职能和语义整理”+(分类只从真实展项产生，新分类自动出现在筛选中)。
const categories = ['全部', ...new Set(entries.map(item => item.category))].map(value => ({ value, label: value === '组合' ? '页面与组合' : value }))
// user:“UI 请按语义整理并展示”+(可直接打开按钮分类，再用现有筛选浏览其他展项)。
const initialCategory = new URLSearchParams(globalThis.location?.search).get('category')
const category = ref(categories.find(option => option.value === initialCategory)?.value ?? '全部')
// user:“按聊天、设置、文件、工作流等实际用途再分一层”+(组合按主要用途归一组，所有组和数量由展项生成)。
const groupCounts = new Map<string, number>()
for (const item of entries) {
  if ('group' in item && item.group) groupCounts.set(item.group, (groupCounts.get(item.group) ?? 0) + 1)
}
const groupOptions = [
  { value: '全部用途', label: '全部用途' },
  ...Array.from(groupCounts, ([value, count]) => ({ value, label: `${value}（${count}）`, selectedLabel: value })),
]
const initialGroup = new URLSearchParams(globalThis.location?.search).get('group')
const compositeGroup = ref(initialGroup && groupCounts.has(initialGroup) ? initialGroup : '全部用途')

const themes = [{ value: 'dark', label: '深色' }, { value: 'light', label: '浅色' }]
const disabled = ref(false)
const theme = ref<'dark' | 'light'>('dark')
const thinking = ref('medium')
const thinkingOptions = [{ value: 'off', label: '关闭' }, { value: 'light', label: '低' }, { value: 'medium', label: '中' }, { value: 'high', label: '高' }, { value: 'xhigh', label: '极高' }, { value: 'max', label: '最高' }]
const catalogRequested = ref(false)
const catalogView = ref<'provider' | 'group'>('provider')
const showSampleModels = ref(true)
const showSampleProviders = ref(true)
const sampleProviders = [{ id: 'example-provider', name: '示例供应商', api_type: 'openai', base_url: 'https://example.invalid', has_api_key: false }]
const sampleModels = [{ id: 'example-model', provider_id: 'example-provider', model_id: 'example', display_name: '示例模型' }]
// user:“直接渲染项目真实组件……交互测试”+(目录使用纯本地示例数据，图表可交互且不会请求真实服务)
async function sampleCatalogRpc(method: string): Promise<Record<string, unknown>> {
  if (method === 'config.models.usage') {
    return { range: '7d', days: 1, totals: { calls: 1, input_tokens: 60, output_tokens: 40, cached_tokens: 0, tokens: 100, cost: 0, unpriced_tokens: 100, currency: 'USD' }, by_model: [], by_provider: [], daily: [{ date: '2026-01-01', calls: 1, input_tokens: 60, output_tokens: 40, cached_tokens: 0, tokens: 100 }], series: {}, tracking_since: '', since: '' }
  }
  return { providers: {} }
}
const actionMode = ref<'send' | 'stop' | 'resume'>('send')
// user:“按钮是否包含主输入栏内的发送/暂停/停止按钮？UI 请按语义整理并展示”+(用真实按钮演示短按和长按的不同结果)。
const actionModes = [
  { value: 'send', label: '待发送' },
  { value: 'stop', label: '运行中' },
  { value: 'resume', label: '已暂停' },
]
const composerActionCards = [
  { title: '发送', detail: '待发送时短按，开始回合。', mode: 'send' },
  { title: '暂停', detail: '运行中短按「停止运行」，保留回合。', mode: 'stop' },
  { title: '继续', detail: '已暂停时短按，接着运行。', mode: 'resume' },
  { title: '终止', detail: '运行或暂停时长按，再确认结束回合。' },
]
const composerActionResult = ref('')
const composerTerminateOpen = ref(false)
const composerActionTransitions = {
  send: { next: 'stop', result: '已发送' },
  stop: { next: 'resume', result: '已暂停' },
  resume: { next: 'stop', result: '已继续运行' },
} as const

function applySampleComposerAction(): void {
  if (disabled.value) return
  const action = composerActionTransitions[actionMode.value]
  actionMode.value = action.next
  composerActionResult.value = action.result
}

function confirmSampleComposerTermination(): void {
  composerTerminateOpen.value = false
  actionMode.value = 'send'
  composerActionResult.value = '已终止回合'
}
const directions = [{ value: 'down', label: '向下' }, { value: 'up', label: '向上' }]
const agentEditorText = ref('# 示例说明')
const agentEditorResult = ref('')
const decisionOffline = ref(false)
const decisionResult = ref('')
const sampleDecisionBase: CorePendingDecision = { partId: 'sample-approval', requestId: 'example', isQuestion: false, kindLabel: '确认', subject: '允许执行示例操作？', title: '示例确认', detail: '此示例不会执行任何操作。', facts: [{ label: '操作', value: '预览命令', tone: 'neutral', mono: true }], options: [{ id: 'approve', label: '允许', description: '继续示例', wireResponse: 'approve' }, { id: 'deny', label: '拒绝', description: '停止示例', wireResponse: 'deny' }], status: 'pending', submitting: false, canGuide: true, subAgentName: '', subAgentSessionId: '', decisionId: 'example', sequence: 1, lifecycle: 'appearing', deliveredBy: '', projectId: '' }
const sampleDecisions = computed<CorePendingDecision[]>(() => [
  { ...sampleDecisionBase, submitting: disabled.value },
  { ...sampleDecisionBase, partId: 'sample-question', requestId: 'question', decisionId: 'question', isQuestion: true, kindLabel: '提问', subject: '预览时先展示哪一项？', options: [{ id: 'first', label: '先展示方案', wireResponse: '先展示方案' }, { id: 'second', label: '先展示结果', wireResponse: '先展示结果' }], submitting: disabled.value },
])
const petEditorRequested = ref(false)
const libraryConfirmOpen = ref(false)
const libraryConfirmResult = ref('')
const libraryNameOpen = ref(false)
const libraryNameValue = ref('')
const libraryNameResult = ref('')
const libraryViewMode = ref<'grid' | 'list'>('grid')
const librarySearchExample = ref('')
const librarySearchClearExample = ref('示例')
const librarySearchItems = computed(() => ['项目设计', '会议记录', '发布计划'].filter(item => item.includes(librarySearchExample.value.trim())))
const settingsPreviewHideNav = ref(false)
const settingsPreviewSections = [{ id: 'general', label: '通用', icon: 'settings' }, { id: 'appearance', label: '界面', icon: 'palette' }]
const sampleThemeArea = ref({ stops: [{ color: '#34363c', position: 0 }, { color: '#707680', position: 100 }], angle: 180, opacity: 1, textColor: '#ffffff', fillMode: 'solid' as ThemeFillMode, glassLevel: 'off' as ThemeGlassPreference, image: '', imageFit: 'cover' as ThemeImageFit })
const sampleWorkflow = ref<WorkflowDef>({ id: 'example', name: '示例工作流', description: '', nodes: [], edges: [], input_params: [], output_port: '', exposed: false, tool_name: '', work_root: '', map: '', created_at: '', updated_at: '', triggers: [{ id: 'example-trigger', type: 'manual', name: '示例触发器', enabled: true, inputs: {} }] })
// user:“实时预览、交互测试”+(画布编辑独立示例，复制不接触系统剪贴板)。
const galleryCanvas = ref<WorkflowDef>({ ...sampleWorkflow.value, nodes: [
  { id: 'sample-start', kind: 'command', title: '读取示例', config: { command: '' }, ports: [{ name: 'out', type: 'string', direction: 'out' }], position: { x: 90, y: 80 }, parent_id: 'sample-frame' },
  { id: 'sample-finish', kind: 'command', title: '处理示例', config: { command: '' }, ports: [{ name: 'in', type: 'string', direction: 'in' }], position: { x: 430, y: 180 } },
], edges: [{ id: 'sample-edge', source: 'sample-start', source_port: 'out', target: 'sample-finish', target_port: 'in' }], canvas_elements: [{ id: 'sample-frame', kind: 'frame', title: '示例容器', text: '', position: { x: 40, y: 20 }, width: 330, height: 270 }] })
const galleryCanvasStates: Record<string, NodeStateStatus> = {}
const galleryCanvasLocked = ref(false)
const galleryCanvasUpdates = ref(0)
const galleryTreeOpened = ref('')
const galleryTreeFailure = ref(false)
// user:“交互测试”+(文件树读取和打开仅使用本地示例)。
async function galleryTreeList(_root: string, path: string) {
  if (galleryTreeFailure.value) throw new Error('示例目录读取失败')
  return path === '示例项目' ? [{ name: '示例目录', path: '示例项目/示例目录', directory: true }, { name: '说明.txt', path: '示例项目/说明.txt', directory: false }]
    : path === '示例项目/示例目录' ? [{ name: '笔记.md', path: '示例项目/示例目录/笔记.md', directory: false }] : []
}
const galleryMenuResult = ref('')
// user:“交互测试”+(菜单动作只记录本地示例结果)。
function openGalleryMenu(event: MouseEvent) {
  openContextMenu({ event, ariaLabel: '示例菜单', items: [{ label: '示例子菜单', type: 'submenu', children: [{ label: '选择示例', action: () => { galleryMenuResult.value = '示例' } }] }] })
}
function updateGalleryCanvas(value: WorkflowDef) { galleryCanvas.value = value; galleryCanvasUpdates.value++ }
const sampleWorkflowResult = ref('')
function saveSampleWorkflow(value: WorkflowDef) { sampleWorkflow.value = value; sampleWorkflowResult.value = '已保存本地示例' }
const planStatus = ref<'running' | 'failed'>('running')
const planStatusOptions = [{ value: 'running', label: '进行中' }, { value: 'failed', label: '失败' }]
const samplePlan = computed<CoreRuntimeStepGroup[]>(() => [{ id: 'sample', label: '示例计划', status: planStatus.value, steps: [{ id: 'done', title: '准备示例结果', status: 'completed' }, { id: 'current', title: '检查结果', status: planStatus.value }] }])
const computerUseStops = ref(0)
const showPingTier = ref(true)
const pingExample = computed(() => {
  const tier = { visible: showPingTier.value, radius: 110, width: 26, sectors: [{ id: 'sample-child', icon: '', label: '示例' }], slots: [1.2], span: 1.2, start: 0, hovered: '' }
  return { overlay: { x: 0, y: 0, width: window.innerWidth }, ring: { visible: true, x: 160, y: 160, hovered: '', sectors: [{ id: 'chat', kind: 'chat', icon: '', label: '对话' }, { id: 'note', kind: 'note', icon: '', label: '记录' }, { id: 'question', kind: 'question', icon: '', label: '提问' }] }, config: { ping: { radius: 75, ringWidth: 24 } }, tiers: { l2: tier, l3: { ...tier, visible: false }, expanded: '' } } as unknown as PingRuntime
})
const captureRequested = ref(false)
const captureResult = ref('')
// user:“支持分类、搜索、筛选、实时预览、交互测试、参数调整、变体对比及源码定位”+(展厅可独立切换截图发送和错误状态)。
const captureBusy = ref(false)
const captureError = ref(false)
// user:“实时预览、交互测试”+(展厅取字和翻译都使用本地示例)。
async function recognizeSampleText() {
  return {
    text: '示例文本',
    language: 'zh-Hans',
    lines: [{ text: '示例文本', bounds: [12, 12, 76, 24] as [number, number, number, number] }],
    image_width: 320,
    image_height: 180,
    max_image_dimension: 320,
    available_languages: ['zh-Hans'],
  }
}
async function translateSampleText() {
  return { text: 'Example text', model: '示例模型' }
}
const captureFrame = { width: 320, height: 180, x: 0, y: 0, scale: 1, capturedAt: 0, data: new Uint8ClampedArray(320 * 180 * 4).fill(200) }
const submissionState = ref<'preparing' | 'sending' | 'failed' | 'unknown'>('sending')
const submissionIsReplacement = ref(false)
const submissionVersionConflict = ref(false)
const submissionStates = [{ value: 'preparing', label: '准备中' }, { value: 'sending', label: '发送中' }, { value: 'failed', label: '发送失败' }, { value: 'unknown', label: '接收待确认' }]
// user:“展品里的图片请用工作区内真实存在的图片文件路径”+(图片走项目自带资源，path 仍是真实工作区路径，url 由 Vite 解析)。
const galleryMediaPreviewRequested = ref('')
function galleryMediaFile(path: string, name: string, url: string, extra: Record<string, unknown> = {}) {
  return { path, name, url, ...extra }
}
const galleryMediaWide = [galleryMediaFile('core/ui/src/assets/sunday-app-icon-dark.png', 'sunday-app-icon-dark.png', galleryMediaIconDark, { mime: 'image/png', size: 51200, width: 1600, height: 900 })]
const galleryMediaSquare = [galleryMediaFile('core/ui/src/assets/sunday-app-icon-light.png', 'sunday-app-icon-light.png', galleryMediaIconLight, { mime: 'image/png', size: 48128, width: 512, height: 512 })]
const galleryMediaThree = [
  galleryMediaFile('core/ui/src/assets/sunday-app-icon-dark.png', 'sunday-app-icon-dark.png', galleryMediaIconDark, { mime: 'image/png', size: 51200, width: 512, height: 512 }),
  galleryMediaFile('core/ui/src/assets/sunday-app-icon-light.png', 'sunday-app-icon-light.png', galleryMediaIconLight, { mime: 'image/png', size: 48128, width: 512, height: 512 }),
  galleryMediaFile('core/ui/src/pet/assets/sunday-skin.png', 'sunday-skin.png', galleryMediaSkin, { mime: 'image/png', size: 96256, width: 1024, height: 1024 }),
]
// user:“多文件……超过 5 张时末位显示 +N 遮罩”+(7 张只画 5 格，末格盖 +2)。
const galleryMediaSeven = Array.from({ length: 7 }, (_, index) => ({ ...galleryMediaThree[index % 3] }))
const galleryMediaBroken = [{ path: 'core/ui/src/assets/process-preview-missing.png', name: 'process-preview-missing.png', mime: 'image/png', error: true }]
const galleryMediaAudio = [{ path: 'core/ui/src/assets/process-preview-voice.mp3', name: 'process-preview-voice.mp3', mime: 'audio/mpeg', size: 48213 }]
const galleryMediaVideo = [{ path: 'core/ui/src/pet/assets/sunday-skin.png', name: 'clip.mp4', mime: 'video/mp4', size: 2202009, thumb: galleryMediaSkin }]
const galleryMediaPdf = [{ path: 'core/ui/src/assets/process-preview-report.pdf', name: 'process-preview-report.pdf', mime: 'application/pdf', size: 204800 }]
// user:“胶囊式（Pill）列表……点击跳转原文”+(示例域名固定 example.com，展厅里点开也只是文档域名)。
const galleryPillOpened = ref('')
const galleryPillResults = [
  { title: 'Sunday 桌面端过程行：工具结果与多媒体预览的分层', url: 'https://example.com/sunday/process-row', favicon: galleryMediaIconDark, source: 'docs' },
  { title: '胶囊列表为什么比整块卡片更适合扫读搜索结果', url: 'https://example.com/sunday/pills', source: 'notes' },
  { title: 'favicon 加载失败降级成首字母圆点', url: 'https://example.com/sunday/favicon-fallback', favicon: './no-such-favicon.ico', source: 'fallback' },
  { title: '过程行样式契约：--ms-proc-* 变量与主题语义色', url: 'https://example.com/sunday/tokens', favicon: galleryMediaIconLight, source: 'design' },
  { title: '这是一个用于验证单行截断与 title 属性是否同时生效的超长搜索结果标题，正常情况下应该被省略号截断', url: 'https://example.com/sunday/truncate', source: 'truncate' },
]
// user:“超过 N 个键值折叠成「+N」（展开可看全部）”+(展厅可切换状态与耗时，验证折叠与分钟级进位)。
const galleryKvStatus = ref<'success' | 'error' | 'running'>('success')
const galleryKvStatusOptions = [{ value: 'success', label: '成功' }, { value: 'error', label: '失败' }, { value: 'running', label: '进行中' }]
const galleryKvDuration = ref('125300')
const galleryKvDurationOptions = [{ value: '87', label: '87ms' }, { value: '1234', label: '1.2s' }, { value: '65400', label: '65s → 1m05s' }, { value: '125300', label: '125.3s → 2m05s' }]
const galleryKvDurationMs = computed(() => Number(galleryKvDuration.value) || 0)
const galleryKvFew = [{ key: 'model', value: 'sunday-v4' }, { key: 'top_k', value: '8' }, { key: 'scope', value: 'workspace' }]
const galleryKvMany = [{ key: 'query', value: '过程行多媒体预览' }, { key: 'model', value: 'sunday-v4' }, { key: 'top_k', value: '8' }, { key: 'scope', value: 'workspace' }, { key: 'lang', value: 'zh-CN' }]
const submissionRetries = ref(0)
const submissionEdits = ref(0)
const historyLoadingActive = ref(false)
const progress = ref(40)
const progressIndeterminate = ref(false)
// user:“UI 请按语义整理并展示”+(以实际动作解释四种普通按钮何时使用)。
const buttonRoles = [
  { id: 'primary', title: '主操作', action: '保存', detail: '当前区域最重要的一步。' },
  { id: 'secondary', title: '次操作', action: '取消', detail: '与主操作并列的备选。' },
  { id: 'quiet', title: '轻量操作', action: '刷新', detail: '查看、复制等辅助动作。' },
  { id: 'danger', title: '危险操作', action: '删除', detail: '会移除数据或撤销权限。' },
] as const
const lastButtonAction = ref('')
const buttonMaterial = ref(false)
const buttonSmall = ref(false)
const confirmOpen = ref(false)
const confirmHasInput = ref(true)
const confirmGuard = ref(false)
const confirmValue = ref('')
const confirmedValue = ref('')
const checkboxValue = ref(false)
const switchValue = ref(false)
const smallSwitch = ref(true)
const range = ref(50)
// user:“交互测试”+(区分滑动中的预览值和松开后提交的值)。
const rangeCommitted = ref<number | null>(null)
const rangeMax = ref(100)
const segmentedValue = ref('a')
const selectValue = ref('a')
const selectDirection = ref<'up' | 'down'>('down')
const selectWidth = ref(220)
const disableOption = ref(false)
const minRows = ref(2)
const maxRows = ref(5)
const text = ref('可以在这里输入文字')
const openSource = ref('')
const sourceCache = ref<Record<string, string>>({})
const sourceErrors = ref<Record<string, string>>({})
const sourcePending = new Set<string>()
const copiedSource = ref(''), copySourceError = ref('')
// user:“源码定位”+(统一展示项目相对路径，让开发者可直接检索和复制)。
function sourcePath(item: (typeof entries)[number]): string {
  return ('sourcePath' in item ? `core/ui/${item.sourcePath}` : `core/ui/src/components/${item.name}.vue`).replace(/^core\/ui\/\.\.\//, 'core/')
}
// user:“源码定位”+(组合预览列出每个真实组件的路径，不把子组件指向主组件)。
function sourcePaths(item: (typeof entries)[number]): string[] {
  return [...new Set([sourcePath(item), ...('alsoPreviews' in item ? item.alsoPreviews : [])])]
}
async function copySource(path: string): Promise<void> {
  try { await copyText(path); copiedSource.value = path; copySourceError.value = '' }
  catch { copiedSource.value = ''; copySourceError.value = path }
}
function toggleSource(item: (typeof entries)[number]): void {
  if (openSource.value === item.name) { openSource.value = ''; return }
  openSource.value = item.name
  if (!('loadSource' in item) || !item.loadSource || sourceCache.value[item.name] || sourcePending.has(item.name)) return
  sourcePending.add(item.name)
  delete sourceErrors.value[item.name]
  void item.loadSource().then(module => { sourceCache.value[item.name] = module.default }).catch(() => { sourceErrors.value[item.name] = '源码加载失败，请重试。' }).finally(() => { sourcePending.delete(item.name) })
}
const options = [{ value: 'a', label: '选项一' }, { value: 'b', label: '选项二' }, { value: 'c', label: '选项三' }]
const selectOptions = computed(() => options.map(option => ({ ...option, disabled: option.value === 'b' && disableOption.value })))
const safeSelectWidth = computed(() => Math.max(80, Number(selectWidth.value) || 80))
const safeMinRows = computed(() => Math.min(5, Math.max(1, Math.trunc(Number(minRows.value) || 1))))
const safeMaxRows = computed(() => Math.max(safeMinRows.value, Math.min(10, Math.trunc(Number(maxRows.value) || 1))))
// user:“支持分类、搜索、筛选、实时预览”+(组合预览中真实展示的组件也能按名称和路径检索)。
const motionExamples = new Set([
  'SundaySpinner', 'SundayProgress', 'HistoryLoadingIndicator', 'CoreSubAgentActivityIndicator',
  'CoreSendStopButton', 'CoreExecutionControls', 'MessageView', 'WorkflowNodeRuntimeDock', 'ContextMenuHost',
])
const visible = computed(() => {
  const needle = query.value.trim().toLowerCase()
  const matches = entries.filter(item => {
    const matchesMotion = category.value === '动效' && motionExamples.has(item.name)
    if (category.value !== '全部' && item.category !== category.value && !matchesMotion) return false
    const group = 'group' in item ? item.group : ''
    if (category.value === '组合' && compositeGroup.value !== '全部用途' && group !== compositeGroup.value) return false
    const relatedPaths = 'alsoPreviews' in item ? item.alsoPreviews.join(' ') : ''
    return `${item.name} ${item.category} ${group} ${item.description} ${sourcePath(item)} ${relatedPaths}`.toLowerCase().includes(needle)
  })
  if (category.value === '动效') {
    matches.sort((first, second) => Number(second.name === 'SundayMotion') - Number(first.name === 'SundayMotion'))
  }
  return matches
})
// user:“建立组件目录、使用说明与复用规范，让后续开发及 Agent 能快速检索”+(按源码线索、静态调用方和预览状态检索，索引不代表运行时完整调用关系)。
const matchedInventory = computed(() => componentInventory.filter(item => {
  const available = previewByPath.has(item.path)
  const matchesStatus = inventoryPreview.value === 'all' || (inventoryPreview.value === 'available' ? available : !available)
  const matchesSignal = inventorySignal.value === 'all' || item.signals.includes(inventorySignal.value)
  return matchesStatus && matchesSignal && `${item.name} ${item.path} ${item.signals.join(' ')} ${item.callers.join(' ')} ${item.previewCallers.join(' ')}`.toLowerCase().includes(query.value.trim().toLowerCase())
}))
const previewByPath = new Map(entries.flatMap(item => [
  ...sourcePaths(item),
].map(path => [path, item.name] as const)))
// user:“让后续开发及 Agent 能快速检索、选用和组合已有组件”+(源码目录直接跳到对应的真实预览)。
async function openInventoryPreview(path: string) {
  const name = previewByPath.get(path)
  if (!name) return
  category.value = '全部'
  query.value = name
  await nextTick()
  const heading = document.getElementById(`specimen-${name}`)
  heading?.scrollIntoView?.({ block: 'start' })
  heading?.focus({ preventScroll: true })
}
const safeMax = computed(() => Math.max(1, Number(rangeMax.value) || 1))
watch(safeMax, max => { if (range.value > max) range.value = max })

// user:“确保视觉、功能和交互不退化”+(预览浅暗主题时连同传送到 body 的菜单一起切换，并在退出后恢复原值)
const rootStyle = document.documentElement.style
const initial = Object.fromEntries(Object.keys(themeToCSSVars(SUNDAY_DARK_THEME)).map(key => [key, { value: rootStyle.getPropertyValue(key), priority: rootStyle.getPropertyPriority(key) }]))
watch(theme, value => {
  for (const [key, color] of Object.entries(themeToCSSVars(value === 'light' ? SUNDAY_LIGHT_THEME : SUNDAY_DARK_THEME))) rootStyle.setProperty(key, color)
}, { immediate: true })
onBeforeUnmount(() => {
  for (const [key, previous] of Object.entries(initial)) {
    if (previous.value) rootStyle.setProperty(key, previous.value, previous.priority)
    else rootStyle.removeProperty(key)
  }
})
</script>

<template>
  <main class="gallery">
    <header><p class="eyebrow">LAMTOOLS · UI</p><h1>组件展厅</h1><p>项目真实组件的交互预览与使用入口</p></header>
    <div class="filters">
      <label>搜索 <input v-model="query" aria-label="搜索组件" placeholder="名称、用途或分类" /></label>
      <!-- user:“建立统一的 Design Tokens 和可复用组件体系”+(展厅的分类和主题筛选也使用项目自身的共享控件) -->
      <div class="filter-control">分类 <UiSelect v-model="category" :options="categories" data-gallery-category aria-label="组件分类" :menu-min-width="120" /></div>
      <div v-if="category === '组合'" class="filter-control">用途
        <UiSelect v-model="compositeGroup" :options="groupOptions" aria-label="组合用途" :menu-min-width="168" />
      </div>
      <div class="filter-control">主题 <UiSelect :model-value="theme" :options="themes" data-gallery-theme aria-label="预览主题" :menu-min-width="120" @update:model-value="theme = $event === 'light' ? 'light' : 'dark'" /></div>
      <label><input v-model="disabled" class="sunday-checkbox" type="checkbox" aria-label="禁用支持此状态的控件" /> 禁用支持此状态的控件</label>
    </div>
    <div class="inventory-header"><p class="count">{{ visible.length }} 个交互预览</p><button type="button" class="source-button btn btn--quiet btn--sm" data-show-inventory :aria-expanded="showInventory" @click="showInventory = !showInventory">{{ showInventory ? '收起源码目录' : '搜索全部源码目录' }}</button></div>
    <section v-if="showInventory" class="inventory" aria-label="源码组件目录">
      <div class="inventory-filters"><UiSelect v-model="inventorySignal" :options="inventorySignals" aria-label="源码线索筛选" :menu-min-width="150" /><UiSelect v-model="inventoryPreview" :options="inventoryPreviewOptions" aria-label="预览状态筛选" :menu-min-width="150" /></div>
      <p>匹配 {{ matchedInventory.length }} 个源码文件；线索和引用来自静态索引，可能包括仅导出且遗漏动态入口。待接入的条目只提供定位。</p>
      <ul><li v-for="component in matchedInventory" :key="component.path" :data-inventory-path="component.path"><div><code>{{ component.path }}</code><p class="inventory-signals">{{ component.signals.join(' · ') || '无线索' }}</p><details v-if="component.callers.length || component.previewCallers.length"><summary>静态引用 {{ component.callers.length }} · 预览引用 {{ component.previewCallers.length }}</summary><div v-for="caller in component.callers" :key="caller"><code>{{ caller }}</code></div><div v-for="caller in component.previewCallers" :key="caller"><code>{{ caller }}</code>（预览）</div></details></div><div><button type="button" class="source-button btn btn--quiet btn--sm" @click="copySource(component.path)">复制路径</button><button v-if="previewByPath.has(component.path)" type="button" class="source-button btn btn--quiet btn--sm" @click="openInventoryPreview(component.path)">已有预览</button><span v-else>待接入预览</span><span v-if="copiedSource === component.path" role="status">路径已复制</span><span v-else-if="copySourceError === component.path" role="status">复制失败，请手动选择路径</span></div></li></ul>
    </section>
    <p v-if="!visible.length">没有匹配的交互预览；可调整筛选条件或搜索源码目录。</p>
    <!-- user:“实时预览”+(网络工具的整版页面使用宽预览以保留原布局)。 -->
    <section v-for="item in visible" :key="item.name" class="specimen" :class="{ 'specimen--wide': item.category === '动效' || item.category === '按钮' || item.category === '材质' || item.name === 'MessageView' || item.name === 'DirectCallView' || item.name === 'CoreSkillsEditor' || item.name === 'CoreHooksEditor' || item.name === 'StudyGraph' || item.name === 'NotesManager' || item.name.startsWith('Network') || item.name === 'MaterialsView' || item.name === 'CoreWorkspace' || item.name === 'CoreSplitPreview' || item.name === 'WorkflowCanvas' || item.name === 'CoreProjectSettings' || item.name === 'SearchShell' || item.name === 'CoreSettings' || item.name === 'CoreModelCatalog' || item.name === 'CoreLoadToolsEditor' || item.name === 'CorePluginSystemEditor' || item.name === 'CoreArrangeManager' || item.name === 'CaptureEditor' || item.name === 'CorePetEditor' || item.name === 'SettingsShell' || item.name === 'CorePendingDecisionPanel' }">
      <div><span class="category">{{ item.category === '组合' ? '页面与组合' : item.category }}<template v-if="'group' in item"> · <span data-composite-group>{{ item.group }}</span></template></span><h2 :id="`specimen-${item.name}`" tabindex="-1">{{ item.name }}</h2><p>{{ item.description }}</p><div v-for="path in sourcePaths(item)" :key="path" :data-source-path="path"><code>{{ path }}</code><button class="source-button btn btn--quiet btn--sm" type="button" @click="copySource(path)">复制源码路径</button><span v-if="copiedSource === path" role="status">路径已复制</span><span v-else-if="copySourceError === path" role="status">复制失败，请手动选择路径</span></div><div><button class="source-button btn btn--quiet btn--sm" type="button" :data-source="item.name" :aria-expanded="openSource === item.name" @click="toggleSource(item)">{{ openSource === item.name ? '收起源码' : '查看源码' }}</button></div></div>
      <!-- user:“实时预览、参数调整、变体对比”+(启用材质时提供本地主题渐变示例，不改应用主题)。 -->
      <div class="preview" :style="item.name === 'SundayButton' && buttonMaterial ? { '--theme-control-image': 'linear-gradient(135deg, var(--theme-control-solid), color-mix(in srgb, var(--theme-control-solid) 80%, var(--theme-control-text)))' } : undefined">
        <button v-if="deferredPreviewNames.has(item.name) && !query.trim() && !requestedPreviews.has(item.name)" type="button" class="btn btn--secondary" :data-load-preview="item.name" @click="requestPreview(item.name)">加载预览</button>
        <template v-else-if="item.name === 'MaterialsView'">
          <p>上传、打开、复制和删除均为本地模拟。</p><div class="library-surface loadtools-preview" style="width: 100%; height: 600px; overflow: auto"><MaterialsView project-id="sample" work-root="" :request-rpc="sampleMaterialsRpc" :transport="galleryMessageTransport" :upload-files="uploadSampleMaterial" :copy-path="async path => { galleryMaterialCopied = path }" /></div>
          <span v-if="galleryMaterialTags">本地标签：{{ galleryMaterialTags }}</span><span v-if="galleryMaterialRating !== null">本地评分：{{ galleryMaterialRating }}</span><span v-if="galleryMaterialCopied">本地复制：{{ galleryMaterialCopied }}</span>
        </template>
        <!-- user:“直接渲染项目真实组件”+(记忆和方案页面在隔离的本地数据中可交互预览)。 -->
        <div v-else-if="item.name === 'MemoryView'" class="loadtools-preview" style="width: 100%; height: 600px; overflow: auto"><MemoryView :request-rpc="sampleMemoryRpc" :client="galleryLibraryClient" platform="desktop" /></div>
        <div v-else-if="item.name === 'PlanLibraryView'" class="loadtools-preview" style="width: 100%; height: 600px; overflow: auto"><PlanLibraryView :client="galleryLibraryClient" project-id="sample" /></div>
        <template v-else-if="item.name === 'WorkflowCanvas'">
          <!-- user:“参数调整、变体对比”+(可模拟运行时画布锁定)。 -->
          <label><input v-model="galleryCanvasLocked" type="checkbox" class="sunday-checkbox" data-gallery-canvas-locked />运行时锁定</label>
          <div class="loadtools-preview" style="position: relative; width: 100%; height: 600px; overflow: hidden"><WorkflowCanvas :definition="galleryCanvas" :node-states="galleryCanvasStates" :locked="galleryCanvasLocked" isolated-clipboard @update:definition="updateGalleryCanvas" /></div>
          <!-- user:“实时预览”+(显示示例节点的位置，便于确认拖拽已同步)。 -->
          <span data-gallery-canvas-position>节点位置：{{ galleryCanvas.nodes.find(node => node.id === 'sample-finish')?.position }}</span><span>本地更新次数：<span data-gallery-canvas-updates>{{ galleryCanvasUpdates }}</span> · 连线：<span data-gallery-canvas-edges>{{ galleryCanvas.edges.length }}</span></span>
        </template>
        <WindowControls v-else-if="item.name === 'WindowControls'" show-in-preview inline />
        <SplitWorkspacePreview v-else-if="item.name === 'CoreWorkspace'" />
        <SplitFilePreview v-else-if="item.name === 'CoreSplitPreview'" />
        <LightboxPreview v-else-if="item.name === 'PreviewLightbox'" />
        <FirstRunPreview v-else-if="item.name === 'FirstRunChecklist'" />
        <NetworkHomePreview v-else-if="item.name === 'NetworkHome'" />
        <NetworkHomePreview v-else-if="item.name === 'NetworkDashboard'" view="dashboard" />
        <NetworkTransferPreview v-else-if="item.name === 'NetworkTransfer'" />
        <NetworkProxyPreview v-else-if="item.name === 'NetworkProxy'" />
        <NetworkInspectionPreview v-else-if="item.name === 'NetworkConnections'" view="connections" />
        <NetworkInspectionPreview v-else-if="item.name === 'NetworkDiagnose'" view="diagnose" />
        <NetworkSettingsPreview v-else-if="item.name === 'NetworkSettings'" view="settings" />
        <NetworkSettingsPreview v-else-if="item.name === 'NetworkSecurity'" view="security" />
        <NetworkSettingsPreview v-else-if="item.name === 'NetworkAdvanced'" view="advanced" />
        <StudyNoteTreePreview v-else-if="item.name === 'StudyNoteTree'" />
        <StudyNotesPreview v-else-if="item.name === 'NotesManager'" />
        <StudyGraphsPreview v-else-if="item.name === 'StudyGraph'" view="knowledge" />
        <StudyGraphsPreview v-else-if="item.name === 'StudyNoteRelationGraph'" view="notes" />
        <StudyMarksPreview v-else-if="item.name === 'MarksPanel'" />
        <SelectionAssistantPreview v-else-if="item.name === 'SelectionAssistant'" />
        <div v-else-if="item.name === 'CoreSkillsEditor' || item.name === 'CoreHooksEditor'" class="loadtools-preview" :style="settingsThemeVars(theme === 'light' ? SUNDAY_LIGHT_THEME : SUNDAY_DARK_THEME)"><SkillsHooksPreview :view="item.name === 'CoreSkillsEditor' ? 'skills' : 'hooks'" /></div>
        <DirectCallPreview v-else-if="item.name === 'DirectCallView'" />
        <TransferPreview v-else-if="item.name === 'TransferPanel'" mode="panel" />
        <TransferPreview v-else-if="item.name === 'SendToDeviceMenu'" mode="menu" />
        <AccountPreview v-else-if="item.name === 'AccountShell'" :theme="theme === 'light' ? SUNDAY_LIGHT_THEME : SUNDAY_DARK_THEME" />
        <SplitBrowserPreview v-else-if="item.name === 'CoreSplitBrowser'" />
        <template v-else-if="item.name === 'LibraryHomeView'">
          <div class="loadtools-preview core-app-page core-app-page--auxiliary" style="width: min(100%, 360px); height: 460px">
            <LibraryHomeView :client="galleryLibraryClient" project-id="sample" work-root="示例项目" platform="desktop" :request-rpc="(method, params) => method.startsWith('artifact.') ? sampleMaterialsRpc(method, params) : sampleMemoryRpc(method, params)" :list-files="galleryTreeList" :open-project-file="path => { galleryTreeOpened = path }" />
          </div>
          <span v-if="galleryTreeOpened">本地打开：{{ galleryTreeOpened }}</span>
        </template>
        <template v-else-if="item.name === 'CoreSplitFileTree'"><label><input v-model="galleryTreeFailure" type="checkbox" class="sunday-checkbox" />模拟目录读取失败</label><div class="loadtools-preview" style="width: 100%; height: 360px"><CoreSplitFileTree root="示例项目" :list-files="galleryTreeList" @open="galleryTreeOpened = $event.replace(/^示例项目\//, '')" /></div><span v-if="galleryTreeOpened">本地打开：{{ galleryTreeOpened }}</span></template>
        <ComposerPreview v-else-if="item.name === 'InlineFileComposer'" />
        <QueuedInputPreview v-else-if="item.name === 'CoreQueuedInputTray'" />
        <ExecutionControlsPreview v-else-if="item.name === 'CoreExecutionControls'" />
        <template v-else-if="item.name === 'ContextMenuHost'"><button type="button" class="btn btn--secondary" @click="openGalleryMenu">打开示例菜单</button><span v-if="galleryMenuResult">本地选择：{{ galleryMenuResult }}</span></template>
        <template v-else-if="item.name === 'CoreProjectSettings'">
          <div class="loadtools-preview" style="width: 100%; height: 650px"><CoreProjectSettings :project="galleryProject" :project-name-draft="galleryProject.name" :theme="theme === 'light' ? SUNDAY_LIGHT_THEME : SUNDAY_DARK_THEME" :request-rpc="async () => ({})" :agents-content="galleryProjectRules" :agents-loading="false" :agents-error="''" :project-action-loading="false" :project-action-error="''" :persist-agents="saveGalleryProjectRules" @rename-project="galleryProject = { ...galleryProject, name: $event }" @update-project-visual="updateGalleryProjectVisual" /></div>
          <span>本地项目：{{ galleryProject.name }}</span><span v-if="galleryProjectRulesSaved">本地规则已保存</span>
        </template>
        <template v-else-if="item.name === 'SearchShell'">
          <div class="loadtools-preview" style="width: 100%; height: 480px"><SearchShell :request-rpc="sampleSearchRpc" :sessions="gallerySearchSessions" :auto-focus="false" :theme="theme === 'light' ? SUNDAY_LIGHT_THEME : SUNDAY_DARK_THEME" :on-jump="() => {}" :on-open-session="id => gallerySearchResult = id" :on-open-plugins="target => gallerySearchResult = target.id || target.section" /></div>
          <span v-if="gallerySearchResult">本地打开：{{ gallerySearchResult }}</span>
        </template>
        <template v-else-if="item.name === 'SpeedChart'">
          <label><input v-model="galleryNetworkEmpty" class="sunday-checkbox" type="checkbox" data-network-chart-empty />等待采样</label>
          <div class="nx-app" style="height: auto; min-height: 0; width: 100%; padding: 12px"><SpeedChart :history="galleryNetworkEmpty ? [] : galleryNetworkHistory" :traffic="galleryNetworkEmpty ? null : { download: 3072, upload: 2048 }" /></div>
        </template>
        <template v-else-if="item.name === 'CoreSettings'">
          <div><button type="button" class="btn btn--secondary" @click="gallerySettingsSection = 'agents'">上下文</button><button type="button" class="btn btn--secondary" data-settings-preview-permissions @click="gallerySettingsSection = 'permissions'">权限</button></div>
          <div class="loadtools-preview" style="width: 100%; height: 650px"><CoreSettings :key="gallerySettingsSection" :models="[]" :providers="[]" density="standard" :theme="theme === 'light' ? SUNDAY_LIGHT_THEME : SUNDAY_DARK_THEME" :section="gallerySettingsSection" :hide-nav="true" command-shell-platform="other" :permission-preset="galleryPermissionPreset" :allow-access-outside-workdir="galleryOutsideWorkdir" :request-rpc="sampleSettingsRpc" @update-permission-preset="galleryPermissionPreset = $event" @update-allow-outside-workdir="galleryOutsideWorkdir = $event" /></div>
          <span v-if="galleryContextResult !== null">本地优先级：{{ galleryContextResult }}</span>
        </template>
        <template v-else-if="item.name === 'PluginRegionBlocks'">
          <label><input v-model="galleryRegionFail" class="sunday-checkbox" type="checkbox" data-region-fail />模拟执行失败</label>
          <div class="loadtools-preview" :style="settingsThemeVars(theme === 'light' ? SUNDAY_LIGHT_THEME : SUNDAY_DARK_THEME)"><PluginRegionBlocks :regions="galleryRegions" :request-rpc="sampleRegionRpc" /></div>
          <span v-if="galleryRegionResult">本地授权：{{ galleryRegionResult }}</span>
        </template>
        <template v-else-if="item.name === 'PluginConfigPanel'">
          <label><input v-model="galleryConfigFail" class="sunday-checkbox" type="checkbox" data-config-fail />模拟保存失败</label>
          <div class="loadtools-preview" :style="settingsThemeVars(theme === 'light' ? SUNDAY_LIGHT_THEME : SUNDAY_DARK_THEME)"><PluginConfigPanel plugin-name="sample" version="1.0" description="本地示例" :request-rpc="sampleConfigRpc" /></div>
        </template>
        <template v-else-if="item.name === 'PluginMarket'">
          <label><input v-model="galleryMarketFail" class="sunday-checkbox" type="checkbox" data-market-fail />模拟安装失败</label>
          <div class="loadtools-preview" :style="settingsThemeVars(theme === 'light' ? SUNDAY_LIGHT_THEME : SUNDAY_DARK_THEME)"><PluginMarket :key="galleryMarketVersion" :request-rpc="sampleMarketRpc" :open-repository="url => galleryMarketLink = url" /></div>
          <button type="button" class="btn btn--secondary" data-market-reset @click="resetGalleryMarket">重置示例</button>
          <span v-if="galleryMarketLink">本地链接示例：{{ galleryMarketLink }}</span>
        </template>
        <template v-else-if="item.name === 'MessageView'">
          <label><input v-model="galleryAssistantBubbles" class="sunday-checkbox" type="checkbox" />助手气泡</label>
          <label><input v-model="galleryMessageReadonly" class="sunday-checkbox" type="checkbox" data-message-readonly />只读模式</label>
          <label><input v-model="galleryMessageLive" class="sunday-checkbox" type="checkbox" data-message-live />过程运行中</label>
          <div class="chat-thread material-stage" style="width: 100%" data-gallery-bubbles><MessageView v-for="message in galleryMessages" :key="message.id" :msg="message" :transport="galleryMessageTransport" :assistant-bubble-appearance="galleryAssistantBubbles ? 'boxed' : 'plain'" :message-actions="false" :decisions-disabled="galleryMessageReadonly" @question-submit="galleryMessageResult = $event.text" /></div>
          <div class="chat-thread" style="width: 100%" data-gallery-process><MessageView :msg="galleryProcessMessage" :transport="galleryMessageTransport" :process-expanded-ids="galleryProcessExpanded" :turn-active="galleryMessageLive" @toggle-process="toggleGalleryProcess" /></div>
          <span v-if="galleryMessageResult">本地回答：{{ galleryMessageResult }}</span>
          <!-- user:“分叉/编辑 稳定性/速度 找优化点进行优化”+(可模拟拒绝替换，检查草稿有没有保留)。 -->
          <details>
            <summary>历史消息编辑</summary>
            <label><input v-model="galleryEditRefused" class="sunday-checkbox" type="checkbox" /> 模拟提交失败</label>
            <MessageView :msg="galleryEditableMessage" :transport="galleryMessageTransport" message-actions
              :read-edit-basis="galleryEditBasis" @edit-message="settleGalleryEdit" />
          </details>
        </template>
        <template v-else-if="item.name === 'WorkflowControlBar'">
          <label><input v-model="galleryWorkflowRunning" class="sunday-checkbox" type="checkbox" data-workflow-controls-running />运行中</label>
          <label><input v-model="galleryWorkflowDirty" class="sunday-checkbox" type="checkbox" />未保存</label>
          <label><input v-model="galleryWorkflowConflict" class="sunday-checkbox" type="checkbox" data-workflow-controls-conflict />版本冲突</label>
          <div class="variant"><WorkflowControlBar :running="galleryWorkflowRunning" :dirty="galleryWorkflowDirty" :conflict="galleryWorkflowConflict ? '示例冲突' : ''" :can-undo="true" :can-redo="true" @run="galleryWorkflowControlResult = 'run'" @cancel="galleryWorkflowControlResult = 'cancel'" @step="galleryWorkflowControlResult = 'step'" @save="galleryWorkflowControlResult = 'save'" @undo="galleryWorkflowControlResult = 'undo'" @redo="galleryWorkflowControlResult = 'redo'" @accept-remote="galleryWorkflowControlResult = 'accept-remote'" @keep-local="galleryWorkflowControlResult = 'keep-local'" /></div>
          <span v-if="galleryWorkflowControlResult">本地操作：{{ galleryWorkflowControlResult }}</span>
        </template>
        <template v-else-if="item.name === 'WorkflowSwitchGuard'">
          <button type="button" class="btn btn--secondary" data-workflow-guard-open @click="galleryWorkflowGuardOpen = true">打开草稿确认</button>
          <WorkflowSwitchGuard :open="galleryWorkflowGuardOpen" @choice="galleryWorkflowGuardResult = $event; galleryWorkflowGuardOpen = false" />
          <span v-if="galleryWorkflowGuardResult">本地选择：{{ galleryWorkflowGuardResult }}</span>
        </template>
        <template v-else-if="item.name === 'WorkflowQueuePanel'">
          <WorkflowQueuePanel :items="galleryQueue" :history="galleryHistory" :selected-item="galleryQueueSelected" :on-inspect="entry => galleryQueueSelected = entry" :on-clear="clearGalleryQueue" :on-cancel="entry => galleryQueue = galleryQueue.filter(item => item.queue_id !== entry.queue_id)" :on-enqueue="() => galleryQueue.push(sampleQueueItem('新示例', 'queued'))" />
          <button type="button" class="btn btn--secondary" data-workflow-queue-reset @click="resetGalleryQueue">重置示例</button>
        </template>
        <template v-else-if="item.name === 'WorkflowNodeRuntimeDock'">
          <div><button v-for="state in ['running', 'waiting', 'done', 'error'] as const" :key="state" type="button" class="btn btn--secondary btn--sm" :data-workflow-runtime-state="state" @click="galleryWorkflowState = state">{{ { running: '运行中', waiting: '等待', done: '完成', error: '失败' }[state] }}</button></div>
          <WorkflowNodeRuntimeDock node-id="example" title="示例节点" kind="script" :state="galleryWorkflowState" :detail="{ node_id: 'example', status: galleryWorkflowState, attempts: 1, error: galleryWorkflowState === 'error' ? '示例错误' : undefined }" />
        </template>
        <template v-else-if="item.name === 'AttachmentTray'">
          <AttachmentTray :attachments="galleryAttachments" :transport="galleryAttachmentTransport" @remove="galleryAttachments = galleryAttachments.filter(entry => entry.id !== $event)" @retry="retryGalleryAttachment" @preview="galleryAttachmentResult = `预览：${$event}`" @open="galleryAttachmentResult = `打开：${$event}`" />
          <button type="button" class="btn btn--secondary" data-attachment-reset @click="galleryAttachments = initialGalleryAttachments(); galleryAttachmentResult = ''">重置示例</button>
          <span v-if="galleryAttachmentResult">{{ galleryAttachmentResult }}</span>
        </template>
        <template v-else-if="item.name === 'CoreArrangeManager'">
          <button v-if="!fullAreaPreviewRequested && !query.trim()" type="button" class="btn btn--secondary" @click="fullAreaPreviewRequested = true">加载页面预览</button>
          <div v-else class="loadtools-preview"><CoreArrangeManager :request-rpc="sampleFullAreaRpc" /></div>
        </template>
        <template v-else-if="item.name === 'RightSidebarProcesses'">
          <button v-if="!processPreviewRequested && !query.trim()" type="button" class="btn btn--secondary" @click="processPreviewRequested = true">加载进程预览</button>
          <template v-else><button type="button" class="btn btn--secondary btn--sm" data-process-preview-reset @click="resetSampleProcess">重置示例</button><div class="study-sidebar-preview"><RightSidebarProcesses :key="processPreviewVersion" title="示例进程" session-id="sample" :request-rpc="sampleProcessRpc" /></div></template>
        </template>
        <template v-else-if="item.name === 'CorePluginSystemEditor'">
          <button v-if="!pluginEditorRequested && !query.trim()" type="button" class="btn btn--secondary" @click="pluginEditorRequested = true">加载插件管理预览</button>
          <div v-else class="loadtools-preview" :style="settingsThemeVars(theme === 'light' ? SUNDAY_LIGHT_THEME : SUNDAY_DARK_THEME)"><CorePluginSystemEditor :request-rpc="samplePluginRpc" :open-window="async () => false" /></div>
        </template>
        <template v-else-if="item.name === 'CoreLoadToolsEditor'">
          <button v-if="!loadToolsRequested && !query.trim()" type="button" class="btn btn--secondary" @click="loadToolsRequested = true">加载工具模式预览</button>
          <div v-else class="loadtools-preview" :style="settingsThemeVars(theme === 'light' ? SUNDAY_LIGHT_THEME : SUNDAY_DARK_THEME)"><CoreLoadToolsEditor :request-rpc="sampleToolModesRpc" /></div>
          <span v-if="loadToolsPreviewResult">{{ loadToolsPreviewResult }}</span>
        </template>
        <MotionPreview v-else-if="item.name === 'SundayMotion'" />
        <template v-else-if="item.name === 'SundaySpinner'">
          <div class="variant"><LoaderCircle class="sunday-spin sunday-spin--fast" aria-hidden="true" />快速</div>
          <div class="variant"><LoaderCircle class="sunday-spin" aria-hidden="true" />标准</div>
          <div class="variant"><LoaderCircle class="sunday-spin sunday-spin--slow" aria-hidden="true" />慢速</div>
          <div class="variant"><LoaderCircle class="sunday-spin sunday-spin--task" aria-hidden="true" />任务</div>
        </template>
        <template v-else-if="item.name === 'StudySidebar'">
          <label><input v-model="studyPreviewNotes" class="sunday-checkbox" type="checkbox" /> 显示笔记入口</label>
          <label><input v-model="studyPreviewFailure" class="sunday-checkbox" type="checkbox" data-study-preview-failure /> 模拟加载失败</label>
          <div class="study-sidebar-preview"><StudySidebar :courses="studyPreviewCourses" :active="studyPreviewActive" :notes-enabled="studyPreviewNotes" :load-children="loadStudyPreviewChildren" :open-node="openStudyPreviewNode" :select="id => { studyPreviewActive = id; studyPreviewResult = id }" /></div>
          <span data-study-preview-result>{{ studyPreviewResult }}</span>
        </template>
        <template v-else-if="item.name === 'CoreModelCatalog'">
          <button v-if="!catalogRequested && !query.trim()" class="btn btn--secondary" type="button" data-load-catalog @click="catalogRequested = true">加载模型目录预览</button>
          <template v-else>
            <label><input v-model="showSampleProviders" class="sunday-checkbox" type="checkbox" aria-label="显示示例供应商" /> 显示供应商</label>
            <label><input v-model="showSampleModels" class="sunday-checkbox" type="checkbox" aria-label="显示示例模型" /> 显示模型</label>
            <CoreModelCatalog :models="showSampleModels ? sampleModels : []" :providers="showSampleProviders ? sampleProviders : []" :request-rpc="sampleCatalogRpc" :catalog-view="catalogView" @update:catalog-view="catalogView = $event" />
          </template>
        </template>
        <div v-else-if="item.name === 'CoreSendStopButton'" class="action-specimen" data-composer-actions>
          <ul class="action-grid" aria-label="主输入栏按钮语义">
            <li v-for="action in composerActionCards" :key="action.title" :data-current="action.mode === actionMode || undefined">
              <strong>{{ action.title }}</strong>
              <p>{{ action.detail }}</p>
            </li>
          </ul>
          <div class="action-toolbar">
            <div class="filter-control">示例状态
              <UiSelect
                :model-value="actionMode"
                :options="actionModes"
                data-gallery-action-mode
                aria-label="动作状态"
                :menu-min-width="120"
                @update:model-value="actionMode = $event === 'stop' || $event === 'resume' ? $event : 'send'"
              />
            </div>
            <span v-if="composerActionResult" role="status">示例操作：{{ composerActionResult }}</span>
          </div>
          <form class="composer-preview" @submit.prevent="applySampleComposerAction">
            <span>{{ actionModes.find(mode => mode.value === actionMode)?.label }}</span>
            <CoreSendStopButton
              :action-mode="actionMode"
              :disabled="disabled"
              :hold-enabled="actionMode !== 'send'"
              @terminate="composerTerminateOpen = true"
            />
          </form>
          <CoreConfirmDialog
            :open="composerTerminateOpen"
            title="终止这个回合？"
            detail="示例回合将结束，无法再继续。"
            confirm-label="终止"
            @cancel="composerTerminateOpen = false"
            @confirm="confirmSampleComposerTermination"
          />
        </div>
        <div v-else-if="item.name === 'OpticalGlass'" class="material-stage glass-specimens">
          <div class="optical-glass"><strong>承载面板</strong><span>保留背景层次，适合较大的浮动区域。</span></div>
          <div class="optical-glass optical-glass--low-trans"><strong>浮层菜单</strong><span>减弱背后文字，便于选择和操作。</span></div>
          <div class="optical-glass optical-glass--reading"><strong>阅读面板</strong><span>底色更稳，正文始终清晰。</span></div>
        </div>
        <template v-else-if="item.name === 'CoreMessageSurface'">
          <div class="material-stage surface-specimens">
            <CoreMessageSurface class="surface-demo message-bubble--user" shape="card"><strong>卡片 · 玻璃</strong><span>默认形状，底色跟随用户淡粉。</span></CoreMessageSurface>
            <CoreMessageSurface class="surface-demo message-bubble--assistant" shape="capsule"><strong>胶囊 · 玻璃</strong><span>短句两端全圆，底色跟随助手淡蓝。</span></CoreMessageSurface>
            <CoreMessageSurface class="surface-demo message-bubble--assistant" shape="card" :glass="false"><strong>卡片 · 实色</strong><span>关掉玻璃后不采样背景，圆角与间距不变。</span></CoreMessageSurface>
            <CoreMessageSurface class="surface-demo message-bubble--user" shape="card" fill="rgb(255 215 106 / 45%)"><strong>自定义填充</strong><span>fill 可传任意颜色，渐变走 --message-surface-fill-image。</span></CoreMessageSurface>
          </div>
        </template>
        <template v-else-if="item.name === 'CoreBubbleAppearance'">
          <div class="bubble-appearance-preview"><CoreBubbleAppearance :request-rpc="bubbleAppearanceRpc" /></div>
        </template>
        <template v-else-if="item.name === 'DesignTokens'">
          <div class="token-list">
            <div v-for="token in colorTokens" :key="token" class="token-row"><span class="token-swatch" :style="{ background: `var(${token})` }" /><code>{{ token }}</code><span class="token-value" :data-token-value="token">{{ tokenValue(token) }}</span></div>
            <div v-for="token in scaleTokens" :key="token" class="token-row"><code>{{ token }}</code><span v-if="token.startsWith('--radius')" class="token-radius" :style="{ borderRadius: `var(${token})` }" /><span v-else class="token-scale" :style="{ width: `var(${token})` }" /><span class="token-value" :data-token-value="token">{{ tokenValue(token) }}</span></div>
            <div v-for="token in otherTokens" :key="token" class="token-row"><code>{{ token }}</code><span class="token-value" :data-token-value="token">{{ tokenValue(token) }}</span></div>
            <small>主题区域值：src/helpers/theme.ts</small>
          </div>
        </template>
        <template v-else-if="item.name === 'ThinkingIntensitySlider'">
          <div class="thinking-preview"><ThinkingIntensitySlider v-model="thinking" :options="thinkingOptions" label="思考强度" :disabled="disabled" /></div>
          <span>当前：{{ thinkingOptions.find(option => option.value === thinking)?.label }}</span>
        </template>
        <template v-else-if="item.name === 'PingRing'">
          <label><input v-model="showPingTier" class="sunday-checkbox" type="checkbox" aria-label="显示子环" /> 显示子环</label>
          <div class="ping-ring-preview"><PingRing :ping="pingExample" /></div>
        </template>
        <template v-else-if="item.name === 'CoreUpdateCard'">
          <div class="filter-control">状态 <UiSelect :model-value="updatePreviewState" :options="updatePreviewStates" aria-label="更新预览状态" @update:model-value="updatePreviewState = $event as CoreUpdateCardState" /></div>
          <SundayRange v-model="updatePreviewProgress" :min="0" :max="100" label="示例下载进度" suffix="%" />
          <button class="btn btn--secondary" type="button" data-update-preview-open @click="updatePreviewOpen = true">打开更新示例</button>
          <CoreUpdateCard v-if="updatePreviewOpen" current-version="1.0" latest-version="2.0" notes="这只是本地预览，不会下载或安装。" :state="updatePreviewState" :received="updatePreviewProgress" :total="100" :error="updatePreviewState === 'failed' ? '示例下载失败' : ''" @confirm="updatePreviewState = 'downloading'; updatePreviewResult = '开始模拟下载'" @cancel="updatePreviewResult = '已取消模拟下载'" @closed="updatePreviewOpen = false">
            <template #preview-actions><button type="button" class="btn btn--ghost" data-update-preview-exit @click="updatePreviewOpen = false">结束预览</button></template>
          </CoreUpdateCard>
          <span v-if="updatePreviewResult" data-update-preview-result>{{ updatePreviewResult }}</span>
        </template>
        <template v-else-if="item.name === 'CoreProjectCreate'">
          <button class="btn btn--secondary" type="button" data-project-create-preview-open @click="projectCreateOpen = true">创建示例项目</button>
          <CoreProjectCreate v-if="projectCreateOpen" :transport="sampleDirectoryTransport" :use-native-picker="false" @cancel="projectCreateOpen = false" @submit="projectCreateResult = JSON.stringify($event); projectCreateOpen = false" />
          <span v-if="projectCreateResult" data-project-create-preview-result>本地示例：{{ projectCreateResult }}</span>
        </template>
        <template v-else-if="item.name === 'CoreProjectPicker'">
          <button class="btn btn--secondary" type="button" data-project-picker-preview-open @click="projectPickerOpen = true">选择示例项目</button>
          <CoreProjectPicker v-if="projectPickerOpen" :projects="sampleProjects" @cancel="projectPickerOpen = false" @select="projectPickerResult = $event; projectPickerOpen = false" />
          <span v-if="projectPickerResult" data-project-picker-preview-result>本地示例：{{ projectPickerResult }}</span>
        </template>
        <template v-else-if="item.name === 'ProjectVisualPicker'">
          <ProjectVisualPicker v-model:icon-key="pickerIcon" v-model:color-key="pickerColor" :disabled="disabled" />
        </template>
        <template v-else-if="item.name === 'ThemeAreaEditor'">
          <div class="theme-area-preview" :style="settingsThemeVars(theme === 'light' ? SUNDAY_LIGHT_THEME : SUNDAY_DARK_THEME)">
            <ThemeAreaEditor v-model:stops="sampleThemeArea.stops" v-model:angle="sampleThemeArea.angle" v-model:opacity="sampleThemeArea.opacity" v-model:text-color="sampleThemeArea.textColor" v-model:fill-mode="sampleThemeArea.fillMode" v-model:glass-level="sampleThemeArea.glassLevel" v-model:image="sampleThemeArea.image" v-model:image-fit="sampleThemeArea.imageFit" label="示例区域" show-opacity @add-stop="sampleThemeArea.stops.push({ color: '#888888', position: 50 })" @remove-stop="sampleThemeArea.stops.splice($event, 1)" @sort-stops="sampleThemeArea.stops.sort((a, b) => a.position - b.position)" />
          </div>
        </template>
        <template v-else-if="item.name === 'CorePendingDecisionPanel'">
          <label><input v-model="decisionOffline" class="sunday-checkbox" type="checkbox" aria-label="模拟通道断开" /> 模拟通道断开</label>
          <div class="decision-preview"><CorePendingDecisionPanel :items="sampleDecisions" :channel-ready="!decisionOffline" @decision-select="decisionResult = $event.response" /></div>
          <span v-if="decisionResult" data-decision-gallery-result>本地示例：{{ decisionResult }}</span>
        </template>
        <template v-else-if="item.name === 'SettingsShell'">
          <label><input v-model="settingsPreviewHideNav" class="sunday-checkbox" type="checkbox" aria-label="隐藏预览导航" /> 隐藏导航</label>
          <div class="settings-shell-preview">
            <SettingsShell :sections="settingsPreviewSections" :hide-nav="settingsPreviewHideNav" :settings-theme-style="settingsThemeVars(theme === 'light' ? SUNDAY_LIGHT_THEME : SUNDAY_DARK_THEME)">
              <template #default="{ activeSection }"><div class="settings-panel"><h3>{{ activeSection === 'appearance' ? '界面示例' : '通用示例' }}</h3><p>这是独立的本地预览内容。</p></div></template>
            </SettingsShell>
          </div>
        </template>
        <template v-else-if="item.name === 'CorePetEditor'">
          <button v-if="!petEditorRequested && !query.trim()" class="btn btn--secondary" type="button" @click="petEditorRequested = true">加载桌宠设置预览</button>
          <div v-else class="pet-settings-preview" :style="settingsThemeVars(theme === 'light' ? SUNDAY_LIGHT_THEME : SUNDAY_DARK_THEME)">
            <CorePetEditor preview />
          </div>
        </template>
        <TrayPreview v-else-if="item.name === 'TrayPanel'" />
        <template v-else-if="item.name === 'CaptureEditor'">
          <button v-if="!captureRequested" type="button" class="btn btn--secondary" data-load-capture @click="captureRequested = true">加载截图编辑预览</button>
          <template v-else>
            <label><input v-model="captureBusy" type="checkbox" class="sunday-checkbox" />模拟截图发送中</label>
            <label><input v-model="captureError" type="checkbox" class="sunday-checkbox" />模拟截图错误</label>
            <CaptureEditor :frame="captureFrame" :recognize-text="recognizeSampleText" :translate="translateSampleText" :busy="captureBusy" :error="captureError ? '示例发送失败' : ''" sandbox @cancel="captureRequested = false" @send="captureResult = `本地示例：${Math.round($event.meta.width)}×${Math.round($event.meta.height)}`" />
            <span v-if="captureResult" data-capture-result>{{ captureResult }}</span>
          </template>
        </template>
        <template v-else-if="item.name === 'LibrarySearchField'">
          <div class="library-surface"><LibrarySearchField v-model="librarySearchExample" label="搜索本地示例" /></div>
          <!-- user:“通过参数、变体和组合保留必要差异”+(展示成果库使用的附加清除操作)。 -->
          <div class="library-surface"><LibrarySearchField v-model="librarySearchClearExample" label="可清除的搜索"><button v-if="librarySearchClearExample" type="button" class="btn btn--ghost btn--sm" @click="librarySearchClearExample = ''">清除</button></LibrarySearchField></div>
          <span v-for="label in librarySearchItems" :key="label" data-library-search-example>{{ label }}</span>
          <span v-if="!librarySearchItems.length">没有匹配的示例</span>
        </template>
        <template v-else-if="item.name === 'LibraryViewToggle'">
          <div class="library-surface"><LibraryViewToggle v-model="libraryViewMode" /></div>
          <span data-library-view-result>{{ libraryViewMode === 'grid' ? '网格' : '列表' }}视图</span>
        </template>
        <template v-else-if="item.name === 'LibraryNameDialog'">
          <div class="library-surface">
            <button class="btn btn--secondary" type="button" data-library-name-open @click="libraryNameOpen = true">打开命名表单</button>
            <LibraryNameDialog v-if="libraryNameOpen" v-model="libraryNameValue" title="新建文件夹" field-label="文件夹名称" submit-label="创建" :busy="disabled" @cancel="libraryNameOpen = false" @submit="libraryNameOpen = false; libraryNameResult = libraryNameValue" />
          </div>
          <span v-if="libraryNameResult" data-library-name-result>本地示例：{{ libraryNameResult }}</span>
        </template>
        <template v-else-if="item.name === 'LibraryConfirmDialog'">
          <div class="library-surface">
            <button class="btn btn--secondary" type="button" data-library-confirm-open @click="libraryConfirmOpen = true">打开删除确认</button>
            <LibraryConfirmDialog :open="libraryConfirmOpen" title="删除示例" confirm-label="删除" @cancel="libraryConfirmOpen = false; libraryConfirmResult = '已取消'" @confirm="libraryConfirmOpen = false; libraryConfirmResult = '已确认（仅为示例）'">示例内容将被删除，且无法恢复。</LibraryConfirmDialog>
          </div>
          <span v-if="libraryConfirmResult" data-library-confirm-result>{{ libraryConfirmResult }}</span>
        </template>
        <template v-else-if="item.name === 'WorkflowTriggersPanel'">
          <WorkflowTriggersPanel :workflow-definition="sampleWorkflow" :activation-busy="disabled" :on-update-definition="saveSampleWorkflow" />
          <span v-if="sampleWorkflowResult" data-trigger-gallery-result>{{ sampleWorkflowResult }}</span>
        </template>
        <template v-else-if="item.name === 'CoreAgentsEditor'">
          <CoreAgentsEditor :content="agentEditorText" :loading="disabled" @save="agentEditorText = $event; agentEditorResult = $event" @close="agentEditorResult = '已取消'" />
          <span v-if="agentEditorResult" data-agent-editor-result>{{ agentEditorResult }}</span>
        </template>
        <template v-else-if="item.name === 'RuntimeChecklistCard'">
          <div class="filter-control">状态 <UiSelect :model-value="planStatus" :options="planStatusOptions" data-gallery-plan-status aria-label="计划状态" @update:model-value="planStatus = $event === 'failed' ? 'failed' : 'running'" /></div>
          <RuntimeChecklistCard :step-groups="samplePlan" />
          <!-- user:“变体对比”+(以相同示例对照计划卡和右侧栏的实际步骤状态)。 -->
          <div class="study-sidebar-preview"><RightSidebarChecklist :step-groups="samplePlan" /></div>
        </template>
        <template v-else-if="item.name === 'ComputerUseCapsule'">
          <div class="computer-use-preview"><ComputerUseCapsule @stop="computerUseStops++" /></div>
          <span>结束 {{ computerUseStops }} 次</span>
        </template>
        <template v-else-if="item.name === 'CoreSystemEventRow'">
          <CoreSystemEventRow :event="{ kind: 'member_wake', text: '子代理已完成', entries: [{ name: '示例代理', state: '已完成', message: '示例结果' }] }" />
          <CoreSystemEventRow :event="{ kind: 'memory_resume', text: '记忆续跑示例', entries: [] }" />
        </template>
        <template v-else-if="item.name === 'CoreSubmissionStatus'">
          <div class="filter-control">状态 <UiSelect :model-value="submissionState" :options="submissionStates" data-gallery-submission-state aria-label="发送状态" @update:model-value="submissionState = $event === 'preparing' || $event === 'failed' || $event === 'unknown' ? $event : 'sending'" /></div>
          <!-- user:“全做”+(展厅也能验证历史替换失败时保留原操作重试)。 -->
          <label><input v-model="submissionIsReplacement" class="sunday-checkbox" type="checkbox" /> 编辑历史消息</label>
          <!-- user:“全修”+(展厅可看历史版本冲突，验证这时不提供旧稿重试)。 -->
          <label v-if="submissionIsReplacement && submissionState === 'failed'"><input v-model="submissionVersionConflict" class="sunday-checkbox" type="checkbox" /> 历史版本冲突</label>
          <CoreSubmissionStatus :submissions="[{ id: 'sample', threadId: 'sample', text: '示例消息', attachments: [], state: submissionState, error: submissionState === 'failed' ? '示例错误' : '', replaceTurnId: submissionIsReplacement ? 'sample-turn' : undefined, needsReopen: submissionIsReplacement && submissionState === 'failed' && submissionVersionConflict }]" :can-edit="true" :busy="disabled" @retry="submissionRetries++" @edit="submissionEdits++" />
          <span>重试 {{ submissionRetries }} 次 · 编辑 {{ submissionEdits }} 次</span>
        </template>
        <template v-else-if="item.name === 'CoreSubAgentActivityIndicator'">
          <div class="variant">运行中 <CoreSubAgentActivityIndicator active :names="['示例']" /></div>
          <div class="variant">未运行（保留占位）<CoreSubAgentActivityIndicator /></div>
        </template>
        <template v-else-if="item.name === 'HistoryLoadingIndicator'">
          <label><input v-model="historyLoadingActive" class="sunday-checkbox" type="checkbox" aria-label="显示加载状态" /> 显示加载状态</label>
          <HistoryLoadingIndicator :active="historyLoadingActive" />
        </template>
        <template v-else-if="item.name === 'SundayProgress'">
          <SundayRange v-model="progress" label="进度值" suffix="%" />
          <label><input v-model="progressIndeterminate" class="sunday-checkbox" type="checkbox" aria-label="模拟未知总量" /> 模拟未知总量</label>
          <SundayProgress :value="progress" :indeterminate="progressIndeterminate" :value-text="progressIndeterminate ? '处理中' : ''" label="示例进度" />
        </template>
        <div v-else-if="item.name === 'SundayButton'" class="action-specimen">
          <div class="action-toolbar">
            <label><input v-model="buttonSmall" class="sunday-checkbox" type="checkbox" aria-label="紧凑尺寸" /> 紧凑尺寸</label>
            <label><input v-model="buttonMaterial" class="sunday-checkbox" type="checkbox" aria-label="主题材质" /> 主题材质</label>
            <span v-if="lastButtonAction" role="status">示例操作：{{ lastButtonAction }}</span>
          </div>
          <ul class="action-grid" aria-label="普通按钮语义">
            <li v-for="role in buttonRoles" :key="role.id">
              <strong>{{ role.title }}</strong>
              <p>{{ role.detail }}</p>
              <button
                type="button"
                class="btn"
                :class="['btn--' + role.id, { 'btn--material': role.id === 'primary' && buttonMaterial, 'btn--sm': buttonSmall }]"
                :data-button-role="role.id"
                :disabled="disabled"
                @click="lastButtonAction = role.action"
              >{{ role.action }}</button>
            </li>
          </ul>
        </div>
        <template v-else-if="item.name === 'CoreConfirmDialog'">
          <!-- user:“参数调整、交互测试”+(可检查输入和确认不可用时的键盘焦点)。 -->
          <label><input v-model="confirmHasInput" class="sunday-checkbox" type="checkbox" aria-label="包含输入框" /> 包含输入框</label>
          <label><input v-model="confirmGuard" class="sunday-checkbox" type="checkbox" aria-label="禁止确认" /> 禁止确认</label>
          <button type="button" class="btn btn--secondary" data-open-confirm @click="confirmOpen = true">打开确认框</button>
          <span v-if="confirmedValue">已确认：{{ confirmedValue }}</span>
          <CoreConfirmDialog v-model:input-value="confirmValue" :open="confirmOpen" title="输入示例名称" :input="confirmHasInput" :confirm-disabled="confirmGuard" @cancel="confirmOpen = false" @confirm="confirmedValue = confirmValue; confirmOpen = false" />
        </template>
        <template v-else-if="item.name === 'SundayCheckbox'"><label>可操作 <input v-model="checkboxValue" class="sunday-checkbox" type="checkbox" aria-label="示例复选框" :disabled="disabled" /></label><label>禁用 <input class="sunday-checkbox" type="checkbox" checked disabled /></label></template>
        <template v-else-if="item.name === 'SundaySwitch'"><div class="variant">标准 <SundaySwitch v-model="switchValue" label="标准开关" :disabled="disabled" /></div><div class="variant">小尺寸 <SundaySwitch v-model="smallSwitch" label="小尺寸开关" size="sm" :disabled="disabled" /></div></template>
        <template v-else-if="item.name === 'SundayRange'"><label>最大值 <input v-model.number="rangeMax" aria-label="滑条最大值" type="number" min="1" /></label><SundayRange v-model="range" label="数值" suffix="%" :max="safeMax" :disabled="disabled" @change="rangeCommitted = $event" /><span v-if="rangeCommitted !== null">已提交：{{ rangeCommitted }}</span></template>
        <template v-else-if="item.name === 'SundaySegmented'">
          <!-- user:“交互测试、参数调整”+(可模拟选项变化后原值缺失并用键盘重新选择)。 -->
          <button type="button" class="btn btn--secondary btn--sm" @click="segmentedValue = 'missing'">模拟选项缺失</button>
          <SundaySegmented v-model="segmentedValue" label="示例选项" :options="options" />
        </template>
        <template v-else-if="item.name === 'UiSelect'">
          <div class="filter-control">菜单方向 <UiSelect :model-value="selectDirection" :options="directions" data-gallery-direction aria-label="菜单方向" :menu-min-width="120" @update:model-value="selectDirection = $event === 'up' ? 'up' : 'down'" /></div>
          <label>菜单宽度 <input v-model.number="selectWidth" type="number" min="80" aria-label="菜单宽度" /></label>
          <label><input v-model="disableOption" class="sunday-checkbox" type="checkbox" aria-label="禁用第二项" />禁用第二项</label>
          <UiSelect v-model="selectValue" data-select-preview aria-label="示例选项" :options="selectOptions" :direction="selectDirection" :menu-width="safeSelectWidth" :disabled="disabled" />
        </template>
        <template v-else-if="item.name === 'ProjectVisualIcon'">
          <div class="filter-control">图案 <UiSelect v-model="projectIcon" :options="projectIcons" data-gallery-project-icon aria-label="项目图案" /></div>
          <div class="filter-control">颜色 <UiSelect v-model="projectColor" :options="projectColors" data-gallery-project-color aria-label="项目颜色" /></div>
          <div class="variant"><ProjectVisualIcon :icon-key="projectIcon" :color-key="projectColor" :size="32" :icon-size="20" /> 图标</div>
          <div class="variant"><ProjectVisualIcon :icon-key="projectIcon" :color-key="projectColor" :size="32" swatch /> 色块</div>
        </template>
        <template v-else-if="item.name === 'AutoTextarea'">
          <label>最少行数 <input v-model.number="minRows" type="number" min="1" max="5" aria-label="最少行数" /></label>
          <!-- user:“参数调整、变体对比”+(可调整输入框的最大行数并验证滚动边界)。 -->
          <label>最多行数 <input v-model.number="maxRows" type="number" min="1" max="10" aria-label="最多行数" /></label>
          <AutoTextarea v-model="text" :min-rows="safeMinRows" :max-rows="safeMaxRows" aria-label="文本示例" />
        </template>
        <!-- user:“单文件：高度固定 80~120px（取 96px），宽度按原图比例自适应，最大不超过容器宽度 60%”+
             “多文件：横向可滑动缩略图轨，超过 5 张时末位显示 +N 遮罩”+
             “文件损坏或加载超时（3s）平滑降级成对应格式的文件类型徽章卡片”+
             (展厅逐态对照：比例、轨道、+N、坏图降级、音频波形、视频首帧、PDF 徽章)。 -->
        <template v-else-if="item.name === 'ProcessMediaPreview'">
          <div class="variant"><span>单图 16:9</span><ProcessMediaPreview :files="galleryMediaWide" @preview="galleryMediaPreviewRequested = $event.name || ''" /></div>
          <div class="variant"><span>单图 1:1</span><ProcessMediaPreview :files="galleryMediaSquare" @preview="galleryMediaPreviewRequested = $event.name || ''" /></div>
          <div class="variant"><span>多图 3 张</span><ProcessMediaPreview :files="galleryMediaThree" @preview="galleryMediaPreviewRequested = $event.name || ''" /></div>
          <div class="variant"><span>多图 7 张（+2 遮罩）</span><ProcessMediaPreview :files="galleryMediaSeven" @preview="galleryMediaPreviewRequested = $event.name || ''" /></div>
          <div class="variant"><span>坏图降级徽章</span><ProcessMediaPreview :files="galleryMediaBroken" @preview="galleryMediaPreviewRequested = $event.name || ''" /></div>
          <div class="variant"><span>音频波形占位</span><ProcessMediaPreview :files="galleryMediaAudio" @preview="galleryMediaPreviewRequested = $event.name || ''" /></div>
          <div class="variant"><span>视频首帧</span><ProcessMediaPreview :files="galleryMediaVideo" @preview="galleryMediaPreviewRequested = $event.name || ''" /></div>
          <div class="variant"><span>PDF 无缩略图 → 徽章</span><ProcessMediaPreview :files="galleryMediaPdf" @preview="galleryMediaPreviewRequested = $event.name || ''" /></div>
          <span>点击只抛 preview 事件，灯箱由消息视图承接。</span>
          <span v-if="galleryMediaPreviewRequested" data-gallery-media-preview-result>已请求预览：{{ galleryMediaPreviewRequested }}</span>
        </template>
        <!-- user:“胶囊式（Pill）列表：横向流式排列多个结果胶囊（Favicon + 截断标题），点击跳转原文”+
             “favicon 加载失败降级成首字母圆点”+(5 条结果覆盖有站标、无站标、站标取不到与超长标题截断)。 -->
        <template v-else-if="item.name === 'ProcessResultPills'">
          <ProcessResultPills :results="galleryPillResults" @open="galleryPillOpened = $event.title" />
          <span>第 2、5 条没有 favicon，第 3 条 favicon 取不到：三种情况都降级成首字母圆点；第 5 条标题超长，单行截断并保留 title 全文。</span>
          <span v-if="galleryPillOpened" data-gallery-pill-result>已点击：{{ galleryPillOpened }}</span>
        </template>
        <!-- user:“超过 N 个键值折叠成「+N」（展开可看全部）”+
             “状态徽章（成功/耗时）”+(可切换三种状态与四档耗时，验证折叠与分钟级进位)。 -->
        <template v-else-if="item.name === 'ProcessKvPill'">
          <div class="filter-control">状态 <UiSelect :model-value="galleryKvStatus" :options="galleryKvStatusOptions" data-gallery-kv-status aria-label="键值状态" :menu-min-width="120" @update:model-value="galleryKvStatus = $event === 'error' || $event === 'running' ? $event : 'success'" /></div>
          <div class="filter-control">耗时 <UiSelect v-model="galleryKvDuration" :options="galleryKvDurationOptions" data-gallery-kv-duration aria-label="键值耗时" :menu-min-width="150" /></div>
          <div class="variant"><span>3 条以内</span><ProcessKvPill :entries="galleryKvFew" :status="galleryKvStatus" :duration-ms="galleryKvDurationMs" /></div>
          <div class="variant"><span>超过 3 条折叠 +2</span><ProcessKvPill :entries="galleryKvMany" :status="galleryKvStatus" :duration-ms="galleryKvDurationMs" /></div>
        </template>
        <template v-else><div class="variant"><FileTypeBadge name="photo.png" />图片</div><div class="variant"><FileTypeBadge name="report.pdf" />PDF</div><div class="variant"><FileTypeBadge name="report.pdf" failed />失败</div></template>
      </div>
      <pre v-if="openSource === item.name" class="source" :data-source-content="item.name"><code>{{ item.source || sourceCache[item.name] || sourceErrors[item.name] || '正在加载源码…' }}</code></pre>
    </section>
    <!-- user:“交互测试”+(预览中的真实页面复用应用的菜单承载器)。 -->
    <ContextMenuHost />
  </main>
</template>
<style scoped>
.gallery { max-width: 1080px; margin: auto; padding: var(--space-6); color: var(--theme-main-text); font-family: var(--font); }
header p, .specimen p, .count { color: color-mix(in srgb, var(--theme-main-text) 65%, transparent); }
h1 { margin: var(--space-2) 0; font-size: 28px; } h2 { font-size: 17px; margin: var(--space-2) 0; }
.eyebrow, .category { font-size: 12px; letter-spacing: .08em; }
.filters { display: flex; gap: var(--space-4); align-items: end; flex-wrap: wrap; margin-top: var(--space-6); }
.filters label, .filter-control, .preview label { display: flex; gap: var(--space-2); align-items: center; }
input:not([type=checkbox]), select { padding: var(--space-2); border-radius: var(--radius-sm); color: var(--theme-composer-text); background: var(--theme-composer-background); border: 1px solid var(--theme-main-border); }
.filter-control :deep(.ui-select) { width: 110px; }
input[type=number] { width: 80px; }
.specimen { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-4); padding: var(--space-4); margin-bottom: var(--space-3); border: 1px solid var(--theme-main-border); border-radius: var(--radius); background: var(--theme-main-soft-background); }
.specimen--wide .preview { grid-column: 1 / -1; min-width: 0; }
.specimen--wide .mc { width: 100%; }
/* user:“确保视觉、功能和交互不退化”+(展厅使用与设置页一致的卡片主题变量)。 */
.pet-settings-preview { width: 100%; --text: var(--theme-main-text); }
.settings-shell-preview { width: 100%; height: 280px; min-width: 0; }
.loadtools-preview { width: 100%; min-width: 0; }
.theme-area-preview { width: 100%; min-width: 0; --text: var(--theme-main-text); }
.decision-preview { width: 100%; padding: var(--space-3); border-radius: var(--radius); background: var(--theme-composer-background); }
.specimen p { margin: var(--space-2) 0; } code { font-family: var(--font-mono); font-size: 12px; overflow-wrap: anywhere; }
.inventory-header { display: flex; gap: var(--space-4); align-items: center; justify-content: space-between; }
.inventory { padding: var(--space-3); margin-bottom: var(--space-3); background: var(--theme-main-soft-background); border: 1px solid var(--theme-main-border); border-radius: var(--radius); }
.inventory-filters { display: flex; gap: var(--space-2); }
.inventory-filters :deep(.ui-select) { width: 150px; }
.inventory-signals { margin: var(--space-1) 0; color: color-mix(in srgb, var(--theme-main-text) 65%, transparent); font-size: 11px; }
.inventory details { font-size: 12px; color: color-mix(in srgb, var(--theme-main-text) 70%, transparent); }
.inventory summary { cursor: pointer; }
.inventory ul { max-height: 320px; overflow: auto; list-style: none; margin: 0; padding: 0; }
.inventory li { display: flex; justify-content: space-between; gap: var(--space-3); padding: var(--space-1); }
.inventory li code { overflow-wrap: anywhere; } .inventory li span { flex: none; color: color-mix(in srgb, var(--theme-main-text) 65%, transparent); }
[data-source-path] code { overflow-wrap: anywhere; }
.source-button { margin-top: var(--space-1); }
.source { grid-column: 1 / -1; max-height: 400px; overflow: auto; white-space: pre; background: var(--theme-main-sunken-background); padding: var(--space-3); }
.preview { display: flex; flex-wrap: wrap; gap: var(--space-4); align-items: center; padding: var(--space-4); background: var(--theme-main-background); border-radius: var(--radius-sm); }
/* user:“UI 请按语义整理并展示”+(用并列的用途和示例按钮建立可比较的层级)。 */
.material-stage {
  border-radius: var(--radius);
  padding: var(--space-3);
  background:
    radial-gradient(ellipse at 10% 20%, color-mix(in srgb, var(--message-bubble-assistant-color) 25%, transparent), transparent 60%),
    radial-gradient(ellipse at 90% 80%, color-mix(in srgb, var(--message-bubble-user-color) 25%, transparent), transparent 60%),
    var(--theme-main-sunken-background);
}
.glass-specimens { width: 100%; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-3); }
.glass-specimens > div { position: relative; width: auto; display: grid; align-content: start; gap: var(--space-2); padding: var(--space-3); border-radius: var(--radius); }
.glass-specimens span { font-size: 12px; }
.surface-specimens { width: 100%; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); }
.surface-demo { display: grid; gap: 2px; font-size: 13px; }
.surface-demo span { font-size: 12px; color: color-mix(in srgb, var(--theme-main-text) 62%, transparent); }
.bubble-appearance-preview { width: min(560px, 100%); }
.action-specimen { display: grid; gap: var(--space-3); width: 100%; }
.action-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-4); }
.action-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--space-2); margin: 0; padding: 0; list-style: none; }
.action-grid li { display: grid; grid-template-rows: auto 1fr auto; justify-items: start; padding: var(--space-3); border: 1px solid var(--theme-main-border); border-radius: var(--radius); }
.action-grid li[data-current] { background: var(--theme-main-soft-background); }
.action-grid strong { font-size: 13px; }
.action-grid p, .action-toolbar [role='status'] { font-size: 12px; color: color-mix(in srgb, var(--theme-main-text) 65%, transparent); }
.composer-preview { display: flex; align-items: center; justify-content: space-between; min-height: 48px; padding: var(--space-2) var(--space-3); background: var(--theme-composer-background); color: var(--theme-composer-text); border-radius: var(--radius); }
@media (max-width: 800px) { .action-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.token-list { display: grid; gap: var(--space-2); width: 100%; }
.token-row { display: flex; align-items: center; gap: var(--space-2); }
.token-swatch { width: 24px; height: 24px; border: 1px solid var(--theme-main-border); border-radius: var(--radius-sm); }
.token-value { margin-left: auto; max-width: 55%; overflow-wrap: anywhere; color: color-mix(in srgb, var(--theme-main-text) 65%, transparent); font-size: 11px; }
.token-radius { width: 24px; height: 24px; background: var(--theme-control-solid); }
.token-scale { height: 6px; background: var(--theme-control-solid); border-radius: var(--radius-sm); }
.thinking-preview { height: 220px; width: 48px; }
.computer-use-preview { position: relative; width: 100%; height: 180px; }
.ping-ring-preview { position: relative; width: 320px; height: 320px; max-width: 100%; }
.variant { display: flex; gap: var(--space-2); align-items: center; } .preview > .sunday-range, .preview > .ui-select { width: 100%; }
.study-sidebar-preview { width: 100%; background: var(--theme-backdrop-background); border-radius: var(--radius); }
</style>
