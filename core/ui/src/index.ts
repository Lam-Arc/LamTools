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
  CoreMessage,
  CoreSubAgentRun,
  CoreAttachmentStatus,
  CoreAttachment,
  CoreAttachmentInputItem,
  CoreCommandSource,
  CoreCommandAction,
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

export type {
  WorkflowNodeKind,
  PortDirection,
  NodeStateStatus,
  WorkflowPort,
  WorkflowNodeData,
  WorkflowEdge,
  WorkflowInputParam,
  WorkflowDef,
  WorkflowNodeState,
  WorkflowRunStatus,
  WorkflowRunResult,
} from './workflow/types';

export {
  listWorkflows,
  getWorkflow,
  createWorkflow,
  updateWorkflow,
  deleteWorkflow,
  runWorkflow,
  setWorkflowExposed,
  listToolNames,
} from './workflow/api';

export {
  listGoals,
  updateGoal,
  createGoal,
  listArrangeJobs,
  updateArrangeJob,
  renameArrangeJob,
  editArrangeJob,
  listArrangeOccurrences,
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
export { default as SessionSidebar } from './components/SessionSidebar.vue';
export { default as ChatThread } from './components/ChatThread.vue';
export { default as ComposerBar } from './components/ComposerBar.vue';
export { default as CoreExecutionControls } from './components/CoreExecutionControls.vue';
export { default as CoreSubAgentPanel } from './components/CoreSubAgentPanel.vue';
export { default as CoreSubAgentDialog } from './components/CoreSubAgentDialog.vue';
export { default as CoreResourceStats } from './components/CoreResourceStats.vue';
export { default as MarkdownRenderer } from './components/MarkdownRenderer.vue';
export { default as UiSelect } from './components/UiSelect.vue';
export { default as CoreQueuedInputTray } from './components/CoreQueuedInputTray.vue';
export { default as CommandPalette } from './components/CommandPalette.vue';
export { default as AttachmentTray } from './components/AttachmentTray.vue';
export { default as RuntimePanel } from './components/RuntimePanel.vue';
export { default as SettingsShell } from './components/SettingsShell.vue';
export { default as ThemeEditor } from './components/ThemeEditor.vue';
export { default as ThemeAreaEditor } from './components/ThemeAreaEditor.vue';
export { default as CoreSettings } from './components/CoreSettings.vue';
export { default as CoreProjectCreate } from './components/CoreProjectCreate.vue';
export { default as CoreSessionTitleEditor } from './components/CoreSessionTitleEditor.vue';
export { default as CoreSessionRollback } from './components/CoreSessionRollback.vue';
export type {
  CoreSessionCheckpoint,
  CoreSessionRollbackResult,
  CoreSessionOperationRequest,
} from './components/CoreSessionRollback.vue';
export { default as CoreAgentsEditor } from './components/CoreAgentsEditor.vue';
export { default as CoreArrangeManager } from './components/CoreArrangeManager.vue';
export { default as CoreGoalStrip } from './components/CoreGoalStrip.vue';
export { default as WorkflowCanvas } from './components/WorkflowCanvas.vue';
export { default as WorkflowNode } from './components/WorkflowNode.vue';
export { default as NodeEditCard } from './components/NodeEditCard.vue';
export { default as WorkflowControlBar } from './components/WorkflowControlBar.vue';
export { default as StagePane } from './components/StagePane.vue';
export { default as StageCodeEditor } from './components/StageCodeEditor.vue';
export { default as StageImagePreview } from './components/StageImagePreview.vue';
export { default as StageMediaPreview } from './components/StageMediaPreview.vue';
export { default as StageBrowser } from './components/StageBrowser.vue';
export { default as FileTreePanel } from './components/FileTreePanel.vue';
export { default as FileTreeNode } from './components/FileTreeNode.vue';
export { default as FolderBrowserDialog } from './components/FolderBrowserDialog.vue';
export type {
  CoreSettingsDensity,
  CoreSettingsModel,
  CoreSettingsModelPayload,
  CoreSettingsProvider,
  CoreSettingsProviderPayload,
  WorkflowListItem,
} from './components/CoreSettings.vue';

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

// Data
export { THEME_PRESETS, THEME_PRESET_GROUPS } from './data/theme-presets';
export { PROVIDER_PRESETS } from './data/provider-presets';
export type { ProviderPreset, ProviderPresetModel } from './data/provider-presets';

// Composables
export {
  CORE_SCROLL_BOTTOM_THRESHOLD_PX,
  coreIsScrollNearBottom,
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
  type CoreProject,
  type CoreProjectAgents,
  type CoreProjectCreatePayload,
  type CoreProjectCreateResult,
  type CoreProjectGroup,
  type CoreProjectSession,
} from './projects/types';

export { usePendingAttachments } from './composables/usePendingAttachments';
export { useComposerCommandPalette } from './composables/useComposerCommandPalette';

export {
  useShellLayout,
  type DensityMode,
  type ShellLayoutOptions,
} from './composables/useShellLayout';

export { useTheme } from './composables/useTheme';

export {
  parseComposerSyntax,
  findActiveSlashCandidate,
  type ComposerSyntaxKind,
  type ComposerSyntaxSpan,
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
  coreModelDisplayLabel,
  coreModelSelectOptions,
  coreThinkingModeOptions,
  coreThinkingPayload,
  normalizeCoreThinkingMode,
  readStoredCoreShallowThinking,
  readStoredCoreThinkingMode,
  selectCoreExecutionModel,
  writeStoredCoreShallowThinking,
  writeStoredCoreThinkingMode,
  type CoreExecutionModelSource,
  type CoreExecutionProviderSource,
  type CoreSelectOption,
  type CoreThinkingLabels,
  type CoreThinkingMode,
  type CoreThinkingModeOption,
  type CoreThinkingPayload,
} from './composer/execution';

export {
  appServerUrl,
  CoreAppServerClient,
  CoreAppServerClosedError,
  fetchAppServerToken,
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
  type CoreComposerActionMode,
  type CoreWorkbenchMessageOptions,
  type CoreWorkbenchTurnStatus,
  type CoreRuntimeItem,
  type CoreRuntimeSnapshot,
  type CoreRuntimeTurn,
  type SubmitCoreComposerTaskOptions,
  type SubmitCoreComposerTaskResult,
} from './appServer';

// Styles
import './styles/variables.css';
import './styles/base.css';
import './styles/layout.css';
import './styles/theme-editor.css';
