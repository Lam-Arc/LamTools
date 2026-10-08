import type {
  CoreMessage,
  CoreSubAgentStatus,
  CoreSubAgentRun,
  MessagePart,
  MessagePartStatus,
} from '../types'

interface MutableSubAgentRun extends CoreSubAgentRun {
  lastOrder: number
}

/** Identity of the sub-agent a transcript part belongs to. The durable child
 * session id leads; the name is the fallback while the first streamed events
 * have not been assigned a session yet. */
export interface CoreSubAgentRef {
  subSessionId: string
  name: string
}

export function coreSubAgentRef(part: MessagePart): CoreSubAgentRef {
  return { subSessionId: subAgentSessionId(part), name: subAgentName(part) }
}

/** Resolve a ref against the projected runs: session id wins, the name matches
 * only as a fallback (a resumed name can own several runs — the live one is
 * what the operator wants to watch). */
export function findCoreSubAgentRun(
  runs: readonly CoreSubAgentRun[],
  ref: CoreSubAgentRef | string,
): CoreSubAgentRun | undefined {
  const wanted: CoreSubAgentRef = typeof ref === 'string'
    ? { subSessionId: ref, name: '' }
    : ref
  const sessionId = String(wanted.subSessionId || '').trim()
  if (sessionId) {
    const bySession = runs.find(run => run.subSessionId === sessionId
      || run.id === sessionId
      || (run.subSessionIds || []).includes(sessionId))
    if (bySession) return bySession
  }
  const name = String(wanted.name || '').trim().toLowerCase()
  if (!name) return undefined
  const byName = runs.filter(run => String(run.name || '').trim().toLowerCase() === name)
  if (byName.length === 0) return undefined
  return byName.find(run => run.status === 'running') || byName[byName.length - 1]
}

export function selectCoreSubAgentRuns(messages: readonly CoreMessage[]): CoreSubAgentRun[] {
  const runs = new Map<string, MutableSubAgentRun>()
  let order = 0

  for (const message of messages) {
    for (const part of message.parts ?? []) {
      if (!isSubAgentPart(part)) continue
      order += 1
      // Agent names are the stable identity across resumed child sessions.
      // During the first streaming events the backend may not have assigned a
      // sub_session_id yet; retain those events by falling back to the name,
      // then the event id as a last resort.
      const subSessionId = subAgentSessionId(part)
      // Completed legacy summaries without a durable id cannot be located
      // safely. Keep active events, and retain old summaries when they carry
      // the model field used by pre-session snapshots (args.model).
      if (
        !subSessionId
        && !isSubAgentLifecyclePart(part)
        && part.status !== 'running'
        && part.status !== 'pending'
        && !subAgentModelId(part)
      ) continue
      const name = subAgentName(part)
      const key = subAgentRunKey(part, name, subSessionId)
      const task = subAgentTask(part)
      const existing = runs.get(key)
      const run = existing ?? createRun(part, key, subSessionId, task, message.timestamp, order)
      if (!existing) runs.set(key, run)

      const lifecycleChanged = Boolean(existing && isNewSubAgentLifecycle(existing, part, subSessionId))
      if (lifecycleChanged) {
        // A named agent can be resumed more than once.  Keep the previous
        // source arrays for navigation, while the scalar timing/status fields
        // describe the currently active lifecycle.
        run.startedAt = subAgentTimestamp(part, 'started') || part.startedAt || message.timestamp || run.startedAt
        run.completedAt = undefined
        run.elapsedMs = 0
      }

      if (!run.task && task) {
        run.task = task
        run.timeline.unshift(taskMessage(run.subSessionId, task, part.startedAt || message.timestamp))
      }

      const modelId = subAgentModelId(part)
      const explicitType = subAgentType(part)
      const explicitReasoningLevel = subAgentReasoningLevel(part)
      const partStartedAt = subAgentTimestamp(part, 'started')
      const partCompletedAt = subAgentTimestamp(part, 'completed')
      const updatedAt = partCompletedAt || part.completedAt || partStartedAt || part.startedAt || message.timestamp
      run.name = name || run.name
      run.modelId = modelId || run.modelId
      run.model = modelId || run.model || run.modelId
      run.type = explicitType || run.type || 'execute'
      run.reasoningLevel = explicitReasoningLevel || run.reasoningLevel
      run.status = subAgentProjectedStatus(part, existing)
      run.startedAt = run.startedAt || partStartedAt || part.startedAt || message.timestamp
      run.updatedAt = updatedAt || run.updatedAt
      run.completedAt = isTerminalStatus(run.status)
        ? partCompletedAt || part.completedAt || run.completedAt || (run.status !== 'completed' ? updatedAt : undefined)
        : undefined
      run.elapsedMs = subAgentElapsedMs(part, run.startedAt, run.completedAt, message.timestamp)
      run.summary = subAgentSummary(part, task) || run.summary || run.task
      run.sourceCallId = subAgentSourceCallId(part) || run.sourceCallId
      run.lastOrder = order
      if (!run.sourcePartIds.includes(part.id)) run.sourcePartIds.push(part.id)
      const sourceMessageId = subAgentSourceMessageId(part) || message.id
      const sourcePartId = subAgentSourcePartId(part) || part.id
      if (!run.sourceMessageIds) run.sourceMessageIds = []
      if (!run.sourceMessageIds.includes(sourceMessageId)) run.sourceMessageIds.push(sourceMessageId)
      run.sourceMessageId = sourceMessageId
      run.sourcePartId = sourcePartId
      if (!run.subSessionIds) run.subSessionIds = []
      if (subSessionId && !run.subSessionIds.includes(subSessionId)) run.subSessionIds.push(subSessionId)
      if (subSessionId) run.subSessionId = subSessionId

      const replacementIndex = run.timeline.findIndex(item => item.metadata?.sourcePartId === part.id)
      run.timeline = run.timeline.filter(item => item.metadata?.sourcePartId !== part.id)
      const projectedMessages = subAgentMessages(part, run.subSessionId, message.timestamp)
      if (replacementIndex >= 0) run.timeline.splice(replacementIndex, 0, ...projectedMessages)
      else run.timeline.push(...projectedMessages)
    }
  }

  return [...runs.values()]
    .sort(compareSubAgentRuns)
    .map(({ lastOrder: _lastOrder, ...run }) => run)
}

