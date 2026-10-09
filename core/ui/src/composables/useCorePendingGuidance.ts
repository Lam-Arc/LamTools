import { computed, ref, watch, type Ref } from 'vue'
import { coreInputToText } from '../appServer/workbenchProjection.ts'
import type { CoreAppSnapshot } from '../appServer/protocol.ts'
import type { CoreInputItem, MessagePart } from '../types'

export interface CorePendingGuidanceOptions {
  snapshot: Readonly<Ref<CoreAppSnapshot | null | undefined>>
  activeThreadId: Readonly<Ref<string | null>>
  composerText: Ref<string>
  queueInput(threadId: string, input: CoreInputItem[]): Promise<void>
  onError?(message: string): void
}

interface PendingGuidanceEntry {
  key: string
  threadId: string
  turnId: string
  text: string
}

const TERMINAL_TURN_STATUSES = new Set(['completed', 'failed', 'cancelled', 'skipped'])

/**
 * 已发出、还没被模型接手的引导。
 *
 * 后端有意等到"模型真正把这条指令吃进去"的那一刻才产生引导条目——只有那时它才
 * 落在正确的步骤位置上。代价是发出去的引导要等一个步骤跑完才看得见；这里先在
 * 过程末尾挂一个"待生效"气泡（虚线 + 呼吸），真实条目落库后撤下。
 *
 * 如果这一轮在生效前就结束了（停止 / 失败），内容不丢：输入框空就放回输入框，
 * 否则退回"待发送"队列——那条指令本来就没被采纳，不该凭空消失。
 */
