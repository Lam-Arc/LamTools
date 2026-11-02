import type { CoreSessionListItem } from '@/types.ts'

/**
 * user:“做完了还是在这转啊”“也没有弹窗提示”“只有点进去才知道已经完成任务了”
 * +(侧栏状态点原本只在“当前打开的会话”里更新，后台会话跑完也不会刷新——用户必须
 *   先点进那个会话才看得到“已完成”。这里把“上一份列表 → 新列表”的状态变化识别
 *   出来，由应用外壳弹一条可点击的提示。)
 */
const BUSY_STATUSES = new Set(['running', 'waiting', 'pending', 'sub_agents', 'interrupting'])
const SETTLED_STATUSES = new Set(['completed', 'done', 'failed', 'error', 'cancelled'])

export function isBusySessionStatus(status?: string | null): boolean {
  return BUSY_STATUSES.has(String(status || '').trim().toLowerCase())
}

export function isSettledSessionStatus(status?: string | null): boolean {
  return SETTLED_STATUSES.has(String(status || '').trim().toLowerCase())
}

export type FinishedSessionStatus = 'completed' | 'failed'

export interface FinishedSessionNotice {
  id: string
  title: string
  status: FinishedSessionStatus
}

export interface SelectFinishedSessionNoticesOptions {
  /** The session the user is already watching: its completion is visible. */
  activeSessionId?: string | null
}

/**
 * Sessions that were busy in `previous` and settled in `next`, excluding the
 * active one and user-requested stops (those do not need a popup).
 */
export function selectFinishedSessionNotices(
  previous: readonly CoreSessionListItem[],
  next: readonly CoreSessionListItem[],
  options: SelectFinishedSessionNoticesOptions = {},
): FinishedSessionNotice[] {
  const activeSessionId = options.activeSessionId || ''
  const previousStatuses = new Map(
    previous.map((session) => [session.id, String(session.status || '').trim().toLowerCase()]),
  )
  const notices: FinishedSessionNotice[] = []
  for (const session of next) {
    if (session.id === activeSessionId) continue
    if (!isBusySessionStatus(previousStatuses.get(session.id))) continue
    const status = String(session.status || '').trim().toLowerCase()
    if (!isSettledSessionStatus(status) || status === 'cancelled') continue
    notices.push({
      id: session.id,
      title: session.title || `Session ${session.id.slice(0, 8)}`,
      status: status === 'failed' || status === 'error' ? 'failed' : 'completed',
    })
  }
  return notices
}
