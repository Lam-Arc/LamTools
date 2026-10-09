import { ref, watch, type Ref } from 'vue'
import {
  assistantSegmentTurnId,
  createCoreWorkbenchProjectionCache,
  isCoreActiveTurnStatus,
  isCoreGuidableTurnStatus,
  selectCoreWorkbenchMessagesWindow,
  type CoreAppSnapshot,
  nextCoreProcessExpandedIds,
  normalizeCoreSessionStatus,
} from '../appServer'
import type { CoreMessage, MessagePart } from '../types'

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
  /** 当前活动 turn id。停止后要把这一轮的过程留在展开态，需要它来认出这一轮
   *  的消息（消息 id 里带 turn id）。 */
  activeTurnId?: Readonly<Ref<string>>
  submittingApprovalRequestIds: Readonly<Ref<Set<string>>>
  shallowThinkingPending: Readonly<Ref<boolean>>
  /** 待生效的引导（按 turn 归属），挂在过程末尾先显示。 */
  pendingGuidance?: Readonly<Ref<ReadonlyArray<{ turnId: string; part: MessagePart }>>>
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
  /** 本轮 turn id：停止后要认出"被停的那一条"是哪条消息。 */
  let currentTurnId = ''
  /** 兜底信号：本轮里出现过的实时消息 id（宿主没有给 activeTurnId 时用）。 */
  let liveProcessMessageIds = new Set<string>()

  // History windowing: only the most recent N complete turns are projected/rendered
  // initially; `loadMoreHistory` widens the window by another complete turn page. This
  // keeps first render of very large threads fast (DOM creation is the
  // dominant cost) while the projection cache keeps identities stable.
  const historyTurnTail = ref(10)
  const hasMoreHistory = ref(false)
  const totalMessages = ref(0)
  const HISTORY_TURN_PAGE_SIZE = 10

  function resetHistoryWindow(): void {
    historyTurnTail.value = HISTORY_TURN_PAGE_SIZE
    hasMoreHistory.value = false
    totalMessages.value = 0
  }

  function loadMoreHistory(): void {
    if (!hasMoreHistory.value) return
    historyTurnTail.value += HISTORY_TURN_PAGE_SIZE
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
        currentTurnId = ''
        liveProcessMessageIds = new Set()
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
        options.onTurnFinished?.(change)
      }
      previousStatus = status
      if (snapshotMatchesActiveThread) previousTurnWasActive = active

      if (!snapshotMatchesActiveThread || !snapshot) {
        messages.value = systemMessages
        liveProcessMessageIds = new Set()
        return
      }

      const projected = selectCoreWorkbenchMessagesWindow(snapshot, {
        source: options.source,
        active: isCoreGuidableTurnStatus(rawStatus),
        shallowThinkingPending: options.shallowThinkingPending.value,
        submittingApprovalRequestIds: options.submittingApprovalRequestIds.value,
        pendingGuidance: options.pendingGuidance?.value,
        tailTurns: historyTurnTail.value,
      }, projectionCache)
      messages.value = [
        ...systemMessages,
        ...projected.messages,
      ]
      hasMoreHistory.value = projected.startIndex > 0
      totalMessages.value = projected.total

      if (finished) {
        // 这一轮结束时怎么处置"实时展开"的过程：
        //  · 正常跑完 → 回到完成态摘要（此前为实时展开的状态收回去）；
        //  · 被停止 / 失败 → 保持当时的样子。用户刚点了一次停止，不该顺手把他
        //    正在看的过程一起收走；要收起由他自己点过程摘要（2026-10-09）。
        const next = new Set(processExpandedIds.value)
        for (const id of turnProcessMessageIds()) {
          if (rawStatus === 'completed') next.delete(id)
          else next.add(id)
        }
        processExpandedIds.value = next
        currentTurnId = ''
        liveProcessMessageIds = new Set()
      } else {
        if (active && options.activeTurnId?.value) currentTurnId = options.activeTurnId.value
        liveProcessMessageIds = new Set(
          messages.value
            .filter(message => message.role === 'assistant' && message.metadata?.live === true)
            .map(message => message.id),
        )
        processExpandedIds.value = nextCoreProcessExpandedIds(
          messages.value,
          processExpandedIds.value,
          isCoreGuidableTurnStatus(rawStatus),
        )
      }
    }

    /** 这一轮自己产生的助手消息（消息 id 里带着 turn id）。 */
    function turnProcessMessageIds(): string[] {
      if (currentTurnId) {
        return messages.value
          .filter(message => message.role === 'assistant'
            && assistantSegmentTurnId(String(message.id)) === currentTurnId)
          .map(message => message.id)
      }
      return [...liveProcessMessageIds]
    }

  watch(
    [
      options.snapshot,
      options.activeThreadId,
      options.status,
      options.submittingApprovalRequestIds,
      options.shallowThinkingPending,
      historyTurnTail,
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