export function useCorePendingGuidance(options: CorePendingGuidanceOptions) {
  const entries = ref<PendingGuidanceEntry[]>([])
  // 每个待生效条目配一个 part 对象，生命周期与条目一致。挂在过程末尾的是同一个
  // 对象引用，投影缓存与 v-memo 才不会逐帧失效。
  const parts = new Map<string, MessagePart>()
  /** `turnId\0text` → 已经被待生效条目配对掉的落库条数（只增不减）。
   *  同一个 turn 里文本相同的引导可能有多条，必须一一配对：配对结果一旦确定就要
   *  记住，否则撤掉一条后，剩下的那条会被同一条落库记录再次"配对"，凭空消失。 */
  const consumedLands = new Map<string, number>()
  let sequence = 0

  /** 记录一条刚被服务端接受的引导。 */
  function track(threadId: string | null | undefined, turnId: string | null | undefined, value: unknown): void {
    const text = String(coreInputToText(value) || '').trim()
    const ownerThread = String(threadId || '')
    const ownerTurn = String(turnId || '')
    if (!text || !ownerThread || !ownerTurn) return
    const key = `pending-guide:${++sequence}`
    parts.set(key, {
      id: key,
      partType: 'guidance',
      status: 'pending',
      content: text,
      label: '引导',
      metadata: { guidancePending: true },
    })
    entries.value = [...entries.value, { key, threadId: ownerThread, turnId: ownerTurn, text }]
  }

  /** 这一轮里已落库的引导文本计数：用来判定待生效的条目是否已经生效。 */
  function landedCounts(turnId: string): Map<string, number> {
    const counts = new Map<string, number>()
    const snapshot = options.snapshot.value
    if (!snapshot) return counts
    // 只扫这一轮的条目（client 快照里 turn.items 就是这件轮次的条目 id 表），
    // 不遍历整条会话——这段评估跑在每一帧的投影路径上。
    const turn = snapshot.core?.turns?.[turnId] || snapshot.turns?.[turnId]
    const itemIds = Array.isArray(turn?.items) ? turn.items : []
    for (const rawId of itemIds) {
      const itemId = String(rawId)
      if (!itemId.includes(':user:guide:')) continue
      const item = snapshot.core?.items?.[itemId] || snapshot.items?.[itemId]
      if (!item) continue
      const payload = (item.payload && typeof item.payload === 'object' ? item.payload : {}) as Record<string, unknown>
      const text = (coreInputToText(item.content) || coreInputToText(payload.content)).trim()
      if (!text) continue
      counts.set(text, (counts.get(text) || 0) + 1)
    }
    return counts
  }

  function turnStatus(turnId: string): string {
    const snapshot = options.snapshot.value
    return String(
      snapshot?.core?.turns?.[turnId]?.status
      ?? snapshot?.turns?.[turnId]?.status
      ?? '',
    )
  }

  /**
   * 评估一次：哪些待生效条目该显示、哪些已经生效、哪些随这一轮结束而作废。
   * 同文本的引导可能有多条，按计数一一对应，不靠猜测。
   */
  function evaluate(): {
    visible: Array<{ turnId: string; part: MessagePart }>
    landed: Array<{ key: string; pairKey: string }>
    ended: PendingGuidanceEntry[]
  } {
    const visible: Array<{ turnId: string; part: MessagePart }> = []
    const landed: Array<{ key: string; pairKey: string }> = []
    const ended: PendingGuidanceEntry[] = []
    const threadId = String(options.activeThreadId.value || '')
    const countsByTurn = new Map<string, Map<string, number>>()
    // 本次评估内的配对增量（不落库；由 watcher 在撤下条目时提交）
    const passConsumed = new Map<string, number>()
    for (const entry of entries.value) {
      // 别的会话的待生效引导：等切回那个会话再判（切走不代表它没生效）
      if (entry.threadId !== threadId) continue
      let counts = countsByTurn.get(entry.turnId)
      if (!counts) {
        counts = landedCounts(entry.turnId)
        countsByTurn.set(entry.turnId, counts)
      }
      const pairKey = `${entry.turnId}\u0000${entry.text}`
      const consumed = (consumedLands.get(pairKey) || 0) + (passConsumed.get(pairKey) || 0)
      if ((counts.get(entry.text) || 0) > consumed) {
        passConsumed.set(pairKey, (passConsumed.get(pairKey) || 0) + 1)
        landed.push({ key: entry.key, pairKey })
        continue
      }
      if (TERMINAL_TURN_STATUSES.has(turnStatus(entry.turnId))) {
        ended.push(entry)
        continue
      }
      const part = parts.get(entry.key)
      if (part) visible.push({ turnId: entry.turnId, part })
    }
    return { visible, landed, ended }
  }

  /** 这一轮结束后，把没生效的引导交回用户：输入框空就回去，否则进待发送队列。 */
  async function returnToUser(entry: PendingGuidanceEntry): Promise<void> {
    if (entry.threadId === String(options.activeThreadId.value || '') && !options.composerText.value.trim()) {
      options.composerText.value = entry.text
      return
    }
    try {
      await options.queueInput(entry.threadId, [{ type: 'text', text: entry.text }])
    } catch (error) {
      // 队列都失败：退回输入框，内容绝不丢
      const current = options.composerText.value.replace(/\s+$/, '')
      options.composerText.value = current ? `${current}\n${entry.text}` : entry.text
      options.onError?.(error instanceof Error ? error.message : String(error))
    }
  }

  const guidanceParts = computed(() => (
    entries.value.length === 0 ? [] : evaluate().visible
  ))

  watch([options.snapshot, options.activeThreadId, entries], () => {
    if (entries.value.length === 0) return
    const { landed, ended } = evaluate()
    if (landed.length === 0 && ended.length === 0) return
    const landedKeys = new Set(landed.map(entry => entry.key))
    const endedKeys = new Set(ended.map(entry => entry.key))
    // 配对结果落账：撤下的这些条目已经把对应的落库记录"用完"，后续评估不再重复配对
    for (const entry of landed) {
      consumedLands.set(entry.pairKey, (consumedLands.get(entry.pairKey) || 0) + 1)
    }
    entries.value = entries.value.filter(entry => !landedKeys.has(entry.key) && !endedKeys.has(entry.key))
    for (const entry of landed) parts.delete(entry.key)
    for (const entry of ended) {
      parts.delete(entry.key)
      void returnToUser(entry)
    }
  })

  return { guidanceParts, track }
}
