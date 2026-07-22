import type { CoreCommandCatalogItem, CoreInputItem, MessagePart } from '../types.ts'
import { buildCoreComposerInputItems, coreStandaloneActionCommand } from '../composer/inputItems.ts'

export type CoreComposerActionMode = 'send' | 'stop'
export type CoreWorkbenchTurnStatus = 'idle' | 'running' | 'waiting' | 'interrupting' | 'completed' | 'failed' | string

export interface SubmitCoreComposerTaskOptions {
  threadId: string
  activeTurnId?: string
  text: string
  status: CoreWorkbenchTurnStatus
  commandCatalog?: CoreCommandCatalogItem[]
  attachments?: CoreInputItem[]
  executeCommand?: (command: string) => Promise<boolean>
  steerTurn?: (threadId: string, turnId: string, inputItems: CoreInputItem[]) => Promise<void>
  queueInput: (threadId: string, inputItems: CoreInputItem[]) => Promise<void>
  startTurn: (threadId: string, inputItems: CoreInputItem[]) => Promise<boolean>
  forceGuide?: boolean
}

export type SubmitCoreComposerTaskResult =
  | { status: 'ignored' }
  | { status: 'command'; command: string; ok: boolean }
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
  const standaloneCommand = attachments.length === 0
    ? coreStandaloneActionCommand(cleaned, commandCatalog)
    : ''
  if (standaloneCommand) {
    const ok = await options.executeCommand?.(standaloneCommand)
    return { status: 'command', command: standaloneCommand, ok: ok === true }
  }

  if (isCoreActiveTurnStatus(options.status)) {
    const inputItems = buildCoreComposerInputItems(cleaned, attachments, commandCatalog)
    if (options.forceGuide && attachments.length === 0 && options.activeTurnId && options.steerTurn) {
      await options.steerTurn(options.threadId, options.activeTurnId, inputItems)
      return { status: 'guided', inputItems }
    }
    await options.queueInput(options.threadId, inputItems)
    return { status: 'queued', inputItems }
  }

  const inputItems = buildCoreComposerInputItems(cleaned, attachments, commandCatalog)
  const ok = await options.startTurn(options.threadId, inputItems)
  return { status: 'started', inputItems, ok }
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
  const source: CoreCommandCatalogItem['source'] = item.source === 'member' ? 'member' : 'core'
  return {
    name,
    title: String(item.title || name),
    description: String(item.description || ''),
    icon: String(item.icon || '/'),
    source,
    action,
    accepts_args: Boolean(item.accepts_args),
  }
}

export function coreAppServerDecision(value: string): string {
  const normalized = value.trim().toLowerCase()
  if (normalized === 'approve' || normalized === 'accept' || normalized === 'approve_once') return 'approve_once'
  if (normalized === 'approve_for_session' || normalized === 'acceptforsession') return 'approve_for_session'
  if (normalized === 'deny' || normalized === 'decline' || normalized === 'cancel') return 'deny'
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
