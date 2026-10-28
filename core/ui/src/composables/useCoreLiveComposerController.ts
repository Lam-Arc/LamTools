import { computed, getCurrentScope, onScopeDispose, ref, shallowRef, watch, type Ref } from 'vue'
import {
  coreComposerActionMode,
  coreComposerSubmissionEffects,
  isCoreActiveTurnStatus,
  isCoreSessionBusyError,
  normalizeCoreCommandCatalogItem,
  submitCoreComposerTask,
  type CoreSteerAttempt,
  type CoreWorkbenchTurnStatus,
  type SubmitCoreComposerTaskResult,
} from '@/appServer/workbenchActions.ts'
import type { CoreCommandCatalogItem, CoreInputItem } from '@/types.ts'
import { buildCoreComposerInputItems } from '@/composer/inputItems.ts'
import { CoreRequestAcceptanceUnknownError } from '@/appServer/client.ts'
import { parseComposerInput } from '@/composer/syntax.ts'
import { useComposerCommandPalette } from '@/composables/useComposerCommandPalette.ts'
import {
  useCoreLiveTurnController,
  type CoreLiveConnectionState,
} from '@/composables/useCoreLiveTurnController.ts'

export interface CoreLiveComposerMessages {
  commandCatalogLoadFailed?: (error: string) => string
  noActiveThread?: string
  queued?: string
  guided?: string
  sendFailed?: string
  stopping?: string
  stopFailed?: string
  forceResetting?: string
  forceResetFailed?: string
}

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
}

