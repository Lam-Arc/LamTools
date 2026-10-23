/**
 * Pending user decisions (approval / question requests) — one canonical home.
 *
 * A `decision` part is the UI form of a runtime waiting request
 * (`runtime.approval_request` → `serverRequest` item → `decision` part). Two
 * surfaces consume it:
 *  - the in-thread card (`MessageView.vue`), and
 *  - the composer takeover panel (`CorePendingDecisionPanel.vue`).
 *
 * Both must agree on which options a request offers and — most importantly —
 * what payload an option click produces. That payload feeds
 * `coreDecisionSelectionPlan` and therefore the wire decision
 * (`approve_once` / `deny` / `other_guidance`), so it lives here once instead
 * of being restated per surface.
 */
import type { CoreAppInteraction } from './protocol.ts'
import type { CoreMessage, MessagePart } from '../types.ts'

export type CoreDecisionFactTone = 'neutral' | 'warn'

export interface CoreDecisionOption {
  id: string
  label: string
  description?: string
  response?: string
}

/**
 * An option plus the exact response text a click sends to the runtime. Resolved
 * once here so both surfaces send identical guidance.
 */
export interface CoreDecisionChoice extends CoreDecisionOption {
  wireResponse: string
}

/** One "what is this about" line shown next to the options. */
export interface CoreDecisionFact {
  label: string
  value: string
  tone: CoreDecisionFactTone
  /** Paths / commands render in the mono stack. */
  mono?: boolean
}

/** A decision part that still needs the user, with its presentation payload. */
export interface CorePendingDecision {
  partId: string
  requestId: string
  /** True for `question` / `ask_clarification` style asks. */
  isQuestion: boolean
  kindLabel: string
  /** What is being asked, unprefixed. */
  subject: string
  /** Card title form (`需要确认：…`) kept stable for MessageView. */
  title: string
  detail: string
  facts: CoreDecisionFact[]
  options: CoreDecisionChoice[]
  status: MessagePart['status']
  /** The decision is on the wire and the runtime has not resolved it yet. */
  submitting: boolean
  /** Free-form guidance can be submitted for this request. */
  canGuide: boolean
  /**
   * The sub-agent that asked, when the request is nested under a delegated
   * run. Answering routes by `requestId`; this is what tells the user (and the
   * panel) which sub-agent the request belongs to instead of silently
   * attributing it to the main agent.
   */
  subAgentName: string
  /** Durable child session id of the asking sub-agent, when known. */
  subAgentSessionId: string
  /** Decision-pool identity and provenance. */
  decisionId: string
  sequence: number
  lifecycle: 'appearing' | 'processing' | 'ending'
  deliveredBy: string
  projectId: string
}

export interface SelectPendingCoreDecisionsOptions {
  /** Request ids already sent to the runtime (from the approval controller). */
  submittingRequestIds?: ReadonlySet<string> | null
  /** Subject truncation; the composer panel has more room than the thread card. */
  subjectLimit?: number
}

const DEFAULT_SUBJECT_LIMIT = 56
const DEFAULT_DETAIL_LIMIT = 240

/**
 * Per-message memo.  The projection reuses message objects for unchanged
 * messages, so the scan below only runs for messages that actually changed —
 * the composer panel derives on every stream tick and must not re-walk the
 * whole thread.  WeakMap keeps the cache from outliving the messages.
 */
const pendingPartsByMessage = new WeakMap<CoreMessage, PendingDecisionEntry[]>()

/**
 * Decisions that still need the user, oldest request first.
 *
 * Mirrors the runtime's own notion of "actionable": status `pending` (waiting)
 * or `running` (decision on the wire, response not projected yet), and no
 * recorded response. Answered (`completed`) parts are excluded — `MessageView`
 * drops them from the process timeline for the same reason.
 */
