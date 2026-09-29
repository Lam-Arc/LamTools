/**
 * UI Core — Public API
 * Exports all components, composables, helpers, and types
 */

// Types
export type {
  ProductFeatureId,
  ProductAdapter,
  CoreSessionGroup,
  CoreRuntimeStepStatus,
  CoreRuntimeStep,
  CoreRuntimeStepGroup,
  SettingsSectionDef,
  CoreApiMapper,
  CoreSessionListItem,
  CoreSessionExportFormat,
  CoreMessage,
  CoreSubAgentRun,
  CoreAttachmentStatus,
  CoreAttachment,
  CoreAttachmentInputItem,
  CoreCommandSource,
  CoreCommandAction,
  CoreCommandKind,
  CoreCommandCatalogItem,
  CoreCommandToken,
  CoreInputItem,
  CoreModelInputCapabilities,
  CoreSkillInputItem,
  MessagePartType,
  MessagePartStatus,
  MessagePart,
  CoreRuntimeEvent,
  CoreComposerPayload,
  CoreMemberDescriptor,
  WorkspaceSlotName,
  MemberSlotSet,
  SlotValidationResult,
  SessionItem,
  ProjectGroup,
  StageKind,
  StageResource,
  ThemeStop,
  ThemeArea,
  ThemeData,
  ThemePreset,
  ThemeCSSVars,
} from './types';

export type { CoreGoal, CoreArrangeJob } from './durable/types';

export {
  createDurableApi,
  type CoreArrangeOccurrence,
  type CoreDurableApi,
  type CoreDurableRequest,
} from './durable/api';

export { WORKSPACE_SLOT_NAMES } from './types';

export {
  buildCoreResourceSummary,
  CORE_CONTEXT_COMPACTION_TRIGGER_RATIO,
  type CoreResourceSummary,
} from './runtime/resources';
export { buildCurrentTurnChecklistGroups } from './runtime/checklist';
export { selectCoreSubAgentRuns } from './agents/subAgentProjection';

