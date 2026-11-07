/**
 * 气泡请求状态（纯函数）。
 *
 * user:“不能通过 ".slice(-8)" 直接截断所有气泡，导致未处理审批从界面消失”+
 * “不得把折叠或暂时隐藏的请求从待处理数量里错误移除”+
 * “不得因为多个请求标题相同就误判重复”+
 * (这里只维护可测试的状态规则：请求用「会话 + requestId」做稳定身份，折叠只影响
 *  显示，解决/过期/取消才把请求移出待处理；普通通知单独限流，永远不挤掉审批。)
 */

export type BubbleKind = 'notification' | 'actionable' | 'session'

export interface BubbleOption {
  id: string
  label: string
  response?: string
}

export interface BubbleState {
  id: string
  petId: string
  sessionId: string
  kind: BubbleKind
  title: string
  /** 一句话请求（去掉“需要确认：”前缀）。 */
  subject: string
  body: string
  /** 来源面包屑：项目 - 会话 - 子代理。 */
  source: string
  requestId: string | null
  isQuestion: boolean
  options: BubbleOption[]
  createdAt: number
  updatedAt: number
  /** 当前是否展开为完整卡片。折叠只是显示状态，不影响请求本身。 */
  expanded: boolean
  /** 用户主动展开过：新请求到达时不自动收起它。 */
  userExpanded: boolean
  /** 后端已解决/过期/取消：不再是待处理请求。 */
  resolved: boolean
  /** 普通通知被用户关掉；审批/提问不允许用 hidden 隐藏。 */
  hidden: boolean
  handling: boolean
  error: string
  /** 连续轮询中不在后端决策池里的次数：连续消失才认定已解决，避免瞬时抖动误删。 */
  absentPolls: number
}

export interface BubbleInput {
  id: string
  petId: string
  sessionId: string
  kind: BubbleKind
  title: string
  subject?: string
  body: string
  source?: string
  requestId?: string | null
  isQuestion?: boolean
  options?: BubbleOption[]
  /** 新气泡是否自动展开（通知的 popup 策略 / 最新的审批）。 */
  expand?: boolean
}

export interface UpsertOptions {
  now?: number
  /** 自动展开上限（只约束自动展开；用户手动展开不受限）。 */
  maxAutoExpanded?: number
}

/** 连续缺席多少次轮询后认定请求已解决（1.2s 一轮 ≈ 2.4s 防抖）。 */
export const REQUEST_ABSENT_CONFIRM_POLLS = 2
/** 已解决气泡在界面上的残留时间：让用户看到它被处理，再移除。 */
export const RESOLVED_LINGER_MS = 2_500
/** 普通通知最多保留数量（不含待处理审批/提问）。 */
export const MAX_NOTIFICATIONS = 12
/** 普通通知默认过期时间。 */
export const NOTIFICATION_TTL_MS = 10 * 60_000

/** 稳定请求身份：同一会话同一 requestId 永远对应同一个气泡。 */
export function requestBubbleId(sessionId: string, requestId: string): string {
  return `request:${sessionId}:${requestId}`
}

/** 普通通知必须每次都拿到唯一 id，不能靠标题去重。 */
export function notificationBubbleId(serial: number): string {
  return `notice:${serial}`
}

export function isPendingBubble(bubble: BubbleState): boolean {
  return bubble.kind === 'actionable' && !bubble.resolved && !bubble.hidden
}

export function isVisibleBubble(bubble: BubbleState): boolean {
  return !bubble.hidden && !bubble.resolved
}

export function pendingBubbleCount(list: BubbleState[]): number {
  return list.filter(isPendingBubble).length
}

export function findBubble(list: BubbleState[], id: string): BubbleState | undefined {
  return list.find(bubble => bubble.id === id)
}

function cloneBubble(bubble: BubbleState, patch: Partial<BubbleState>): BubbleState {
  return { ...bubble, ...patch }
}

function replaceBubble(list: BubbleState[], next: BubbleState): BubbleState[] {
  return list.map(bubble => (bubble.id === next.id ? next : bubble))
}

/**
 * 新请求自动展开，同时把「自动展开」的旧气泡收起。
 *
 * 用户手动展开的气泡标记 userExpanded，不会被新请求挤掉；maxAutoExpanded
 * 只限制自动展开数量，不限制用户同时展开多个。
 */