export function selectPendingCoreDecisions(
  messages: readonly CoreMessage[],
  options: SelectPendingCoreDecisionsOptions = {},
): CorePendingDecision[] {
  const decisions: CorePendingDecision[] = []
  const seenPartIds = new Set<string>()
  const submittingRequestIds = options.submittingRequestIds ?? null
  const subjectLimit = options.subjectLimit ?? DEFAULT_SUBJECT_LIMIT
  // Oldest request first: the queue is presented in the order the runtime asked
  // it, so the user drains it front to back.
  for (const message of messages) {
    if (!message || message.role !== 'assistant') continue
    for (const entry of pendingDecisionParts(message)) {
      const part = entry.part
      if (seenPartIds.has(part.id)) continue
      seenPartIds.add(part.id)
      const requestId = coreDecisionRequestId(part)
      const subject = coreDecisionSubject(part, subjectLimit)
      decisions.push({
        partId: part.id,
        requestId,
        isQuestion: coreDecisionIsQuestion(part),
        kindLabel: coreDecisionKindLabel(part),
        subject,
        title: coreDecisionTitle(part),
        detail: supplementalDetail(part, subject),
        facts: coreDecisionFacts(part),
        options: coreDecisionOptions(part).map(option => ({
          ...option,
          wireResponse: coreDecisionOptionResponse(part, option),
        })),
        status: part.status,
        submitting: part.status === 'running'
          || Boolean(requestId && submittingRequestIds?.has(requestId)),
        canGuide: part.status === 'pending',
        subAgentName: entry.subAgentName,
        subAgentSessionId: entry.subAgentSessionId,
        decisionId: String(part.metadata?.decision_id || ''),
        sequence: Number(part.metadata?.sequence || 0),
        lifecycle: part.status === 'running' ? 'processing' : 'appearing',
        deliveredBy: String(part.metadata?.delivered_by || (entry.subAgentName ? `agent:${entry.subAgentName}` : 'main')),
        projectId: String(part.metadata?.project_id || ''),
      })
    }
  }
  return decisions
}

/**
 * Request identities the server already knows about.
 *
 * The interaction index is authoritative for a request's lifecycle. A card
 * recovered from the message tree must not re-appear once the pool has the
 * same request — open (the pool card wins) or terminal (it was answered).
 * Legacy servers without a pool keep the message-backed fallback.
 */
export function coreKnownRequestIds(
  interactions: readonly CoreAppInteraction[] | undefined,
  requests: Readonly<Record<string, { status?: unknown; request_id?: unknown }>> | undefined,
): Set<string> {
  const known = new Set<string>()
  for (const interaction of interactions || []) {
    if (!interaction) continue
    for (const id of [
      interaction.interaction_id,
      interaction.request_id,
      interaction.tool_call_id,
    ]) {
      if (id) known.add(String(id))
    }
  }
  for (const [key, request] of Object.entries(requests || {})) {
    const status = String(request?.status || '')
    if (status !== 'resolved' && status !== 'cancelled' && status !== 'expired') continue
    if (key) known.add(key)
    if (request?.request_id) known.add(String(request.request_id))
  }
  return known
}

/**
 * The cards the interface should show.
 *
 * The interaction pool is the single display authority: a card appears when
 * the pool gains a row, changes when that row changes, and disappears when the
 * row ends (the next row fills the slot by its assigned sequence). The message
 * tree is only a fallback for hosts/snapshots that have no pool field at all —
 * never a second source next to a present pool. This is what prevents an
 * answered request from reappearing out of a stale message part.
 *
 * 用户要求（原文）：“前端显示的更新时间应当是池子内信息发生变动的时候，当一个
 * 卡片或请求被回答完毕之后，这个东西被丢出池子，然后池子顺位补上下一个。”
 * 用户要求（原文）：“这个东西不应该是前端显示池子内拥有的东西”
 */
export function selectVisiblePendingDecisions(
  messages: readonly CoreMessage[],
  interactions: readonly CoreAppInteraction[] | undefined,
  options: SelectPendingCoreDecisionsOptions & {
    requests?: Readonly<Record<string, { status?: unknown; request_id?: unknown }>> | undefined
  } = {},
): CorePendingDecision[] {
  if (Array.isArray(interactions)) {
    return selectPendingInteractionDecisions(interactions)
  }
  const settled = coreKnownRequestIds(undefined, options.requests)
  return selectPendingCoreDecisions(messages, options)
    .filter(item => !item.requestId || !settled.has(item.requestId))
}