// Components
export { default as WorkspaceShell } from './components/WorkspaceShell.vue';
export { default as LamToolsApp } from './app/LamToolsApp.vue';
export { default as LeftSidebarShell } from './components/LeftSidebarShell.vue';
export { default as RailAction } from './components/RailAction.vue';
export { default as SessionSidebar } from './components/SessionSidebar.vue';
export { default as ChatThread } from './components/ChatThread.vue';
export { default as ComposerBar } from './components/ComposerBar.vue';
export { default as CoreSendStopButton } from './components/CoreSendStopButton.vue';
export { default as MobileTopBar } from './components/MobileTopBar.vue';
export { default as CoreExecutionControls } from './components/CoreExecutionControls.vue';
export { default as CoreRuntimeMenu } from './components/CoreRuntimeMenu.vue';
export { default as CoreWorkspaceMenu } from './components/CoreWorkspaceMenu.vue';
export { default as CoreModelThinkingMenu } from './components/CoreModelThinkingMenu.vue';
export { default as CoreSubAgentPanel } from './components/CoreSubAgentPanel.vue';
export { default as CoreSubAgentDialog } from './components/CoreSubAgentDialog.vue';
export { default as CoreResourceStats } from './components/CoreResourceStats.vue';
export { default as MarkdownRenderer } from './components/MarkdownRenderer.vue';
export { default as UiSelect } from './components/UiSelect.vue';
export { default as CoreQueuedInputTray } from './components/CoreQueuedInputTray.vue';
export { default as CommandPalette } from './components/CommandPalette.vue';
export { default as AttachmentTray } from './components/AttachmentTray.vue';
export { default as RuntimePanel } from './components/RuntimePanel.vue';
export { default as RuntimeChecklistCard } from './components/RuntimeChecklistCard.vue';
export { default as SettingsShell } from './components/SettingsShell.vue';
export { default as ThemeEditor } from './components/ThemeEditor.vue';
export { default as ThemeAreaEditor } from './components/ThemeAreaEditor.vue';
export { default as CoreSettings } from './components/CoreSettings.vue';
export { default as MobileControlPanel } from './components/MobileControlPanel.vue';
export { default as PluginsShell } from './components/PluginsShell.vue';
export { default as PluginModeHost } from './components/PluginModeHost.vue';
export { default as CoreProjectSettings } from './components/CoreProjectSettings.vue';
export type { CoreProjectSettingsProject } from './components/CoreProjectSettings.vue';
export { default as CoreProjectCreate } from './components/CoreProjectCreate.vue';
export { default as CoreSessionTitleEditor } from './components/CoreSessionTitleEditor.vue';
export { default as CoreImageGenEditor } from './components/CoreImageGenEditor.vue';
export { default as ArtifactPanel } from './components/ArtifactPanel.vue';
export { default as RightSidebarHost } from './components/RightSidebarHost.vue';
export { default as RightSidebarModule } from './components/RightSidebarModule.vue';
export { default as RightSidebarLayoutEditor } from './components/RightSidebarLayoutEditor.vue';
export { default as RightSidebarWidgetRenderer } from './components/RightSidebarWidgetRenderer.vue';
export { default as RightSidebarRuntimeStatus } from './components/RightSidebarRuntimeStatus.vue';
export { default as RightSidebarWebSearch } from './components/RightSidebarWebSearch.vue';
export { default as RightSidebarRag } from './components/RightSidebarRag.vue';
export { default as CoreAgentsEditor } from './components/CoreAgentsEditor.vue';
export { default as CoreArrangeManager } from './components/CoreArrangeManager.vue';
export { default as CoreGoalStrip } from './components/CoreGoalStrip.vue';
export {
  PluginUIRegistry,
  pluginUIRegistry,
  registerMode,
  getMode,
  listModes,
  registerWidget,
  getWidget,
  listWidgets,
  unregisterPlugin,
  unregisterWidgets,
} from './plugins/registry';
export {
  listPluginUI,
  refreshPluginUIModes,
  listPluginWidgets,
  getPluginWidget,
  invokePluginWidget,
  refreshPluginUIWidgets,
} from './plugins/api';
export { PLUGIN_WIDGET_RPC_METHODS } from './plugins/types';
export type {
  PluginMode,
  PluginModeLoader,
  PluginRpc,
  PluginUIEntry,
  PluginUIListPayload,
  PluginWidget,
  PluginWidgetEntry,
  PluginWidgetLoader,
  PluginWidgetListPayload,
  PluginWidgetInvokeParams,
  PluginWidgetRpcMethod,
  PluginWidgetAction,
  RightSidebarWidgetAction,
  RightSidebarWidgetSnapshot,
} from './plugins/types';
export type {
  RightSidebarLayoutController,
  RightSidebarLayoutState,
  RightSidebarModuleDefinition,
  RightSidebarModuleLoader,
  RightSidebarModuleStatus,
  RightSidebarPluginContribution,
  RightSidebarRpc,
  RightSidebarWidgetBlock,
  RightSidebarWidgetState,
  RightSidebarWidgetTextBlock,
  RightSidebarWidgetStatusBlock,
  RightSidebarWidgetMetricBlock,
  RightSidebarWidgetListBlock,
  RightSidebarWidgetProgressBlock,
} from './right-sidebar/types';
export { default as StagePane } from './components/StagePane.vue';
export { default as StageCodeEditor } from './components/StageCodeEditor.vue';
export { default as StageImagePreview } from './components/StageImagePreview.vue';
export { default as StageMediaPreview } from './components/StageMediaPreview.vue';
export { default as StageBrowser } from './components/StageBrowser.vue';
export { default as FileTreePanel } from './components/FileTreePanel.vue';
export { default as FileTreeNode } from './components/FileTreeNode.vue';
export { default as FolderBrowserDialog } from './components/FolderBrowserDialog.vue';
export {
  ContextMenuHost,
  ContextMenuPanel,
  ContextMenuItem,
  ContextMenuSubmenu,
  closeContextMenu,
  contextMenuState,
  isNativeContextTarget,
  isContextMenuOpen,
  openContextMenu,
  registerTextSelectionMenuContributor,
} from './components/context-menu';
export type {
  ContextMenuAction,
  ContextMenuAnchor,
  ContextMenuAttributes,
  ContextMenuEntry,
  ContextMenuLabel,
  ContextMenuPointAnchor,
  ContextMenuRectAnchor,
  ContextMenuSeparator,
  ContextMenuSubmenu as ContextMenuSubmenuEntry,
  OpenContextMenuOptions,
  TextSelectionMenuContext,
  TextSelectionMenuContributor,
} from './components/context-menu';
export type {
  CoreSettingsDensity,
  CoreSettingsModel,
  CoreSettingsModelPayload,
  CoreSettingsProvider,
  CoreSettingsProviderPayload,
} from './components/CoreSettings.vue';
export type {
  MobileControlAccountContext,
  MobileControlAccountDevice,
  MobileControlAccountPayload,
  MobileControlAccountStatus,
  MobileControlGatewayStatus,
  MobileControlPairing,
  MobileControlTrustedDevice,
} from './components/MobileControlPanel.vue';

