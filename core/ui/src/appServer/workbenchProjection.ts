import type { CoreMessage, MessagePart } from '../types'
import { coreAppItemPartStatus, coreAppItemToMessagePart } from './messageParts.ts'
import type {
  CoreAppItem,
  CoreAppQueueItem,
  CoreAppRequestState,
  CoreAppSnapshot,
  CoreRuntimeItem,
} from './protocol.ts'
import { selectChatMessages, selectQueueTray, type CoreAppServerChatMessage } from './selectors.ts'

export interface CoreWorkbenchMessageOptions {
  source?: string
  active?: boolean
  shallowThinkingPending?: boolean
  submittingApprovalRequestIds?: Set<string>
  /** Project only the most recent N messages (history windowing). */
  tailWindow?: number
}

export interface CoreQueuedInput {
  id: string
  thread_id: string
  text: string
  mode: string
  status: string
  position: number
  metadata?: Record<string, unknown>
}

// ── Incremental projection cache ──
// During a stream the snapshot is replaced every frame; without caching every
// message and every part would be rebuilt from scratch on each frame. The
// cache keys on the underlying snapshot references (core items, request
// states) — snapshot replacement keeps untouched object references stable, so
// a cache hit means "this input genuinely did not change" and the previously
// built part/message object can be reused as-is (stable object identity is
// what lets downstream components skip re-rendering).
interface ProjectionPartCacheEntry {
  sourceCoreItem: CoreRuntimeItem | undefined
  sourceRequest: CoreAppRequestState | null | undefined
  sourceSubmitting: boolean
  /** Identity of the sub-agent children array attached to the item. The
   * parent card's core item reference is stable while its sub-agent streams,
   * so without this the cached part (with frozen sub-line children) would be
   * returned every frame and the sub-agent output would only appear once the
   * parent tool finishes. */
  sourceSubLineItems: CoreAppItem[] | undefined
  part: MessagePart
}

interface ProjectionMessageCacheEntry {
  fingerprint: unknown[]
  message: CoreMessage
}

export interface CoreWorkbenchProjectionCache {
  clear(): void
  partsByItemId: Map<string, ProjectionPartCacheEntry>
  messagesById: Map<string, ProjectionMessageCacheEntry>
  /** Expanded CoreAppItem cache keyed by the underlying CoreRuntimeItem reference. */
  itemsApp: Map<CoreRuntimeItem, CoreAppItem>
  /** Stable per-parent sub-agent children arrays (identity-reused across
   * frames while no child changed — see selectors.ts). */
  subAgentChildren: Map<string, CoreAppItem[]>
  /** splitShallowThinking results keyed by content value (stable for history). */
  shallowByContent: Map<string, { thinking: string; content: string }>
}

export function createCoreWorkbenchProjectionCache(): CoreWorkbenchProjectionCache {
  return {
    clear() {
      this.partsByItemId.clear()
      this.messagesById.clear()
      this.itemsApp.clear()
      this.subAgentChildren.clear()
      this.shallowByContent.clear()
    },
    partsByItemId: new Map<string, ProjectionPartCacheEntry>(),
    messagesById: new Map<string, ProjectionMessageCacheEntry>(),
    itemsApp: new Map<CoreRuntimeItem, CoreAppItem>(),
    subAgentChildren: new Map<string, CoreAppItem[]>(),
    shallowByContent: new Map<string, { thinking: string; content: string }>(),
  }
}

export function selectCoreWorkbenchMessages(
  snapshot: CoreAppSnapshot,
  options: CoreWorkbenchMessageOptions = {},
  cache?: CoreWorkbenchProjectionCache | null,
): CoreMessage[] {
  return selectCoreWorkbenchMessagesWindow(snapshot, options, cache).messages
}

export interface CoreWorkbenchMessageProjection {
  messages: CoreMessage[]
  /** Total chat message count in the snapshot (before windowing). */
  total: number
  /** Index (into the chronological message list) of the first projected message. */
  startIndex: number
}

