import { computed, ref, watch, type Ref } from 'vue'
import {
  coreComposerActionMode,
  coreComposerSubmissionEffects,
  isCoreActiveTurnStatus,
  normalizeCoreCommandCatalogItem,
  submitCoreComposerTask,
  type CoreWorkbenchTurnStatus,
  type SubmitCoreComposerTaskResult,
} from '../appServer/workbenchActions'
import type { CoreCommandCatalogItem, CoreInputItem } from '../types'
import { useComposerCommandPalette } from './useComposerCommandPalette'
import {
  useCoreLiveTurnController,
  type CoreLiveConnectionState,
} from './useCoreLiveTurnController'

export interface CoreLiveComposerMessages {
  commandCatalogLoadFailed?: (error: string) => string
  noActiveThread?: string
  queued?: string
  guided?: string
  sendFailed?: string
  stopping?: string
  stopFailed?: string
}

export interface UseCoreLiveComposerControllerOptions {
  activeThreadId: Readonly<Ref<string | null>>
  activeTurnId?: Readonly<Ref<string>>
  connectedThreadId: Readonly<Ref<string>>
  connectionState: Readonly<Ref<CoreLiveConnectionState>>
  text: Ref<string>
  cursor: Ref<number>
  status: Readonly<Ref<CoreWorkbenchTurnStatus>>
  attachments: Readonly<Ref<CoreInputItem[]>>
  connect(threadId: string): Promise<void>
  startTurn(threadId: string, input: CoreInputItem[], workRoot?: string, options?: Record<string, unknown>): Promise<void>
  interruptTurn(threadId: string, turnId?: string): Promise<void>
  steerTurn?(threadId: string, turnId: string, input: CoreInputItem[]): Promise<void>
  queueInput(threadId: string, input: CoreInputItem[]): Promise<void>
  listCommands(workRoot?: string): Promise<unknown[]>
  getWorkRoot(): string
  executeCommand(threadId: string, command: string, workRoot?: string): Promise<boolean>
  canExecuteCommand?(): boolean
  commandUnavailableMessage?: string
  turnOptions?(): Record<string, unknown>
  clearComposer?(submittedText: string): void
  clearAttachments?(): void
  focusComposer?(cursor: number): void
  setStatusText?(text: string): void
  onError?(text: string): void
  onTurnStarted?(): void | Promise<void>
  onTurnStartedError?(error: unknown): void
  messages?: CoreLiveComposerMessages
}

