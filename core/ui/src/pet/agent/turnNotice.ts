/**
 * 回合终态通知判定（纯函数）。
 *
 * user:“特别补齐任务完成通知，不能仅仅有通知气泡 UI，却没有可靠的上游事件来源”+
 * (状态来自 App Server 的 core/runItem status 事件，经 SessionChannel.turnStatus()
 *  暴露。这里只判断“真实活跃回合 → 终态”的迁移；首次快照直接是终态时不补发，
 *  避免启动时把历史任务当成刚完成。)
 */

export type TurnNoticeStatus = 'completed' | 'failed' | 'cancelled'

export interface TurnNotice {
  status: TurnNoticeStatus
  title: string
  body: string
}

function isActive(status: string | undefined): boolean {
  return status === 'running' || status === 'waiting' || status === 'interrupting'
}

/**
 * previous 为空表示第一次看到这个会话；返回 null。
 * 只有 previous 是活跃状态、current 是终态时才产生通知。
 */
export function turnCompletionNotice(
  previous: string | undefined,
  current: string,
): TurnNotice | null {
  if (!previous || !isActive(previous)) return null
  if (current === 'completed') {
    return { status: current, title: '任务完成', body: '本轮任务已结束，可以在主界面继续追问。' }
  }
  if (current === 'failed') {
    return { status: current, title: '任务失败', body: '本轮任务失败，详情可回到主界面查看。' }
  }
  if (current === 'cancelled') {
    return { status: current, title: '任务已停止', body: '本轮任务已停止，未完成的内容仍保留在会话里。' }
  }
  return null
}

/**
 * 每个会话记住上一次看到的状态。
 *
 * user:“当一个会话结束后，桌宠上面并没有触发通知”+
 * (通道已经常开，但没有任何地方把 turnStatus 的迁移转成通知气泡：
 *  轮询每 1.2 秒读一次状态，靠这里判断“活跃 → 终态”的那一次跳变，
 *  第一次看到某会话只记状态、不补发历史通知。)
 */
export class TurnNoticeTracker {
  private readonly last = new Map<string, string>()

  observe(sessionId: string, status: string): TurnNotice | null {
    const previous = this.last.get(sessionId)
    this.last.set(sessionId, status)
    return turnCompletionNotice(previous, status)
  }

  forget(sessionId: string): void {
    this.last.delete(sessionId)
  }

  reset(): void {
    this.last.clear()
  }
}

/** 通知气泡策略：与 config.bubbles.done 同一组取值。 */
export type TurnNoticePolicy = 'popup' | 'badge' | 'silent'

export interface TurnNoticeBubble {
  id: string
  kind: 'notification'
  title: string
  body: string
  expanded: boolean
}

/**
 * 通知 → 气泡参数。
 *
 * id 带状态和时间：同一会话连着跑完两轮是两次通知，不能被 pushBubble 的去重吃掉。
 * silent 直接不出，与设置面板里“任务完成 = 静默”保持一致。
 */
export function turnNoticeBubble(
  sessionId: string,
  notice: TurnNotice,
  policy: TurnNoticePolicy,
  at: number,
): TurnNoticeBubble | null {
  if (policy === 'silent') return null
  return {
    id: `${sessionId}:done:${notice.status}:${at}`,
    kind: 'notification',
    title: notice.title,
    body: notice.body,
    expanded: policy === 'popup',
  }
}