function createRun(
  part: MessagePart,
  key: string,
  subSessionId: string,
  task: string,
  timestamp: string,
  order: number,
): MutableSubAgentRun {
  const startedAt = subAgentTimestamp(part, 'started') || part.startedAt || timestamp
  const sessionId = subSessionId || key
  const modelId = subAgentModelId(part)
  return {
    id: subSessionId || key,
    subSessionId: sessionId,
    name: subAgentName(part) || 'Sub Agent',
    task,
    status: part.status,
    modelId,
    startedAt,
    updatedAt: subAgentTimestamp(part, 'completed') || part.completedAt || startedAt,
    timeline: task ? [taskMessage(sessionId, task, startedAt)] : [],
    sourcePartIds: [],
    type: subAgentType(part),
    model: modelId,
    reasoningLevel: subAgentReasoningLevel(part),
    summary: subAgentSummary(part, task),
    completedAt: isTerminalStatus(part.status) ? subAgentTimestamp(part, 'completed') || part.completedAt : undefined,
    elapsedMs: subAgentElapsedMs(part, startedAt, subAgentTimestamp(part, 'completed') || part.completedAt, timestamp),
    sourceMessageIds: [],
    subSessionIds: subSessionId ? [subSessionId] : [],
    lastOrder: order,
  }
}

function subAgentRunKey(part: MessagePart, name: string, subSessionId: string): string {
  const stableName = name.trim().toLowerCase()
  if (stableName && stableName !== 'sub_agent' && stableName !== 'subagent') return `name:${stableName}`
  if (subSessionId) return `session:${subSessionId}`
  return `part:${part.id}`
}

/**
 * Lifecycle/tool rows do not always carry a child session id.  They are still
 * useful evidence for the durable named-agent row (create/close/message), so
 * retain them when the action or mailbox tool identifies the event.
 */
function isSubAgentLifecyclePart(part: MessagePart): boolean {
  const toolName = String(part.toolName || part.label || '').trim().toLowerCase()
  if (toolName === 'sub_agent_message' || toolName === 'sub_agent_receive') return true
  if (toolName !== 'sub_agent' && toolName !== 'subagent') return false
  const action = subAgentLifecycleAction(part)
  return action === 'create'
    || action === 'close'
    || action === 'created'
    || action === 'enabled'
    || action === 'reopened'
    || action === 'closed'
    || action === 'message_sent'
    || action === 'message_received'
}

function subAgentLifecycleAction(part: MessagePart): string {
  const metadata = record(part.metadata)
  const nestedMetadata = record(metadata.metadata)
  const envelope = record(metadata.sub_agent || metadata.subAgent)
  const args = record(part.toolArgs)
  const explicit = firstText(
    args.action,
    metadata.lifecycle_action,
    metadata.lifecycleAction,
    metadata.action,
    nestedMetadata.lifecycle_action,
    nestedMetadata.lifecycleAction,
    nestedMetadata.action,
    envelope.lifecycle_action,
    envelope.lifecycleAction,
    envelope.action,
  ).toLowerCase()
  if (explicit) return explicit
  const toolName = String(part.toolName || part.label || '').trim().toLowerCase()
  if (toolName === 'sub_agent_message') return 'message_sent'
  if (toolName === 'sub_agent_receive') return 'message_received'
  return ''
}