export function useCoreLiveComposerController(options: UseCoreLiveComposerControllerOptions) {
  const commandCatalog = ref<CoreCommandCatalogItem[]>([])
  const commandError = ref('')
  const commandCatalogLoading = ref(false)
  const dismissedText = ref('')
  const lastEnterHandledAt = ref(0)
  const commandRunning = ref(false)
  let commandCatalogGeneration = 0
  let stopPending = false
  const liveTurnController = useCoreLiveTurnController<CoreInputItem[]>({
    activeThreadId: options.activeThreadId,
    activeTurnId: options.activeTurnId,
    connectedThreadId: options.connectedThreadId,
    connectionState: options.connectionState,
    connect: options.connect,
    startTurn: options.startTurn,
    interruptTurn: options.interruptTurn,
  })
  const commandPalette = useComposerCommandPalette({
    text: options.text,
    cursor: options.cursor,
    commands: commandCatalog,
  })
  const paletteVisible = computed(() => (
    commandPalette.open.value && dismissedText.value !== options.text.value
  ))
  const actionMode = computed(() => commandRunning.value
    ? 'stop'
    : coreComposerActionMode({
        status: options.status.value,
        text: options.text.value,
        pendingAttachmentCount: options.attachments.value.length,
      }))

  watch(options.text, () => {
    if (dismissedText.value && dismissedText.value !== options.text.value) dismissedText.value = ''
  })
  watch(options.status, (status) => {
    if (!stopPending || isCoreActiveTurnStatus(status)) return
    stopPending = false
    options.setStatusText?.('')
  })

  async function loadCommandCatalog(threadId = options.activeThreadId.value || ''): Promise<boolean> {
    if (!threadId || threadId !== options.activeThreadId.value) return false
    const generation = ++commandCatalogGeneration
    const workRoot = options.getWorkRoot()
    commandCatalog.value = []
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
  }

  function replaceActiveSlash(command: CoreCommandCatalogItem, replacement?: string): void {
    const span = commandPalette.activeSlash.value
    if (!span) return
    const nextText = replacement ?? (command.action === 'insert_token' ? `/${command.name}` : '')
    const updatedText = `${options.text.value.slice(0, span.start)}${nextText}${options.text.value.slice(span.end)}`
    const nextCursor = span.start + nextText.length
    options.text.value = updatedText
    options.cursor.value = nextCursor
    if (command.action === 'insert_token') dismissedText.value = updatedText
    options.focusComposer?.(nextCursor)
  }

  async function selectCommand(command: CoreCommandCatalogItem): Promise<boolean> {
    commandPalette.reset()
    if (command.action === 'insert_token') {
      replaceActiveSlash(command)
      return true
    }
    replaceActiveSlash(command, `/${command.name}`)
    const ok = await runCommand(command.name)
    if (ok) replaceActiveSlash(command, '')
    else dismissedText.value = options.text.value
    return ok
  }

  async function runCommand(command: string): Promise<boolean> {
    const threadId = options.activeThreadId.value || ''
    if (!threadId) {
      reportError(options.messages?.noActiveThread || 'An active thread is required')
      return false
    }
    const workRoot = options.getWorkRoot()
    const submittedCommand = options.text.value.trim()
    const clearRunningCommand = submittedCommand === `/${command}`
    if (options.canExecuteCommand && !options.canExecuteCommand()) {
      reportError(options.commandUnavailableMessage || 'Command is unavailable while the turn is active')
      return false
    }
    try {
      if (!await liveTurnController.ensureConnected(threadId)) {
        throw new Error(liveTurnController.lastError.value)
      }
      commandPalette.reset()
      if (clearRunningCommand) clearCommandComposer(submittedCommand)
      commandRunning.value = true
      const ok = await options.executeCommand(threadId, command, workRoot)
      if (!ok && clearRunningCommand && !options.text.value) options.text.value = submittedCommand
      return ok
    } catch (error) {
      if (clearRunningCommand && !options.text.value) options.text.value = submittedCommand
      reportError(errorMessage(error))
      return false
    } finally {
      commandRunning.value = false
    }
  }

  async function stop(): Promise<boolean> {
    stopPending = true
    options.setStatusText?.(options.messages?.stopping || 'Stopping')
    const ok = await liveTurnController.interruptActiveTurn()
    if (!ok) {
      stopPending = false
      reportError(liveTurnController.lastError.value || options.messages?.stopFailed || 'Unable to stop turn')
    }
    return ok
  }

  async function submit(submissionOptions: { clearComposer?: boolean } = {}): Promise<SubmitCoreComposerTaskResult | null> {
    if (actionMode.value === 'stop') {
      await stop()
      return null
    }
    const threadId = options.activeThreadId.value || ''
    if (!threadId) {
      reportError(options.messages?.noActiveThread || 'An active thread is required')
      return null
    }
    const submittedText = options.text.value.trim()
    const workRoot = options.getWorkRoot()
    const turnOptions = options.turnOptions?.() || {}
    try {
      const result = await submitCoreComposerTask({
        threadId,
        activeTurnId: options.activeTurnId?.value || '',
        text: submittedText,
        status: options.status.value,
        commandCatalog: commandCatalog.value,
        attachments: options.attachments.value,
        executeCommand: runCommand,
        steerTurn: options.steerTurn,
        queueInput: options.queueInput,
        startTurn: async (_threadId, input) => {
          const started = await liveTurnController.startThreadTurn(
            input,
            threadId,
            workRoot,
            turnOptions,
          )
          if (started) {
            notifyTurnStarted()
          } else {
            reportError(liveTurnController.lastError.value || options.messages?.sendFailed || 'Unable to send message')
          }
          return started
        },
      })
      applySubmissionEffects(result, submittedText, submissionOptions.clearComposer === true)
      return result
    } catch (error) {
      reportError(errorMessage(error) || options.messages?.sendFailed || 'Unable to send message')
      return null
    }
  }

  async function handleKeydown(event: KeyboardEvent): Promise<boolean> {
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
    if (event.key === 'Enter' && (!event.shiftKey || paletteVisible.value)) {
      event.preventDefault()
      lastEnterHandledAt.value = Date.now()
      const selected = paletteVisible.value ? commandPalette.selected() : null
      if (selected) await selectCommand(selected)
      else await submit({ clearComposer: true })
      return true
    }
    return false
  }

  async function handleKeyup(event: KeyboardEvent, fallbackMs = 750): Promise<boolean> {
    if (event.key !== 'Enter' || event.shiftKey || Date.now() - lastEnterHandledAt.value < fallbackMs) return false
    event.preventDefault()
    lastEnterHandledAt.value = Date.now()
    if (paletteVisible.value) {
      const selected = commandPalette.selected()
      if (selected) await selectCommand(selected)
      return true
    }
    await submit({ clearComposer: true })
    return true
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
    options.onError?.(message)
    options.setStatusText?.(message)
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
    actionMode,
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
