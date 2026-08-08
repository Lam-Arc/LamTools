import { ref, watch, type Ref } from 'vue'
import {
  createCoreWorkbenchProjectionCache,
  isCoreActiveTurnStatus,
  isCoreGuidableTurnStatus,
  selectCoreWorkbenchMessagesWindow,
  type CoreAppSnapshot,
  nextCoreProcessExpandedIds,
  normalizeCoreSessionStatus,
} from '../appServer'
import type { CoreMessage } from '../types'

export interface CoreWorkbenchProjectionStatusChange {
  threadId: string
  status: string
  rawStatus: string
  previousStatus: string | null
}

export interface UseCoreWorkbenchProjectionControllerOptions {
  snapshot: Readonly<Ref<CoreAppSnapshot | null | undefined>>
  activeThreadId: Readonly<Ref<string | null>>
  status: Readonly<Ref<string>>
  submittingApprovalRequestIds: Readonly<Ref<Set<string>>>
  shallowThinkingPending: Readonly<Ref<boolean>>
  source?: string
  systemMessages?: Readonly<Ref<CoreMessage[]>>
  onStatusChange?(change: CoreWorkbenchProjectionStatusChange): void
  onTurnFinished?(change: CoreWorkbenchProjectionStatusChange): void
}

export function useCoreWorkbenchProjectionController(options: UseCoreWorkbenchProjectionControllerOptions) {
  const messages = ref<CoreMessage[]>([])
  const processExpandedIds = ref<Set<string>>(new Set())
  const projectionCache = createCoreWorkbenchProjectionCache()
  let observedThreadId: string | null = null
  let previousStatus: string | null = null
  let previousTurnWasActive = false

  // History windowing: only the most recent N messages are projected/rendered
  // initially; `loadMoreHistory` widens the window toward older messages. This
  // keeps first render of very large threads fast (DOM creation is the
  // dominant cost) while the projection cache keeps identities stable.
  const historyTail = ref(150)
  const hasMoreHistory = ref(false)
  const totalMessages = ref(0)
  const HISTORY_WINDOW_STEP = 150

  function resetHistoryWindow(): void {
    historyTail.value = 150
    hasMoreHistory.value = false
    totalMessages.value = 0
  }

  function loadMoreHistory(): void {
    if (!hasMoreHistory.value) return
    historyTail.value += HISTORY_WINDOW_STEP
  }

  function toggleProcess(id: string): void {
    const next = new Set(processExpandedIds.value)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    processExpandedIds.value = next
  }

  function syncProjection(): void {
      const threadId = options.activeThreadId.value
      if (threadId !== observedThreadId) {
        observedThreadId = threadId
        previousStatus = null
        previousTurnWasActive = false
        processExpandedIds.value = new Set()
        projectionCache.clear()
        resetHistoryWindow()
      }

      const systemMessages = options.systemMessages?.value ?? []
      const snapshot = options.snapshot.value
      const snapshotMatchesActiveThread = Boolean(threadId && snapshot?.thread_id === threadId)
      const rawStatus = String(options.status.value || 'idle')
      const status = normalizeCoreSessionStatus(rawStatus)
      const change = { threadId: threadId || '', status, rawStatus, previousStatus }
      if (threadId && status !== previousStatus) options.onStatusChange?.(change)

      const active = isCoreActiveTurnStatus(rawStatus)
      const finished = Boolean(snapshotMatchesActiveThread && previousTurnWasActive && isTerminalStatus(rawStatus))
      if (finished) {
        processExpandedIds.value = new Set()
        options.onTurnFinished?.(change)
      }
      previousStatus = status
      if (snapshotMatchesActiveThread) previousTurnWasActive = active

      if (!snapshotMatchesActiveThread || !snapshot) {
        messages.value = systemMessages
        return
      }

      const projected = selectCoreWorkbenchMessagesWindow(snapshot, {
        source: options.source,
        active: isCoreGuidableTurnStatus(rawStatus),
        shallowThinkingPending: options.shallowThinkingPending.value,
        submittingApprovalRequestIds: options.submittingApprovalRequestIds.value,
        tailWindow: historyTail.value,
      }, projectionCache)
      messages.value = [
        ...systemMessages,
        ...projected.messages,
      ]
      hasMoreHistory.value = projected.startIndex > 0
      totalMessages.value = projected.total

      if (!finished) {
        processExpandedIds.value = nextCoreProcessExpandedIds(
          messages.value,
          processExpandedIds.value,
          isCoreGuidableTurnStatus(rawStatus),
        )
      }
  }

  watch(
    [
      options.snapshot,
      options.activeThreadId,
      options.status,
      options.submittingApprovalRequestIds,
      options.shallowThinkingPending,
    ],
    syncProjection,
    { immediate: true },
  )

  if (options.systemMessages) {
    watch(options.systemMessages, syncProjection, { deep: true })
  }

  return {
    messages,
    processExpandedIds,
    toggleProcess,
    hasMoreHistory,
    totalMessages,
    loadMoreHistory,
  }
}

function isTerminalStatus(status: string): boolean {
  return status === 'completed' || status === 'failed' || status === 'cancelled'
}