function compareSubAgentRuns(left: MutableSubAgentRun, right: MutableSubAgentRun): number {
  // Active work stays above historical rows; within a state, newest evidence
  // wins.  This is deterministic for equal timestamps because lastOrder is a
  // monotonic source-order tie breaker.
  const stateRank: Record<string, number> = {
    running: 0,
    pending: 1,
    paused: 2,
    error: 3,
    failed: 3,
    interrupted: 4,
    idle: 5,
    closed: 6,
    completed: 7,
  }
  const rankDelta = (stateRank[String(left.status)] ?? 8) - (stateRank[String(right.status)] ?? 8)
  if (rankDelta !== 0) return rankDelta
  const leftTime = Date.parse(left.updatedAt || left.completedAt || left.startedAt || '')
  const rightTime = Date.parse(right.updatedAt || right.completedAt || right.startedAt || '')
  if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) return rightTime - leftTime
  return right.lastOrder - left.lastOrder
}

function isNewSubAgentLifecycle(
  run: CoreSubAgentRun,
  part: MessagePart,
  subSessionId: string,
): boolean {
  const currentStatus = run.status
  const active = part.status === 'running' || part.status === 'pending'
  const action = subAgentLifecycleAction(part)
  if ((action === 'create' || action === 'created' || action === 'enabled' || action === 'reopened')
    && (currentStatus === 'closed' || currentStatus === 'interrupted' || currentStatus === 'error' || currentStatus === 'completed')) {
    return true
  }
  if (action === 'message_sent' && (currentStatus === 'closed' || currentStatus === 'paused' || currentStatus === 'completed')) {
    return true
  }
  if (active && (currentStatus === 'completed' || currentStatus === 'error')) return true
  return Boolean(subSessionId && run.subSessionId && subSessionId !== run.subSessionId)
}

function isTerminalStatus(status: CoreSubAgentStatus | undefined): boolean {
  return status === 'completed' || status === 'error'
}

function taskMessage(subSessionId: string, task: string, timestamp: string): CoreMessage {
  return {
    id: 'sub-agent:' + subSessionId + ':task',
    role: 'user',
    content: task,
    timestamp,
    parts: [],
  }
}

function subAgentMessages(part: MessagePart, subSessionId: string, timestamp: string): CoreMessage[] {
  const eventKind = subAgentEventKind(part)
  const parts = subAgentTimelineParts(part)
  // Mailbox prompts are user turns in the child transcript.  The transport
  // result is only an acknowledgement ("accepted"), which must never appear
  // as a fabricated assistant answer.
  //
  // The same row also owns the delegated run's own process (its reasoning and
  // tool calls arrive as nested timeline parts).  When those exist, keep the
  // prompt as the first user turn and let the shared projection below carry
  // the child's work — otherwise the sub-agent view can only ever show the
  // assignment and never what the child actually did.
  if (eventKind === 'message_sent') {
    const prompt = subAgentPrompt(part)
    if (parts.length === 0) {
      return prompt ? [timelineMessage(part, subSessionId, part.startedAt || timestamp, 'user', 0, prompt, [])] : []
    }
    const messages: CoreMessage[] = prompt
      ? [timelineMessage(part, subSessionId, part.startedAt || timestamp, 'user', 0, prompt, [])]
      : []
    // The row's own content is the transport acknowledgement ("accepted"), not
    // an answer: let the child's own final text own the answer slot.
    const conclusion = childAnswerText(parts) || subAgentConclusion(part)
    return messages.concat(
      childTimeline(part, subSessionId, timestamp, parts, messages.length, conclusion),
    )
  }
  if (eventKind === 'message_received') {
    const content = subAgentConclusion(part)
    return content
      ? [timelineMessage(part, subSessionId, part.completedAt || part.startedAt || timestamp, 'assistant', 0, content, [])]
      : []
  }
  // Lifecycle rows (create/enable/close) belong to the parent process stream,
  // not the child conversation itself.
  if (eventKind === 'created' || eventKind === 'enabled' || eventKind === 'closed') return []

  const conclusion = subAgentConclusion(part)
  return childTimeline(part, subSessionId, timestamp, parts, 0, conclusion)
}

/** The child's own last model output — its answer when the parent row only
 * carries a transport acknowledgement. */
function childAnswerText(parts: MessagePart[]): string {
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const part = parts[index]
    if (part.partType !== 'model_text') continue
    const text = String(part.content || '').trim()
    if (text) return text
  }
  return ''
}