interface SubmissionAttempt extends CoreComposerSubmission {
  rawText: string
  draftVersion: number
  activeTurnId: string
  status: CoreWorkbenchTurnStatus
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

export interface UseCoreLiveComposerControllerOptions {
  activeThreadId: Readonly<Ref<string | null>>
  activeTurnId?: Readonly<Ref<string>>
  resumableTurnId?: Readonly<Ref<string>>
  /** Whether the session is paused as a whole: its members follow the session. */
  sessionPaused?: Readonly<Ref<boolean>>
  /** Continue the paused turn. Text typed while paused rides the same press. */
  resumeTurn?(threadId: string, turnId: string, input?: CoreInputItem[], clientMessageId?: string): Promise<void>
  /** Long-press confirm: end the turn and its members for good. */
  terminateTurn?(threadId: string, turnId?: string): Promise<void>
  /**
   * Members currently working. When the parent turn is not the active target,
   * Stop addresses these members: a parent turn that already ended is never
   * restarted to control them.
   */
  interruptibleSubAgents?: Readonly<Ref<string[]>>
  /** Members whose last recorded state is `interrupted`; Resume continues them. */
  resumableSubAgents?: Readonly<Ref<string[]>>
  /**
   * Whether the connected server implements the child-directed operations.
   * Runtimes that do not (embedded mobile standalone) must not show a control
   * whose request would fail.
   */
  subAgentControl?: Readonly<Ref<boolean>>
  interruptSubAgents?(threadId: string): Promise<void>
  resumeSubAgents?(threadId: string): Promise<void>
  connectedThreadId: Readonly<Ref<string>>
  connectionState: Readonly<Ref<CoreLiveConnectionState>>
  text: Ref<string>
  cursor: Ref<number>
  status: Readonly<Ref<CoreWorkbenchTurnStatus>>
  attachments: Readonly<Ref<CoreInputItem[]>>
  connect(threadId: string): Promise<void>
  startTurn(
    threadId: string,
    input: CoreInputItem[],
    workRoot?: string,
    options?: Record<string, unknown>,
    clientMessageId?: string,
  ): Promise<void>
  interruptTurn(threadId: string, turnId?: string): Promise<void>
  /** Single click on the stop button: pause instead of ending. */
  pauseTurn(threadId: string, turnId?: string): Promise<void>
  forceResetTurn(threadId: string, turnId?: string): Promise<void>
  steerTurn?(
    threadId: string,
    turnId: string,
    input: CoreInputItem[],
    clientMessageId?: string,
  ): Promise<boolean | CoreSteerAttempt>
  queueInput(
    threadId: string,
    input: CoreInputItem[],
    options?: Record<string, unknown>,
    clientMessageId?: string,
  ): Promise<void>
  listCommands(workRoot?: string): Promise<unknown[]>
  getWorkRoot(): string
  executeCommand(threadId: string, command: string, workRoot?: string, argumentsText?: string): Promise<boolean>
  canExecuteCommand?(): boolean
  canSubmit?(): boolean
  commandUnavailableMessage?: string
  turnOptions?(): Record<string, unknown> | Promise<Record<string, unknown>>
  clearComposer?(submittedText: string): void
  clearAttachments?(submittedAttachments?: CoreInputItem[]): void
  restoreAttachments?(attachments: CoreInputItem[]): void
  /** Retire only the parked draft belonging to this accepted submission. */
  onSubmissionAccepted?(submission: CoreComposerSubmission, rawText: string): void
  focusComposer?(cursor: number): void
  setStatusText?(text: string): void
  onError?(text: string): void
  onTurnStarted?(): void | Promise<void>
  onTurnStartedError?(error: unknown): void
  onSubmitStart?: (submittedText: string) => void
  /** 一次提交走到终点（发送/排队/引导/失败）都会回调一次：宿主用它收掉"待发送"占位。
   *  引导与排队不会立刻产生用户消息，只等消息出现会永远等不到。 */
  onSubmitSettled?: () => void
  messages?: CoreLiveComposerMessages
}

export function useCoreLiveComposerController(options: UseCoreLiveComposerControllerOptions) {
  const attempts = new Map<string, SubmissionAttempt>()
  const submissions = shallowRef<CoreComposerSubmission[]>([])
  let draftVersion = 0
  watch([options.text, options.activeThreadId], () => { draftVersion += 1 }, { flush: 'sync' })
  function publishSubmissions(): void {
    // Confirmed display rows no longer need an in-memory copy of the input.
    for (const [id, attempt] of attempts) {
      if (attempt.displayed && !submitting.value && attempt.state === 'accepted') attempts.delete(id)
    }
    const receipts = [...attempts.values()].filter(a => ['accepted', 'queued', 'guided'].includes(a.state))
    for (const receipt of receipts.slice(0, Math.max(0, receipts.length - 20))) attempts.delete(receipt.id)
    submissions.value = [...attempts.values()].filter(attempt => !attempt.displayed).map(attempt => ({ ...attempt }))
  }
  const commandCatalog = ref<CoreCommandCatalogItem[]>([])
  const commandError = ref('')
  const commandCatalogLoading = ref(false)
  const dismissedText = ref('')
  const lastEnterHandledAt = ref(0)
  const commandRunning = ref(false)
  const submitting = ref(false)
  let commandCatalogGeneration = 0
  let stopPending = false
  let stopGraceTimer: ReturnType<typeof setTimeout> | null = null

  function clearStopGraceTimer(): void {
    if (stopGraceTimer !== null) {
      clearTimeout(stopGraceTimer)
      stopGraceTimer = null
    }
  }
  // The 3s grace timer must never fire after the owning component unmounts —
  // escalateForceReset would target whatever thread activeThreadId points at
  // by then (possibly another session, or none) (audit 19 S2).
  if (getCurrentScope()) {
    onScopeDispose(() => {
      clearStopGraceTimer()
      stopPending = false
    })
  }
  const liveTurnController = useCoreLiveTurnController<CoreInputItem[]>({
    activeThreadId: options.activeThreadId,
    activeTurnId: options.activeTurnId,
    connectedThreadId: options.connectedThreadId,
    connectionState: options.connectionState,
    connect: options.connect,
    startTurn: options.startTurn,
    interruptTurn: options.interruptTurn,
    // Hosts that predate the pause contract keep their stop behaviour instead of
    // sending a method the runtime may not implement.
    pauseTurn: options.pauseTurn ?? options.interruptTurn,
    terminateTurn: options.terminateTurn ?? (async () => {}),
    forceResetTurn: options.forceResetTurn,
  })
  const commandPalette = useComposerCommandPalette({
    text: options.text,
    cursor: options.cursor,
    commands: commandCatalog,
  })
  const paletteVisible = computed(() => (
    commandPalette.open.value && dismissedText.value !== options.text.value
  ))
  // A stop/resume affordance must name its target: the parent turn while one is
  // active, otherwise the delegated members it can actually control. With the
  // parent turn already terminal, the old derivation fell back to `send`, so
  // running members had no stop control at all.
  const draftEmpty = computed(() => (
    !options.text.value.trim() && !options.attachments.value.length
  ))
  const childControlSupported = computed(() => options.subAgentControl?.value === true)
  const childStopTarget = computed(() => (
    childControlSupported.value
    && !isCoreActiveTurnStatus(options.status.value)
    && !options.resumableTurnId?.value
    && draftEmpty.value
    && (options.interruptibleSubAgents?.value.length ?? 0) > 0
    && Boolean(options.interruptSubAgents)
  ))
  const childResumeTarget = computed(() => (
    childControlSupported.value
    && !isCoreActiveTurnStatus(options.status.value)
    && options.sessionPaused?.value !== true
    && !options.resumableTurnId?.value
    && draftEmpty.value
    && !childStopTarget.value
    && (options.resumableSubAgents?.value.length ?? 0) > 0
    && Boolean(options.resumeSubAgents)
  ))
  const actionMode = computed(() => commandRunning.value
    ? 'stop'
    : childStopTarget.value
      ? 'stop'
      : options.resumableTurnId?.value && options.resumeTurn && draftEmpty.value
        ? 'resume'
        : childResumeTarget.value
          ? 'resume'
          : coreComposerActionMode({
            status: options.status.value,
            text: options.text.value,
            pendingAttachmentCount: options.attachments.value.length,
          }))

  watch(options.text, () => {
    if (dismissedText.value && dismissedText.value !== options.text.value) dismissedText.value = ''
  })
  watch(
    () => commandPalette.activeSlash.value !== null,
    (active, wasActive) => {
      if (active && !wasActive && options.activeThreadId.value) {
        void loadCommandCatalog(options.activeThreadId.value)
      }
    },
  )
  watch(options.status, (status) => {
    if (!stopPending || isCoreActiveTurnStatus(status)) return
    stopPending = false
    clearStopGraceTimer()
    options.setStatusText?.('')
  })

  async function loadCommandCatalog(threadId = options.activeThreadId.value || ''): Promise<boolean> {
    if (!threadId || threadId !== options.activeThreadId.value) return false
    const generation = ++commandCatalogGeneration
    const workRoot = options.getWorkRoot()
    commandError.value = ''
    dismissedText.value = ''
    if (!threadId) return true
    commandCatalogLoading.value = true
    try {
      if (!await liveTurnController.ensureConnected(threadId)) {
        throw new Error(liveTurnController.lastError.value)
      }
      const commands = await options.listCommands(workRoot)
      if (generation !== commandCatalogGeneration) return false
      commandCatalog.value = commands
        .map(normalizeCoreCommandCatalogItem)
        .filter((item): item is CoreCommandCatalogItem => item !== null)
      return true
    } catch (error) {
      if (generation !== commandCatalogGeneration) return false
      const message = errorMessage(error)
      commandError.value = message
      options.setStatusText?.(options.messages?.commandCatalogLoadFailed?.(message) || message)
      return false
    } finally {
      if (generation === commandCatalogGeneration) commandCatalogLoading.value = false
    }
  }

  function resetForThreadChange(): void {
    commandCatalogGeneration += 1
    commandCatalog.value = []
    commandError.value = ''
    commandCatalogLoading.value = false
    dismissedText.value = ''
    commandPalette.reset()
    stopPending = false
    clearStopGraceTimer()
  }

  function replaceActiveSlash(command: CoreCommandCatalogItem, replacement?: string): void {
    const span = commandPalette.activeSlash.value
    if (!span) return
    const nextText = replacement ?? `/${command.name}${command.accepts_args ? ' ' : ''}`
    const updatedText = `${options.text.value.slice(0, span.start)}${nextText}${options.text.value.slice(span.end)}`
    const nextCursor = span.start + nextText.length
    options.text.value = updatedText
    options.cursor.value = nextCursor
    dismissedText.value = updatedText
    options.focusComposer?.(nextCursor)
  }

  async function selectCommand(command: CoreCommandCatalogItem): Promise<boolean> {
    commandPalette.reset()
    replaceActiveSlash(command)
    return true
  }

  async function runCommand(command: string, argumentsText = ''): Promise<boolean> {
    const threadId = options.activeThreadId.value || ''
    if (!threadId) {
      reportCommandError(options.messages?.noActiveThread || 'An active thread is required')
      return false
    }
    const workRoot = options.getWorkRoot()
    const submittedCommand = options.text.value.trim()
    // user:“做吧”+(命令的迟到清理或失败恢复不能写入另一聊天的新草稿)。
    const commandDraftVersion = draftVersion
    let clearedVersion: number | undefined
    const expectedCommandText = `/${command}${argumentsText ? ` ${argumentsText}` : ''}`
    const clearRunningCommand = submittedCommand === expectedCommandText || submittedCommand === `/${command}`
    if (options.canExecuteCommand && !options.canExecuteCommand()) {
      reportCommandError(options.commandUnavailableMessage || 'Command is unavailable while the turn is active')
      return false
    }
    try {
      if (!await liveTurnController.ensureConnected(threadId)) {
        throw new Error(liveTurnController.lastError.value)
      }
      commandPalette.reset()
      if (clearRunningCommand && options.activeThreadId.value === threadId && draftVersion === commandDraftVersion) {
        clearCommandComposer(submittedCommand)
        clearedVersion = draftVersion
      }
      commandRunning.value = true
      const ok = await options.executeCommand(threadId, command, workRoot, argumentsText)
      if (!ok && clearedVersion === draftVersion && options.activeThreadId.value === threadId && !options.text.value) options.text.value = submittedCommand
      return ok
    } catch (error) {
      if (clearedVersion === draftVersion && options.activeThreadId.value === threadId && !options.text.value) options.text.value = submittedCommand
      if (options.activeThreadId.value === threadId) reportCommandError(errorMessage(error))
      return false
    } finally {
      commandRunning.value = false
    }
  }

  async function stop(): Promise<boolean> {
    if (childStopTarget.value) {
      // The parent turn is not the target (already terminal): Stop means stop
      // the members it left running. Nothing here may restart the parent, and
      // there is no turn to force-reset, so no grace escalation applies.
      const threadId = options.activeThreadId.value || ''
      options.setStatusText?.(options.messages?.stopping || 'Stopping')
      try {
        if (!await liveTurnController.ensureConnected(threadId)) {
          reportError(liveTurnController.lastError.value || options.messages?.stopFailed || 'Unable to stop turn')
          return false
        }
        await options.interruptSubAgents?.(threadId)
        options.setStatusText?.('')
        return true
      } catch (error) {
        reportError(errorMessage(error) || options.messages?.stopFailed || 'Unable to stop turn')
        return false
      }
    }
    stopPending = true
    clearStopGraceTimer()
    options.setStatusText?.(options.messages?.stopping || 'Stopping')
    // Single click parks the turn: the model answer of the running step is
    // dropped, finished tools stay, and Continue brings the same turn back.
    const ok = await liveTurnController.pauseActiveTurn(options.activeTurnId?.value || '')
    if (!ok) {
      stopPending = false
      reportError(liveTurnController.lastError.value || options.messages?.stopFailed || 'Unable to stop turn')
      return ok
    }
    // No grace escalation. It used to force-reset a turn that still looked
    // active 3 s after Stop, and with Stop being a pause that is exactly wrong:
    // a pause that has not settled yet (the cut tool still unwinding, a member
    // still being parked) was terminated by the user's own Stop press
    // (2026-10-14). A pause that genuinely fails just leaves the turn running;
    // the user presses Stop again, and nothing is destroyed by a timeout.
    return ok
  }

  /**
   * Long-press confirm result: terminate the turn and every member with it.
   * Nothing is offered to continue afterwards.
   */
  async function terminate(): Promise<boolean> {
    const threadId = options.activeThreadId.value || ''
    if (!threadId) return false
    if (!await liveTurnController.ensureConnected(threadId)) {
      reportError(liveTurnController.lastError.value || options.messages?.stopFailed || 'Unable to stop turn')
      return false
    }
    // A paused turn is not the "active" one, so name it explicitly.
    const ok = await liveTurnController.terminateActiveTurn(options.resumableTurnId?.value || '')
    if (!ok) {
      reportError(liveTurnController.lastError.value || options.messages?.stopFailed || 'Unable to stop turn')
      return false
    }
    stopPending = false
    clearStopGraceTimer()
    options.setStatusText?.('')
    return true
  }

  // user:“做吧”+(先固定提交快照；准备、发送、确认和重试共享同一个请求身份)。
  function acceptSubmission(attempt: SubmissionAttempt): void {
    if (attempt.acknowledged) return
    attempt.acknowledged = true
    if (options.activeThreadId.value === attempt.threadId) {
      if (attempt.clearComposer && draftVersion === attempt.draftVersion && options.text.value === attempt.rawText) {
        options.clearComposer?.(attempt.text)
      }
      // Remove exactly the accepted files, never files added while awaiting a reply.
      options.clearAttachments?.(attempt.attachments)
    }
    options.onSubmissionAccepted?.(attempt, attempt.rawText)
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
      attempt.error = attempt.resumeParentDone
        ? `主任务已继续，子任务尚未全部恢复：${errorMessage(error)}`
        : errorMessage(error)
      if (options.activeThreadId.value === attempt.threadId) {
        liveTurnController.lastError.value = attempt.error
        reportError(attempt.error)
      }
    }
    try {
      if (attempt.intent === 'resume') {
        if (!await ensureSubmissionConnection(attempt.threadId)) throw new Error(liveTurnController.lastError.value)
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
        attempt.turnOptions = copySubmissionValue(await options.turnOptions?.() || {})
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
        steerTurn: options.steerTurn,
        queueInput: async (...args) => {
          attempt.intent = 'queue'
          await options.queueInput(...args)
        },
        startTurn: async (_threadId, input) => {
          try {
            if (!await ensureSubmissionConnection(attempt.threadId)) throw new Error(liveTurnController.lastError.value)
            await options.startTurn(attempt.threadId, input, attempt.workRoot, attempt.turnOptions, attempt.id)
            liveTurnController.lastError.value = ''
            notifyTurnStarted()
            return { ok: true }
          } catch (error) {
            startError = error
            return { ok: false, busy: isCoreSessionBusyError(error) }
          }
        },
      })
      if (result.status === 'started' && !result.ok) {
        fail(startError)
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
    return await liveTurnController.ensureConnected(threadId)
  }

  async function retrySubmission(id: string): Promise<SubmitCoreComposerTaskResult | null> {
    const attempt = attempts.get(id)
    if (!attempt || options.activeThreadId.value !== attempt.threadId || !['failed', 'unknown'].includes(attempt.state)) return null
    return await runSubmission(attempt)
  }

  function editSubmission(id: string): boolean {
    const attempt = attempts.get(id)
    if (!attempt || attempt.state !== 'failed' || attempt.resumeParentDone || options.activeThreadId.value !== attempt.threadId) return false
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

  async function submit(submissionOptions: { clearComposer?: boolean; forceGuide?: boolean } = {}): Promise<SubmitCoreComposerTaskResult | null> {
    const pausedTurnId = options.resumableTurnId?.value || ''
    const resuming = Boolean(pausedTurnId || actionMode.value === 'resume')
    if (!resuming && actionMode.value === 'stop') { await stop(); return null }
    if (submitting.value) return null
    // user:“做吧”+(鼠标与键盘发送共用校验，停止操作不被发送条件阻挡)。
    if (options.canSubmit && !options.canSubmit()) return null
    const threadId = options.activeThreadId.value || ''
    if (!threadId) { reportError(options.messages?.noActiveThread || 'An active thread is required'); return null }
    const rawText = options.text.value
    const text = rawText.trim()
    const attachments = copySubmissionValue(options.attachments.value || [])
    const catalog = copySubmissionValue(commandCatalog.value)
    if (!resuming && !text && !attachments.length) return { status: 'ignored' }
    const command = attachments.length ? null : parseComposerInput(text, catalog)
    if (!resuming && command?.kind === 'action') {
      const version = draftVersion
      submitting.value = true
      try {
        const ok = await runCommand(command.name, command.arguments)
        if (options.activeThreadId.value === threadId && draftVersion === version) {
          applySubmissionEffects({ status: 'command', command: command.name, ok }, text, submissionOptions.clearComposer === true)
        }
        return { status: 'command', command: command.name, ok }
      } finally { submitting.value = false; options.onSubmitSettled?.() }
    }
    const prior = [...attempts.values()].find(a => a.threadId === threadId && a.rawText === rawText
      && JSON.stringify(a.attachments) === JSON.stringify(attachments) && ['unknown', 'failed'].includes(a.state))
    if (prior) return await runSubmission(prior)
    const attempt: SubmissionAttempt = {
      id: crypto.randomUUID(), threadId, text, rawText, attachments,
      state: resuming ? 'sending' : 'preparing', error: '',
      draftVersion, activeTurnId: resuming ? pausedTurnId : options.activeTurnId?.value || '',
      status: options.status.value, catalog, workRoot: options.getWorkRoot(),
      clearComposer: submissionOptions.clearComposer === true || resuming,
      intent: resuming ? 'resume' : isCoreActiveTurnStatus(options.status.value) ? (submissionOptions.forceGuide ? 'guide' : 'queue') : 'start',
      resumeMembers: (options.resumableSubAgents?.value.length ?? 0) > 0,
    }
    attempts.set(attempt.id, attempt)
    publishSubmissions()
    if (text || attachments.length) options.onSubmitStart?.(text)
    return await runSubmission(attempt)
  }

  async function handleKeydown(event: KeyboardEvent): Promise<boolean> {
    // user:“极简、可靠、功能性强”+(输入法确认键不触发菜单或发送)。
    if (event.isComposing) return false
    if (paletteVisible.value && event.key === 'Tab') {
      event.preventDefault()
      const command = commandPalette.selected()
      if (command) await selectCommand(command)
      return true
    }
    if (paletteVisible.value) {
      if (event.key === 'ArrowDown') {
        event.preventDefault()
        commandPalette.move(1)
        return true
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault()
        commandPalette.move(-1)
        return true
      }
      if (event.key === 'Escape') {
        event.preventDefault()
        commandPalette.reset()
        dismissedText.value = options.text.value
        return true
      }
    }
    if (event.key === 'Enter' && !event.isComposing && !event.repeat && (!event.shiftKey || paletteVisible.value)) {
      event.preventDefault()
      lastEnterHandledAt.value = Date.now()
      const forceGuide = event.ctrlKey || event.metaKey
      const selected = paletteVisible.value ? commandPalette.selected() : null
      if (selected) await selectCommand(selected)
      else if (canEnterSubmit()) await submit({ clearComposer: true, forceGuide })
      return true
    }
    return false
  }

  async function handleKeyup(event: KeyboardEvent, fallbackMs = 750): Promise<boolean> {
    if (event.isComposing || event.key !== 'Enter' || event.shiftKey || Date.now() - lastEnterHandledAt.value < fallbackMs) return false
    event.preventDefault()
    lastEnterHandledAt.value = Date.now()
    if (paletteVisible.value) {
      const selected = commandPalette.selected()
      if (selected) await selectCommand(selected)
      return true
    }
    if (canEnterSubmit()) await submit({ clearComposer: true })
    return true
  }

  /**
   * 回车只发送，不停止：按钮处于停止形态（没有可发送的内容，或命令仍在执行）时，
   * 回车不下发任何请求——把正在跑的这一轮停掉是发送/停止按钮的职责，不是键盘的
   * （用户按第二次回车只是习惯性重复发送，不该杀掉整轮）。
   */
  function canEnterSubmit(): boolean {
    return actionMode.value !== 'stop'
  }

  function applySubmissionEffects(
    result: SubmitCoreComposerTaskResult,
    submittedText: string,
    clearComposer: boolean,
  ): void {
    const plan = coreComposerSubmissionEffects(result, {
      clearComposer,
      submittedText,
      queuedStatusText: options.messages?.queued || 'Queued',
      guidedStatusText: options.messages?.guided || 'Guidance sent',
    })
    if (plan.clearComposer) options.clearComposer?.(plan.clearComposerText || '')
    if (plan.restoreText !== undefined) options.text.value = plan.restoreText
    if (plan.clearAttachments) options.clearAttachments?.()
    if (plan.statusText) options.setStatusText?.(plan.statusText)
  }

  function clearCommandComposer(submittedCommand: string): void {
    options.clearComposer?.(submittedCommand)
    if (options.text.value.trim() === submittedCommand) options.text.value = ''
  }

  function reportError(message: string): void {
    // Status text is a notice toast in the host. Failures belong only in the
    // error channel; sending them to both channels shows green and red copies.
    options.setStatusText?.('')
    options.onError?.(message)
  }

  function reportCommandError(message: string): void {
    // Command failures already have the dedicated error toast.  Clear the
    // transient status banner instead of showing the same error twice.
    options.setStatusText?.('')
    options.onError?.(message)
  }

  function notifyTurnStarted(): void {
    if (!options.onTurnStarted) return
    void Promise.resolve()
      .then(() => options.onTurnStarted?.())
      .catch((error) => {
        if (options.onTurnStartedError) options.onTurnStartedError(error)
        else console.error('Core live composer post-start callback failed:', error)
      })
  }

  return {
    submissions,
    submitting,
    retrySubmission,
    editSubmission,
    dismissSubmission,
    acknowledgeSubmission,
    actionMode,
    terminate,
    commandCatalog,
    commandCatalogLoading,
    commandError,
    commandPalette,
    ensureConnected: liveTurnController.ensureConnected,
    handleKeydown,
    handleKeyup,
    lastError: liveTurnController.lastError,
    loadCommandCatalog,
    paletteVisible,
    resetForThreadChange,
    runCommand,
    selectCommand,
    stop,
    submit,
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
