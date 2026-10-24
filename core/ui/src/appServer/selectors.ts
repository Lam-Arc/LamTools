import type {
  CoreAppItem,
  CoreAppQueueItem,
  CoreAppRequestState,
  CoreAppSnapshot,
  CoreRuntimeItem,
  CoreRuntimeTurn,
} from './protocol.ts'
import { coreSystemEventForItem } from './systemEvents.ts'

const RENDERABLE_ITEM_TYPES = new Set([
  'userMessage',
  // The runtime injects its own turns (member wake, memory resume) as system
  // messages; the projection turns them into system rows, never user bubbles.
  'systemMessage',
  'agentMessage',
  'reasoning',
  'dynamicToolCall',
  'mcpToolCall',
  'collabToolCall',
  'commandExecution',
  'fileChange',
  'serverRequest',
  'plan',
  'error',
  'webSearch',
  'imageView',
  'contextCompaction',
  'compaction',
  'status',
  'agent_summary',
])

type CoreUsageCall = NonNullable<CoreRuntimeTurn['usage_calls']>[number]

interface CoreUsageCallIndex {
  main: CoreUsageCall[]
  byParentItemId: Map<string, CoreUsageCall[]>
}

// Usage events replace a turn's `usage_calls` array in the snapshot reducer.
// Index each immutable array once so every projection frame does O(calls)
// work per changed turn instead of filtering the same turn once per parent
// item. Weak keys keep each index tied to its source array's lifetime.
const usageCallIndexes = new WeakMap<CoreUsageCall[], CoreUsageCallIndex>()
const EMPTY_USAGE_CALLS: CoreUsageCall[] = []

function indexUsageCalls(calls: CoreUsageCall[]): CoreUsageCallIndex {
  const cached = usageCallIndexes.get(calls)
  if (cached) return cached

  const main: CoreUsageCall[] = []
  const byParentItemId = new Map<string, CoreUsageCall[]>()
  for (const call of calls) {
    if (!call.parent_item_id) {
      main.push(call)
      continue
    }
    const parentCalls = byParentItemId.get(call.parent_item_id)
    if (parentCalls) parentCalls.push(call)
    else byParentItemId.set(call.parent_item_id, [call])
  }

  const index = { main, byParentItemId }
  usageCallIndexes.set(calls, index)
  return index
}

export interface CoreAppServerChatMessage {
  id: string
  turnId?: string
  role: 'user' | 'assistant'
  content: string
  timestamp?: string
  parts: CoreAppItem[]
  attachments?: Array<{
    id: string
    filename: string
    label: string
    mime_type: string
    size: number
    preview_type: string
    status: 'uploaded'
  }>
  metadata?: Record<string, unknown>
}

export function selectLatestTurnStatus(state: CoreAppSnapshot): 'idle' | 'running' | 'waiting' | 'paused' | 'completed' | 'failed' | 'cancelled' {
  // A turn the server reports as active wins. The thread-level status is not a
  // reliable "is a turn running" signal: right after a turn is accepted it can
  // still read the previous turn's terminal value (turn/accepted updates the
  // turn map and the top-level status, not `core.status`), which hid the stop
  // affordance and made the composer try to start a new turn during a run.
  const activeTurnStatus = latestActiveTurnStatus(state)
  if (activeTurnStatus) return activeTurnStatus
  const coreStatus = state.core?.status
  if (coreStatus && coreStatus !== 'idle') return coreStatus
  return state.status ?? 'idle'
}

/**
 * The status of the newest turn the server reports as active, or null when none
 * is. Deliberately reads the turn map (`snapshot.turns` and
 * `snapshot.core.turns`), which is where a turn's own status lives.
 */
function latestActiveTurnStatus(state: CoreAppSnapshot): 'running' | 'waiting' | null {
  const turns = {
    ...(state.turns || {}),
    ...(state.core?.turns || {}),
  }
  const active: Array<{ status: 'running' | 'waiting'; seq: number; id: string }> = []
  for (const [turnId, turn] of Object.entries(turns)) {
    const status = String(turn?.status || '')
    // `interrupting` is active too; it reports as running (the public status
    // union has no separate value for it).
    if (status !== 'running' && status !== 'interrupting' && status !== 'waiting') continue
    active.push({
      status: status === 'waiting' ? 'waiting' : 'running',
      seq: Number(turn?.last_seq ?? turn?.seq ?? 0),
      id: String(turn?.turn_id || turnId),
    })
  }
  active.sort((a, b) => b.seq - a.seq || a.id.localeCompare(b.id))
  return active[0]?.status ?? null
}

export type CoreTurnActionMode = 'send' | 'stop' | 'resume'

export interface CoreTurnControl {
  turnId: string
  status: 'idle' | 'running' | 'waiting' | 'paused' | 'stopping' | 'completed' | 'failed' | 'cancelled'
  actionMode: CoreTurnActionMode
  /** The turn a Continue press would continue (empty unless paused). */
  pausedTurnId: string
  canSend: boolean
  canPause: boolean
  canResume: boolean
  canTerminate: boolean
}

/**
 * One canonical derivation of "what can the composer do right now".
 *
 * The previous UI had four independent derivations (latest status, resumable
 * turn, composer action mode, session activity). They could disagree after a
 * delegated member event or a restart. The backend now owns the turn status
 * contract; this selector is the only UI reader of it.
 */
