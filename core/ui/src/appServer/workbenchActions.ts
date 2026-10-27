import type { CoreCommandCatalogItem, CoreInputItem, MessagePart } from '@/types.ts'
import { buildCoreComposerInputItems } from '@/composer/inputItems.ts'
import { parseComposerInput, resolveComposerCommandKind } from '@/composer/syntax.ts'

export type CoreComposerActionMode = 'send' | 'stop' | 'resume'
export type CoreWorkbenchTurnStatus = 'idle' | 'running' | 'waiting' | 'interrupting' | 'completed' | 'failed' | string

/** Outcome of a start-turn attempt. `busy` marks the runtime's "session has an
 *  active turn" refusal, which the composer turns into a queue fallback instead
 *  of a user-visible error. */
export interface CoreStartTurnOutcome {
  ok: boolean
  busy?: boolean
}

/** Outcome of a steer attempt. `queued` marks the refusals where the runtime
 *  already put the message into the queue for the next turn, so the composer
 *  reports it as queued without issuing a second queue write. */
export interface CoreSteerAttempt {
  ok: boolean
  queued?: boolean
}

export interface SubmitCoreComposerTaskOptions {
  threadId: string
  activeTurnId?: string
  text: string
  status: CoreWorkbenchTurnStatus
  commandCatalog?: CoreCommandCatalogItem[]
  attachments?: CoreInputItem[]
  executeCommand?: (command: string, argumentsText?: string) => Promise<boolean>
  steerTurn?: (threadId: string, turnId: string, inputItems: CoreInputItem[]) => Promise<boolean | CoreSteerAttempt>
  queueInput: (
    threadId: string,
    inputItems: CoreInputItem[],
    turnOptions?: Record<string, unknown>,
    clientMessageId?: string,
  ) => Promise<void>
  startTurn: (
    threadId: string,
    inputItems: CoreInputItem[],
    workRoot?: string,
    turnOptions?: Record<string, unknown>,
    clientMessageId?: string,
  ) => Promise<boolean | CoreStartTurnOutcome>
  workRoot?: string
  turnOptions?: Record<string, unknown>
  forceGuide?: boolean
  /** One identity for the whole submission: the start attempt and its queue
   *  fallback carry it, so a repeated write dedupes on the server instead of
   *  sending the message twice. */
  clientMessageId?: string
}

export type SubmitCoreComposerTaskResult =
  | { status: 'ignored' }
  | { status: 'command'; command: string; arguments?: string; ok: boolean }
  | { status: 'guided'; inputItems: CoreInputItem[] }
  | { status: 'queued'; inputItems: CoreInputItem[] }
  | { status: 'started'; inputItems: CoreInputItem[]; ok: boolean }

export interface CoreComposerSubmissionEffectOptions {
  clearComposer?: boolean
  submittedText: string
  queuedStatusText?: string
  guidedStatusText?: string
}

export interface CoreComposerSubmissionEffectPlan {
  clearComposer: boolean
  clearAttachments: boolean
  clearComposerText?: string
  restoreText?: string
  statusText?: string
}

export interface CoreDecisionSelectionPayload {
  partId: string
  option: { id?: string; label?: string; response?: string }
  response: string
}

export type CoreDecisionSelectionPlan =
  | { status: 'approval'; requestId: string; decision: string; guidance: string }
  | { status: 'text'; text: string }
  | { status: 'ignored' }

export function isCoreActiveTurnStatus(status: CoreWorkbenchTurnStatus): boolean {
  return status === 'running' || status === 'waiting' || status === 'interrupting'
}

/** A turn the user paused. It owns the session, but nothing is executing, so it
 *  is not active; it stays resumable until the user continues or terminates. */
export function isCorePausedTurnStatus(status: CoreWorkbenchTurnStatus): boolean {
  return status === 'paused'
}

export function isCoreGuidableTurnStatus(status: CoreWorkbenchTurnStatus): boolean {
  return status === 'running' || status === 'waiting'
}

