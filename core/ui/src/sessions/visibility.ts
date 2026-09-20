import type { CoreSessionListItem } from '../types'

export function isPluginOwnedSession(session: CoreSessionListItem | undefined): boolean {
  return typeof session?.metadata?.owner_plugin === 'string'
    && Boolean(session.metadata.owner_plugin)
}

/** Internal orchestration threads must never be offered as Core conversations. */
export function isInternalSession(session: CoreSessionListItem | undefined): boolean {
  return isPluginOwnedSession(session)
    || Boolean(session?.id.startsWith('workflow_thread_'))
    || Boolean(session?.id.startsWith('workflow:'))
    || session?.id === 'study:main'
}