export function selectTurnControl(state: CoreAppSnapshot): CoreTurnControl {
  const turns = {
    ...(state.turns || {}),
    ...(state.core?.turns || {}),
  } as Record<string, CoreRuntimeTurn>
  const ordered = Object.entries(turns)
    .map(([id, turn]) => ({
      id: String(turn?.turn_id || id),
      status: String(turn?.status || ''),
      seq: Number(turn?.last_seq ?? turn?.seq ?? 0),
    }))
    .sort((a, b) => b.seq - a.seq || a.id.localeCompare(b.id))

  const active = ordered.find(item => ['running', 'waiting', 'interrupting'].includes(item.status))
  const paused = ordered.find(item => item.status === 'paused')
  const latest = ordered[0]
  const rawStatus = active
    ? (active.status === 'interrupting' ? 'stopping' : active.status)
    : paused
      ? 'paused'
      : (latest?.status || state.core?.status || state.status || 'idle')
  const status = (
    ['idle', 'running', 'waiting', 'paused', 'stopping', 'completed', 'failed', 'cancelled'].includes(rawStatus)
      ? rawStatus
      : 'idle'
  ) as CoreTurnControl['status']
  const actionMode: CoreTurnActionMode = status === 'paused'
    ? 'resume'
    : status === 'running' || status === 'waiting' || status === 'stopping'
      ? 'stop'
      : 'send'
  return {
    turnId: (active || paused || latest)?.id || '',
    status,
    actionMode,
    pausedTurnId: paused?.id || '',
    canSend: actionMode === 'send',
    canPause: status === 'running' || status === 'waiting',
    canResume: status === 'paused',
    canTerminate: !['idle', 'completed', 'failed', 'cancelled'].includes(status),
  }
}

export function selectQueueTray(state: CoreAppSnapshot): CoreAppQueueItem[] {  return [...(state.queue ?? [])].sort((a, b) => Number(a.seq ?? 0) - Number(b.seq ?? 0))
}

export function selectApprovalCards(state: CoreAppSnapshot): CoreAppRequestState[] {
  const requests = new Map<string, CoreAppRequestState>()
  for (const request of Object.values(state.core?.requests ?? {})) {
    if (!request.request_id) continue
    requests.set(request.request_id, request)
  }
  for (const request of Object.values(state.requests ?? {})) {
    if (!request.request_id) continue
    requests.set(request.request_id, { ...(requests.get(request.request_id) ?? {}), ...request })
  }
  return [...requests.values()].sort((a, b) => Number(a.seq ?? 0) - Number(b.seq ?? 0))
}

/**
 * Mid-turn guidance reaches the transcript as its own user message, projected
 * when the kernel drains the instruction (`<turn>:user:guide:<event>`). It
 * belongs to the running turn rather than opening a new one, so it carries no
 * editable source message — the id is the only durable marker.
 */
function isGuidanceMessageId(messageId: string): boolean {
  return messageId.includes(':user:guide:')
}

