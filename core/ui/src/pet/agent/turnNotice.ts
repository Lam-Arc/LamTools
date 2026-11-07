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