export function coreComposerActionMode(params: {
  status: CoreWorkbenchTurnStatus
  text: string
  pendingAttachmentCount?: number
}): CoreComposerActionMode {
  return isCoreActiveTurnStatus(params.status)
    && !params.text.trim()
    && (params.pendingAttachmentCount || 0) === 0
    ? 'stop'
    : 'send'
}

export async function submitCoreComposerTask(
  options: SubmitCoreComposerTaskOptions,
): Promise<SubmitCoreComposerTaskResult> {
  const cleaned = options.text.trim()
  const attachments = options.attachments || []
  if (!cleaned && attachments.length === 0) return { status: 'ignored' }

  const commandCatalog = options.commandCatalog || []
  const parsed = attachments.length === 0 ? parseComposerInput(cleaned, commandCatalog) : null
  if (parsed?.kind === 'action') {
    const definition = commandCatalog.find((item) => (
      item.name.trim().replace(/^\/+/, '').toLowerCase() === parsed.name
      && resolveComposerCommandKind(item) === 'action'
    ))
    if (parsed.arguments && !definition?.accepts_args) {
      throw new Error(`Command "${parsed.name}" does not accept arguments`)
    }
    const ok = await options.executeCommand?.(parsed.name, parsed.arguments)
    return { status: 'command', command: parsed.name, arguments: parsed.arguments, ok: ok === true }
  }

  // Guidance mode reaches for the live turn first; every refusal ends in the
  // queue rather than in a dropped message.
  const guideOrQueue = async (inputItems: CoreInputItem[]): Promise<SubmitCoreComposerTaskResult> => {
    if (!options.forceGuide || !options.activeTurnId || !options.steerTurn) {
      await options.queueInput(options.threadId, inputItems, options.turnOptions, options.clientMessageId)
      return { status: 'queued', inputItems }
    }
    const steered = await options.steerTurn(options.threadId, options.activeTurnId, inputItems)
    const steerOutcome = typeof steered === 'boolean' ? { ok: steered } : steered
    if (steerOutcome.ok) return { status: 'guided', inputItems }
    // A refusal is a success response with `applied: false` (or a failed call).
    // There is no live run to steer in that moment, so the message waits in the
    // queue for the next turn. If the runtime already queued it, do not write a
    // second copy.
    if (!steerOutcome.queued) {
      await options.queueInput(options.threadId, inputItems, options.turnOptions, options.clientMessageId)
    }
    return { status: 'queued', inputItems }
  }

  if (isCoreActiveTurnStatus(options.status)) {
    return await guideOrQueue(buildCoreComposerInputItems(cleaned, attachments, commandCatalog))
  }

  const inputItems = buildCoreComposerInputItems(cleaned, attachments, commandCatalog)
  const started = await options.startTurn(
    options.threadId,
    inputItems,
    options.workRoot,
    options.turnOptions,
    options.clientMessageId,
  )
  const outcome = typeof started === 'boolean' ? { ok: started } : started
  if (!outcome.ok && outcome.busy) {
    // The runtime still considers a turn active even though this client thinks
    // it is over (a short window after the main agent stops, or any transient
    // busy). A new turn would be refused: fall back to the mode-appropriate
    // path instead of showing an error. The shared client message id keeps a
    // repeat from double-sending.
    return await guideOrQueue(inputItems)
  }
  return { status: 'started', inputItems, ok: outcome.ok }
}

/**
 * The runtime's refusal when a turn is already active for the session
 * (`SESSION_BUSY` / "session has an active turn"). The composer falls back to
 * the queue path for this and never surfaces it as a failure.
 */
export function isCoreSessionBusyError(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false
  const record = error as { code?: unknown; data?: unknown; message?: unknown }
  if (record.code === 'SESSION_BUSY') return true
  const data = isRecord(record.data) ? record.data : null
  if (data?.code === 'SESSION_BUSY' || data?.reason === 'active_turn_exists') return true
  return typeof record.message === 'string' && /session has an active turn/i.test(record.message)
}

