/**
 * Composables barrel — re-exports all composables and their public types.
 */

export {
  useCoreWorkbenchController,
  type CoreTurnStartResult,
  type CoreWorkbenchApi,
  type UseCoreWorkbenchControllerContext,
  type UseCoreWorkbenchControllerOptions,
} from '@/composables/useCoreWorkbenchController.ts'

export { usePendingAttachments } from '@/composables/usePendingAttachments.ts'

export {
  NARROW_VIEWPORT_MAX_WIDTH,
  useNarrowViewport,
} from '@/composables/useNarrowViewport.ts'

export {
  useOutsidePointerDismiss,
  type OutsidePointerDismissOptions,
} from '@/composables/useOutsidePointerDismiss.ts'

export {
  calculateKeyboardInset,
  useComposerLayout,
  type ComposerLayoutOptions,
  type ComposerLayoutState,
  type ComposerPlacement,
} from '@/composables/useComposerLayout.ts'

export {
  CORE_EXECUTION_CONTROLS_STORAGE_KEYS,
  useCoreExecutionControlsState,
  type CoreExecutionControlsStorage,
  type CoreExecutionControlsState,
  type CoreExecutionControlsStateInitial,
  type CoreExecutionControlsStateLabels,
  type UseCoreExecutionControlsStateOptions,
} from '@/composables/useCoreExecutionControlsState.ts'

export {
  useCoreApprovalController,
  type CoreApprovalHandlingResult,
  type UseCoreApprovalControllerOptions,
} from '@/composables/useCoreApprovalController.ts'

export {
  ASK_SKIP_GUIDANCE,
  ASK_SKIP_TIMEOUT_MS,
  useCoreAskAutoContinue,
  type UseCoreAskAutoContinueOptions,
} from '@/composables/useCoreAskAutoContinue.ts'

export {
  useCoreLiveTurnController,
  type CoreLiveConnectionState,
  type UseCoreLiveTurnControllerOptions,
} from '@/composables/useCoreLiveTurnController.ts'

export {
  useCoreLiveComposerController,
  type CoreLiveComposerMessages,
  type UseCoreLiveComposerControllerOptions,
} from '@/composables/useCoreLiveComposerController.ts'

export {
  useCoreWorkbenchProjectionController,
  type CoreWorkbenchProjectionStatusChange,
  type UseCoreWorkbenchProjectionControllerOptions,
} from '@/composables/useCoreWorkbenchProjectionController.ts'

export {
  useCorePendingGuidance,
  type CorePendingGuidanceOptions,
} from '@/composables/useCorePendingGuidance.ts'

export {
  useCoreQueuedInputController,
  type CoreQueuedInputControllerItem,
  type UseCoreQueuedInputControllerOptions,
} from '@/composables/useCoreQueuedInputController.ts'

export {
  useCoreProjectSessionState,
  type CoreOwnedProject,
  type CoreOwnedSession,
  type CoreProjectSessionAdapter,
} from '@/composables/useCoreProjectSessionState.ts'

export {
  useCoreConfigState,
  type CoreConfigAdapter,
  type CoreConfigEntity,
} from '@/composables/useCoreConfigState.ts'

export {
  useCoreUiPreferences,
  type CoreUiDensity,
  type CoreUiPreferencesAdapter,
  type CoreUiPreferencesValue,
} from '@/composables/useCoreUiPreferences.ts'

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
} from '@/composables/useCoreAutoFollowScroll.ts'

export {
  createIdleHistoryMount,
  IDLE_HISTORY_MAX_BATCHES,
  type IdleHistoryMountController,
  type IdleHistoryMountOptions,
} from '@/composables/useIdleHistoryMount.ts'

export {
  useCoreGoals,
  type UseCoreGoalsOptions,
} from '@/composables/useCoreGoals.ts'

export {
  useRightSidebarLayout,
  type RightSidebarLayoutOptions,
  type RightSidebarModuleDefaults,
} from '@/composables/useRightSidebarLayout.ts'

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
} from '@/composables/useCoreToast.ts'

export {
  readUpdateAutoCheck,
  setUpdateAutoCheck,
  useCoreUpdateState,
  type CoreUpdateCheckPayload,
  type CoreUpdateRequestRpc,
  type CoreUpdateState,
  type CoreUpdateStatus,
} from '@/composables/useCoreUpdateState.ts'

