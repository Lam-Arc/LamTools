import type { CoreMessage, MessagePart } from '../types'
import { coreAppItemPartStatus, coreAppItemToMessagePart } from './messageParts.ts'
import type { CoreAppItem, CoreAppQueueItem, CoreAppRequestState, CoreAppSnapshot } from './protocol.ts'
import { selectChatMessages, selectQueueTray } from './selectors.ts'

export interface CoreWorkbenchMessageOptions {
  source?: string
  active?: boolean
  shallowThinkingPending?: boolean
  submittingApprovalRequestIds?: Set<string>
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

export function selectCoreWorkbenchMessages(
  snapshot: CoreAppSnapshot,
  options: CoreWorkbenchMessageOptions = {},
): CoreMessage[] {
  const sourceMessages = selectChatMessages(snapshot)
  const lastAssistantIndex = sourceMessages.findLastIndex(message => message.role === 'assistant')
  return sourceMessages.map((message, index) => {
    const activeAssistant = Boolean(options.active && message.role === 'assistant' && index === lastAssistantIndex)
    return {
      id: message.id,
      role: message.role,
      content: message.content,
      timestamp: '',
      parts: [
        ...message.parts.map(item => coreAppItemToWorkbenchPart(snapshot, item, options)),
        ...(message.attachments || []).map(attachment => ({
          id: `${message.id}:attachment:${attachment.id}`,
          partType: 'attachment' as const,
          status: 'completed' as const,
          content: '',
          label: attachment.label || attachment.filename,
          metadata: { attachment },
        })),
      ],
      metadata: {
        ...(options.source ? { source: options.source } : {}),
        ...(message.metadata || {}),
        live: message.metadata?.live,
        shallowThinkingPending: activeAssistant && options.shallowThinkingPending ? true : undefined,
      },
    } satisfies CoreMessage
  })
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
  return {
    ...coreAppItemToMessagePart(item, { status }),
    toolArgs: Array.isArray(item.options)
      ? {
          ...(isRecord(item.arguments) ? item.arguments : {}),
          options: item.options,
        }
      : isRecord(item.arguments)
        ? item.arguments
        : undefined,
    toolResult: typeof item.content === 'string' ? item.content : undefined,
    metadata: {
      ...(isRecord(item.metadata) ? item.metadata : {}),
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
  if (!active) return currentExpandedIds
  const next = new Set(currentExpandedIds)
  for (const message of messages) {
    if (message.role === 'assistant' && coreMessageHasProcessParts(message)) {
      next.add(message.id)
    }
  }
  return next
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