export function coreComposerSubmissionEffects(
  result: SubmitCoreComposerTaskResult,
  options: CoreComposerSubmissionEffectOptions,
): CoreComposerSubmissionEffectPlan {
  if (result.status === 'ignored') {
    return { clearComposer: false, clearAttachments: false }
  }
  if (result.status === 'command') {
    return result.ok
      ? _clearablePlan(options, { clearAttachments: false })
      : { clearComposer: false, clearAttachments: false, restoreText: options.submittedText }
  }
  if (result.status === 'queued') {
    return _clearablePlan(options, {
      clearAttachments: false,
      statusText: options.queuedStatusText || 'Queued',
    })
  }
  if (result.status === 'guided') {
    return _clearablePlan(options, {
      clearAttachments: false,
      statusText: options.guidedStatusText || 'Guidance sent',
    })
  }
  if (result.ok) {
    return _clearablePlan(options, {
      clearAttachments: true,
    })
  }
  return {
    clearComposer: false,
    clearAttachments: false,
    restoreText: options.clearComposer === true ? options.submittedText : undefined,
  }
}

function _clearablePlan(
  options: CoreComposerSubmissionEffectOptions,
  plan: Omit<CoreComposerSubmissionEffectPlan, 'clearComposer' | 'clearComposerText'>,
): CoreComposerSubmissionEffectPlan {
  const clearComposer = options.clearComposer === true
  return {
    clearComposer,
    ...(clearComposer ? { clearComposerText: options.submittedText } : {}),
    ...plan,
  }
}

export function normalizeCoreCommandCatalogItem(item: unknown): CoreCommandCatalogItem | null {
  if (!isRecord(item)) return null
  const name = String(item.name || '').trim().replace(/^\/+/, '')
  if (!name) return null
  const rawAction = String(item.action || 'run_action')
  const action: CoreCommandCatalogItem['action'] =
    rawAction === 'insert_token' || rawAction === 'expand_on_send' ? rawAction : 'run_action'
  const source: CoreCommandCatalogItem['source'] = item.source === 'member'
    ? 'member'
    : item.source === 'plugin'
      ? 'plugin'
      : 'core'
  const rawKind = String(item.kind || '').toLowerCase()
  const kind: CoreCommandCatalogItem['kind'] = rawKind === 'action' || rawKind === 'skill'
    ? rawKind
    : action === 'insert_token' || action === 'expand_on_send' ? 'skill' : 'action'
  return {
    name,
    title: String(item.title || name),
    description: String(item.description || ''),
    icon: String(item.icon || '/'),
    source,
    action,
    kind,
    accepts_args: Boolean(item.accepts_args),
    ...(isRecord(item.metadata) ? { metadata: { ...item.metadata } } : {}),
  }
}

export function coreAppServerDecision(value: string): string {
  const normalized = value.trim().toLowerCase()
  // user:“一次性处理干净 不要留尾巴”+(保留明确的信任选择，不降成普通引导消息)。
  if (normalized === 'trust') return 'trust'
  if (normalized === 'approve' || normalized === 'accept' || normalized === 'approve_once') return 'approve_once'
  if (normalized === 'approve_for_session' || normalized === 'acceptforsession') return 'approve_for_session'
  if (normalized === 'deny' || normalized === 'decline' || normalized === 'cancel') return 'deny'
  // A question option may deliberately be labelled "cancel"; its stable id is
  // option-N, so only the explicit skip option reaches this branch.
  if (normalized === 'skip' || normalized === 'option-skip' || normalized === 'skipped') return 'skip'
  return 'other_guidance'
}

export function coreDecisionSelectionPlan(
  part: MessagePart | null | undefined,
  payload: CoreDecisionSelectionPayload,
): CoreDecisionSelectionPlan {
  const waitingRequest = isRecord(part?.metadata?.waitingRequest) ? part?.metadata?.waitingRequest : null
  const requestId = String(waitingRequest?.request_id || '')
  if (requestId) {
    const response = String(payload.response || '')
    return {
      status: 'approval',
      requestId,
      decision: coreAppServerDecision(String(payload.option?.id || response)),
      guidance: response,
    }
  }
  const text = String(payload.response || '').trim()
  return text ? { status: 'text', text } : { status: 'ignored' }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}
