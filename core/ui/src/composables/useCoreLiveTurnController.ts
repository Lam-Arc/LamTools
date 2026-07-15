import { computed, ref, type Ref } from 'vue'

export type CoreLiveConnectionState = 'connecting' | 'open' | 'closed' | 'error'

export interface UseCoreLiveTurnControllerOptions<Input> {
  activeThreadId: Readonly<Ref<string | null>>
  activeTurnId?: Readonly<Ref<string>>
  connectedThreadId: Readonly<Ref<string>>
  connectionState: Readonly<Ref<CoreLiveConnectionState>>
  connect(threadId: string): Promise<void>
  startTurn(threadId: string, input: Input, workRoot?: string, options?: Record<string, unknown>): Promise<void>
  interruptTurn(threadId: string, turnId?: string): Promise<void>
}

export function useCoreLiveTurnController<Input>(options: UseCoreLiveTurnControllerOptions<Input>) {
  const lastError = ref('')
  const isActiveThreadConnected = computed(() => {
    const threadId = options.activeThreadId.value
    return threadId !== null && isThreadConnected(threadId)
  })

  async function ensureConnected(threadId: string): Promise<boolean> {
    if (!threadId) {
      lastError.value = 'Core App Server thread id is required'
      return false
    }
    try {
      if (!isThreadConnected(threadId)) {
        await options.connect(threadId)
      }
      lastError.value = ''
      return true
    } catch (error) {
      lastError.value = error instanceof Error ? error.message : String(error)
      return false
    }
  }

  async function startActiveTurn(
    input: Input,
    workRoot?: string,
    turnOptions: Record<string, unknown> = {},
  ): Promise<boolean> {
    const threadId = options.activeThreadId.value || ''
    return await startThreadTurn(input, threadId, workRoot, turnOptions)
  }

  async function startThreadTurn(
    input: Input,
    threadId: string,
    workRoot?: string,
    turnOptions: Record<string, unknown> = {},
  ): Promise<boolean> {
    if (!await ensureConnected(threadId)) return false
    try {
      await options.startTurn(threadId, input, workRoot, turnOptions)
      lastError.value = ''
      return true
    } catch (error) {
      lastError.value = error instanceof Error ? error.message : String(error)
      return false
    }
  }

  async function interruptActiveTurn(): Promise<boolean> {
    const threadId = options.activeThreadId.value || ''
    if (!await ensureConnected(threadId)) return false
    try {
      await options.interruptTurn(threadId, options.activeTurnId?.value || undefined)
      lastError.value = ''
      return true
    } catch (error) {
      lastError.value = error instanceof Error ? error.message : String(error)
      return false
    }
  }

  function isThreadConnected(threadId: string): boolean {
    return options.connectedThreadId.value === threadId && options.connectionState.value === 'open'
  }

  return {
    ensureConnected,
    interruptActiveTurn,
    isActiveThreadConnected,
    lastError,
    startActiveTurn,
    startThreadTurn,
  }
}
