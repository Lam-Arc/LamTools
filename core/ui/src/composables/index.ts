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
  CORE_SCROLL_BOTTOM_THRESHOLD_PX,
  coreIsScrollNearBottom,
  useCoreAutoFollowScroll,
  type CoreAutoFollowScrollController,
  type CoreScrollableElement,
  type UseCoreAutoFollowScrollOptions,
} from './useCoreAutoFollowScroll'
