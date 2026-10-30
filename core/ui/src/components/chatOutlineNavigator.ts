import type { CoreMessage } from '@/types.ts'

/** The compact outline row returned by the `thread.outline` RPC. */
export interface ChatOutlineItem {
  message_id: string
  turn_id: string
  seq: number
  timestamp: string
  prompt: string
  response_excerpt: string
}

export const CHAT_OUTLINE_ACTIVATION_RATIO = 0.38

// user:“上下竖向 > 分页，每页 20 条”+(左栏竖向翻页控件每页固定 20 条用户消息)
export const CHAT_OUTLINE_PAGE_SIZE = 20

/** Catalog filter dimension: guide instructions vs. ordinary prompts. */
// user:“区分引导消息与普通消息”+(目录卡片按类型筛选，引导与普通是两种不同的用户消息)
export type ChatOutlineKind = 'all' | 'guide' | 'normal'

/** Time ordering used by the catalog card. */
export type ChatOutlineSortDirection = 'asc' | 'desc'

/**
 * Mid-turn guidance reaches the transcript as its own user row whose id is the
 * only durable marker (`<turn>:user:guide:<event>`), so that suffix is what
 * separates guide instructions from ordinary user prompts.
 */
export function isGuideOutlineMessageId(messageId: string): boolean {
  return String(messageId || '').includes(':user:guide:')
}

export function isGuideOutlineItem(item: ChatOutlineItem | null | undefined): boolean {
  return isGuideOutlineMessageId(item?.message_id || '')
}

/** Total pages for a user-message count; an empty outline still has one page. */
export function outlinePageCount(total: number, pageSize = CHAT_OUTLINE_PAGE_SIZE): number {
  const size = Math.max(1, Math.floor(pageSize))
  return Math.max(1, Math.ceil(Math.max(0, Math.floor(total)) / size))
}

/** Keep a page number inside the available range. */
export function clampOutlinePage(
  page: number,
  total: number,
  pageSize = CHAT_OUTLINE_PAGE_SIZE,
): number {
  const last = outlinePageCount(total, pageSize) - 1
  const value = Number.isFinite(page) ? Math.floor(page) : 0
  return Math.max(0, Math.min(last, value))
}

export function sliceOutlinePage<T>(
  items: readonly T[],
  page: number,
  pageSize = CHAT_OUTLINE_PAGE_SIZE,
): T[] {
  const size = Math.max(1, Math.floor(pageSize))
  const start = clampOutlinePage(page, items.length, size) * size
  return items.slice(start, start + size)
}

export interface ChatOutlineCatalogEntry {
  item: ChatOutlineItem
  /** Position in the original (sequence) order, zero based. */
  index: number
  isGuide: boolean
  /** Parsed timestamp in ms, or null when the row has no usable time. */
  timestampMs: number | null
}

/**
 * Parse an outline timestamp. The server may send an ISO string, epoch
 * seconds, or epoch milliseconds; anything else yields null so ordering falls
 * back to the original sequence.
 */
export function parseOutlineTimestamp(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value > 0 && value < 1e12 ? Math.round(value * 1000) : Math.round(value)
  }
  const text = typeof value === 'string' ? value.trim() : ''
  if (!text) return null
  if (/^\d{9,14}$/.test(text)) {
    const number = Number(text)
    return Number.isFinite(number) ? (number < 1e12 ? Math.round(number * 1000) : number) : null
  }
  const parsed = Date.parse(text)
  return Number.isFinite(parsed) ? parsed : null
}