function autoExpand(
  list: BubbleState[],
  newId: string,
  maxAutoExpanded: number,
): BubbleState[] {
  if (maxAutoExpanded <= 0) return list
  const target = findBubble(list, newId)
  if (!target || target.expanded) return list
  const others = list
    .filter(bubble => (
      bubble.id !== newId
      && bubble.expanded
      && !bubble.userExpanded
      && !bubble.resolved
      && !bubble.hidden
    ))
    .sort((a, b) => b.updatedAt - a.updatedAt)
  const keep = Math.max(0, maxAutoExpanded - 1)
  const keepIds = new Set(others.slice(0, keep).map(bubble => bubble.id))
  return list.map(bubble => {
    if (bubble.id === newId) return cloneBubble(bubble, { expanded: true })
    if (others.some(item => item.id === bubble.id) && !keepIds.has(bubble.id)) {
      return cloneBubble(bubble, { expanded: false })
    }
    return bubble
  })
}

/**
 * 插入或更新一条气泡。同一 requestId 只更新原气泡，绝不重复创建；
 * 普通通知每次都是独立气泡，标题相同也不会被误判为重复。
 */
export function upsertBubble(
  list: BubbleState[],
  input: BubbleInput,
  options: UpsertOptions = {},
): BubbleState[] {
  const now = options.now ?? Date.now()
  const existing = list.find(bubble => bubble.id === input.id)
  if (existing) {
    const revived = existing.resolved && input.kind === 'actionable'
    const next = cloneBubble(existing, {
      petId: input.petId || existing.petId,
      sessionId: input.sessionId,
      kind: input.kind,
      title: input.title,
      subject: input.subject || input.title,
      body: input.body,
      source: input.source ?? existing.source,
      requestId: input.requestId ?? existing.requestId,
      isQuestion: Boolean(input.isQuestion),
      options: input.options || [],
      updatedAt: now,
      resolved: revived ? false : existing.resolved,
      hidden: revived ? false : existing.hidden,
      absentPolls: 0,
    })
    return replaceBubble(list, next)
  }
  const created: BubbleState = {
    id: input.id,
    petId: input.petId,
    sessionId: input.sessionId,
    kind: input.kind,
    title: input.title,
    subject: input.subject || input.title,
    body: input.body,
    source: input.source || '',
    requestId: input.requestId || null,
    isQuestion: Boolean(input.isQuestion),
    options: input.options || [],
    createdAt: now,
    updatedAt: now,
    expanded: Boolean(input.expand),
    userExpanded: false,
    resolved: false,
    hidden: false,
    handling: false,
    error: '',
    absentPolls: 0,
  }
  const withNew = [...list, created]
  // 只有审批/提问参与「自动展开一个」的竞争；通知按自己的策略展开。
  // expand=false 是 silent 策略：保留收纳入口，但不主动弹开。
  if (input.kind !== 'actionable' || input.expand === false) return withNew
  return autoExpand(withNew, created.id, options.maxAutoExpanded ?? 1)
}

/** 用户点击展开/折叠：手动展开不受自动上限约束。 */
export function toggleBubbleExpanded(list: BubbleState[], id: string): BubbleState[] {
  const bubble = findBubble(list, id)
  if (!bubble || bubble.resolved || bubble.hidden) return list
  return replaceBubble(list, cloneBubble(bubble, {
    expanded: !bubble.expanded,
    userExpanded: !bubble.expanded,
  }))
}

export function expandBubble(list: BubbleState[], id: string): BubbleState[] {
  const bubble = findBubble(list, id)
  if (!bubble || bubble.resolved || bubble.hidden) return list
  if (bubble.expanded && bubble.userExpanded) return list
  return replaceBubble(list, cloneBubble(bubble, { expanded: true, userExpanded: true }))
}

export function foldBubble(list: BubbleState[], id: string): BubbleState[] {
  const bubble = findBubble(list, id)
  if (!bubble) return list
  return replaceBubble(list, cloneBubble(bubble, { expanded: false, userExpanded: false }))
}