/** Child process parts → one assistant turn per user turn they follow. */function childTimeline(
  part: MessagePart,
  subSessionId: string,
  timestamp: string,
  parts: MessagePart[],
  startSegment: number,
  conclusion: string,
): CoreMessage[] {
  const messages: CoreMessage[] = []
  let assistantParts: MessagePart[] = []
  let segment = startSegment

  const flushAssistant = () => {
    if (assistantParts.length === 0) return
    messages.push(assistantMessage(part, subSessionId, timestamp, assistantParts, segment))
    assistantParts = []
    segment += 1
  }

  for (const timelinePart of parts) {
    if (!isUserTimelinePart(timelinePart)) {
      assistantParts.push(timelinePart)
      continue
    }
    flushAssistant()
    messages.push(userTimelineMessage(part, subSessionId, timestamp, timelinePart, segment))
    segment += 1
  }
  flushAssistant()

  const lastAssistant = [...messages].reverse().find(message => message.role === 'assistant')
  if (lastAssistant) lastAssistant.content = conclusion
  else if (conclusion) messages.push(assistantMessage(part, subSessionId, timestamp, [], segment, conclusion))
  return messages
}

function subAgentProjectedStatus(part: MessagePart, previous?: CoreSubAgentRun): CoreSubAgentStatus {
  const lifecycle = subAgentLifecycleAction(part)
  const metadata = record(part.metadata)
  const nestedMetadata = record(metadata.metadata)
  const envelope = record(metadata.sub_agent || metadata.subAgent)
  const durableStatus = firstText(
    metadata.status,
    nestedMetadata.status,
    metadata.agent_status,
    metadata.agentStatus,
    envelope.status,
    envelope.agent_status,
    envelope.agentStatus,
  ).toLowerCase()
  const childParts = subAgentTimelineParts(part).filter(item => !isUserTimelinePart(item))
  const childStatus = subAgentLatestChildStatus(part, childParts)
  const statuses = [part.status, childStatus]
  if (statuses.includes('running')) return 'running'
  if (statuses.includes('pending')) return 'pending'
  if (statuses.includes('error')) return 'error'
  if (childStatus === 'interrupted') return 'interrupted'
  if (lifecycle === 'closed' || lifecycle === 'close') return 'closed'
  if (durableStatus) {
    const normalizedDurable = normalizeSubAgentStatus(durableStatus)
    if (normalizedDurable === 'error' || normalizedDurable === 'interrupted'
      || normalizedDurable === 'paused' || normalizedDurable === 'closed') return normalizedDurable
  }
  if (lifecycle === 'message_sent') {
    // The acknowledgement itself is completed, but a terminal child item
    // proves that the asynchronous invocation already settled.
    if (childStatus === 'completed') return 'idle'
    if (childStatus === 'error') return 'error'
    if (childStatus === 'paused') return 'paused'
    // 没有子过程的投递：运行中途并入的指令永远不会有自己的子过程。若本轮已
    // 有收敛证据（上一次调用已完结），继承它的状态，不要凭空宣称运行中。
    if (previous && previous.status !== 'running' && previous.status !== 'pending') {
      return previous.status
    }
    return 'running'
  }
  if (lifecycle === 'message_received' && previous) return previous.status
  if (durableStatus) return normalizeSubAgentStatus(durableStatus)
  if (lifecycle === 'created' || lifecycle === 'create' || lifecycle === 'enabled' || lifecycle === 'reopened') return 'idle'
  return childStatus || part.status
}

type SubAgentEventKind = '' | 'created' | 'enabled' | 'closed' | 'message_sent' | 'message_received'

function subAgentEventKind(part: MessagePart): SubAgentEventKind {
  const toolName = String(part.toolName || part.label || '').trim().toLowerCase()
  if (toolName === 'sub_agent_message') return 'message_sent'
  if (toolName === 'sub_agent_receive') return 'message_received'
  if (toolName !== 'sub_agent' && toolName !== 'subagent') return ''
  const action = subAgentLifecycleAction(part)
  if (action === 'close' || action === 'closed') return 'closed'
  if (action === 'create' || action === 'created') return 'created'
  if (action === 'enabled' || action === 'reopened') return 'enabled'
  return ''
}

function subAgentPrompt(part: MessagePart): string {
  const metadata = record(part.metadata)
  const nestedMetadata = record(metadata.metadata)
  const args = record(part.toolArgs)
  return firstText(
    args.prompt,
    args.message,
    metadata.prompt,
    metadata.message,
    nestedMetadata.prompt,
    nestedMetadata.message,
  )
}

function normalizeSubAgentStatus(value: unknown): CoreSubAgentStatus {
  const status = String(value || '').trim().toLowerCase()
  if (status === 'running' || status === 'active' || status === 'interrupting') return 'running'
  if (status === 'pending' || status === 'waiting' || status === 'queued') return 'pending'
  if (status === 'error' || status === 'failed' || status === 'rejected') return 'error'
  if (status === 'paused' || status === 'blocked' || status === 'wait') return 'paused'
  if (status === 'closed' || status === 'disabled') return 'closed'
  if (status === 'interrupted' || status === 'cancelled' || status === 'canceled') return 'interrupted'
  if (status === 'idle' || status === 'ready' || status === 'enabled') return 'idle'
  if (status === 'completed' || status === 'done' || status === 'success' || status === 'ok') return 'completed'
  return 'completed'
}

