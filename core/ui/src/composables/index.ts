/**
 * Composables barrel — re-exports all composables and their public types.
 */

export {
  useCoreWorkbenchController,
  type CoreTurnStartResult,
  type CoreWorkbenchApi,
  type UseCoreWorkbenchControllerContext,
  type UseCoreWorkbenchControllerOptions,
} from './useCoreWorkbenchController'

export { usePendingAttachments } from './usePendingAttachments'

export {
  NARROW_VIEWPORT_MAX_WIDTH,
  useNarrowViewport,
} from './useNarrowViewport'

export {
  useOutsidePointerDismiss,
  type OutsidePointerDismissOptions,
} from './useOutsidePointerDismiss'

export {
  calculateKeyboardInset,
  useComposerLayout,
  type ComposerLayoutOptions,
  type ComposerLayoutState,
  type ComposerPlacement,
} from './useComposerLayout'

export {
  CORE_EXECUTION_CONTROLS_STORAGE_KEYS,
  useCoreExecutionControlsState,
  type CoreExecutionControlsStorage,
  type CoreExecutionControlsState,
  type CoreExecutionControlsStateInitial,
  type CoreExecutionControlsStateLabels,
  type UseCoreExecutionControlsStateOptions,
} from './useCoreExecutionControlsState'

export {
  useCoreApprovalController,
  type CoreApprovalHandlingResult,
  type UseCoreApprovalControllerOptions,
} from './useCoreApprovalController'

export {
  useCoreLiveTurnController,
  type CoreLiveConnectionState,
  type UseCoreLiveTurnControllerOptions,
} from './useCoreLiveTurnController'

export {
  useCoreLiveComposerController,
  type CoreLiveComposerMessages,
  type UseCoreLiveComposerControllerOptions,
} from './useCoreLiveComposerController'

export {
  useCoreWorkbenchProjectionController,
  type CoreWorkbenchProjectionStatusChange,
  type UseCoreWorkbenchProjectionControllerOptions,
} from './useCoreWorkbenchProjectionController'

export {
  useCoreQueuedInputController,
  type CoreQueuedInputControllerItem,
  type UseCoreQueuedInputControllerOptions,
} from './useCoreQueuedInputController'

export {
  useCoreProjectSessionState,
  type CoreOwnedProject,
  type CoreOwnedSession,
  type CoreProjectSessionAdapter,
} from './useCoreProjectSessionState'

export {
  useCoreConfigState,
  type CoreConfigAdapter,
  type CoreConfigEntity,
} from './useCoreConfigState'

export {
  useCoreUiPreferences,
  type CoreUiDensity,
  type CoreUiPreferencesAdapter,
  type CoreUiPreferencesValue,
} from './useCoreUiPreferences'

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
  type CoreAutoFollowScrollController,
  type CoreScrollSentinel,
  type CoreScrollableElement,
  type UseCoreAutoFollowScrollOptions,
} from './useCoreAutoFollowScroll'

export {
  useCoreGoals,
  type UseCoreGoalsOptions,
} from './useCoreGoals'

export {
  useRightSidebarLayout,
  type RightSidebarLayoutOptions,
  type RightSidebarModuleDefaults,
} from './useRightSidebarLayout'

export {
  createCoreConnectionErrorToastGate,
  useCoreToast,
  showToast,
  dismissToast,
  dismissAllToasts,
  isTransientCoreConnectionError,
  TRANSIENT_CONNECTION_ERROR_GRACE_MS,
  type CoreConnectionErrorToastGate,
  type CoreToast,
  type CoreToastKind,
} from './useCoreToast'

export {
  readUpdateAutoCheck,
  setUpdateAutoCheck,
  useCoreUpdateState,
  type CoreUpdateCheckPayload,
  type CoreUpdateRequestRpc,
  type CoreUpdateState,
  type CoreUpdateStatus,
} from './useCoreUpdateState'

export {
  useCheckpoints,
  type CoreCheckpointNode,
  type CoreCheckpointRequest,
  type CoreCheckpointRestoreResult,
  type CoreCheckpointRestoreScope,
  type CoreCheckpointState,
} from './useCheckpoints'
