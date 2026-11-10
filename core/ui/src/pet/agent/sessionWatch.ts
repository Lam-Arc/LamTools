/**
 * 桌宠的会话守望：把“所有会话”压成一份可执行的计划。
 *
 * user:“改让桌宠盯所有会话 不只是一个会话，自己去考虑边界情况与设计”+
 * (发现来自后端全局 /sessions，一条请求拿到全部会话与状态。守望器只做三件事：
 *  一、上一轮忙、这一轮落定 → 弹一次完成通知，不把历史任务当成刚完成；
 *  二、只有“可能产生审批/提问”的会话才常开通道，忙的、绑定到桌宠的、
 *      还有未处理气泡的；其余不订阅，避免几十条会话各挂一条 App Server 订阅；
 *  三、通道有上限，落定后再留一段宽限期接收晚到的审批，过期就释放。)
 */
import { isBusySessionStatus, isSettledSessionStatus } from '@/sessions/completion.ts'
import type { PetProjectSession } from './client.ts'

/** 常开通道的默认上限：只为“可能弹审批”的会话付费，不随会话总数增长。 */
export const WATCH_MAX_CHANNELS = 8
/** 会话落定后通道再留多久：给晚到的审批/提问留窗口。 */
export const WATCH_SETTLED_GRACE_MS = 60_000

export interface WatchOptions {
  now: number
  /** 绑定到某只桌宠的聊天目标：无论忙闲都保留通道。 */
  bound: ReadonlySet<string>
  /** 头上还挂着未处理审批/提问气泡的会话：通道不能释放，否则用户点了没处提交。 */
  pending: ReadonlySet<string>
  maxChannels?: number
  settledGraceMs?: number
}

export interface WatchPlan {
  /** 需要常开通道的会话，顺序即优先级。 */
  subscribe: PetProjectSession[]
  /** 本轮刚落定的会话：弹完成通知。 */
  finished: PetProjectSession[]
  /** 因为超出上限没订阅的会话数：只用于诊断，通知不受影响。 */
  dropped: number
}

export type WatchBinding = {
  sessionId?: string | null
  temporarySessionId?: string | null
}

function normalizeStatus(value: string | undefined): string {
  return String(value || '').trim().toLowerCase()
}

function stamp(value: string | number | undefined): number {
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0
  if (typeof value === 'string' && value) {
    const parsed = Date.parse(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return 0
}

export class SessionWatcher {
  /** 上一轮看到的状态：判“忙 → 落定”的一次跳变。 */
  private readonly statuses = new Map<string, string>()
  /** 落定的时间点：宽限期从这里开始算。 */
  private readonly settledAt = new Map<string, number>()

  observe(sessions: readonly PetProjectSession[], options: WatchOptions): WatchPlan {
    const now = options.now
    const maxChannels = Math.max(1, options.maxChannels ?? WATCH_MAX_CHANNELS)
    const grace = Math.max(0, options.settledGraceMs ?? WATCH_SETTLED_GRACE_MS)

    // 插件/内部编排会话不参与守望：没有人会给它们发审批，通知也只会变成噪音。
    const live = sessions.filter(session => session && session.id && !session.internal)
    const seen = new Set(live.map(session => session.id))
    for (const id of [...this.statuses.keys()]) {
      if (seen.has(id)) continue
      // 会话被删掉/归档：把记忆一起丢掉，免得同名 id 复用时误判。
      this.statuses.delete(id)
      this.settledAt.delete(id)
    }

    const finished: PetProjectSession[] = []
    for (const session of live) {
      const previous = this.statuses.get(session.id)
      const current = normalizeStatus(session.status)
      // 用户自己停的不通知，与主界面侧栏的完成提示同一口径。
      if (isBusySessionStatus(previous) && isSettledSessionStatus(current) && current !== 'cancelled') {
        finished.push(session)
      }
      if (isBusySessionStatus(current)) {
        this.settledAt.delete(session.id)
      } else if (isSettledSessionStatus(current) && !this.settledAt.has(session.id)) {
        // 只有“刚跑完”的会话才给宽限：第一次看到就已经落定的历史会话
        // 和桌宠没关系，给它留通道只会白白占掉上限。
        if (isBusySessionStatus(previous)) this.settledAt.set(session.id, now)
      }
      this.statuses.set(session.id, current)
    }

    const mandatory: PetProjectSession[] = []
    const busy: PetProjectSession[] = []
    const graceLeft: PetProjectSession[] = []
    for (const session of live) {
      if (options.bound.has(session.id) || options.pending.has(session.id)) {
        mandatory.push(session)
        continue
      }
      const current = normalizeStatus(session.status)
      if (isBusySessionStatus(current)) {
        busy.push(session)
        continue
      }
      const settled = this.settledAt.get(session.id)
      if (settled !== undefined && now - settled <= grace) graceLeft.push(session)
    }

    const byRecent = (a: PetProjectSession, b: PetProjectSession): number => stamp(b.updatedAt) - stamp(a.updatedAt)
    busy.sort(byRecent)
    graceLeft.sort(byRecent)

    const subscribe = [...mandatory]
    let dropped = 0
    for (const session of [...busy, ...graceLeft]) {
      if (subscribe.length >= maxChannels) {
        dropped += 1
        continue
      }
      subscribe.push(session)
    }

    return { subscribe, finished, dropped }
  }

  /** 当前还记得多少会话状态：调试/测试用。 */
  size(): number {
    return this.statuses.size
  }
}

/**
 * 通知落在谁头上。
 *
 * user:“改让桌宠盯所有会话”+(一条通知总要有个宠物来背：优先该会话绑定的那只，
 *  其次第一只可见的，再次任意一只；一只都没有就不出气泡，因为气泡要靠宠物定位。)
 */
export function resolveWatchPet(
  bindings: Record<string, WatchBinding | undefined>,
  pets: readonly { id: string; visible?: boolean }[],
  sessionId: string,
): string {
  for (const pet of pets) {
    const binding = bindings[pet.id]
    if (!binding) continue
    if (binding.temporarySessionId === sessionId || binding.sessionId === sessionId) return pet.id
  }
  return pets.find(pet => pet.visible !== false)?.id || pets[0]?.id || ''
}
