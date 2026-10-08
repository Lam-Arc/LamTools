import type { CoreSubAgentStatus } from '../types'

/** Durable run status → UI label. One vocabulary for the pane, the dialog and
 * the rail so the same run never reads differently in two places. */
export function subAgentStatusLabel(status: CoreSubAgentStatus | string): string {
  if (status === 'running') return '运行中'
  if (status === 'pending') return '等待中'
  if (status === 'paused') return '已暂停'
  if (status === 'interrupted') return '已中断'
  if (status === 'closed') return '已关闭'
  if (status === 'idle') return '空闲'
  if (status === 'error') return '失败'
  return '已完成'
}

/** Raw delegation kind → the two-token vocabulary every sub-agent surface
 * shares (`consider` / `execute`). */
export function normalizeSubAgentType(value: unknown): 'consider' | 'execute' {
  const raw = String(value || '').toLowerCase()
  return raw.includes('consider') || raw.includes('think') || raw.includes('reason')
    ? 'consider'
    : 'execute'
}

/** Elapsed duration → compact label (`840ms` / `12.4s` / `27m 10s`). */
export function formatSubAgentElapsed(value: number | null | undefined): string {
  const ms = Math.max(0, Number.isFinite(Number(value)) ? Number(value) : 0)
  if (ms < 1000) return `${Math.round(ms)}ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`
  const minutes = Math.floor(seconds / 60)
  const remainder = Math.floor(seconds % 60)
  return `${minutes}m ${String(remainder).padStart(2, '0')}s`
}