/**
 * Pending decisions from the server's interaction index.
 *
 * The transcript window can omit the turn that owns a card; these rows are
 * still answerable and appear in the composer panel. A part-backed card with
 * the same request id wins (it carries the richer tool metadata), so callers
 * should merge and dedupe by `requestId`.
 */
export function selectPendingInteractionDecisions(
  interactions: readonly CoreAppInteraction[] | undefined,
): CorePendingDecision[] {
  const decisions: CorePendingDecision[] = []
  for (const interaction of interactions || []) {
    if (!interaction || !interaction.interaction_id) continue
    const status = String(interaction.status || 'open')
    if (status !== 'open' && status !== 'deferred' && status !== 'processing') continue
    const lifecycle = String(interaction.lifecycle || (status === 'processing' ? 'processing' : 'appearing'))
    if (lifecycle === 'ending') continue
    const isQuestion = String(interaction.kind || '') === 'question'
    const title = String(interaction.title || '').trim() || '等待确认'
    const context = String(interaction.context || '').trim()
    const rawOptions = Array.isArray(interaction.options) ? interaction.options : []
    const options: CoreDecisionChoice[] = rawOptions
      .filter(option => Boolean(option && (option.label || option.id)))
      .map((option, index) => {
        const label = String(option.label || option.id || `选项 ${index + 1}`)
        return {
          id: String(option.id || `option-${index + 1}`),
          label,
          description: String(option.description || ''),
          response: option.response ? String(option.response) : undefined,
          wireResponse: option.response ? String(option.response) : label,
        }
      })
    if (options.length === 0) {
      options.push(
        ...(isQuestion
          ? [
              { id: 'option-confirm', label: '确认并继续', wireResponse: '确认并继续' },
              { id: 'option-skip', label: '跳过问题', wireResponse: '（用户跳过了这个问题，未提供回答。）' },
            ]
          : [
              { id: 'approve', label: '批准执行', wireResponse: 'approve' },
              { id: 'deny', label: '拒绝执行', wireResponse: 'deny' },
            ]),
      )
    }
    decisions.push({
      partId: `interaction:${interaction.interaction_id}`,
      requestId: interaction.interaction_id,
      isQuestion,
      kindLabel: isQuestion ? '提问' : '审批',
      subject: compactDetail(title, DEFAULT_SUBJECT_LIMIT),
      title: `需要确认：${compactDetail(title, DEFAULT_SUBJECT_LIMIT)}`,
      detail: context ? compactDetail(context, DEFAULT_DETAIL_LIMIT) : '',
      facts: [
        ...(context ? [{ label: '背景', value: compactDetail(context, 200), tone: 'neutral' as const }] : []),
        ...(interaction.delivered_by && interaction.delivered_by !== 'main'
          ? [{ label: '来源', value: interaction.delivered_by, tone: 'neutral' as const }]
          : []),
        ...(interaction.project_id
          ? [{ label: '项目', value: interaction.project_id, tone: 'neutral' as const }]
          : []),
      ],
      options,
      status: status === 'processing' ? 'running' : 'pending',
      submitting: status === 'processing',
      canGuide: isQuestion && status !== 'processing',
      subAgentName: String(interaction.agent_name || ''),
      subAgentSessionId: String(interaction.agent_session_id || ''),
      decisionId: String(interaction.decision_id || interaction.interaction_id),
      sequence: Number(interaction.sequence || 0),
      lifecycle: lifecycle === 'processing' ? 'processing' : 'appearing',
      deliveredBy: String(interaction.delivered_by || 'main'),
      projectId: String(interaction.project_id || ''),
    })
  }
  return decisions
}

/**
 * What the runtime is asking about, preferring the ask sentence the runtime
 * itself wrote (`需要授权后才能执行命令：npm test`). The composer panel is the
 * surface that answers a request, so it must name the request.
 */