function subAgentLatestChildStatus(part: MessagePart, childParts: MessagePart[]): CoreSubAgentStatus | undefined {
  const latest = childParts.at(-1)
  if (!latest) return undefined
  const metadata = record(part.metadata)
  const envelope = record(metadata.sub_agent || metadata.subAgent)
  const rawLists = [
    metadata.subLineParts,
    metadata.sub_line_parts,
    envelope.subLineParts,
    envelope.sub_line_parts,
    envelope.events,
    envelope.items,
  ]
  for (const rawList of rawLists) {
    if (!Array.isArray(rawList)) continue
    const raw = rawList.find(item => record(item).id === latest.id || record(item).item_id === latest.id)
      || rawList[rawList.length - 1]
    const rawStatus = firstText(record(raw).status, record(raw).state)
    if (rawStatus) return normalizeSubAgentStatus(rawStatus)
  }
  return normalizeSubAgentStatus(latest.status)
}

function assistantMessage(
  part: MessagePart,
  subSessionId: string,
  timestamp: string,
  parts: MessagePart[],
  segment: number,
  content = '',
): CoreMessage {
  return timelineMessage(
    part,
    subSessionId,
    part.completedAt || part.startedAt || timestamp,
    'assistant',
    segment,
    content,
    parts,
  )
}

function userTimelineMessage(
  part: MessagePart,
  subSessionId: string,
  timestamp: string,
  timelinePart: MessagePart,
  segment: number,
): CoreMessage {
  return timelineMessage(
    part,
    subSessionId,
    timelinePart.completedAt || timelinePart.startedAt || timestamp,
    'user',
    segment,
    timelinePart.content || '',
    [],
  )
}

function timelineMessage(
  part: MessagePart,
  subSessionId: string,
  timestamp: string,
  role: CoreMessage['role'],
  segment: number,
  content: string,
  parts: MessagePart[],
): CoreMessage {
  return {
    id: 'sub-agent:' + subSessionId + ':' + part.id + ':' + segment,
    role,
    content,
    timestamp,
    parts,
    metadata: {
      timeline: role === 'assistant' && parts.length > 0 || undefined,
      live: role === 'assistant' && part.status === 'running' || undefined,
      liveStatus: role === 'assistant' ? subAgentStatusLabel(part.status) : undefined,
      subSessionId,
      sourcePartId: part.id,
    },
  }
}

function isUserTimelinePart(part: MessagePart): boolean {
  const metadata = record(part.metadata)
  return metadata.subAgentRole === 'user' || metadata.type === 'userMessage'
}

function isSubAgentPart(part: MessagePart): boolean {
  const toolName = String(part.toolName || part.label || '').toLowerCase()
  if (part.partType === 'sub_line') return true
  if (toolName === 'sub_agent_message' || toolName === 'sub_agent_receive') return true
  if (toolName === 'sub_agent' || toolName === 'subagent') return true
  if (part.partType === 'agent_summary') return !toolName
  return false
}

function subAgentSessionId(part: MessagePart): string {
  const metadata = record(part.metadata)
  const nestedMetadata = record(metadata.metadata)
  const envelope = record(metadata.sub_agent || metadata.subAgent)
  const args = record(part.toolArgs)
  return firstText(
    part.subSessionId,
    metadata.sub_session_id,
    metadata.subSessionId,
    nestedMetadata.sub_session_id,
    nestedMetadata.subSessionId,
    envelope.sub_session_id,
    envelope.subSessionId,
    envelope.session_id,
    envelope.sessionId,
    envelope.id,
    args.sub_session_id,
    args.subSessionId,
    args.session_id,
    args.sessionId,
  )
}

function subAgentName(part: MessagePart): string {
  const metadata = record(part.metadata)
  const nestedMetadata = record(metadata.metadata)
  const envelope = record(metadata.sub_agent || metadata.subAgent)
  const args = record(part.toolArgs)
  return firstText(
    part.agentName,
    (part as MessagePart & { name?: unknown }).name,
    (part as MessagePart & { agent?: unknown }).agent,
    metadata.agent_name,
    metadata.agentName,
    metadata.agent,
    nestedMetadata.agent_name,
    nestedMetadata.agentName,
    nestedMetadata.agent,
    envelope.name,
    envelope.agent_name,
    envelope.agentName,
    envelope.agent,
    args.agent_name,
    args.agentName,
    args.agent,
    args.name,
  )
}

function subAgentTask(part: MessagePart): string {
  const metadata = record(part.metadata)
  const nestedMetadata = record(metadata.metadata)
  const envelope = record(metadata.sub_agent || metadata.subAgent)
  const args = record(part.toolArgs)
  return firstText(
    (part as MessagePart & { task?: unknown }).task,
    args.task,
    args.task_description,
    args.taskDescription,
    args.description,
    metadata.task,
    metadata.task_description,
    metadata.taskDescription,
    nestedMetadata.task,
    nestedMetadata.task_description,
    nestedMetadata.taskDescription,
    envelope.task,
    envelope.task_description,
    envelope.taskDescription,
    envelope.prompt,
  )
}