// Helpers
export {
  createSessionMapper,
  createMessageMapper,
  createLoadingStepGroup,
  createProductAdapter,
  createMemberSessionGroup,
  type CoreSessionRawLike,
  type CoreMessageRawLike,
  type CreateSessionMapperOptions,
  type CreateMessageMapperOptions,
} from './helpers';

export {
  DEFAULT_THEME,
  clampNumber,
  normalizeColor,
  rgbaFromHex,
  normalizeGradientStops,
  gradientFromStops,
  gradientFromThemeColors,
  normalizeTheme,
  themeToCSSVars,
  addGradientStop,
  removeGradientStop,
  sortGradientStops,
} from './helpers/theme';

export { copyText } from './helpers/clipboard';

// Data
export { THEME_PRESETS, THEME_PRESET_GROUPS } from './data/theme-presets';
export { PROVIDER_PRESETS, PROVIDER_PRESET_GROUP_LABELS, providerPresetModelExtra } from './data/provider-presets';
export type { ProviderPreset, ProviderPresetGroup, ProviderPresetModel } from './data/provider-presets';

// Composables
export {
  CORE_HISTORY_AUTO_LOAD_THRESHOLD_PX,
  CORE_SCROLL_BOTTOM_THRESHOLD_PX,
  CORE_SCROLL_SENTINEL_VISIBLE_RATIO,
  coreApplyHistoryScrollCeiling,
  coreHistoryAutoLoadThreshold,
  coreIsBottomSentinelVisible,
  coreIsScrollNearBottom,
  coreShouldAutoLoadHistory,
  useCoreAutoFollowScroll,
  useCoreExecutionControlsState,
  useCoreApprovalController,
  useCoreLiveComposerController,
  useCoreLiveTurnController,
  useCoreWorkbenchProjectionController,
  useCoreQueuedInputController,
  useCoreProjectSessionState,
  useCoreConfigState,
  useCoreUiPreferences,
  useCoreWorkbenchController,
  useCoreGoals,
  type CoreAutoFollowScrollController,
  type CoreScrollSentinel,
  type CoreExecutionControlsStorage,
  type CoreExecutionControlsState,
  type CoreExecutionControlsStateInitial,
  type CoreExecutionControlsStateLabels,
  type CoreApprovalHandlingResult,
  type CoreLiveComposerMessages,
  type CoreLiveConnectionState,
  type CoreWorkbenchProjectionStatusChange,
  type CoreTurnStartResult,
  type CoreScrollableElement,
  type CoreQueuedInputControllerItem,
  type CoreOwnedProject,
  type CoreOwnedSession,
  type CoreProjectSessionAdapter,
  type CoreConfigAdapter,
  type CoreConfigEntity,
  type CoreUiDensity,
  type CoreUiPreferencesAdapter,
  type CoreUiPreferencesValue,
  type UseCoreAutoFollowScrollOptions,
  type UseCoreExecutionControlsStateOptions,
  type UseCoreApprovalControllerOptions,
  type UseCoreLiveComposerControllerOptions,
  type UseCoreLiveTurnControllerOptions,
  type UseCoreWorkbenchProjectionControllerOptions,
  type UseCoreQueuedInputControllerOptions,
  type CoreWorkbenchApi,
  type UseCoreWorkbenchControllerContext,
  type UseCoreWorkbenchControllerOptions,
  type UseCoreGoalsOptions,
} from './composables';