/**
 * Project chat messages with an optional history window.
 *
 * With ``options.tailWindow`` only the most recent N messages are built
 * (older ones are skipped entirely — no placeholder, no DOM). This cuts the
 * dominant first-render cost for very large threads without touching the
 * projection cache semantics: windowed messages keep stable identities, so
 * widening the window only builds the newly revealed ones.
 */
export function selectCoreWorkbenchMessagesWindow(
  snapshot: CoreAppSnapshot,
  options: CoreWorkbenchMessageOptions = {},
  cache?: CoreWorkbenchProjectionCache | null,
): CoreWorkbenchMessageProjection {
  const sourceMessages = selectChatMessages(snapshot, cache?.itemsApp, cache?.subAgentChildren)
  const tail = (
    typeof options.tailWindow === 'number' && options.tailWindow > 0
      ? Math.min(options.tailWindow, sourceMessages.length)
      : sourceMessages.length
  )
  const startIndex = sourceMessages.length - tail
  const lastAssistantIndex = sourceMessages.findLastIndex(message => message.role === 'assistant')
  const messages: CoreMessage[] = new Array(tail)
  for (let index = startIndex; index < sourceMessages.length; index += 1) {
    const message = sourceMessages[index]
    const activeAssistant = Boolean(options.active && message.role === 'assistant' && index === lastAssistantIndex)
    const content = splitShallowCached(message.content, cache)
    const parts = buildMessageParts(snapshot, message, content, options, activeAssistant, cache)
    if (cache) {
      const fingerprint = messageFingerprint(message, parts, content, activeAssistant, options.shallowThinkingPending)
      const entry = cache.messagesById.get(message.id)
      if (entry && fingerprintEquals(entry.fingerprint, fingerprint)) {
        messages[index - startIndex] = entry.message
        continue
      }
      const built = buildWorkbenchMessage(message, content, parts, options, activeAssistant)
      cache.messagesById.set(message.id, { fingerprint, message: built })
      messages[index - startIndex] = built
      continue
    }
    messages[index - startIndex] = buildWorkbenchMessage(message, content, parts, options, activeAssistant)
  }
  return { messages, total: sourceMessages.length, startIndex }
}

function splitShallowCached(
  text: string,
  cache?: CoreWorkbenchProjectionCache | null,
): { thinking: string; content: string } {
  if (cache) {
    const hit = cache.shallowByContent.get(text)
    if (hit) return hit
    const result = splitShallowThinking(text)
    cache.shallowByContent.set(text, result)
    if (cache.shallowByContent.size > 1_000) cache.shallowByContent.clear()
    return result
  }
  return splitShallowThinking(text)
}

function buildMessageParts(
  snapshot: CoreAppSnapshot,
  message: CoreAppServerChatMessage,
  shallow: { thinking: string; content: string },
  options: CoreWorkbenchMessageOptions,
  activeAssistant: boolean,
  cache?: CoreWorkbenchProjectionCache | null,
): MessagePart[] {
  return [
    ...(shallow.thinking ? [{
      id: `${message.id}:shallow-thinking`,
      partType: 'reasoning' as const,
      status: activeAssistant ? 'running' as const : 'completed' as const,
      content: shallow.thinking,
      label: 'Shallow thinking',
      metadata: { shallowThinking: true },
    }] : []),
    ...message.parts.map(item => buildOrGetPart(snapshot, item, options, cache)),
    ...(message.attachments || []).map(attachment => ({
      id: `${message.id}:attachment:${attachment.id}`,
      partType: 'attachment' as const,
      status: 'completed' as const,
      content: '',
      label: attachment.label || attachment.filename,
      metadata: { attachment },
    })),
  ]
}

