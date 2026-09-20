import type { Ref } from 'vue'
import type { CoreSessionListItem } from '../types'
import { isInternalSession } from './visibility'

/** Plugin views own their sessions; Core remembers its last conversation. */
export function createModeSessionState(options: {
  mode: Ref<string>
  session: Ref<string | null>
  draft: Ref<string>
  sessions: () => CoreSessionListItem[]
  reset: () => void
  select: (id: string) => Promise<void>
}) {
  let agentSession: string | null = null
  const drafts = new Map<string, string>()
  return async (mode: string) => {
    if (mode === options.mode.value) return
    const previous = options.mode.value
    if (previous === 'core:agent') agentSession = options.session.value
    drafts.set(previous, options.draft.value)
    // The App Server client is connection-scoped and already supports
    // switchThread. Keep it alive across modes so entering a plugin does not
    // pay a fresh socket initialize + resume cycle.
    options.reset()
    options.session.value = null
    options.mode.value = mode
    options.draft.value = drafts.get(mode) || ''
    if (mode === 'core:agent' && agentSession) {
      const session = options.sessions().find(item => item.id === agentSession)
      if (session && !isInternalSession(session)) await options.select(session.id)
    }
    if (options.mode.value === mode) options.draft.value = drafts.get(mode) || ''
  }
}
