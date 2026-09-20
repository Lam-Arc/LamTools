import type { CoreMessage } from '../types'

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

export interface MountedOutlineMessagePosition {
  index: number
  centerY: number
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
  if (selectedIndex < 0) return { length: unit * 0.75, opacity: 0.56 }
  const distance = Math.abs(index - selectedIndex)
  return {
    length: unit * Math.max(0.75, 2.1 - Math.min(distance, 8) * 0.18),
    opacity: Math.max(0.44, 0.84 - Math.min(distance, 8) * 0.05),
  }
}