function buildWorkbenchMessage(
  message: CoreAppServerChatMessage,
  shallow: { thinking: string; content: string },
  parts: MessagePart[],
  options: CoreWorkbenchMessageOptions,
  activeAssistant: boolean,
): CoreMessage {
  return {
    id: message.id,
    role: message.role,
    content: shallow.content,
    timestamp: '',
    parts,
    metadata: {
      ...(options.source ? { source: options.source } : {}),
      ...(message.metadata || {}),
      // The running turn's last assistant message is the live-streaming one:
      // mark it so MessageView takes the incremental streaming render path,
      // auto-expands tool parts and shows the live status bar (audit 15 S1 —
      // the main-thread live path was never wired because nothing set
      // metadata.live for main-line messages).
      live: activeAssistant || message.metadata?.live,
      shallowThinkingPending: activeAssistant && options.shallowThinkingPending ? true : undefined,
    },
  } satisfies CoreMessage
}

// Fingerprint of everything a message's rendering depends on. Every member is
// compared by identity (===): a stable reference means "unchanged", so the
// cached message object can be reused. Parts are expanded flat so their
// individual references are compared element-wise.
function messageFingerprint(
  message: CoreAppServerChatMessage,
  parts: MessagePart[],
  shallow: { thinking: string; content: string },
  activeAssistant: boolean,
  shallowThinkingPending?: boolean,
): unknown[] {
  const meta = message.metadata || {}
  return [
    message.id,
    message.role,
    shallow.content,
    activeAssistant,
    shallowThinkingPending === true,
    meta.live === true,
    meta.initialWaiting === true,
    meta.processMetrics,
    message.attachments,
    ...parts.map(part => part),
  ]
}

function fingerprintEquals(a: unknown[], b: unknown[]): boolean {
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] !== b[i]) return false
  }
  return true
}

function buildOrGetPart(
  snapshot: CoreAppSnapshot,
  item: CoreAppItem,
  options: CoreWorkbenchMessageOptions,
  cache?: CoreWorkbenchProjectionCache | null,
): MessagePart {
  const requestId = typeof item.request_id === 'string' ? item.request_id : ''
  const requestState = requestStateForId(snapshot, requestId)
  const sourceSubmitting = requestId
    ? options.submittingApprovalRequestIds?.has(requestId) === true
    : false
  const sourceCoreItem = snapshot.core?.items?.[item.item_id]
  const itemMetadata = isRecord(item.metadata) ? item.metadata : {}
  // Raw reference identity (not a filtered copy — a fresh array every frame
  // would defeat the cache check below).
  const rawSubLineItems = Array.isArray(itemMetadata.subLineItems) ? itemMetadata.subLineItems : undefined
  if (cache) {
    const entry = cache.partsByItemId.get(item.item_id)
    if (
      entry
      && entry.sourceCoreItem === sourceCoreItem
      && entry.sourceRequest === requestState
      && entry.sourceSubmitting === sourceSubmitting
      && entry.sourceSubLineItems === rawSubLineItems
    ) {
      return entry.part
    }
  }
  const part = coreAppItemToWorkbenchPart(snapshot, item, options)
  if (cache) {
    cache.partsByItemId.set(item.item_id, {
      sourceCoreItem,
      sourceRequest: requestState,
      sourceSubmitting,
      sourceSubLineItems: rawSubLineItems,
      part,
    })
  }
  return part
}

const SHALLOW_THINKING_START = '[>SHALLOW_thinking_START<]'
const SHALLOW_THINKING_END = '[>SHALLOW_thinking_END<]'

function splitShallowThinking(text: string): { thinking: string; content: string } {
  const start = text.indexOf(SHALLOW_THINKING_START)
  const end = text.indexOf(SHALLOW_THINKING_END, Math.max(0, start))
  if (start >= 0) {
    const thinkingStart = start + SHALLOW_THINKING_START.length
    if (end >= thinkingStart) {
      return {
        thinking: text.slice(thinkingStart, end).trim(),
        content: `${text.slice(0, start)}${text.slice(end + SHALLOW_THINKING_END.length)}`.trim(),
      }
    }
    return {
      thinking: text.slice(thinkingStart).trim(),
      content: text.slice(0, start).trim(),
    }
  }
  if (end >= 0) {
    return {
      thinking: text.slice(0, end).trim(),
      content: text.slice(end + SHALLOW_THINKING_END.length).trim(),
    }
  }
  return { thinking: '', content: text }
}