export function coreDecisionSubject(part: MessagePart, limit = DEFAULT_SUBJECT_LIMIT): string {
  const raw = coreDecisionAskText(part)
  return raw ? compactDetail(raw, limit) : '等待确认'
}

/**
 * Compact timeline label for the in-thread card. Keeps the historical candidate
 * order (`MessageView` behaviour) because the card already prints the ask
 * sentence on its detail line.
 */
export function coreDecisionTitle(part: MessagePart): string {
  const raw = coreDecisionLegacySubject(part)
  return raw ? `需要确认：${compactDetail(raw, DEFAULT_SUBJECT_LIMIT)}` : '等待确认'
}

export function coreDecisionDetail(part: MessagePart, limit = DEFAULT_DETAIL_LIMIT): string {
  const args = part.toolArgs || {}
  const meta = part.metadata || {}
  const detail = args.reason || args.description || meta.reason || meta.description || part.detail || part.content
  const title = coreDecisionLegacySubject(part)
  if (!detail || detail === title) return ''
  return compactDetail(String(detail), limit)
}

export function coreDecisionOptions(part: MessagePart): CoreDecisionOption[] {
  const args = part.toolArgs || {}
  const meta = part.metadata || {}
  const raw = args.options || meta.options
  if (!Array.isArray(raw)) {
    return part.status === 'pending'
      ? [{ id: 'confirm', label: '确认并继续', description: '按当前方案继续执行' }]
      : []
  }
  return raw
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object' && !Array.isArray(item)))
    .map((item, index) => ({
      id: String(item.id || item.value || `option-${index + 1}`),
      label: String(item.label || item.title || item.id || `选项 ${index + 1}`),
      description: String(item.description || item.detail || ''),
      response: item.response ? String(item.response) : undefined,
    }))
    .filter(option => option.label)
}

/**
 * The exact `response` an option click sends to the runtime. Shared so the
 * in-thread card and the composer panel cannot drift apart on the wire text.
 */
export function coreDecisionOptionResponse(part: MessagePart, option: CoreDecisionOption): string {
  if (option.response) return option.response
  const raw = coreDecisionAskText(part)
  const lines = [`我选择：${option.label}`]
  if (option.description) lines.push(`原因/说明：${option.description}`)
  if (raw && raw !== '等待确认') lines.push(`对应决策：${compactDetail(raw, DEFAULT_SUBJECT_LIMIT)}`)
  return lines.join('\n')
}

export function coreDecisionRequestId(part: MessagePart): string {
  const meta = (part.metadata || {}) as Record<string, unknown>
  const waiting = asRecord(meta.waitingRequest)
  const requestId = waiting?.request_id ?? meta.request_id
  return requestId === undefined || requestId === null ? '' : String(requestId)
}

export function coreDecisionToolName(part: MessagePart): string {
  const meta = (part.metadata || {}) as Record<string, unknown>
  const candidate = part.toolName || meta.tool_name || meta.name || ''
  return typeof candidate === 'string' ? candidate : String(candidate || '')
}

/** True for `question` / `ask_clarification` style asks. */
export function coreDecisionIsQuestion(part: MessagePart): boolean {
  return isQuestionToolName(coreDecisionToolName(part))
}

/**
 * `审批` / `提问` — the ask's category tag. Shared by both surfaces so the
 * thread card and the answering panel label the same request the same way.
 */
export function coreDecisionKindLabel(part: MessagePart): string {
  return coreDecisionIsQuestion(part) ? '提问' : '审批'
}

export function coreDecisionIsUnanswered(part: MessagePart): boolean {
  if (part.partType !== 'decision') return false
  if (part.status !== 'pending' && part.status !== 'running') return false
  const meta = (part.metadata || {}) as Record<string, unknown>
  const waiting = asRecord(meta.waitingRequest)
  if (waiting && waiting.response) return false
  return !meta.waitingResponse
}