function subAgentModelId(part: MessagePart): string {
  const metadata = record(part.metadata)
  const nestedMetadata = record(metadata.metadata)
  const envelope = record(metadata.sub_agent || metadata.subAgent)
  const args = record(part.toolArgs)
  return firstText(
    part.model,
    (part as MessagePart & { modelId?: unknown }).modelId,
    metadata.model_id,
    metadata.modelId,
    metadata.model,
    nestedMetadata.model_id,
    nestedMetadata.modelId,
    nestedMetadata.model,
    envelope.model_id,
    envelope.modelId,
    envelope.model,
    args.model,
    args.model_id,
    args.modelId,
  )
}

function subAgentSourceCallId(part: MessagePart): string {
  const metadata = record(part.metadata)
  const nestedMetadata = record(metadata.metadata)
  const envelope = record(metadata.sub_agent || metadata.subAgent)
  const args = record(part.toolArgs)
  return firstText(
    part.sourceCallId,
    (part as MessagePart & { callId?: unknown }).callId,
    metadata.source_call_id,
    metadata.sourceCallId,
    metadata.call_id,
    metadata.callId,
    nestedMetadata.source_call_id,
    nestedMetadata.sourceCallId,
    envelope.source_call_id,
    envelope.sourceCallId,
    envelope.call_id,
    envelope.callId,
    args.source_call_id,
    args.sourceCallId,
    args.call_id,
    args.callId,
  )
}

function subAgentSourceMessageId(part: MessagePart): string {
  const metadata = record(part.metadata)
  const nestedMetadata = record(metadata.metadata)
  const envelope = record(metadata.sub_agent || metadata.subAgent)
  return firstText(
    part.sourceMessageId,
    metadata.source_message_id,
    metadata.sourceMessageId,
    metadata.message_id,
    metadata.messageId,
    nestedMetadata.source_message_id,
    nestedMetadata.sourceMessageId,
    envelope.source_message_id,
    envelope.sourceMessageId,
    envelope.message_id,
    envelope.messageId,
  )
}

function subAgentSourcePartId(part: MessagePart): string {
  const metadata = record(part.metadata)
  const nestedMetadata = record(metadata.metadata)
  const envelope = record(metadata.sub_agent || metadata.subAgent)
  return firstText(
    part.sourcePartId,
    metadata.source_part_id,
    metadata.sourcePartId,
    metadata.part_id,
    metadata.partId,
    nestedMetadata.source_part_id,
    nestedMetadata.sourcePartId,
    envelope.source_part_id,
    envelope.sourcePartId,
    envelope.part_id,
    envelope.partId,
  )
}

function subAgentType(part: MessagePart): 'consider' | 'execute' | '' {
  const metadata = record(part.metadata)
  const nestedMetadata = record(metadata.metadata)
  const envelope = record(metadata.sub_agent || metadata.subAgent)
  const args = record(part.toolArgs)
  const raw = firstText(
    part.agentType,
    (part as MessagePart & { type?: unknown }).type,
    metadata.type,
    metadata.agent_type,
    metadata.agentType,
    metadata.mode,
    metadata.active_mode,
    nestedMetadata.type,
    nestedMetadata.agent_type,
    envelope.type,
    envelope.agent_type,
    envelope.agentType,
    envelope.mode,
    args.type,
    args.mode,
    args.active_mode,
  ).toLowerCase()
  if (raw.includes('consider') || raw.includes('think') || raw.includes('reason')) return 'consider'
  if (raw.includes('execute')) return 'execute'
  return ''
}

function subAgentReasoningLevel(part: MessagePart): string {
  const metadata = record(part.metadata)
  const nestedMetadata = record(metadata.metadata)
  const envelope = record(metadata.sub_agent || metadata.subAgent)
  const args = record(part.toolArgs)
  return firstText(
    part.reasoningLevel,
    (part as MessagePart & { reasoningEffort?: unknown }).reasoningEffort,
    metadata.reasoning_level,
    metadata.reasoningLevel,
    metadata.reasoning_effort,
    metadata.reasoningEffort,
    nestedMetadata.reasoning_level,
    nestedMetadata.reasoningLevel,
    nestedMetadata.reasoning_effort,
    envelope.reasoning_level,
    envelope.reasoningLevel,
    envelope.reasoning_effort,
    envelope.reasoningEffort,
    args.reasoning_level,
    args.reasoningLevel,
    args.reasoning_effort,
  )
}