export function coreAppItemToWorkbenchPart(
  snapshot: CoreAppSnapshot,
  item: CoreAppItem,
  options: Pick<CoreWorkbenchMessageOptions, 'submittingApprovalRequestIds'> = {},
): MessagePart {
  const requestId = typeof item.request_id === 'string' ? item.request_id : ''
  const requestState = requestStateForId(snapshot, requestId)
  const isResolvedRequest = requestState?.status === 'resolved' || item.status === 'resolved'
  const isSubmittingRequest = requestId ? options.submittingApprovalRequestIds?.has(requestId) === true : false
  const status = coreWorkbenchPartStatus(String(item.status || ''), isResolvedRequest, isSubmittingRequest)
  const waitingResponse = requestState?.status === 'resolved'
    ? coreDecisionToWaitingResponse(String(requestState.decision || ''), String(requestState.guidance || ''))
    : undefined
  const basePart = coreAppItemToMessagePart(item, { status })
  const itemMetadata = isRecord(item.metadata) ? item.metadata : {}
  const subLineItems = Array.isArray(itemMetadata.subLineItems)
    ? itemMetadata.subLineItems.filter(isRecord) as CoreAppItem[]
    : []
  const subLineParts = subLineItems.map(child => coreAppItemToWorkbenchPart(snapshot, child, options))
  return {
    ...basePart,
    toolArgs: Array.isArray(item.options)
      ? {
          ...(isRecord(item.arguments) ? item.arguments : {}),
          options: item.options,
        }
      : isRecord(item.arguments)
        ? item.arguments
        : undefined,
    toolResult: typeof item.content === 'string' ? item.content : basePart.toolResult,
    metadata: {
      ...(isRecord(basePart.metadata) ? basePart.metadata : {}),
      ...itemMetadata,
      ...(subLineParts.length > 0 ? { subLineParts } : {}),
      request_id: requestId || undefined,
      title: item.title,
      question: item.question,
      description: item.description || item.message,
      options: item.options,
      waitingResponse,
      waitingRequest: requestId ? {
        kind: item.kind || 'approval',
        request_id: requestId,
        options: item.options,
        response: waitingResponse,
      } : undefined,
    },
  }
}

export function selectCoreQueuedInputs(snapshot: CoreAppSnapshot): CoreQueuedInput[] {
  return selectQueueTray(snapshot).map((item, index) => coreQueueItemToQueuedInput(snapshot, item, index))
}

export function coreMessageHasProcessParts(message: CoreMessage): boolean {
  return (message.parts || []).some(part => part.partType !== 'text' && part.partType !== 'model_text')
}

export function nextCoreProcessExpandedIds(
  messages: CoreMessage[],
  currentExpandedIds: Set<string>,
  active: boolean,
): Set<string> {
  const next = new Set(currentExpandedIds)
  for (const message of messages) {
    const parts = message.parts || []
    // Only messages with live-streaming parts (running) auto-expand.
    // Adding EVERY assistant message here at turn start flipped all messages'
    // v-memo keys at once (full-thread re-render ~1s on large threads);
    // historical/completed messages stay collapsed (compact groups).
    const hasLiveRunning = active && message.role === 'assistant'
      && coreMessageHasProcessParts(message)
      && parts.some(part => part.status === 'running')
    // 未响应的审批卡必须直接可见：pending decision part（waitingRequest 无
    // response）与 running part 同等待遇。turn 挂起（decision=wait）时
    // active=false，但审批卡仍需展开——否则用户看不到问题、无法回答（死锁）。
    const hasPendingApproval = message.role === 'assistant'
      && parts.some(part => part.partType === 'decision' && part.status === 'pending'
        && !isApprovalResponded(part))
    if (hasLiveRunning || hasPendingApproval) {
      next.add(message.id)
    }
  }
  // Content-stable identity: return the SAME set reference when nothing
  // changed. This runs on every stream tick while a turn is active, and a
  // fresh Set every frame would invalidate downstream memo keys (v-memo on
  // MessageView) and re-render the whole thread on every tick.
  if (next.size === currentExpandedIds.size) {
    let same = true
    for (const id of next) {
      if (!currentExpandedIds.has(id)) {
        same = false
        break
      }
    }
    if (same) return currentExpandedIds
  }
  return next
}

