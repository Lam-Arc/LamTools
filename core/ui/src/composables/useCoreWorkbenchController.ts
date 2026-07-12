import { computed, ref } from 'vue'
import type { CoreSessionListItem, CoreMessage, CoreRuntimeEvent } from '../types'
import { createLoadingStepGroup } from '../helpers'

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/** API surface that the host application must provide. */
export interface CoreTurnStartResult {
  messages?: CoreMessage[]
  events?: CoreRuntimeEvent[]
  userMessage?: CoreMessage
  assistantMessage?: CoreMessage
}

export interface CoreWorkbenchApi {
  listSessions(): Promise<CoreSessionListItem[]>
  createSession(): Promise<CoreSessionListItem>
  getMessages?(sessionId: string): Promise<CoreMessage[]>
  createMessage?(sessionId: string, content: string, role?: string): Promise<CoreMessage>
  startTurn?(sessionId: string, content: string): Promise<CoreTurnStartResult | void>
  getEvents?(sessionId: string): Promise<CoreRuntimeEvent[]>
  listProviders?(): Promise<unknown[]>
}

/** Context passed to the onMountedExtra callback. */
export interface UseCoreWorkbenchControllerContext {
  sessions: CoreSessionListItem[]
  activeSessionId: string | null
  providerCount: number
}

/** Options for the useCoreWorkbenchController composable. */
export interface UseCoreWorkbenchControllerOptions {
  api: CoreWorkbenchApi
  onMountedExtra?: (ctx: UseCoreWorkbenchControllerContext) => Promise<void> | void
  initialSessionId?: string | null
}

// ---------------------------------------------------------------------------
// Composable
// ---------------------------------------------------------------------------

export function useCoreWorkbenchController(options: UseCoreWorkbenchControllerOptions) {
  const { api, onMountedExtra } = options

  const sessions = ref<CoreSessionListItem[]>([])
  const activeSessionId = ref<string | null>(null)
  const messages = ref<CoreMessage[]>([])
  const events = ref<CoreRuntimeEvent[]>([])
  const composerText = ref('')
  const loading = ref(false)
  const providerCount = ref(0)
  const loadError = ref<string | null>(null)

  const stepGroups = computed(() =>
    loading.value ? createLoadingStepGroup() : [],
  )

  async function selectSession(id: string) {
    activeSessionId.value = id
    // Clear immediately to avoid flashing old session's data
    messages.value = []
    events.value = []
    loading.value = true
    try {
      const [msgs, evts] = await Promise.all([
        api.getMessages?.(id) ?? Promise.resolve([]),
        api.getEvents?.(id) ?? Promise.resolve([]),
      ])
      if (activeSessionId.value !== id) return
      messages.value = msgs
      events.value = evts
    } catch (err) {
      if (activeSessionId.value !== id) return
      console.error(err)
      messages.value = []
      events.value = []
    } finally {
      if (activeSessionId.value === id) {
        loading.value = false
      }
    }
  }

  async function newSession() {
    try {
      const session = await api.createSession()
      sessions.value.unshift(session)
      await selectSession(session.id)
    } catch (err) {
      console.error('Failed to create session:', err)
    }
  }

  async function sendMessage() {
    const text = composerText.value.trim()
    if (!text || !activeSessionId.value) return
    if (!api.startTurn && !api.createMessage) return

    const sessionId = activeSessionId.value
    composerText.value = ''
    loading.value = true
    const timestamp = new Date().toISOString()
    const optimisticId = `optimistic-${timestamp}-${Math.random().toString(16).slice(2, 8)}`
    messages.value = [
      ...messages.value,
      {
        id: `${optimisticId}:user`,
        role: 'user',
        content: text,
        timestamp,
        metadata: { optimistic: true },
      },
      {
        id: `${optimisticId}:assistant`,
        role: 'assistant',
        content: '',
        timestamp,
        parts: [],
        metadata: { optimistic: true, live: true, initialWaiting: true },
      },
    ]
    try {
      if (api.startTurn) {
        const result = await api.startTurn(sessionId, text)
        if (activeSessionId.value !== sessionId) return
        if (result?.messages) {
          messages.value = result.messages
        } else {
          messages.value = await (api.getMessages?.(sessionId) ?? Promise.resolve([]))
        }
        if (result?.events) {
          events.value = result.events
        } else {
          events.value = await (api.getEvents?.(sessionId) ?? Promise.resolve([]))
        }
        return
      }
      await api.createMessage?.(sessionId, text, 'user')
      if (activeSessionId.value !== sessionId) return
      messages.value = await (api.getMessages?.(sessionId) ?? Promise.resolve([]))
    } catch (err) {
      console.error('Failed to send message:', err)
    } finally {
      if (activeSessionId.value === sessionId) {
        loading.value = false
      }
    }
  }

  async function loadInitialData() {
    try {
      loadError.value = null
      const [sessionList, providers] = await Promise.all([
        api.listSessions(),
        api.listProviders?.() ?? Promise.resolve(undefined),
      ])
      sessions.value = sessionList
      if (providers !== undefined) {
        providerCount.value = providers.length
      }
      const ctx: UseCoreWorkbenchControllerContext = {
        sessions: sessionList,
        activeSessionId: activeSessionId.value,
        providerCount: providerCount.value,
      }
      await onMountedExtra?.(ctx)
      const initialSessionId = options.initialSessionId
      const sessionToSelect = initialSessionId && sessionList.some((session) => session.id === initialSessionId)
        ? initialSessionId
        : sessionList[0]?.id
      if (sessionToSelect) {
        await selectSession(sessionToSelect)
      }
    } catch (err) {
      console.error('Failed to load initial data:', err)
      loadError.value = err instanceof Error ? err.message : String(err)
    }
  }

  return {
    sessions,
    activeSessionId,
    messages,
    events,
    composerText,
    loading,
    loadError,
    providerCount,
    stepGroups,
    selectSession,
    newSession,
    sendMessage,
    loadInitialData,
  }
}
