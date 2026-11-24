import { shallowRef, type Ref } from 'vue'
import { CoreHistoryEditConflictError, CoreRequestAcceptanceUnknownError } from '@/appServer/client.ts'
import {
  corePausedTurnIdFromError,
  isCorePausedSessionError,
  isCoreSessionBusyError,
  submitCoreComposerTask,
  type SubmitCoreComposerTaskResult,
} from '@/appServer/workbenchActions.ts'
import { buildCoreComposerInputItems } from '@/composer/inputItems.ts'
import type { UseCoreLiveComposerControllerOptions } from '@/composables/useCoreLiveComposerController.ts'
import type { CoreCommandCatalogItem, CoreInputItem } from '@/types.ts'

// user:“做吧”+(每次发送拥有固定身份、原始输入和独立状态，异步结果不得操作另一份草稿)。
export interface CoreComposerSubmission {
  id: string
  threadId: string
  text: string
  attachments: CoreInputItem[]
  state: 'preparing' | 'sending' | 'accepted' | 'queued' | 'guided' | 'failed' | 'unknown'
  error: string
  intent?: 'start' | 'queue' | 'guide' | 'resume'
  displayed?: boolean
  turnId?: string
  replaceTurnId?: string
  replaceRevision?: number
  needsReopen?: boolean
  ownsDraft?: boolean
}

interface SubmissionAttempt extends CoreComposerSubmission {
  rawText: string
  draftVersion: number
  activeTurnId: string
  ownsDraft: boolean
  catalog: CoreCommandCatalogItem[]
  workRoot: string
  turnOptions?: Record<string, unknown>
  clearComposer: boolean
  resumeParentDone?: boolean
  resumeMembers: boolean
  acknowledged?: boolean
}

function copySubmissionValue<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

type NewSubmission = Pick<SubmissionAttempt,
  'threadId' | 'rawText' | 'attachments' | 'intent' | 'activeTurnId' | 'catalog' |
  'workRoot' | 'clearComposer' | 'ownsDraft' | 'resumeMembers' | 'replaceTurnId' | 'replaceRevision'>

interface SubmissionControl {
  submitting: Ref<boolean>
  lastError: Ref<string>
  getDraftVersion(): number
  ensureConnected(threadId: string): Promise<boolean>
  reportError(message: string): void
  notifyTurnStarted(): void
}