export function selectChatMessages(
  state: CoreAppSnapshot,
  itemCache?: Map<CoreRuntimeItem, CoreAppItem>,
  subAgentChildrenCache?: Map<string, CoreAppItem[]>,
): CoreAppServerChatMessage[] {
  const messages: CoreAppServerChatMessage[] = []
  const itemOrder = mergedItemOrder(state)
  const artifactsByItem = artifactsGroupedByItem(state)
  const allSubAgentChildren = subAgentChildrenByParentId(state, itemOrder, artifactsByItem, itemCache, subAgentChildrenCache)
  const nestedChildItemIds = new Set(
    [...allSubAgentChildren.values()].flatMap(items => items.map(item => item.item_id)),
  )
  const deletedAgents = new Set(Object.keys(state.deleted_agents ?? {}))
  // Deleted members keep their rows suppressed (they are still nested child
  // ids), but their subtree is no longer attached to the parent card. This is
  // derived from a durable snapshot fact, not a process-local dismissal set.
  const subAgentChildren = new Map<string, CoreAppItem[]>()
  for (const [parent, items] of allSubAgentChildren) {
    subAgentChildren.set(parent, items.filter(item => !isDeletedSubAgentItem(item, deletedAgents)))
  }
  const suppressedItemIds = duplicateSubAgentChildItemIds(state, itemOrder, itemCache)
  // Mid-turn user messages (queue guide) split a turn's runtime items into
  // several assistant segments; each segment needs a unique message id
  // (ChatThread keys on msg.id). The first segment keeps the legacy
  // `assistant:<turn>` id, later ones append `:<n>`.
  const assistantSegments = new Map<string, number>()
  // One cancel explanation per turn. Stop, force reset and crash recovery each
  // used to write their own terminal status row (different item ids), so a
  // reopened session stacked several cancel bubbles at the turn's tail; the
  // backend now shares one identity, but legacy threads still hold the stack —
  // keep only the newest terminal row per turn when projecting.
  const terminalStatusPartByTurn = new Map<string, CoreAppItem>()
  /** Open (or reuse) this turn's assistant segment. A mid-turn guidance part
   *  is rendered inside it — the instruction belongs to the turn's process and
   *  must not open a second assistant block, which is what made one turn look
   *  severed into two replies. */
  const ensureAssistantSegment = (item: CoreAppItem, turnId: string): CoreAppServerChatMessage => {
    const last = messages[messages.length - 1]
    if (last && last.role === 'assistant' && assistantSegmentTurnId(last.id) === turnId) return last
    const segment = (assistantSegments.get(turnId) ?? 0) + 1
    assistantSegments.set(turnId, segment)
    const appTurn = typeof item.turn_id === 'string' ? state.turns?.[item.turn_id] : undefined
    const coreTurn = typeof item.turn_id === 'string' ? state.core?.turns?.[item.turn_id] : undefined
    // New snapshots keep context pressure and provider billing data in
    // separate fields. Older snapshots only have `usage`; expose it in
    // both compatibility slots so historical turns remain readable while
    // new data cannot accidentally mix the two categories.
    const providerUsage = coreTurn && isRecord(coreTurn.usage) ? coreTurn.usage : null
    const contextMetrics = coreTurn && isRecord(coreTurn.context_metrics)
      ? coreTurn.context_metrics
      : providerUsage
    const usageCallIndex = coreTurn?.usage_calls ? indexUsageCalls(coreTurn.usage_calls) : undefined
    const runtimeModelId = runtimeModelIdForTurn(appTurn, coreTurn)
    const timestamp = runtimeTimestampForTurn(appTurn, coreTurn)
    const durationMs = runtimeDurationMsForTurn(appTurn, coreTurn)
    messages.push({
      // Real turn ids contain colons (`<session>:turn:<run>`), so segments
      // are separated with `#` — never a colon.
      id: segment === 1 ? `assistant:${turnId}` : `assistant:${turnId}#${segment}`,
      turnId,
      role: 'assistant',
      content: '',
      ...(timestamp ? { timestamp } : {}),
      parts: [],
      // Carry the item metadata through (audit 15 S1: the source item's
      // ``metadata.live`` flag was dropped here, so the projection could
      // never see it for main-line messages).
      metadata: {
        ...(isRecord(item.metadata) ? item.metadata : {}),
        ...(contextMetrics ? {
          // `processMetrics` is the historical name consumed by members;
          // it now intentionally means context metrics only.
          processMetrics: contextMetrics,
          contextMetrics,
        } : {}),
        ...(providerUsage ? { usageMetrics: providerUsage } : {}),
        ...(usageCallIndex ? { resourceCalls: usageCallIndex.main } : {}),
        ...(runtimeModelId ? { runtime_model_id: runtimeModelId } : {}),
        ...(durationMs !== null ? { duration_ms: durationMs } : {}),
      },
    })
    return messages[messages.length - 1]
  }
  for (const itemId of itemOrder) {
    if (suppressedItemIds.has(itemId) || nestedChildItemIds.has(itemId)) continue
    const rawItem = canonicalItemForId(state, itemId, itemCache) ?? outerProductItemForId(state, itemId)
    const itemWithArtifacts = rawItem ? withItemArtifacts(rawItem, artifactsByItem.get(itemId)) : undefined
    let item = itemWithArtifacts
      ? withSubAgentChildren(itemWithArtifacts, subAgentChildren.get(itemId))
      : undefined
    if (!item) continue
    if (isDeletedSubAgentItem(item, deletedAgents)) continue
    if (isSubAgentParentItem(item)) {
      const turn = state.core?.turns?.[String(item.turn_id || '')]
      const usageCallIndex = turn?.usage_calls ? indexUsageCalls(turn.usage_calls) : undefined
      item = { ...item, metadata: { ...(isRecord(item.metadata) ? item.metadata : {}),
        ...(usageCallIndex ? { resourceCalls: usageCallIndex.byParentItemId.get(itemId) ?? EMPTY_USAGE_CALLS } : {}),
        ...(turn?.child_context_metrics?.[itemId] ? { contextMetrics: turn.child_context_metrics[itemId] } : {}),
      } }
    }
    if (isMemberWaitSignalItem(item)) continue
    if (!isRenderableItem(item)) continue
    const resolvedTurnId = itemTurnId(state, item)
    if (item.type === 'userMessage' || item.type === 'systemMessage') {
      if (item.type === 'userMessage' && isGuidanceMessageId(item.item_id)) {
        // Guidance is part of the running turn, not a new turn's opening
        // message: it rides the segment's process timeline at its own point in
        // time, so collapsing the process hides it with everything else.
        const assistant = ensureAssistantSegment(item, resolvedTurnId || 'none')
        assistant.parts.push({ ...item, type: 'guidance', content: inputToText(item.content) })
        continue
      }
      const text = inputToText(item.content)
      const systemEvent = coreSystemEventForItem(item, text, turnOriginForId(state, resolvedTurnId))
      messages.push({
        id: item.item_id,
        ...(resolvedTurnId ? { turnId: resolvedTurnId } : {}),
        role: 'user',
        content: text,
        parts: [],
        attachments: inputAttachments(item.content),
        // A machine-authored row reads as a system event instead of a bubble the
        // user typed. The check lives in systemEvents.ts.
        ...(systemEvent ? { metadata: { systemEvent } } : {}),
      })
      continue
    }
    const turnId = resolvedTurnId || 'none'
    const assistant = ensureAssistantSegment(item, turnId)
    if (isDeadModelRetryItem(item)) continue
    if (isTurnTerminalStatusItem(item)) {
      const previous = terminalStatusPartByTurn.get(turnId)
      if (previous) {
        const index = assistant.parts.indexOf(previous)
        if (index >= 0) assistant.parts.splice(index, 1)
      }
      terminalStatusPartByTurn.set(turnId, item)
    }
    if (item.type === 'agentMessage') {
      const content = String(item.content ?? '')
      // Always accumulate the last agentMessage text as content for backward compat
      // (simple text-only Q&A, message filtering etc.) while keeping ALL agentMessages
      // in parts for inline chronological rendering.
      // An LLM can emit text before tool calls. Keep that item in the process
      // timeline; only a final (or legacy unmarked) item supplies the flat
      // answer field consumed by history, copy, and export paths.
      if (!isProtocolEnvelopeText(content)
        && item.final_response !== false
        && item.has_tool_calls !== true) assistant.content = content
    }
    assistant.parts.push(item)
  }
  maybeAppendInitialAssistantWaiting(state, messages)
  return messages.filter((message) => (
    message.role !== 'assistant'
    || message.content
    || message.parts.length > 0
    || Boolean(message.metadata?.initialWaiting)
  ))
}