/**
 * "What am I being asked about" lines: the concrete target (command / file /
 * tool) and, for permission asks, whether it leaves the project directory.
 *
 * The approval projection carries no structured `arguments`, so the command or
 * path is recovered from the runtime's own ask sentence
 * (`kernel/loop.py:_approval_request_options_and_message`). Structured fields
 * win whenever a request does provide them.
 */
export function coreDecisionFacts(part: MessagePart): CoreDecisionFact[] {
  const facts: CoreDecisionFact[] = []
  const args = asRecord(part.toolArgs) || {}
  const meta = (part.metadata || {}) as Record<string, unknown>
  const callArgs = asRecord(meta.arguments) || {}
  const approval = asRecord(meta.approval)
  const message = typeof meta.message === 'string' ? meta.message : ''
  const toolName = coreDecisionToolName(part)
  const isQuestion = isQuestionToolName(toolName)

  const command = firstString(args.command, callArgs.command, matchAsk(message, /^需要授权后才能执行命令[：:]\s*(.+)$/))
  if (command) {
    pushFact(facts, { label: '命令', value: compactDetail(command, 120), tone: 'neutral', mono: true })
  }

  const paths = collectPaths(args, callArgs)
  if (paths.length > 0) {
    pushFact(facts, {
      label: paths.length > 1 ? `文件 (${paths.length})` : '文件',
      value: compactDetail(paths.join('、'), 140),
      tone: 'neutral',
      mono: true,
    })
  }

  const askedTool = toolName || matchAsk(message, /^需要授权后才能执行工具[：:]\s*(.+)$/)
  if (askedTool && !isQuestion) {
    pushFact(facts, { label: '工具', value: compactDetail(askedTool, 64), tone: 'neutral', mono: true })
  }

  const context = firstString(args.context, meta.context)
  if (context) {
    pushFact(facts, { label: '背景', value: compactDetail(context, 200), tone: 'neutral' })
  }

  const askReason = matchAsk(message, /^需要授权[：:]\s*(.+)$/)
  if (askReason) pushFact(facts, { label: '原因', value: compactDetail(askReason, 160), tone: 'neutral' })

  if (!isQuestion && approval) {
    const outside = approval.outside_workdir === true
    pushFact(facts, {
      label: '范围',
      value: outside ? '项目目录之外' : '项目目录内',
      tone: outside ? 'warn' : 'neutral',
    })
  }

  return facts
}

/** Ask sentence written by the runtime, preferred for the answering surface. */
function coreDecisionAskText(part: MessagePart): string {
  const args = part.toolArgs || {}
  const meta = (part.metadata || {}) as Record<string, unknown>
  return firstString(args.title, args.question, meta.title, meta.question, meta.message, part.label)
}

/**
 * Detail line for the panel: only kept when it says something the subject line
 * does not already say. A permission ask repeats itself (part content == ask
 * sentence), and printing the same sentence twice reads as noise.
 */
function supplementalDetail(part: MessagePart, subject: string): string {
  const detail = coreDecisionDetail(part)
  if (!detail) return ''
  const normalized = oneLine(detail)
  if (normalized === oneLine(subject)) return ''
  if (normalized === oneLine(coreDecisionAskText(part))) return ''
  return detail
}

/** Historical card label chain (no runtime ask sentence). */
function coreDecisionLegacySubject(part: MessagePart): string {
  const args = part.toolArgs || {}
  const meta = (part.metadata || {}) as Record<string, unknown>
  return firstString(args.title, args.question, meta.title, meta.question, part.label)
}

/** A pending part plus the sub-agent that owns it (empty for main-agent asks). */
interface PendingDecisionEntry {
  part: MessagePart
  subAgentName: string
  subAgentSessionId: string
}

