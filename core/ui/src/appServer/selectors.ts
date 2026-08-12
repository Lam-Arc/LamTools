import type {
  CoreAppItem,
  CoreAppQueueItem,
  CoreAppRequestState,
  CoreAppSnapshot,
  CoreRuntimeItem,
} from './protocol.ts'

const RENDERABLE_ITEM_TYPES = new Set([
  'userMessage',
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

export interface CoreAppServerChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
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

export function selectLatestTurnStatus(state: CoreAppSnapshot): 'idle' | 'running' | 'waiting' | 'completed' | 'failed' | 'cancelled' {
  const coreStatus = state.core?.status
  if (coreStatus && coreStatus !== 'idle') return coreStatus
  return state.status ?? 'idle'
}

export function selectQueueTray(state: CoreAppSnapshot): CoreAppQueueItem[] {
  return [...(state.queue ?? [])].sort((a, b) => Number(a.seq ?? 0) - Number(b.seq ?? 0))
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

export function selectChatMessages(
  state: CoreAppSnapshot,
  itemCache?: Map<CoreRuntimeItem, CoreAppItem>,
  subAgentChildrenCache?: Map<string, CoreAppItem[]>,
): CoreAppServerChatMessage[] {
  const messages: CoreAppServerChatMessage[] = []
  const itemOrder = mergedItemOrder(state)
  const artifactsByItem = artifactsGroupedByItem(state)
  const subAgentChildren = subAgentChildrenByParentId(state, itemOrder, artifactsByItem, itemCache, subAgentChildrenCache)
  const nestedChildItemIds = new Set(
    [...subAgentChildren.values()].flatMap(items => items.map(item => item.item_id)),
  )
  const suppressedItemIds = duplicateSubAgentChildItemIds(state, itemOrder, itemCache)
  // Mid-turn user messages (queue guide) split a turn's runtime items into
  // several assistant segments; each segment needs a unique message id
  // (ChatThread keys on msg.id). The first segment keeps the legacy
  // `assistant:<turn>` id, later ones append `:<n>`.
  const assistantSegments = new Map<string, number>()
  for (const itemId of itemOrder) {
    if (suppressedItemIds.has(itemId) || nestedChildItemIds.has(itemId)) continue
    const rawItem = canonicalItemForId(state, itemId, itemCache) ?? outerProductItemForId(state, itemId)
    const itemWithArtifacts = rawItem ? withItemArtifacts(rawItem, artifactsByItem.get(itemId)) : undefined
    const item = itemWithArtifacts
      ? withSubAgentChildren(itemWithArtifacts, subAgentChildren.get(itemId))
      : undefined
    if (!item) continue
    if (!isRenderableItem(item)) continue
    if (item.type === 'userMessage') {
      messages.push({
        id: item.item_id,
        role: 'user',
        content: inputToText(item.content),
        parts: [],
        attachments: inputAttachments(item.content),
      })
      continue
    }
    const turnId = item.turn_id ?? 'none'
    const last = messages[messages.length - 1]
    if (!last || last.role !== 'assistant' || assistantSegmentTurnId(last.id) !== turnId) {
      const segment = (assistantSegments.get(turnId) ?? 0) + 1
      assistantSegments.set(turnId, segment)
      const coreTurn = typeof item.turn_id === 'string' ? state.core?.turns?.[item.turn_id] : null
      const runtimeMetrics = coreTurn && typeof coreTurn.usage === 'object' && coreTurn.usage ? coreTurn.usage : null
      messages.push({
        // Real turn ids contain colons (`<session>:turn:<run>`), so segments
        // are separated with `#` — never a colon.
        id: segment === 1 ? `assistant:${turnId}` : `assistant:${turnId}#${segment}`,
        role: 'assistant',
        content: '',
        parts: [],
        metadata: runtimeMetrics ? { processMetrics: runtimeMetrics } : undefined,
      })
    }
    const assistant = messages[messages.length - 1]
    if (item.type === 'agentMessage') {
      const content = String(item.content ?? '')
      // Always accumulate the last agentMessage text as content for backward compat
      // (simple text-only Q&A, message filtering etc.) while keeping ALL agentMessages
      // in parts for inline chronological rendering.
      if (!isProtocolEnvelopeText(content)) assistant.content = content
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
  const orderedItems: CoreAppItem[] = []
  for (const itemId of itemOrder) {
    const rawItem = canonicalItemForId(state, itemId, cache) ?? outerProductItemForId(state, itemId)
    if (!rawItem) continue
    const item = withItemArtifacts(rawItem, artifactsByItem.get(itemId))
    orderedItems.push(item)
    if (item.type === 'agent_summary' && item.tool_name === 'sub_agent') {
      subAgentParentIds.add(item.item_id)
    }
  }

  const children = new Map<string, CoreAppItem[]>()
  for (const item of orderedItems) {
    const parentId = typeof item.parent_item_id === 'string' ? item.parent_item_id : ''
    if (!parentId || !subAgentParentIds.has(parentId)) continue
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
  if (!children?.length || item.type !== 'agent_summary' || item.tool_name !== 'sub_agent') return item
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
  messages.push({
    id: `assistant:waiting:${last.id}`,
    role: 'assistant',
    content: '',
    parts: [],
    metadata: {
      live: true,
      initialWaiting: true,
    },
  })
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
  if (!item || item.type !== 'userMessage') return undefined
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
    content: typeof item.content === 'string'
      ? item.content
      : typeof payload.content === 'string'
        ? payload.content
        : undefined,
    deltas: item.deltas,
    artifacts: item.artifacts,
    usage: item.usage,
    core_kind: item.kind,
    core_last_kind: item.last_kind,
  }
}

function normalizeCoreItemDisplayType(payload: Record<string, unknown>, fallback: string): string {
  if (fallback === 'status' || fallback === 'error') return fallback
  const type = String(payload.type || fallback)
  if (type === 'dynamicToolCall' && String(payload.tool_name || '') === 'sub_agent') {
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function coreItemType(item: CoreRuntimeItem): string {
  if (item.kind === 'thinking') return 'reasoning'
  if (item.kind === 'tool_call' || item.kind === 'tool_result') return 'dynamicToolCall'
  if (item.kind === 'approval_request') return 'serverRequest'
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