function subAgentSummary(part: MessagePart, task = ''): string {
  const metadata = record(part.metadata)
  const nestedMetadata = record(metadata.metadata)
  const envelope = record(metadata.sub_agent || metadata.subAgent)
  const direct = firstText(
    part.summary,
    metadata.summary,
    metadata.final_answer,
    metadata.finalAnswer,
    nestedMetadata.summary,
    envelope.summary,
    envelope.final_answer,
    envelope.finalAnswer,
  )
  if (subAgentEventKind(part) === 'created' || subAgentEventKind(part) === 'enabled'
    || subAgentEventKind(part) === 'closed' || subAgentEventKind(part) === 'message_sent') {
    return direct || task
  }
  return direct || subAgentConclusion(part) || task
}

function subAgentElapsedMs(
  part: MessagePart,
  startedAt: string,
  completedAt: string | undefined,
  fallbackEnd: string,
): number {
  const metadata = record(part.metadata)
  const nestedMetadata = record(metadata.metadata)
  const envelope = record(metadata.sub_agent || metadata.subAgent)
  const explicit = firstNumber(
    part.elapsedMs,
    metadata.elapsed_ms,
    metadata.elapsedMs,
    metadata.duration_ms,
    metadata.durationMs,
    nestedMetadata.elapsed_ms,
    nestedMetadata.elapsedMs,
    nestedMetadata.duration_ms,
    nestedMetadata.durationMs,
    envelope.elapsed_ms,
    envelope.elapsedMs,
    envelope.duration_ms,
    envelope.durationMs,
  )
  if (explicit !== undefined && Number.isFinite(explicit) && explicit >= 0) return Math.round(explicit)
  const start = Date.parse(startedAt || '')
  if (!Number.isFinite(start)) return 0
  const terminal = isTerminalStatus(part.status)
  const end = Date.parse(completedAt || (terminal ? fallbackEnd : new Date().toISOString()))
  if (!Number.isFinite(end) || end < start) return 0
  return Math.max(0, end - start)
}

function subAgentTimestamp(part: MessagePart, edge: 'started' | 'completed'): string {
  const metadata = record(part.metadata)
  const nestedMetadata = record(metadata.metadata)
  const envelope = record(metadata.sub_agent || metadata.subAgent)
  const values = edge === 'started'
    ? [part.startedAt, metadata.started_at, metadata.startedAt, nestedMetadata.started_at, nestedMetadata.startedAt, envelope.started_at, envelope.startedAt]
    : [part.completedAt, metadata.completed_at, metadata.completedAt, nestedMetadata.completed_at, nestedMetadata.completedAt, envelope.completed_at, envelope.completedAt]
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return new Date(value < 1e12 ? value * 1000 : value).toISOString()
    }
    const text = firstText(value)
    if (!text) continue
    const numeric = Number(text)
    if (Number.isFinite(numeric)) {
      return new Date(numeric < 1e12 ? numeric * 1000 : numeric).toISOString()
    }
    if (Number.isFinite(Date.parse(text))) return text
  }
  return ''
}

function subAgentTimelineParts(part: MessagePart): MessagePart[] {
  const metadata = record(part.metadata)
  const envelope = record(metadata.sub_agent || metadata.subAgent)
  const rawParts = Array.isArray(metadata.subLineParts)
    ? metadata.subLineParts
    : Array.isArray(metadata.sub_line_parts)
      ? metadata.sub_line_parts
      : Array.isArray(envelope.subLineParts)
        ? envelope.subLineParts
        : Array.isArray(envelope.sub_line_parts)
          ? envelope.sub_line_parts
          : Array.isArray(envelope.events)
            ? envelope.events
            : Array.isArray(envelope.items)
              ? envelope.items
              : []
  const normalized = rawParts
    .map((item, index) => normalizeTimelinePart(part.id, item, index))
    .filter((item): item is MessagePart => Boolean(item))
  if (normalized.length > 0) return normalized

  const fallback: MessagePart[] = []
  const reasoning = Array.isArray(metadata.reasoning_blocks)
    ? metadata.reasoning_blocks
    : Array.isArray(envelope.reasoning_blocks) ? envelope.reasoning_blocks : []
  for (const [index, item] of reasoning.entries()) {
    const content = typeof item === 'string' ? item : firstText(record(item).content)
    if (!content) continue
    fallback.push({
      id: part.id + ':reasoning:' + index,
      partType: 'reasoning',
      status: 'completed',
      content,
    })
  }

  const toolCalls = Array.isArray(metadata.tool_calls)
    ? metadata.tool_calls
    : Array.isArray(envelope.tool_calls) ? envelope.tool_calls : []
  for (const [index, item] of toolCalls.entries()) {
    const tool = record(item)
    const toolName = firstText(tool.name, tool.tool_name, tool.toolName) || 'tool'
    const toolArgs = record(tool.arguments || tool.args || tool.tool_args || tool.toolArgs)
    const output = firstText(tool.output, tool.result, tool.content, tool.summary)
    const error = firstText(tool.error, tool.tool_error, tool.toolError)
    fallback.push({
      id: part.id + ':tool:' + index,
      partType: 'tool_call',
      status: normalizeStatus(tool.status),
      content: output || error,
      label: toolName,
      toolName,
      toolArgs,
      toolResult: output || undefined,
      toolError: error || undefined,
      artifacts: Array.isArray(tool.artifacts) ? tool.artifacts as MessagePart['artifacts'] : undefined,
    })
  }
  return fallback
}

