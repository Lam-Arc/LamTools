
import { t } from '../i18n/index'
import type { CoreSubAgentRun, CoreSubAgentStatus } from '../types'

/** Durable run status → UI label. One vocabulary for the pane, the dialog and
 * the rail so the same run never reads differently in two places. */
export function subAgentStatusLabel(status: CoreSubAgentStatus | string): string {
  if (status === 'running') return t("运行中")
  if (status === 'pending') return t("等待中")
  if (status === 'paused') return t("已暂停")
  if (status === 'interrupted') return t("已中断")
  if (status === 'closed') return t("已关闭")
  if (status === 'idle') return t("空闲")
  if (status === 'error') return t("失败")
  return t("已完成")
}

/** Raw delegation kind → the two-token vocabulary every sub-agent surface
 * shares (`consider` / `execute`). */
export function normalizeSubAgentType(value: unknown): 'consider' | 'execute' {
  const raw = String(value || '').toLowerCase()
  return raw.includes('consider') || raw.includes('think') || raw.includes('reason')
    ? 'consider'
    : 'execute'
}

/**
 * Durable identity of a projected run: the child session id leads, the run id is
 * the fallback. Stable across the per-frame rebuilds of the run object while the
 * child streams, so a watcher can tell "same run, new frame" from "a different
 * run". Watchers keyed on the run object itself fire on every projection change
 * (a new object each frame), which is how the durable-record refresh became a
 * per-frame RPC.
 */
export function subAgentRunIdentity(
  run: Pick<CoreSubAgentRun, 'subSessionId' | 'id'> | null | undefined,
): string {
  if (!run) return ''
  return String(run.subSessionId || run.id || '').trim()
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