function subAgentChildrenByParentId(
  state: CoreAppSnapshot,
  itemOrder: string[],
  artifactsByItem: Map<string, Array<Record<string, unknown>>>,
  cache?: Map<CoreRuntimeItem, CoreAppItem>,
  childrenCache?: Map<string, CoreAppItem[]>,
): Map<string, CoreAppItem[]> {
  const subAgentParentIds = new Set<string>()
  /** call_id → 父条目 id。历史数据里子条目记录的运行范围可能与父行不一致
   *  （旧内核只给 sub_agent 盖运行章，sub_agent_message 沿用了旧 run），
   *  call_id 全局唯一，按 `{call}:tool` 后缀兜底认亲。 */
  const subAgentParentsByCallId = new Map<string, string>()
  const orderedItems: CoreAppItem[] = []
  for (const itemId of itemOrder) {
    const rawItem = canonicalItemForId(state, itemId, cache) ?? outerProductItemForId(state, itemId)
    if (!rawItem) continue
    const item = withItemArtifacts(rawItem, artifactsByItem.get(itemId))
    orderedItems.push(item)
    if (isSubAgentParentItem(item)) {
      subAgentParentIds.add(item.item_id)
      const callMatch = /:([^:]+):tool$/.exec(item.item_id)
      if (callMatch) subAgentParentsByCallId.set(callMatch[1], item.item_id)
    }
  }

  const children = new Map<string, CoreAppItem[]>()
  for (const item of orderedItems) {
    let parentId = typeof item.parent_item_id === 'string' ? item.parent_item_id : ''
    if (!parentId) continue
    if (!subAgentParentIds.has(parentId)) {
      const callMatch = /:([^:]+):tool$/.exec(parentId)
      const fallback = callMatch ? subAgentParentsByCallId.get(callMatch[1]) : undefined
      if (!fallback) continue
      parentId = fallback
    }
    // Stable-identity children arrays: reuse the previous frame's array when
    // every child reference is identical (nothing changed). The sub-agent card
    // part in workbenchProjection is cache-keyed on the parent item's own
    // reference, which is stable while the child streams — the children array
    // identity is the only signal that a rebuild is needed. A fresh array per
    // frame would freeze the card: the cached part (empty sub-line body) would
    // be returned until the parent tool finishes and its reference changes.
    const siblings = children.get(parentId) ?? []
    siblings.push(item)
    children.set(parentId, siblings)
  }
  if (childrenCache) {
    for (const [parentId, siblings] of children) {
      const prev = childrenCache.get(parentId)
      if (prev && prev.length === siblings.length && prev.every((child, index) => child === siblings[index])) {
        children.set(parentId, prev)
      } else {
        childrenCache.set(parentId, siblings)
      }
    }
  }
  return children
}

function withSubAgentChildren(item: CoreAppItem, children: CoreAppItem[] | undefined): CoreAppItem {
  if (!children?.length || !isSubAgentParentItem(item)) return item
  return {
    ...item,
    metadata: {
      ...(isRecord(item.metadata) ? item.metadata : {}),
      subLineItems: children,
    },
  }
}

function isProtocolEnvelopeText(content: string): boolean {
  const text = content.trim()
  if (!text.startsWith('{') || !text.endsWith('}')) return false
  try {
    const value = JSON.parse(text) as Record<string, unknown>
    if (!value || Array.isArray(value) || typeof value !== 'object') return false
    if (value.jsonrpc === '2.0' && ('method' in value || 'result' in value || 'error' in value)) return true
    return typeof value.event === 'string' && ('payload' in value || 'params' in value)
  } catch {
    return false
  }
}

function duplicateSubAgentChildItemIds(state: CoreAppSnapshot, itemOrder: string[], cache?: Map<CoreRuntimeItem, CoreAppItem>): Set<string> {
  const subAgentOutputs = new Set<string>()
  const items = new Map<string, CoreAppItem>()
  for (const itemId of itemOrder) {
    const item = canonicalItemForId(state, itemId, cache) ?? outerProductItemForId(state, itemId)
    if (!item) continue
    items.set(itemId, item)
    if (item.type !== 'agent_summary' || item.tool_name !== 'sub_agent') continue
    const text = normalizedComparableText(itemText(item))
    if (text.length >= 20) subAgentOutputs.add(text)
  }
  if (subAgentOutputs.size === 0) return new Set()

  const suppressed = new Set<string>()
  for (const [itemId, item] of items) {
    if (item.type !== 'agentMessage') continue
    const text = normalizedComparableText(itemText(item))
    if (!subAgentOutputs.has(text)) continue
    suppressed.add(itemId)
    const runId = subAgentChildRunId(itemId)
    if (runId) suppressed.add(`${runId}:stream-fallback`)
  }
  return suppressed
}

function itemText(item: CoreAppItem): string {
  return String(item.content || item.message || item.summary || item.tool_result || '')
}

