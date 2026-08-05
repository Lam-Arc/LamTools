export type SessionWithId = { id: string }

export function removeSessionsByIds<T extends SessionWithId>(sessions: T[], ids: ReadonlySet<string>): T[] {
  if (ids.size === 0) return sessions
  return sessions.filter((session) => !ids.has(session.id))
}