/** `HH:mm` for today, `MM-DD HH:mm` otherwise; empty when the row has no time. */
export function formatOutlineTimestamp(value: unknown, now: Date = new Date()): string {
  const ms = parseOutlineTimestamp(value)
  if (ms === null) return ''
  const date = new Date(ms)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (part: number): string => String(part).padStart(2, '0')
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`
  const sameDay = date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate()
  return sameDay
    ? time
    : `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${time}`
}

/**
 * Record every user message in its original order. The index travels with the
 * entry so later filtering and time sorting never lose the original position
 * used to jump back into the transcript.
 */
export function buildOutlineCatalog(items: readonly ChatOutlineItem[]): ChatOutlineCatalogEntry[] {
  return items.map((item, index) => ({
    item,
    index,
    isGuide: isGuideOutlineItem(item),
    timestampMs: parseOutlineTimestamp(item.timestamp),
  }))
}

/** Keyword search over prompt text plus the assistant excerpt, plus type filter. */
// user:“支持时间排序、关键词搜索和类型筛选”+(目录卡片能按关键词、消息类型筛出要跳转的那条)
export function filterOutlineCatalog(
  entries: readonly ChatOutlineCatalogEntry[],
  query: string,
  kind: ChatOutlineKind = 'all',
): ChatOutlineCatalogEntry[] {
  const needle = String(query || '').trim().toLowerCase()
  return entries.filter((entry) => {
    if (kind === 'guide' && !entry.isGuide) return false
    if (kind === 'normal' && entry.isGuide) return false
    if (!needle) return true
    const haystack = `${entry.item.prompt}\u0000${entry.item.response_excerpt}`.toLowerCase()
    return haystack.includes(needle)
  })
}

/**
 * Order catalog entries by their timestamp. Rows without a usable time stay
 * behind the timed ones in original order, for both directions, so the list is
 * always deterministic.
 */
export function sortOutlineCatalog(
  entries: readonly ChatOutlineCatalogEntry[],
  direction: ChatOutlineSortDirection = 'asc',
): ChatOutlineCatalogEntry[] {
  const timed = entries.filter((entry) => entry.timestampMs !== null)
  const untimed = entries.filter((entry) => entry.timestampMs === null)
  const ordered = [...timed].sort((left, right) => {
    const delta = (left.timestampMs as number) - (right.timestampMs as number)
    return direction === 'desc' ? -delta || right.index - left.index : delta || left.index - right.index
  })
  return [...ordered, ...untimed]
}

/**
 * The navigator intentionally keys refreshes on ids and roles only.  A
 * streamed answer changes the message objects frequently, but does not alter
 * the set of loaded user instructions, so those ticks must not refetch the
 * outline.
 */
export function loadedUserMessageSignature(messages: readonly CoreMessage[]): string {
  return messages
    .filter((message) => message.role === 'user' && Boolean(message.id))
    .map((message) => message.id)
    .join('\u001f')
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value)
}

function finiteNumber(value: unknown, fallback: number): number {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? number : fallback
}

/** Normalize an untrusted RPC envelope without making the render path throw. */
export function normalizeChatOutlinePayload(value: unknown): ChatOutlineItem[] {
  const payload = recordValue(value)
  if (!payload || !Array.isArray(payload.items)) return []

  const items: ChatOutlineItem[] = []
  payload.items.forEach((raw, index) => {
    const row = recordValue(raw)
    if (!row) return
    const messageId = stringValue(row.message_id).trim()
    if (!messageId) return
    items.push({
      message_id: messageId,
      turn_id: stringValue(row.turn_id),
      seq: finiteNumber(row.seq, index),
      timestamp: stringValue(row.timestamp),
      prompt: stringValue(row.prompt),
      response_excerpt: stringValue(row.response_excerpt),
    })
  })

  // The server normally sends sequence order. Sorting here keeps an eventual
  // paged/merged response deterministic while preserving duplicate rows.
  return items
    .map((item, index) => ({ item, index }))
    .sort((left, right) => left.item.seq - right.item.seq || left.index - right.index)
    .map(({ item }) => item)
}

export function nearestOutlineIndex(positions: readonly number[], target: number): number {
  if (positions.length === 0 || !Number.isFinite(target)) return -1
  let nearest = 0
  let distance = Math.abs(positions[0] - target)
  for (let index = 1; index < positions.length; index += 1) {
    const nextDistance = Math.abs(positions[index] - target)
    if (nextDistance < distance) {
      nearest = index
      distance = nextDistance
    }
  }
  return nearest
}

/**
 * Keep short conversations compact like ChatGPT's turn rail instead of
 * stretching a handful of markers from the top edge to the bottom edge.
 * Longer conversations progressively compress only when the group would no
 * longer fit inside the available thread viewport.
 */
export function compactOutlineMarkerPositions(
  count: number,
  trackTop: number,
  trackHeight: number,
  preferredGap: number,
): number[] {
  if (count <= 0) return []
  const center = trackTop + trackHeight / 2
  if (count === 1) return [center]
  const last = count - 1
  const gap = Math.min(
    Math.max(1, preferredGap),
    Math.max(0, trackHeight) / last,
  )
  const groupTop = center - (gap * last) / 2
  return Array.from({ length: count }, (_, index) => (
    groupTop + gap * index
  ))
}

export interface OutlineControlBracket {
  /** Top edge (px from the rail top) of the up-arrow stack. */
  top: number
  /** Top edge (px from the rail top) of the down-arrow stack. */
  bottom: number
}

/**
 * user:“紧贴标记组的上下边缘”+(上箭头贴在第一条标记上方，下箭头/目录/页码贴在最后一条标记下方)
 */
export function bracketOutlineControls(
  positions: readonly number[],
  gap: number,
  topControlsHeight: number,
  bottomControlsHeight: number,
  containerHeight: number,
): OutlineControlBracket {
  const spacing = Math.max(0, gap)
  if (positions.length === 0) return { top: spacing, bottom: spacing }
  const first = Math.min(...positions)
  const last = Math.max(...positions)
  const top = Math.max(0, first - spacing - Math.max(0, topControlsHeight))
  // Without a measured container the lower stack still hugs the last marker.
  const bottomLimit = containerHeight > 0
    ? Math.max(0, containerHeight - Math.max(0, bottomControlsHeight))
    : Number.POSITIVE_INFINITY
  const bottom = Math.min(Math.max(0, last + spacing), bottomLimit)
  return { top, bottom }
}

export interface OutlineCatalogBounds {
  /** Distance (px) from the rail bottom to the card's bottom edge. */
  bottom: number
  /** Tallest the card may grow inside the space above its bottom edge. */
  maxHeight: number
}

/**
 * user:“点击目录按钮出的那个卡片它现在被输入框给遮挡了”+(目录卡片贴在下翻控件下方、始终留在
 * 消息区内，向上生长，不再落到被输入框盖住的主卡底部)
 */
export function outlineCatalogBounds(
  rootHeight: number,
  stackBottom: number,
  gap: number,
): OutlineCatalogBounds {
  const spacing = Math.max(0, gap)
  const bottom = rootHeight > 0
    ? Math.max(spacing, rootHeight - stackBottom)
    : spacing
  return { bottom, maxHeight: Math.max(0, stackBottom - spacing) }
}

export interface MountedOutlineMessagePosition {
  index: number
  centerY: number
}

/**
 * user:“那个小条的判定框太大了”+(每条标记的悬停/点击判定只取相邻间距的一半，按 2–6px 夹紧)
 */
export function outlineMarkerHitRadius(
  positions: readonly number[],
  minRadius = 2,
  maxRadius = 6,
): number {
  if (positions.length < 2) return maxRadius
  let smallest = Number.POSITIVE_INFINITY
  for (let index = 1; index < positions.length; index += 1) {
    const gap = Math.abs(positions[index] - positions[index - 1])
    if (gap > 0 && gap < smallest) smallest = gap
  }
  if (!Number.isFinite(smallest)) return maxRadius
  return Math.min(maxRadius, Math.max(minRadius, smallest / 2))
}

/** Resolve the active item from mounted message geometry only. */
export function nearestMountedOutlineIndex(
  mounted: readonly MountedOutlineMessagePosition[],
  activationY: number,
): number {
  if (mounted.length === 0 || !Number.isFinite(activationY)) return -1
  let nearest = mounted[0].index
  let distance = Math.abs(mounted[0].centerY - activationY)
  for (let cursor = 1; cursor < mounted.length; cursor += 1) {
    const candidate = mounted[cursor]
    const nextDistance = Math.abs(candidate.centerY - activationY)
    if (nextDistance < distance) {
      nearest = candidate.index
      distance = nextDistance
    }
  }
  return nearest
}

/** Fall back to the real scroll progress when no outline user card is mounted. */
export function outlineIndexFromScrollProgress(
  scrollTop: number,
  scrollHeight: number,
  clientHeight: number,
  count: number,
): number {
  if (count <= 0) return -1
  const range = Math.max(0, scrollHeight - clientHeight)
  const progress = range > 0
    ? Math.max(0, Math.min(1, scrollTop / range))
    : 0
  return Math.round(progress * Math.max(0, count - 1))
}

export interface ChatOutlineMarkerStyle {
  length: number
  opacity: number
}

/** Resting markers stay uniformly short; hover or keyboard focus adds emphasis. */
export function resolveOutlineSelectedIndex(
  hoverIndex: number,
  keyboardIndex: number,
  focused: boolean,
): number {
  if (hoverIndex >= 0) return hoverIndex
  if (focused && keyboardIndex >= 0) return keyboardIndex
  return -1
}

/** Progressive marker treatment used by the canvas renderer and its tests. */
export function outlineMarkerStyle(
  index: number,
  selectedIndex: number,
  markerUnit: number,
): ChatOutlineMarkerStyle {
  const unit = Math.max(1, markerUnit)
  if (index === selectedIndex) return { length: unit * 3, opacity: 1 }
  // user:“它本身不是一种类似淡灰色吗？你把它的那种给整明显一点就行了”+
  // (标记条整体抬高对比度：未选中也保持可读，远近只做轻微衰减)
  if (selectedIndex < 0) return { length: unit * 0.75, opacity: 0.62 }
  const distance = Math.abs(index - selectedIndex)
  return {
    length: unit * Math.max(0.75, 2.1 - Math.min(distance, 8) * 0.18),
    opacity: Math.max(0.5, 0.88 - Math.min(distance, 8) * 0.05),
  }
}
