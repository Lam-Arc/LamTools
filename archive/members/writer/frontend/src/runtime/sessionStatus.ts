const TERMINAL_SESSION_STATUSES = new Set(['completed', 'failed'])
const PASSIVE_REPLAY_SESSION_STATUSES = new Set(['idle', 'completed', 'failed', 'waiting'])

export function isTerminalSessionStatus(status: unknown): boolean {
  return TERMINAL_SESSION_STATUSES.has(String(status || '').toLowerCase())
}

export function isPassiveReplaySessionStatus(status: unknown): boolean {
  return PASSIVE_REPLAY_SESSION_STATUSES.has(String(status || '').toLowerCase())
}