function pendingDecisionParts(message: CoreMessage): PendingDecisionEntry[] {
  const cached = pendingPartsByMessage.get(message)
  if (cached) return cached
  const found: PendingDecisionEntry[] = []
  // Breadth-first over nested sub-agent lines, the same traversal order the
  // approval controller uses for request lookup. Each nested level remembers
  // the sub-agent it lives under, so an answer can be attributed (and the
  // request routed) to that run rather than to the main agent.
  const queue: Array<{ part: MessagePart; owner: PendingDecisionEntry | null }> = (
    message.parts || []
  ).map(part => ({ part, owner: null }))
  for (let cursor = 0; cursor < queue.length; cursor += 1) {
    const { part, owner } = queue[cursor]
    if (!part) continue
    // The part that owns a nested level is itself a sub-agent row when it
    // carries a child identity; otherwise the enclosing owner keeps applying.
    const selfOwner = owner ?? subAgentOwnerOf(part)
    if (coreDecisionIsUnanswered(part)) {
      found.push({
        part,
        subAgentName: selfOwner?.subAgentName ?? '',
        subAgentSessionId: selfOwner?.subAgentSessionId ?? '',
      })
    }
    const nested = part.metadata?.subLineParts || part.metadata?.sub_line_parts
    if (!Array.isArray(nested)) continue
    for (const child of nested) {
      if (isMessagePart(child)) queue.push({ part: child, owner: selfOwner })
    }
  }
  pendingPartsByMessage.set(message, found)
  return found
}

/** The sub-agent identity a part carries, if it is a delegated-run row. */
function subAgentOwnerOf(part: MessagePart): PendingDecisionEntry | null {
  const meta = (part.metadata || {}) as Record<string, unknown>
  const args = asRecord(part.toolArgs) || {}
  const name = firstString(
    meta.agent_name,
    meta.agentName,
    meta.sub_agent_name,
    args.agent_name,
    args.agentName,
    args.agent,
    args.name,
  )
  const sessionId = firstString(
    meta.sub_session_id,
    meta.subSessionId,
    args.sub_session_id,
    args.subSessionId,
  )
  if (!name && !sessionId) return null
  return { part, subAgentName: name, subAgentSessionId: sessionId }
}

/**
 * Every decision part in a message tree, nested sub-agent lines included.
 * Callers that only care about the parts themselves (e.g. the question
 * auto-continue) use this instead of re-walking the tree, so a request that
 * lives under a delegated run is never invisible to a decision surface.
 */
export function collectDecisionParts(parts: readonly MessagePart[]): MessagePart[] {
  const found: MessagePart[] = []
  const queue: MessagePart[] = [...parts]
  for (let cursor = 0; cursor < queue.length; cursor += 1) {
    const part = queue[cursor]
    if (!part) continue
    if (part.partType === 'decision') found.push(part)
    const nested = part.metadata?.subLineParts || part.metadata?.sub_line_parts
    if (!Array.isArray(nested)) continue
    for (const child of nested) {
      if (isMessagePart(child)) queue.push(child)
    }
  }
  return found
}

function matchAsk(message: string, pattern: RegExp): string {
  const match = message ? message.match(pattern) : null
  return match?.[1]?.trim() || ''
}

function collectPaths(...sources: Array<Record<string, unknown> | null>): string[] {
  const paths: string[] = []
  for (const source of sources) {
    if (!source) continue
    for (const key of ['path', 'file_path', 'filepath', 'target', 'paths', 'file_paths']) {
      const value = source[key]
      if (typeof value === 'string' && value.trim()) paths.push(value.trim())
      else if (Array.isArray(value)) {
        for (const item of value) {
          if (typeof item === 'string' && item.trim()) paths.push(item.trim())
        }
      }
    }
  }
  return [...new Set(paths)]
}

function firstString(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return ''
}

function pushFact(facts: CoreDecisionFact[], fact: CoreDecisionFact) {
  if (!fact.value) return
  if (facts.some(existing => existing.label === fact.label && existing.value === fact.value)) return
  facts.push(fact)
}

function isQuestionToolName(name: string): boolean {
  return /question|ask_clarification/i.test(name)
}

function oneLine(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

function compactDetail(value: string, limit: number): string {
  const collapsed = oneLine(value)
  return collapsed.length > limit ? `${collapsed.slice(0, limit)}...` : collapsed
}

function isMessagePart(value: unknown): value is MessagePart {
  return Boolean(value) && typeof value === 'object' && typeof (value as MessagePart).id === 'string'
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}