function normalizedComparableText(value: string): string {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

function subAgentChildRunId(itemId: string): string {
  const match = itemId.match(/^(.+):response-\d+:text$/)
  return match?.[1] || ''
}

function maybeAppendInitialAssistantWaiting(state: CoreAppSnapshot, messages: CoreAppServerChatMessage[]): void {
  if (selectLatestTurnStatus(state) !== 'running') return
  const last = messages[messages.length - 1]
  if (!last || last.role !== 'user') return
  const turnId = typeof state.items?.[last.id]?.turn_id === 'string'
    ? state.items[last.id]?.turn_id || ''
    : Object.entries(state.turns ?? {}).find(([, turn]) => turn.items?.includes(last.id))?.[0] || ''
  const runtimeModelId = runtimeModelIdForTurn(
    turnId ? state.turns?.[turnId] : undefined,
    turnId ? state.core?.turns?.[turnId] : undefined,
  )
  const timestamp = runtimeTimestampForTurn(
    turnId ? state.turns?.[turnId] : undefined,
    turnId ? state.core?.turns?.[turnId] : undefined,
  )
  // user:“这个会话已经跑了很久了，不可能没有上下文”
  // +(恢复中的等待消息也必须携带该回合已有的测量，不以助手正文是否到达决定有无上下文)。
  const coreTurn = turnId ? state.core?.turns?.[turnId] : undefined
  const providerUsage = coreTurn && isRecord(coreTurn.usage) ? coreTurn.usage : null
  const contextMetrics = coreTurn && isRecord(coreTurn.context_metrics)
    ? coreTurn.context_metrics
    : providerUsage
  const usageCallIndex = coreTurn?.usage_calls ? indexUsageCalls(coreTurn.usage_calls) : undefined
  messages.push({
    id: `assistant:waiting:${last.id}`,
    ...(turnId ? { turnId } : {}),
    role: 'assistant',
    content: '',
    ...(timestamp ? { timestamp } : {}),
    parts: [],
    metadata: {
      live: true,
      initialWaiting: true,
      ...(contextMetrics ? { processMetrics: contextMetrics, contextMetrics } : {}),
      ...(providerUsage ? { usageMetrics: providerUsage } : {}),
      ...(usageCallIndex ? { resourceCalls: usageCallIndex.main } : {}),
      ...(runtimeModelId ? { runtime_model_id: runtimeModelId } : {}),
    },
  })
}

/** Return true for the long-running delegated call, excluding create/close
 * lifecycle controls.  Older snapshots retain ``dynamicToolCall`` while newer
 * projections normalize the call to ``agent_summary``; both shapes need the
 * same child suppression/nesting semantics. */
function isSubAgentParentItem(item: CoreAppItem): boolean {
  const toolName = String(item.tool_name || '').trim().toLowerCase()
  // Asynchronous mailbox calls can own child events too.  They remain an
  // ordinary process tool in the main transcript, but their descendants must
  // be nested under the call instead of leaking as sibling assistant rows.
  if (toolName === 'sub_agent_message') return true
  if (toolName !== 'sub_agent' && toolName !== 'subagent') return false
  if (item.type === 'agent_summary') return true
  const args = isRecord(item.arguments) ? item.arguments : {}
  const metadata = isRecord(item.metadata) ? item.metadata : {}
  const nested = isRecord(metadata.metadata) ? metadata.metadata : {}
  const action = String(
    args.action
    || metadata.lifecycle_action
    || metadata.lifecycleAction
    || metadata.action
    || nested.lifecycle_action
    || nested.lifecycleAction
    || nested.action
    || '',
  ).trim().toLowerCase()
  return action !== 'create' && action !== 'close' && action !== 'created' && action !== 'closed'
}

function itemTurnId(state: CoreAppSnapshot, item: CoreAppItem): string {
  if (typeof item.turn_id === 'string' && item.turn_id) return item.turn_id
  for (const turns of [state.turns, state.core?.turns]) {
    const match = Object.entries(turns ?? {}).find(([, turn]) => turn.items?.includes(item.item_id))
    if (match) return String(match[1].turn_id || match[0])
  }
  return ''
}

/** The turn's own origin marker (`member_wake` / `memory_resume`), when set. */
function turnOriginForId(state: CoreAppSnapshot, turnId: string): string {
  if (!turnId) return ''
  const turn = state.turns?.[turnId] ?? state.core?.turns?.[turnId] as { origin?: unknown } | undefined
  return typeof turn?.origin === 'string' ? turn.origin : ''
}

function runtimeModelIdForTurn(
  appTurn: { runtime_snapshot?: unknown } | undefined,
  coreTurn: { runtime_snapshot?: unknown } | undefined,
): string {
  const appSnapshot = isRecord(appTurn?.runtime_snapshot) ? appTurn.runtime_snapshot : null
  const coreSnapshot = isRecord(coreTurn?.runtime_snapshot) ? coreTurn.runtime_snapshot : null
  const modelId = appSnapshot?.model_id ?? coreSnapshot?.model_id
  return typeof modelId === 'string' ? modelId.trim() : ''
}

function runtimeTimestampForTurn(
  appTurn: unknown,
  coreTurn: unknown,
): string {
  const appRecord = isRecord(appTurn) ? appTurn : null
  const coreRecord = isRecord(coreTurn) ? coreTurn : null
  const timestamp = appRecord?.created_at ?? coreRecord?.created_at
  return typeof timestamp === 'string' ? timestamp.trim() : ''
}

function runtimeDurationMsForTurn(appTurn: unknown, coreTurn: unknown): number | null {
  const appRecord = isRecord(appTurn) ? appTurn : null
  const coreRecord = isRecord(coreTurn) ? coreTurn : null
  const value = coreRecord?.duration_ms ?? appRecord?.duration_ms
  const duration = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(duration) && duration >= 0 ? Math.round(duration) : null
}

/**
 * Extract the turn id from an `assistant:<turn>` or `assistant:<turn>#<n>`
 * message id. Turn ids themselves contain colons, so the segment marker is
 * `#` — everything before it (including colons) is the turn id.
 */
export function assistantSegmentTurnId(messageId: string): string {
  if (!messageId.startsWith('assistant:') || messageId.startsWith('assistant:waiting:')) return ''
  const rest = messageId.slice('assistant:'.length)
  const hash = rest.indexOf('#')
  return hash >= 0 ? rest.slice(0, hash) : rest
}

function mergedItemOrder(state: CoreAppSnapshot): string[] {
  const order: string[] = []
  const seen = new Set<string>()

  const outerItems = state.items ?? {}
  const coreItems = state.core?.items ?? {}
  const turnItems = new Map<string, { outer: string[]; core: string[] }>()
  const outerTurnOrder: string[] = []
  const outerTurnIds = new Set<string>()
  const coreTurnOrder: string[] = []
  const coreTurnIds = new Set<string>()
  const looseOuter: string[] = []
  const looseCore: string[] = []

  for (const itemId of state.item_order ?? []) {
    const item = outerItems[itemId]
    const turnId = typeof item?.turn_id === 'string' ? item.turn_id : ''
    if (!turnId) {
      looseOuter.push(itemId)
      if (import.meta.env.DEV) console.warn('[order] looseOuter:', itemId, 'seq:', (item as any)?.seq, 'turn_id:', (item as any)?.turn_id)
      continue
    }
    const group = turnItems.get(turnId) ?? { outer: [], core: [] }
    group.outer.push(itemId)
    turnItems.set(turnId, group)
    if (!outerTurnIds.has(turnId)) {
      outerTurnIds.add(turnId)
      outerTurnOrder.push(turnId)
    }
  }

  for (const itemId of state.core?.item_order ?? []) {
    const item = coreItems[itemId]
    const turnId = typeof item?.turn_id === 'string' ? item.turn_id : ''
    if (!turnId) {
      looseCore.push(itemId)
      if (import.meta.env.DEV) console.warn('[order] looseCore:', itemId, 'seq:', (item as any)?.seq, 'turn_id:', (item as any)?.turn_id)
      continue
    }
    const group = turnItems.get(turnId) ?? { outer: [], core: [] }
    group.core.push(itemId)
    turnItems.set(turnId, group)
    if (!coreTurnIds.has(turnId)) {
      coreTurnIds.add(turnId)
      coreTurnOrder.push(turnId)
    }
  }

  const continuationsByOuterTurn = new Map<string, string[]>()
  let precedingOuterTurn = ''
  for (const turnId of coreTurnOrder) {
    if (outerTurnIds.has(turnId)) {
      precedingOuterTurn = turnId
      continue
    }
    if (!precedingOuterTurn) continue
    const continuations = continuationsByOuterTurn.get(precedingOuterTurn) ?? []
    continuations.push(turnId)
    continuationsByOuterTurn.set(precedingOuterTurn, continuations)
  }

  for (const itemId of [...looseOuter, ...looseCore]) {
    pushOnce(order, seen, itemId)
  }
  for (const turnId of outerTurnOrder) {
    const group = turnItems.get(turnId)
    if (!group) continue
    // DEV diagnostic: a core item sequenced BEFORE this turn's outer items
    // would render the assistant segment above the user message.
    if (import.meta.env.DEV && group.outer.length > 0 && group.core.length > 0) {
      const outerMin = Math.min(...group.outer.map(id => outerSeqAnchor(outerItems[id])))
      const coreMin = Math.min(...group.core.map(id => coreSeqAnchor(coreItems[id])))
      if (coreMin < outerMin) {
        console.warn(
          '[order] core-before-outer turn:', turnId,
          'outerMin:', outerMin,
          'coreMin:', coreMin,
          'outer:', group.outer.map(id => `${id}@${(outerItems[id] as any)?.seq}`).join(', '),
          'core:', group.core.map(id => `${id}@${(coreItems[id] as any)?.seq}`).join(', '),
        )
      }
    }
    // Outer (user-side) and core (runtime) items share the thread-global seq
    // timeline. Mid-turn user messages (e.g. queue guide: `turn:user:guide:*`)
    // must appear between the runtime items they chronologically follow, so
    // the two lists are interleaved by seq instead of outer-first concatenation.
    for (const itemId of mergeOuterCoreBySeq(group.outer, group.core, outerItems, coreItems)) {
      pushOnce(order, seen, itemId)
    }
    for (const continuationTurnId of continuationsByOuterTurn.get(turnId) ?? []) {
      for (const itemId of turnItems.get(continuationTurnId)?.core ?? []) {
        pushOnce(order, seen, itemId)
      }
    }
  }
  for (const turnId of coreTurnOrder) {
    for (const itemId of turnItems.get(turnId)?.core ?? []) {
      pushOnce(order, seen, itemId)
    }
  }
  return order
}

function pushOnce(order: string[], seen: Set<string>, itemId: string) {
  if (!itemId || seen.has(itemId)) return
  seen.add(itemId)
  order.push(itemId)
}

/**
 * Interleave a turn's outer (user-side) and core (runtime) item ids by their
 * thread-global seq anchors. Both lists are individually seq-ascending, so a
 * two-pointer merge stays O(n) (hot path: runs on every stream frame).
 * Items without a seq anchor keep the legacy concatenation position: missing
 * outer seq sorts first (outer-first), missing core seq sorts last (core-last).
 */
function mergeOuterCoreBySeq(
  outer: string[],
  core: string[],
  outerItems: Record<string, CoreAppItem>,
  coreItems: Record<string, CoreRuntimeItem>,
): string[] {
  const result: string[] = []
  let i = 0
  let j = 0
  while (i < outer.length || j < core.length) {
    const outerNext = i < outer.length ? outerSeqAnchor(outerItems[outer[i]]) : Number.POSITIVE_INFINITY
    const coreNext = j < core.length ? coreSeqAnchor(coreItems[core[j]]) : Number.POSITIVE_INFINITY
    if (i < outer.length && outerNext <= coreNext) {
      result.push(outer[i])
      i += 1
    } else if (j < core.length) {
      result.push(core[j])
      j += 1
    } else {
      result.push(outer[i])
      i += 1
    }
  }
  return result
}

function outerSeqAnchor(item: CoreAppItem | undefined): number {
  const seq = typeof item?.seq === 'number' ? item.seq : Number.NaN
  return Number.isFinite(seq) ? seq : Number.NEGATIVE_INFINITY
}

function coreSeqAnchor(item: CoreRuntimeItem | undefined): number {
  const seq = typeof item?.seq === 'number' ? item.seq : Number.NaN
  return Number.isFinite(seq) ? seq : Number.POSITIVE_INFINITY
}

function isFinalAssistantContentItem(
  state: CoreAppSnapshot,
  item: CoreAppItem,
  itemId: string,
  itemOrder: string[],
): boolean {
  const turnId = typeof item.turn_id === 'string' ? item.turn_id : ''
  if (!turnId) return false
  const turnStatus = String(state.core?.turns?.[turnId]?.status || state.turns?.[turnId]?.status || '')
  const turnIsTerminal = ['completed', 'failed', 'cancelled'].includes(turnStatus)
  if (turnStatus && !turnIsTerminal) return false
  if (!turnIsTerminal && String(item.status || '') !== 'completed') return false
  return lastAgentMessageItemIdForTurn(state, turnId, itemOrder) === itemId
}

function lastAgentMessageItemIdForTurn(state: CoreAppSnapshot, turnId: string, itemOrder: string[]): string {
  let last = ''
  for (const orderedItemId of itemOrder) {
    const candidate = canonicalItemForId(state, orderedItemId) ?? outerProductItemForId(state, orderedItemId)
    if (!candidate || candidate.type !== 'agentMessage') continue
    if (candidate.turn_id !== turnId) continue
    last = orderedItemId
  }
  return last
}

function canonicalItemForId(
  state: CoreAppSnapshot,
  itemId: string,
  cache?: Map<CoreRuntimeItem, CoreAppItem>,
): CoreAppItem | undefined {
  const coreItem = state.core?.items?.[itemId]
  if (!coreItem) return undefined
  if (cache) {
    const cached = cache.get(coreItem)
    if (cached) return cached
    const app = coreItemToAppItem(coreItem)
    cache.set(coreItem, app)
    return app
  }
  return coreItemToAppItem(coreItem)
}

function outerProductItemForId(state: CoreAppSnapshot, itemId: string): CoreAppItem | undefined {
  const item = state.items?.[itemId]
  if (!item || (item.type !== 'userMessage' && item.type !== 'systemMessage')) return undefined
  return item
}

function coreItemToAppItem(item: CoreRuntimeItem): CoreAppItem {
  const rawPayload: Record<string, unknown> = item.payload && typeof item.payload === 'object' ? item.payload : {}
  const payload = normalizeLegacyDeliveryFields(rawPayload)
  const type = normalizeCoreItemDisplayType(payload, coreItemType(item))
  return {
    ...payload,
    item_id: item.item_id,
    turn_id: item.turn_id,
    parent_item_id: item.parent_item_id,
    type,
    status: item.status,
    // userMessage content is an array of typed input parts.  Keeping only
    // strings made locally-created mobile user messages render as empty.
    // The same trap bites a run-item user message (mid-turn guidance): it
    // carries its parts in payload.content while the record's own ``content``
    // stays empty — an empty string is not nullish, so ``??`` never fell
    // through and the bubble rendered without its text.
    content: item.content || payload.content,
    deltas: item.deltas,
    artifacts: item.artifacts,
    usage: item.usage,
    core_kind: item.kind,
    core_last_kind: item.last_kind,
    // Carry the source item's metadata through (audit 15 S1: it was dropped
    // here, so message-level flags like ``metadata.live`` never reached the
    // projection).
    // Preserve both runtime envelope metadata and tool-result metadata. The
    // latter carries task_plan/active_plan for checklist projection.
    metadata: {
      ...(isRecord(payload.metadata) ? payload.metadata : {}),
      ...(isRecord(item.metadata) ? item.metadata : {}),
    },
  }
}

function normalizeCoreItemDisplayType(payload: Record<string, unknown>, fallback: string): string {
  if (fallback === 'status' || fallback === 'error') return fallback
  const type = String(payload.type || fallback)
  if (type === 'dynamicToolCall' && String(payload.tool_name || '') === 'sub_agent') {
    const args = isRecord(payload.arguments) ? payload.arguments : {}
    if (args.action === 'create' || args.action === 'close') return type
    return 'agent_summary'
  }
  return type
}

function normalizeLegacyDeliveryFields(payload: Record<string, unknown>): Record<string, unknown> {
  const metadata = normalizeMetadataDelivery(payload.metadata)
  let normalized = metadata === payload.metadata ? payload : { ...payload, metadata }
  if (!("limit_tokens" in normalized) && "target_tokens" in normalized) {
    normalized = { ...normalized, limit_tokens: normalized.target_tokens }
  }
  if ("target_tokens" in normalized) {
    const { target_tokens: _legacyTargetTokens, ...current } = normalized
    normalized = current
  }
  return normalized
}

function normalizeMetadataDelivery(value: unknown): unknown {
  if (!isRecord(value)) return value
  let next: Record<string, unknown> | null = null

  const directDelivery = normalizeDeliveryRecord(value.workspace_delivery)
  if (directDelivery !== value.workspace_delivery) {
    next = { ...value, workspace_delivery: directDelivery }
  }

  const current = next ?? value
  const camelDelivery = normalizeDeliveryRecord(current.workspaceDelivery)
  if (camelDelivery !== current.workspaceDelivery) {
    next = { ...current, workspaceDelivery: camelDelivery }
  }

  const afterDirect = next ?? value
  if (isRecord(afterDirect.diagnostics)) {
    let diagnostics: Record<string, unknown> | null = null
    const diagnosticsDelivery = normalizeDeliveryRecord(afterDirect.diagnostics.workspace_delivery)
    if (diagnosticsDelivery !== afterDirect.diagnostics.workspace_delivery) {
      diagnostics = { ...afterDirect.diagnostics, workspace_delivery: diagnosticsDelivery }
    }

    const currentDiagnostics = diagnostics ?? afterDirect.diagnostics
    const diagnosticsCamelDelivery = normalizeDeliveryRecord(currentDiagnostics.workspaceDelivery)
    if (diagnosticsCamelDelivery !== currentDiagnostics.workspaceDelivery) {
      diagnostics = { ...currentDiagnostics, workspaceDelivery: diagnosticsCamelDelivery }
    }

    if (diagnostics) {
      next = { ...afterDirect, diagnostics }
    }
  }

  return next ?? value
}

function normalizeDeliveryRecord(value: unknown): unknown {
  if (!isRecord(value)) return value
  return value
}

function isDeletedSubAgentItem(item: CoreAppItem, deleted: ReadonlySet<string>): boolean {
  if (deleted.size === 0) return false
  const meta = isRecord(item.metadata) ? item.metadata : {}
  const sub = isRecord(meta.sub_agent) ? meta.sub_agent : null
  if (!sub) return false
  return [sub.name, sub.agent, sub.session_id, sub.sub_session_id].some(
    value => typeof value === 'string' && value.length > 0 && deleted.has(value),
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

/** Turn-level terminal row ("已中断。" / a named failure): the one explanation
 *  a cancelled or failed turn is allowed to show. */
function isTurnTerminalStatusItem(item: CoreAppItem): boolean {
  return item.type === 'status'
    && (item.status === 'cancelled' || item.status === 'failed')
    && typeof item.raw_end_reason === 'string'
}

/** A model-retry bar the turn can no longer answer: crash recovery flipped it
 *  to a terminal status, so it would render forever as a stuck "重试中" row. */
function isDeadModelRetryItem(item: CoreAppItem): boolean {
  return typeof item.item_id === 'string'
    && item.item_id.includes(':model-retry:')
    && (item.status === 'cancelled' || item.status === 'failed')
}

function coreItemType(item: CoreRuntimeItem): string {
  if (item.kind === 'thinking') return 'reasoning'
  // 审批请求恢复：事件流里 kind='approval_request'；持久化快照里同一 item 的
  // kind 保持 'tool_call'（_upsert_item 不覆盖既有 kind），只更新 last_kind /
  // payload.type='serverRequest'——断连重连走快照恢复时必须按这两个信号识别，
  // 否则审批卡在恢复后永久丢失（question/decision_point 等 control tool 不渲染工具卡）。
  if (item.kind === 'approval_request'
    || item.last_kind === 'approval_request'
    || (isRecord(item.payload) && item.payload.type === 'serverRequest')) {
    return 'serverRequest'
  }
  if (item.kind === 'tool_call' || item.kind === 'tool_result') return 'dynamicToolCall'
  if (item.kind === 'error') return 'error'
  if (item.kind === 'status') return 'status'
  return 'agentMessage'
}

function artifactsGroupedByItem(state: CoreAppSnapshot): Map<string, Record<string, unknown>[]> {
  const grouped = new Map<string, Record<string, unknown>[]>()
  const artifacts = [
    ...Object.values(state.artifacts ?? {}),
    ...Object.values(state.core?.artifacts ?? {}),
  ]
  const seen = new Set<string>()
  for (const artifact of artifacts) {
    const itemId = typeof artifact.item_id === 'string' ? artifact.item_id : ''
    if (!itemId) continue
    const artifactId = typeof artifact.artifact_id === 'string'
      ? artifact.artifact_id
      : typeof artifact.id === 'string'
        ? artifact.id
        : `${itemId}:${JSON.stringify(artifact)}`
    if (seen.has(artifactId)) continue
    seen.add(artifactId)
    const list = grouped.get(itemId) ?? []
    list.push(artifact)
    grouped.set(itemId, list)
  }
  return grouped
}

function withItemArtifacts(item: CoreAppItem, artifacts?: Record<string, unknown>[]): CoreAppItem {
  if (!artifacts?.length) return item
  return {
    ...item,
    artifacts,
  }
}

function isRenderableItem(item: CoreAppItem): boolean {
  const type = String(item.type || '')
  if (!RENDERABLE_ITEM_TYPES.has(type)) return false
  return true
}

/**
 * The member-wait status row (`<turn>:sub-agent-wait`, payload type
 * `subAgents`) is a machine signal: `selectCoreSessionActivity` reads it for
 * the "main stopped, members still running" state. It is not conversation
 * content, so it must not render as a stray status row in the transcript.
 */
function isMemberWaitSignalItem(item: CoreAppItem): boolean {
  return typeof item.item_id === 'string' && item.item_id.endsWith(':sub-agent-wait')
}

function inputToText(value: unknown): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) {
    return value.map((item) => {
      if (item && typeof item === 'object' && 'text' in item) {
        return String((item as { text?: unknown }).text ?? '')
      }
      return ''
    }).join('')
  }
  return ''
}

function inputAttachments(value: unknown): CoreAppServerChatMessage['attachments'] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (!item || typeof item !== 'object') return []
    const record = item as Record<string, unknown>
    if (record.type !== 'attachment') return []
    const id = String(record.attachment_id || record.attachmentId || record.id || '').trim()
    if (!id) return []
    const filename = String(record.filename || record.label || 'attachment')
    return [{
      id,
      filename,
      label: filename,
      mime_type: String(record.mime_type || record.mimeType || 'application/octet-stream'),
      size: Number(record.size || 0),
      preview_type: String(record.preview_type || record.previewType || 'external'),
      status: 'uploaded' as const,
    }]
  })
}