/** 审批是否已响应：waitingRequest.response（或 waitingResponse metadata）存在即已答复 */
function isApprovalResponded(part: MessagePart): boolean {
  const metadata = (part.metadata || {}) as Record<string, unknown>
  const waiting = metadata.waitingRequest
  if (waiting && typeof waiting === 'object') {
    const request = waiting as Record<string, unknown>
    if (request.response) return true
  }
  return Boolean(metadata.waitingResponse)
}

export function normalizeCoreSessionStatus(status: string): string {
  const value = String(status || '').toLowerCase()
  if (value === 'active') return 'idle'
  if (value === 'running' || value === 'waiting' || value === 'completed' || value === 'failed') return value
  return 'idle'
}

export function updateCoreSessionListStatus<T extends {
  id: string
  status?: string
  updatedAt?: string
}>(
  sessions: T[],
  sessionId: string,
  status: string,
  updatedAt: string,
): T[] {
  if (!sessionId) return sessions
  const nextStatus = normalizeCoreSessionStatus(status)
  const index = sessions.findIndex(session => session.id === sessionId)
  if (index < 0 || sessions[index].status === nextStatus) return sessions
  const next = [...sessions]
  next[index] = {
    ...sessions[index],
    status: nextStatus,
    updatedAt,
  } as T
  return next
}

export function selectLatestActiveTurnId(snapshot: CoreAppSnapshot): string {
  const turns = {
    ...(snapshot.turns || {}),
    ...(snapshot.core?.turns || {}),
  }
  const active: Array<{ id: string; seq: number }> = []
  for (const [turnId, turn] of Object.entries(turns)) {
    const status = String(turn?.status || '')
    if (!['running', 'waiting', 'interrupting'].includes(status)) continue
    active.push({
      id: String(turn.turn_id || turnId),
      seq: Number(turn.last_seq ?? turn.seq ?? 0),
    })
  }
  active.sort((a, b) => b.seq - a.seq || a.id.localeCompare(b.id))
  return active[0]?.id || ''
}

function coreQueueItemToQueuedInput(snapshot: CoreAppSnapshot, item: CoreAppQueueItem, index: number): CoreQueuedInput {
  return {
    id: item.queue_item_id,
    thread_id: snapshot.thread_id,
    text: coreInputToText(item.input),
    mode: String(item.mode || 'next_turn'),
    status: String(item.status || 'queued'),
    position: index + 1,
    metadata: { source: 'core_app_server' },
  }
}

export function coreInputToText(input: unknown): string {
  if (typeof input === 'string') return input
  if (!Array.isArray(input)) return ''
  return input.map((item) => {
    if (!isRecord(item)) return ''
    if (item.type === 'skill') return String(item.source_text || `/${item.name || ''}`)
    return String(item.text || '')
  }).join('')
}

function requestStateForId(snapshot: CoreAppSnapshot, requestId: string): CoreAppRequestState | null {
  if (!requestId) return null
  return snapshot.core?.requests?.[requestId] || snapshot.requests?.[requestId] || null
}

function coreDecisionToWaitingResponse(decision: string, guidance: string): Record<string, unknown> {
  if (decision === 'deny') return { action: 'deny', response: guidance || 'deny' }
  if (decision === 'other_guidance') return { action: 'guide', response: guidance || 'guide' }
  if (decision === 'approve_once' || decision === 'approve_for_session') {
    return { action: 'approve', response: decision }
  }
  return { action: decision || 'handled', response: guidance || decision }
}

function coreWorkbenchPartStatus(
  rawStatus: string,
  isResolvedRequest: boolean,
  isSubmittingRequest: boolean,
): MessagePart['status'] {
  if (isResolvedRequest) return 'completed'
  if (isSubmittingRequest) return 'running'
  return coreAppItemPartStatus(rawStatus)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}