/** 一键收起：只改变显示，不解决、不拒绝任何请求。 */
export function foldAllBubbles(list: BubbleState[]): BubbleState[] {
  return list.map(bubble => (
    bubble.expanded ? cloneBubble(bubble, { expanded: false, userExpanded: false }) : bubble
  ))
}

/**
 * 关闭气泡。
 * - 审批/提问：只折叠，待处理数量不变（关闭 ≠ 拒绝/取消）。
 * - 普通通知：标记隐藏，可以真正从界面移除。
 */
export function dismissBubbleState(list: BubbleState[], id: string): BubbleState[] {
  const bubble = findBubble(list, id)
  if (!bubble) return list
  if (bubble.kind === 'actionable') {
    return replaceBubble(list, cloneBubble(bubble, { expanded: false, userExpanded: false }))
  }
  return replaceBubble(list, cloneBubble(bubble, { hidden: true, expanded: false, userExpanded: false }))
}

/** 提交成功/后端确认解决：立即从待处理里移除。 */
export function resolveBubbleState(list: BubbleState[], id: string): BubbleState[] {
  const bubble = findBubble(list, id)
  if (!bubble) return list
  return replaceBubble(list, cloneBubble(bubble, {
    resolved: true,
    expanded: false,
    userExpanded: false,
    handling: false,
    absentPolls: 0,
    updatedAt: Date.now(),
  }))
}

export function setBubbleHandling(list: BubbleState[], id: string, handling: boolean, error = ''): BubbleState[] {
  const bubble = findBubble(list, id)
  if (!bubble) return list
  return replaceBubble(list, cloneBubble(bubble, { handling, error }))
}

/**
 * 用真实决策池对账：某会话的请求从后端消失（已解决/过期/取消）时，
 * 连续缺席两轮才标记解决；重新出现则清零。
 */
export function reconcileSessionRequests(
  list: BubbleState[],
  sessionId: string,
  presentRequestIds: Iterable<string>,
): BubbleState[] {
  const present = new Set(presentRequestIds)
  let changed = false
  const next = list.map(bubble => {
    if (
      bubble.kind !== 'actionable'
      || bubble.sessionId !== sessionId
      || !bubble.requestId
      || bubble.resolved
      || bubble.hidden
    ) return bubble
    if (present.has(bubble.requestId)) {
      if (bubble.absentPolls === 0) return bubble
      changed = true
      return cloneBubble(bubble, { absentPolls: 0 })
    }
    const absentPolls = bubble.absentPolls + 1
    changed = true
    if (absentPolls < REQUEST_ABSENT_CONFIRM_POLLS) {
      return cloneBubble(bubble, { absentPolls })
    }
    return cloneBubble(bubble, {
      resolved: true,
      expanded: false,
      userExpanded: false,
      handling: false,
      absentPolls,
    })
  })
  return changed ? next : list
}

/**
 * 淘汰：普通通知按数量/时间限流；待处理审批/提问永远不因数量被删。
 * 已解决的气泡留一小段时间再移除，避免界面突兀。
 */
export function pruneBubbles(
  list: BubbleState[],
  options: { now?: number; maxNotifications?: number; notificationTtlMs?: number; resolvedLingerMs?: number } = {},
): BubbleState[] {
  const now = options.now ?? Date.now()
  const maxNotifications = options.maxNotifications ?? MAX_NOTIFICATIONS
  const ttl = options.notificationTtlMs ?? NOTIFICATION_TTL_MS
  const linger = options.resolvedLingerMs ?? RESOLVED_LINGER_MS
  const notices = list
    .filter(bubble => bubble.kind !== 'actionable' && !bubble.hidden)
    .sort((a, b) => b.createdAt - a.createdAt)
  const keepNoticeIds = new Set(notices.slice(0, maxNotifications).map(bubble => bubble.id))
  return list.filter(bubble => {
    if (bubble.kind === 'actionable') {
      // 待处理与刚解决的审批都保留到 UI 完成过渡；不会因数量被丢掉。
      if (!bubble.resolved) return true
      return now - bubble.updatedAt < linger
    }
    if (bubble.hidden) return false
    if (!keepNoticeIds.has(bubble.id)) return false
    return now - bubble.createdAt < ttl
  })
}