export { CORE_EXECUTION_CONTROLS_STORAGE_KEYS } from './composables';

export {
  createCoreProjectClient,
  type CoreProjectClient,
  type CoreFileEntry,
} from './projects/client';

export {
  buildCoreProjectGroups,
  CORE_PROJECT_COLOR_KEYS,
  CORE_PROJECT_GRADIENT_COLOR_KEYS,
  CORE_PROJECT_ICON_KEYS,
  CORE_PROJECT_SOLID_COLOR_KEYS,
  DEFAULT_CORE_PROJECT_COLOR_KEY,
  DEFAULT_CORE_PROJECT_ICON_KEY,
  type CoreProject,
  type CoreProjectAgents,
  type CoreProjectColorKey,
  type CoreProjectCreatePayload,
  type CoreProjectCreateResult,
  type CoreProjectGroup,
  type CoreProjectIconKey,
  type CoreProjectSession,
  type CoreProjectUpdatePayload,
} from './projects/types';

export { usePendingAttachments } from './composables/usePendingAttachments';
export { useComposerCommandPalette } from './composables/useComposerCommandPalette';
export {
  useOutsidePointerDismiss,
  type OutsidePointerDismissOptions,
} from './composables/useOutsidePointerDismiss';

// Shared Workbench runtime
export {
  createWorkbench,
  createWorkbenchClient,
  type WorkbenchClientOptions,
  type WorkbenchConnectionState,
  type WorkbenchClientFactory,
  type WorkbenchRuntimeOptions,
  type WorkbenchRuntime,
  type WorkbenchSessionApi,
  type WorkbenchComposerCallbacks,
} from './workbench';

export {
  createLamToolsRuntime,
  type CreateLamToolsRuntimeOptions,
  type LamToolsPlatform,
  type LamToolsRuntime,
  type RuntimeCapabilities,
  type RuntimeFileCapabilities,
  type RuntimeWorkspaceControl,
  type RuntimeWorkspaceOption,
} from './app/runtime';

export {
  useShellLayout,
  type DensityMode,
  type ShellLayoutOptions,
} from './composables/useShellLayout';

export { useTheme } from './composables/useTheme';

export {
  parseComposerSyntax,
  parseComposerInput,
  findActiveSlashCandidate,
  type ComposerSyntaxKind,
  type ComposerSyntaxSpan,
  type ParsedComposerCommand,
} from './composer/syntax';

export {
  buildCoreComposerHighlightSegments,
  buildCoreComposerInputItems,
  coreStandaloneActionCommand,
  type CoreComposerHighlightSegment,
} from './composer/inputItems';

