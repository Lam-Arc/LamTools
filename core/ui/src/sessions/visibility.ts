import type { CoreSessionListItem } from '@/types.ts'

export function isPluginOwnedSession(session: CoreSessionListItem | undefined): boolean {
  return typeof session?.metadata?.owner_plugin === 'string'
    && Boolean(session.metadata.owner_plugin)
}

/** Internal orchestration threads must never be offered as Core conversations. */
export function isInternalSessionId(id: string | null | undefined): boolean {
  const value = String(id || '')
  return value.startsWith('workflow_thread_')
    || value.startsWith('workflow:')
    || value === 'study:main'
}

export function isInternalSession(session: CoreSessionListItem | undefined): boolean {
  return isPluginOwnedSession(session) || isInternalSessionId(session?.id)
}