function normalizeTimelinePart(parentId: string, value: unknown, index: number): MessagePart | null {
  const item = record(value)
  if (Object.keys(item).length === 0) return null
  const rawType = firstText(item.partType, item.part_type, item.type) || 'tool_result'
  const partType = normalizePartType(rawType)
  const content = firstTextContent(item.content, item.message, item.summary, item.toolResult, item.tool_result)
  const sourceMetadata = record(item.metadata)
  return {
    id: firstText(item.id, item.item_id) || parentId + ':timeline:' + index,
    partType,
    status: normalizeStatus(item.status),
    content,
    label: firstText(item.label, item.title) || undefined,
    detail: firstText(item.detail, item.message, item.summary) || undefined,
    toolName: firstText(item.toolName, item.tool_name) || undefined,
    toolArgs: recordOrUndefined(item.toolArgs || item.tool_args || item.arguments),
    toolResult: firstText(item.toolResult, item.tool_result) || undefined,
    toolError: firstText(item.toolError, item.tool_error, item.error) || undefined,
    inputPreview: isInputPreview(item.inputPreview || item.input_preview),
    artifacts: Array.isArray(item.artifacts) ? item.artifacts as MessagePart['artifacts'] : undefined,
    metadata: recordOrUndefined({
      ...sourceMetadata,
      ...(rawType === 'userMessage' || sourceMetadata.type === 'userMessage' ? { subAgentRole: 'user' } : {}),
    }),
    startedAt: firstText(item.startedAt, item.started_at) || undefined,
    completedAt: firstText(item.completedAt, item.completed_at) || undefined,
  }
}

function normalizePartType(value: string): MessagePart['partType'] {
  const known: MessagePart['partType'][] = [
    'text', 'attachment', 'reasoning', 'model_text', 'tool_call', 'tool_result',
    'file_diff', 'command_output', 'plan', 'todo_update', 'status', 'error',
    'decision', 'sub_line', 'agent_summary', 'compaction',
  ]
  if (known.includes(value as MessagePart['partType'])) return value as MessagePart['partType']
  if (value === 'agentMessage') return 'model_text'
  if (value === 'dynamicToolCall') return 'tool_call'
  return 'tool_result'
}

function normalizeStatus(value: unknown): MessagePartStatus {
  const status = String(value || '').toLowerCase()
  if (status === 'running' || status === 'interrupting') return 'running'
  if (status === 'pending' || status === 'waiting') return 'pending'
  if (status === 'error' || status === 'failed' || status === 'rejected') return 'error'
  return 'completed'
}

function subAgentConclusion(part: MessagePart): string {
  const metadata = record(part.metadata)
  const finalAnswer = firstText(metadata.final_answer, metadata.finalAnswer)
  if (finalAnswer) return finalAnswer
  const content = firstText(part.content, part.toolResult)
  if (content) return content
  const detail = firstText(part.detail)
  const toolName = firstText(part.toolName, part.label)
  return detail && detail !== toolName ? detail : ''
}

function subAgentStatusLabel(status: CoreSubAgentStatus): string {
  if (status === 'running') return '运行中'
  if (status === 'pending') return '等待中'
  if (status === 'paused') return '已暂停'
  if (status === 'interrupted') return '已中断'
  if (status === 'closed') return '已关闭'
  if (status === 'idle') return '空闲'
  if (status === 'error') return '失败'
  return '已完成'
}

function isInputPreview(value: unknown): MessagePart['inputPreview'] | undefined {
  const preview = record(value)
  const field = firstText(preview.field)
  const content = firstText(preview.content)
  if (!field || !content) return undefined
  return {
    field,
    content,
    chars: Number(preview.chars || content.length),
    truncated: preview.truncated === true,
  }
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function recordOrUndefined(value: unknown): Record<string, unknown> | undefined {
  const result = record(value)
  return Object.keys(result).length > 0 ? result : undefined
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    if (value === null || value === undefined) continue
    const text = String(value).trim()
    if (text) return text
  }
  return ''
}

function firstNumber(...values: unknown[]): number | undefined {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value)) return value
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value)
      if (Number.isFinite(parsed)) return parsed
    }
  }
  return undefined
}

function firstTextContent(...values: unknown[]): string {
  for (const value of values) {
    if (Array.isArray(value)) {
      const text = value
        .map(item => firstText(record(item).text, record(item).content))
        .filter(Boolean)
        .join('\n')
        .trim()
      if (text) return text
      continue
    }
    const text = firstText(value)
    if (text) return text
  }
  return ''
}
