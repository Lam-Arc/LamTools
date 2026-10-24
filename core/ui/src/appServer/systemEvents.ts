
import { t } from '@/i18n/index.ts'
/**
 * Machine-authored transcript rows.
 *
 * The runtime injects its own turns as system messages: a member wake (a
 * sub-agent finished after the earlier turn ended) and the memory-resume
 * continuation. Both arrive as `systemMessage` items with role `system` and an
 * `origin` marker, but the message projection used to render any non-assistant
 * item as a bubble, so the transcript showed text that looked like something the
 * user typed. This module carries the one check that tells such a row apart and
 * parses what it says.
 */
import type { CoreAppItem } from '@/appServer/protocol.ts'

export type CoreSystemEventKind = 'member_wake' | 'memory_resume' | 'system'

export interface CoreSystemEventEntry {
  /** Sub-agent name. */
  name: string
  /** Status word (`已完成` / `已失败` / ...). */
  state: string
  /** The member's own message, empty when it sent none. */
  message: string
}

export interface CoreSystemEvent {
  kind: CoreSystemEventKind
  text: string
  entries: CoreSystemEventEntry[]
}

/** Origin markers the runtime stamps on the item and on its turn. */
const MEMBER_WAKE_ORIGIN = 'member_wake'
const MEMORY_RESUME_ORIGIN = 'memory_resume'

/**
 * The single place a system row is recognised. Keyed on the item's own shape
 * (type, role, origin) and never on the text, so a wording change cannot turn
 * the row back into a user bubble.
 */
export function coreSystemEventForItem(
  item: CoreAppItem,
  text: string,
  turnOrigin = '',
): CoreSystemEvent | null {
  const metadata = isRecord(item.metadata) ? item.metadata : {}
  const origin = firstText(item.origin, metadata.origin, turnOrigin)
  const kind = systemEventKind(origin)
  const isSystemItem = String(item.type || '') === 'systemMessage'
    && firstText(item.role, metadata.role) === 'system'
  if (!kind && !isSystemItem) return null
  const resolved = kind || 'system'
  return {
    kind: resolved,
    text,
    entries: resolved === 'member_wake' ? parseMemberWakeEntries(text) : [],
  }
}

function systemEventKind(origin: string): CoreSystemEventKind | null {
  if (origin === MEMBER_WAKE_ORIGIN) return 'member_wake'
  if (origin === MEMORY_RESUME_ORIGIN) return 'memory_resume'
  return null
}

/** Shape guard for the value carried on a projected message's metadata. */
export function isCoreSystemEvent(value: unknown): value is CoreSystemEvent {
  if (!isRecord(value)) return false
  return typeof value.kind === 'string' && typeof value.text === 'string' && Array.isArray(value.entries)
}

/**
 * The wake line templates, one per finished member:
 *   `子代理 <name> 已完成。`
 *   `子代理 <name> 已完成：<message>`
 *   `子代理 <name> 已失败。`
 *   `子代理 <name> 已失败：<summary>`
 * The message part is optional and never required. Two patterns so a message
 * that itself ends with a period keeps it; the bare shape owns the trailing
 * `。`.
 */
const MEMBER_WAKE_STATE = t("已完成|已失败|已中断|已取消")
const MEMBER_WAKE_LINE_WITH_MESSAGE = new RegExp(
  t("^子代理\\s+(.+?)\\s+({0})\\s*[：:]\\s*([\\s\\S]+)$", { 0: MEMBER_WAKE_STATE }),
)
const MEMBER_WAKE_LINE_BARE = new RegExp(
  t("^子代理\\s+(.+?)\\s+({0})\\s*。?\\s*$", { 0: MEMBER_WAKE_STATE }),
)

export function parseMemberWakeEntries(text: string): CoreSystemEventEntry[] {
  const entries: CoreSystemEventEntry[] = []
  for (const line of String(text || '').split('\n')) {
    const trimmed = line.trim()
    const withMessage = MEMBER_WAKE_LINE_WITH_MESSAGE.exec(trimmed)
    if (withMessage) {
      entries.push({
        name: withMessage[1].trim(),
        state: withMessage[2],
        message: withMessage[3].trim(),
      })
      continue
    }
    const bare = MEMBER_WAKE_LINE_BARE.exec(trimmed)
    if (bare) entries.push({ name: bare[1].trim(), state: bare[2], message: '' })
  }
  return entries
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return ''
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}