export {
  CORE_THINKING_BUDGETS,
  CORE_THINKING_LABELS,
  CORE_PERMISSION_PRESET_DESCRIPTIONS,
  CORE_PERMISSION_PRESET_LABELS,
  coreModelDisplayLabel,
  coreModelSelectOptions,
  coerceCoreThinkingMode,
  coreDeclaredThinkingLadder,
  coreThinkingModeOptions,
  coreThinkingPayload,
  normalizeCoreThinkingMode,
  normalizeCorePermissionPreset,
  corePermissionPresetLabel,
  readStoredCoreShallowThinking,
  readStoredCoreThinkingMode,
  selectCoreExecutionModel,
  writeStoredCoreShallowThinking,
  writeStoredCoreThinkingMode,
  type CoreExecutionModelSource,
  type CoreExecutionProviderSource,
  type CorePermissionPreset,
  type CoreSelectOption,
  type CoreThinkingLabels,
  type CoreThinkingMode,
  type CoreThinkingModeOption,
  type CoreThinkingPayload,
} from './composer/execution';

export {
  CoreAppServerClient,
  CoreAppServerClosedError,
  hydrateSnapshot,
  coreAppItemInputPreview,
  coreAppItemPartLabel,
  coreAppItemPartStatus,
  coreAppItemPartType,
  coreAppItemToMessagePart,
  coreAppItemToWorkbenchPart,
  coreInputToText,
  coreMessageHasProcessParts,
  normalizeCoreSessionStatus,
  nextCoreProcessExpandedIds,
  selectApprovalCards,
  selectChatMessages,
  selectCoreQueuedInputs,
  selectCoreWorkbenchMessages,
  selectLatestTurnStatus,
  selectLatestActiveTurnId,
  updateCoreSessionListStatus,
  selectQueueTray,
  createCoreAppServerRuntimeController,
  createCoreAppServerRuntimeState,
  applyCoreAppEvent,
  coreAppServerDecision,
  coreDecisionSelectionPlan,
  coreComposerActionMode,
  coreComposerSubmissionEffects,
  isCoreActiveTurnStatus,
  isCoreGuidableTurnStatus,
  normalizeCoreCommandCatalogItem,
  submitCoreComposerTask,
  CORE_APP_SERVER_PROTOCOL_VERSION,
  type CoreAppEvent,
  type CoreAppInputItem,
  type CoreAppItem,
  type CoreAppQueueItem,
  type CoreAppRuntimeSnapshot,
  type CoreAppRequestState,
  type CoreAppServerChatMessage,
  type CoreAppServerClientOptions,
  type JsonRpcClientResponse,
  type JsonRpcRequest,
  type JsonRpcResponse,
  type CoreAppSnapshot,
  type CoreAppThreadStatus,
  type CoreAppTurn,
  type CoreTextInputItem,
  type CoreQueuedInput,
  type CoreAppCommandCatalogItem,
  type CoreAppItemPartOptions,
  type CoreAppServerRuntimeClient,
  type CoreAppServerRuntimeControllerOptions,
  type CoreComposerSubmissionEffectOptions,
  type CoreComposerSubmissionEffectPlan,
  type CoreDecisionSelectionPayload,
  type CoreDecisionSelectionPlan,
  type CoreAppServerRuntimeState,
  type CoreAppServerThreadSwitchOptions,
  type CoreComposerActionMode,
  type CoreWorkbenchMessageOptions,
  type CoreWorkbenchTurnStatus,
  type CoreRuntimeItem,
  type CoreRuntimeSnapshot,
  type CoreRuntimeTurn,
  type SubmitCoreComposerTaskOptions,
  type SubmitCoreComposerTaskResult,
} from './appServer';

// Transport
export {
  DirectTransport,
  createDirectTransport,
  type DirectTransportOptions,
  isLamToolsTransport,
  type LamToolsTransport,
  type TransportConnectionState,
  type TransportHttpRequest,
  type TransportHttpResponse,
  type TransportMessage,
  type TransportMessageType,
  type TransportRequest,
  type TransportRpcRequest,
} from './transport';

// Styles
import './styles/variables.css';
import './styles/base.css';
import './styles/layout.css';
import './styles/theme-editor.css';