// user:“全做”+(发送、引导、排队和历史编辑的请求身份、回执、重试和草稿归属由同一处管理)。
export function useCoreComposerSubmissions(
  options: UseCoreLiveComposerControllerOptions,
  { submitting, lastError, getDraftVersion, ensureConnected, reportError, notifyTurnStarted }: SubmissionControl,
) {
  const attempts = new Map<string, SubmissionAttempt>()
  const submissions = shallowRef<CoreComposerSubmission[]>([])
  function publishSubmissions(): void {
    // Confirmed display rows no longer need an in-memory copy of the input.
    for (const [id, attempt] of attempts) {
      if (attempt.displayed && !submitting.value && attempt.state === 'accepted') attempts.delete(id)
    }
    const receipts = [...attempts.values()].filter(a => ['accepted', 'queued', 'guided'].includes(a.state))
    for (const receipt of receipts.slice(0, Math.max(0, receipts.length - 20))) attempts.delete(receipt.id)
    submissions.value = [...attempts.values()].filter(attempt => !attempt.displayed).map(attempt => ({ ...attempt }))
  }
  // user:“做吧”+(先固定提交快照；准备、发送、确认和重试共享同一个请求身份)。
  function acceptSubmission(attempt: SubmissionAttempt): void {
    if (attempt.acknowledged) return
    attempt.acknowledged = true
    if (options.activeThreadId.value === attempt.threadId) {
      if (attempt.clearComposer && getDraftVersion() === attempt.draftVersion && options.text.value === attempt.rawText) {
        options.clearComposer?.(attempt.text)
      }
      // Remove exactly the accepted files, never files added while awaiting a reply.
      if (attempt.ownsDraft) options.clearAttachments?.(attempt.attachments)
    }
    options.onSubmissionAccepted?.(attempt, attempt.clearComposer ? attempt.rawText : undefined)
  }

  function acknowledgeSubmission(threadId: string, id: string, displayed = false, turnId?: string): void {
    const attempt = attempts.get(id)
    if (!attempt || attempt.threadId !== threadId) return
    const memberRecoveryFailed = attempt.intent === 'resume' && attempt.resumeParentDone && attempt.state === 'failed'
    attempt.turnId = turnId || attempt.turnId
    if (attempt.intent === 'resume') attempt.resumeParentDone = true
    attempt.displayed ||= displayed && attempt.intent !== 'resume'
    if (!attempt.acknowledged) acceptSubmission(attempt)
    // A repeated parent receipt cannot erase an unfinished member recovery.
    if (!memberRecoveryFailed) {
      if (attempt.state !== 'queued' && attempt.state !== 'guided') attempt.state = 'accepted'
      attempt.error = ''
    }
    publishSubmissions()
  }

  async function runSubmission(attempt: SubmissionAttempt): Promise<SubmitCoreComposerTaskResult | null> {
    if (submitting.value) return null
    submitting.value = true
    attempt.error = ''
    attempt.state = attempt.turnOptions === undefined && attempt.intent !== 'resume' ? 'preparing' : 'sending'
    publishSubmissions()
    const fail = (error: unknown): void => {
      // A matching server receipt wins over a late transport timeout.
      if (attempt.acknowledged && !attempt.resumeParentDone) {
        attempt.state = 'accepted'
        return
      }
      attempt.state = error instanceof CoreRequestAcceptanceUnknownError && !attempt.resumeParentDone ? 'unknown' : 'failed'
      attempt.needsReopen = error instanceof CoreHistoryEditConflictError
      attempt.error = attempt.resumeParentDone
        ? `主任务已继续，子任务尚未全部恢复：${errorMessage(error)}`
        : errorMessage(error)
      if (options.activeThreadId.value === attempt.threadId) {
        lastError.value = attempt.error
        reportError(attempt.error)
      }
    }
    try {
      if (attempt.intent === 'resume') {
        if (!await ensureSubmissionConnection(attempt.threadId)) throw new Error(lastError.value)
        const input = attempt.text || attempt.attachments.length
          ? buildCoreComposerInputItems(attempt.text, attempt.attachments, attempt.catalog)
          : []
        if (attempt.activeTurnId && !attempt.resumeParentDone) {
          await options.resumeTurn?.(attempt.threadId, attempt.activeTurnId, input, attempt.id)
          attempt.resumeParentDone = true
          acceptSubmission(attempt)
        }
        // The parent may have accepted its supplement even if a member fails.
        // Retrying this record only retries the unfinished member recovery.
        if (attempt.resumeMembers) await options.resumeSubAgents?.(attempt.threadId)
        attempt.state = 'accepted'
        if (!attempt.acknowledged) acceptSubmission(attempt)
        return null
      }
      if (attempt.turnOptions === undefined) {
        // Invoke the provider before yielding: the host captures its controls now.
        const turnOptions = attempt.replaceTurnId
          ? options.turnOptions?.({ historicalEdit: true }) : options.turnOptions?.()
        attempt.turnOptions = copySubmissionValue(await turnOptions || {})
      }
      attempt.state = 'sending'
      publishSubmissions()
      let startError: unknown
      const result = await submitCoreComposerTask({
        threadId: attempt.threadId,
        activeTurnId: attempt.activeTurnId,
        text: attempt.text,
        status: attempt.intent === 'start' ? 'idle' : 'running',
        commandCatalog: attempt.catalog,
        attachments: attempt.attachments,
        workRoot: attempt.workRoot,
        turnOptions: attempt.turnOptions,
        clientMessageId: attempt.id,
        forceGuide: attempt.intent === 'guide',
        allowCommand: attempt.ownsDraft,
        steerTurn: options.steerTurn,
        queueInput: async (...args) => {
          attempt.intent = 'queue'
          await options.queueInput(...args)
        },
        startTurn: async (_threadId, input) => {
          try {
            if (!await ensureSubmissionConnection(attempt.threadId)) throw new Error(lastError.value)
            await options.startTurn(attempt.threadId, input, attempt.workRoot, {
              ...attempt.turnOptions,
              ...(attempt.replaceTurnId ? { replace_turn_id: attempt.replaceTurnId } : {}),
              // user:“全修”+(重试沿用编辑打开时的版本，由用户重新打开编辑才允许更新版本)。
              ...(attempt.replaceRevision !== undefined ? { expected_revision: attempt.replaceRevision } : {}),
            }, attempt.id)
            if (options.activeThreadId.value === attempt.threadId) lastError.value = ''
            notifyTurnStarted()
            return { ok: true }
          } catch (error) {
            startError = error
            // user:“修吧 让用户更易用”+(服务端说会话仍停在暂停回合时，普通发送要落成
            // “继续那一轮”；继续失败就把这条消息排到下一轮，绝不直接报“发送失败”)。
            if (!attempt.replaceTurnId && options.resumeTurn && isCorePausedSessionError(error)) {
              // 错误里可能没带回合 id（旧服务端只回文字）：空 id 让服务端继续最近
              // 暂停的那一轮，和点“继续”是同一个语义。
              const pausedTurnId = corePausedTurnIdFromError(error) || options.resumableTurnId?.value || ''
              try {
                await options.resumeTurn(attempt.threadId, pausedTurnId, input, attempt.id)
                attempt.intent = 'resume'
                attempt.resumeParentDone = true
                if (options.activeThreadId.value === attempt.threadId) lastError.value = ''
                notifyTurnStarted()
                return { ok: true }
              } catch (resumeError) {
                // 送达结果未知时不能盲目排队（可能已经继续成功），保留可重试状态。
                startError = resumeError
                if (resumeError instanceof CoreRequestAcceptanceUnknownError) {
                  return { ok: false, busy: false }
                }
              }
              // 暂停回合已经恢复不了（例如被回退掉了）：把消息排到下一轮，内容不丢。
              return { ok: false, busy: true }
            }
            return { ok: false, busy: !attempt.replaceTurnId && isCoreSessionBusyError(error) }
          }
        },
      })
      if (result.status === 'started' && !result.ok) {
        fail(startError)
      } else if (result.status === 'submitted') {
        // user:“引导在结束边界之后被接收：原回合结束，创建一条真实用户消息并开启
        // 新回合”+(这条发送的落点已经是新回合里的一条用户消息：按"已开始"收尾，
        // 不做排队提示、不显示引导成功、也不再补发一次队列写入)。
        attempt.state = 'accepted'
        if (!attempt.acknowledged) acceptSubmission(attempt)
        notifyTurnStarted()
      } else if (result.status !== 'ignored') {
        attempt.state = result.status === 'queued' ? 'queued' : result.status === 'guided' ? 'guided' : 'accepted'
        // Preserve fallback intent on retry: never start a second turn for a queued write.
        if (result.status === 'queued') attempt.intent = 'queue'
        if (result.status === 'guided') attempt.intent = 'guide'
        if (!attempt.acknowledged) acceptSubmission(attempt)
        if (options.activeThreadId.value === attempt.threadId) {
          if (result.status === 'queued') options.setStatusText?.(options.messages?.queued || 'Queued')
          if (result.status === 'guided') options.setStatusText?.(options.messages?.guided || 'Guidance sent')
        }
      }
      return result
    } catch (error) {
      fail(error)
      return null
    } finally {
      submitting.value = false
      publishSubmissions()
      options.onSubmitSettled?.()
    }
  }

  async function ensureSubmissionConnection(threadId: string): Promise<boolean> {
    // user:“做吧”+(旧聊天的迟到发送复用已打开的连接，不抢回当前聊天的订阅)。
    if (options.connectionState.value === 'open' && options.connectedThreadId.value) return true
    return await ensureConnected(threadId)
  }

  async function retrySubmission(id: string): Promise<SubmitCoreComposerTaskResult | null> {
    const attempt = attempts.get(id)
    // user:“全修”+(版本冲突必须从刷新后的历史重新打开编辑，旧稿不能重试截断)。
    if (!attempt || attempt.needsReopen || options.activeThreadId.value !== attempt.threadId
      || !['failed', 'unknown'].includes(attempt.state)) return null
    return await runSubmission(attempt)
  }

  function editSubmission(id: string): boolean {
    const attempt = attempts.get(id)
    if (!attempt || attempt.state !== 'failed' || attempt.resumeParentDone || attempt.replaceTurnId
      || options.activeThreadId.value !== attempt.threadId) return false
    if (options.text.value.trim() || options.attachments.value.length) return false
    options.text.value = attempt.rawText
    // A failed record remains available for attachment-only submissions too.
    options.restoreAttachments?.(copySubmissionValue(attempt.attachments))
    attempts.delete(id)
    publishSubmissions()
    options.focusComposer?.(attempt.rawText.length)
    return true
  }

  function dismissSubmission(id: string): void {
    const attempt = attempts.get(id)
    if (!attempt || ['preparing', 'sending', 'unknown'].includes(attempt.state)) return
    attempts.delete(id)
    publishSubmissions()
  }

  async function submit(input: NewSubmission): Promise<SubmitCoreComposerTaskResult | null> {
    if (submitting.value) return null
    if (input.replaceTurnId) {
      for (const [id, attempt] of attempts) {
        if (attempt.needsReopen && attempt.threadId === input.threadId && attempt.replaceTurnId === input.replaceTurnId) {
          attempts.delete(id)
        }
      }
    }
    const attachments = copySubmissionValue(input.attachments)
    const prior = [...attempts.values()].find(attempt => attempt.threadId === input.threadId
      && attempt.rawText === input.rawText && attempt.ownsDraft === input.ownsDraft
      && attempt.replaceTurnId === input.replaceTurnId
      && attempt.replaceRevision === input.replaceRevision
      && (attempt.intent !== 'resume' || attempt.activeTurnId === input.activeTurnId)
      && JSON.stringify(attempt.attachments) === JSON.stringify(attachments)
      && ['unknown', 'failed'].includes(attempt.state))
    if (prior) return await runSubmission(prior)

    const text = input.rawText.trim()
    const attempt: SubmissionAttempt = {
      ...input,
      id: crypto.randomUUID(),
      text,
      attachments,
      catalog: copySubmissionValue(input.catalog),
      state: input.intent === 'resume' ? 'sending' : 'preparing',
      error: '',
      draftVersion: getDraftVersion(),
    }
    attempts.set(attempt.id, attempt)
    publishSubmissions()
    if (text || attachments.length) options.onSubmitStart?.(text)
    return await runSubmission(attempt)
  }

  return { submissions, submit, acknowledgeSubmission, retrySubmission, editSubmission, dismissSubmission }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
