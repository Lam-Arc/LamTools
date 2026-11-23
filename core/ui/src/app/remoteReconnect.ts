/**
 * 断线重连策略与「能不能显示已连接」的判定。
 *
 * user:“自动恢复：Wi-Fi/移动网络切换、电脑休眠唤醒、Core 重启后自动恢复”“短暂断线尽量
 * 无感（不弹提示），持续异常才轻量提示”“只有业务真正可用才显示「已连接电脑」”+
 * (策略必须只有一份：界面、宿主、CLI 说的是同一套节奏和同一套判定，否则会出现「CLI 已经
 * 恢复、界面还在转圈」)。
 *
 * 这里刻意不 import 任何 Tauri/宿主 API：纯函数才能被单测，也才能在手机与桌面两端共用。
 */

/** 第 attempt 次重试前等多久（毫秒，1-based）。先快后慢，封顶 5 秒。 */
export function retryDelayMs(attempt: number): number {
  const step = Math.max(1, Math.floor(attempt))
  const raw = 1_000 * 2 ** Math.min(step - 1, 3)
  return Math.min(raw, 5_000)
}

/** 最多重试几次；用完就看用户要不要手动重连，不能无限撞。 */
export const MAX_RECONNECT_ATTEMPTS = 20

/**
 * user:“短暂断线尽量无感（不弹提示），持续异常才轻量提示”+
 * (20 秒之内自己连回去就别打扰用户)。
 */
export const NOTICE_AFTER_MS = 20_000

export function shouldNotify(elapsedMs: number): boolean {
  return elapsedMs >= NOTICE_AFTER_MS
}

/** 宿主给的状态（`p2p_status` 的子集；老宿主没有这些字段时按老语义处理）。 */
export interface LayeredStatus {
  view?: string
  reason?: string
  layers?: {
    transport?: boolean
    device?: string
    core?: string
    session?: string
  }
  connected?: boolean
  connecting?: boolean
  peer?: string | null
}

/**
 * 这条连接现在能不能当成「可用」。
 *
 * user:“只有业务真正可用才显示「已连接电脑」；Core 无响应时必须降级显示”+
 * (老宿主只给 connected，新宿主给 view；两者都认，但 degraded / connecting / offline
 *  一律不算可用，哪怕隧道还活着)。
 */
export function isUsable(status: LayeredStatus | null | undefined): boolean {
  if (!status) return false
  if (typeof status.view === 'string') {
    return status.view === 'connected'
  }
  return status.connected === true && status.connecting !== true
}

/** 为什么现在不是可用状态：一句话，能直接显示给用户。 */
export function explainStatus(status: LayeredStatus | null | undefined): string {
  if (!status) return '还没有连接到电脑'
  const reason = status.reason || ''
  switch (reason) {
    case 'core_unavailable':
      return '电脑上的 Sunday 没有响应'
    case 'device_rejected':
      return '这台设备没有被电脑接受（可能已被移除授权）'
    case 'session_not_resumed':
      return '正在恢复会话'
    case 'transport_down':
      return '和电脑的连接断了'
    case 'no_device':
      return '还没有设备连上这台电脑'
    case 'start_failed':
      return '远程访问服务没有启动'
    default:
      break
  }
  if (status.view === 'degraded') return '连接不可用，正在重试'
  if (status.view === 'connecting' || status.connecting) return '正在连接电脑'
  if (status.view === 'waiting') return '等待手机连接'
  if (status.view === 'offline') return '远程访问未开启'
  return '还没有连接到电脑'
}

/** 断线横幅的判定结果。 */
export interface OutageBanner {
  visible: boolean
  text: string
}

/**
 * user:“短暂断线尽量无感（不弹提示），持续异常才轻量提示”+
 * (这条判定以前散在界面里：什么时候弹横幅、弹什么字，没有一处能被单测。现在只剩一个
 * 纯函数：连着就不弹；断得短不弹；超过阈值才弹，并说清是断了还是在降级)。
 */
export function outageBanner(input: {
  elapsedMs: number
  status: LayeredStatus | null | undefined
}): OutageBanner {
  if (isUsable(input.status)) {
    return { visible: false, text: '' }
  }
  if (!shouldNotify(Math.max(0, input.elapsedMs))) {
    return { visible: false, text: '' }
  }
  if (!input.status) {
    return { visible: true, text: '和电脑的连接断了，仍在自动重连' }
  }
  return { visible: true, text: explainStatus(input.status) }
}
