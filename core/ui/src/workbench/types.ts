import type { ComputedRef, Ref } from 'vue'
import type {
  CoreAppEvent,
  CoreAppServerRuntimeClient,
  CoreAppSnapshot,
  CoreAppServerThreadSwitchOptions,
  CoreSessionActivity,
  CoreSessionPhase,
  CoreSteerOutcome,
  CoreSyncChangeNotification,
} from '@/appServer/index.ts'
import type { CoreCommandCatalogItem, CoreInputItem, CoreMessage, CoreSessionListItem, CoreSubAgentDurableRecord } from '@/types.ts'
import type { useComposerCommandPalette } from '@/composables/useComposerCommandPalette.ts'
import type { useCoreApprovalController } from '@/composables/useCoreApprovalController.ts'
import type { useCoreLiveComposerController } from '@/composables/useCoreLiveComposerController.ts'
import type { CoreComposerSubmission } from '@/composables/useCoreLiveComposerController.ts'
import type { useCoreQueuedInputController } from '@/composables/useCoreQueuedInputController.ts'
import type { CoreQueuedInput } from '@/appServer/workbenchProjection.ts'
import type { ComposerDraftStorage } from '@/composer/drafts.ts'
import type { LamToolsTransport, TransportHttpRequest, TransportHttpResponse } from '@/transport/index.ts'

export type WorkbenchConnectionState = 'connecting' | 'open' | 'closed' | 'error'

export interface WorkbenchSessionApi {
  listSessions(): Promise<CoreSessionListItem[]>
  createSession?(input?: { title?: string; metadata?: Record<string, unknown> }): Promise<CoreSessionListItem>
}

export interface WorkbenchClientFactory {
  createClient(params: {
    transport: LamToolsTransport
    onEvent: (event: CoreAppEvent) => void
    onSnapshot: (snapshot: CoreAppSnapshot) => void
    onSyncChange?: (change: CoreSyncChangeNotification) => void
    onConnectionState: (state: WorkbenchConnectionState) => void
  }): CoreAppServerRuntimeClient | Promise<CoreAppServerRuntimeClient>
}

export interface WorkbenchRuntimeOptions {
  /** Initial connection-neutral transport used by the shared workbench. */
  transport: LamToolsTransport
  /** Optional session adapter; the default uses the injected transport HTTP path. */
  sessions?: WorkbenchSessionApi
  clientFactory?: WorkbenchClientFactory
  getWorkRoot?: (session: CoreSessionListItem | undefined) => string | undefined
  onError?: (message: string) => void
  onStatusText?: (message: string) => void
  /**
   * Supplies the execution snapshot captured when a composer submission is
   * accepted. Desktop and mobile shells can therefore share the same
   * composer controls and transport semantics.
   */
  getTurnOptions?: () => Record<string, unknown> | Promise<Record<string, unknown>>
  /** Shared UI controls the projection's shallow-thinking state. */
  shallowThinking?: Readonly<Ref<boolean>>
  /** Called when the live composer accepts a submission, with the trimmed text. */
  onSubmitStart?: (submittedText: string) => void
  /** Called once a submission reaches any outcome (sent / queued / guided /
   *  failed). Hosts use it to retire the "sending" placeholder. */
  onSubmitSettled?: () => void
  /** Optional host capability hook for command side effects. */
  onCommandResult?: (result: Record<string, unknown>) => void | Promise<void>
  /**
   * Storage for per-thread unsent composer drafts. Defaults to
   * window.localStorage; tests and non-browser hosts may inject their own.
   */
  composerDraftStorage?: ComposerDraftStorage | null
}

export interface WorkbenchComposerCallbacks {
  canSubmit?: () => boolean
  /** user:“做吧”+(附件清理限定为已接收提交所属的聊天与文件)。 */
  onSubmissionAccepted?: (submission: CoreComposerSubmission) => void
  onRestoreAttachments?: (attachments: CoreInputItem[]) => void
  onError?: (message: string) => void
  onStatusText?: (message: string) => void
  onSubmitStart?: (submittedText: string) => void
  onSubmitSettled?: () => void
  onTurnStarted?: () => void | Promise<void>
  onCommandResult?: (result: Record<string, unknown>) => void | Promise<void>
}

export interface WorkbenchRuntime {
  transport: Readonly<Ref<LamToolsTransport | null>>
  activeThreadId: ComputedRef<string>
  sessions: Ref<CoreSessionListItem[]>
  activeSessionId: Ref<string | null>
  snapshot: ComputedRef<CoreAppSnapshot | null>
  messages: Ref<CoreMessage[]>
  connectionState: ComputedRef<WorkbenchConnectionState>
  turnState: ComputedRef<string>
  activeTurnId: ComputedRef<string>
  turnActive: ComputedRef<boolean>
  /** Derived session activity: main agent running vs awaiting sub-agents. */
  sessionActivity: ComputedRef<CoreSessionActivity>
  sessionPhase: ComputedRef<CoreSessionPhase>
  composerText: Ref<string>
  composerCursor: Ref<number>
  attachments: Ref<CoreInputItem[]>
  queuedInputs: ComputedRef<CoreQueuedInput[]>
  processExpandedIds: Ref<Set<string>>
  toggleProcess(id: string): void
  hasMoreHistory: Ref<boolean>
  /** True while at least one complete history page is already available locally. */
  historyBuffered: Readonly<Ref<boolean>>
  totalMessages: Ref<number>
  loadMoreHistory(): void | Promise<void>
  lastEvent: Ref<CoreAppEvent | null>
  approval: ReturnType<typeof useCoreApprovalController>
  queue: ReturnType<typeof useCoreQueuedInputController>
  /** The single composer controller used by every host shell. */
  composer: ReturnType<typeof useCoreLiveComposerController>
  commandCatalog: Ref<CoreCommandCatalogItem[]>
  commandPalette: ReturnType<typeof useComposerCommandPalette>
  paletteVisible: ComputedRef<boolean>
  actionMode: ComputedRef<'send' | 'stop' | 'resume'>
  handleComposerKeydown(event: KeyboardEvent): Promise<boolean>
  handleComposerKeyup(event: KeyboardEvent): Promise<boolean>
  selectCommand(command: CoreCommandCatalogItem): Promise<boolean>
  runCommand(command: string, argumentsText?: string): Promise<boolean>
  connect(threadId?: string, options?: CoreAppServerThreadSwitchOptions): Promise<void>
  switchThread(threadId: string, options?: CoreAppServerThreadSwitchOptions): Promise<void>
  disconnect(): void
  selectSession(id: string): Promise<void>
  createSession(input?: { title?: string; metadata?: Record<string, unknown> }): Promise<CoreSessionListItem | null>
  setSubAgentRecords(threadId: string, records: Record<string, CoreSubAgentDurableRecord>): void
  refreshSessions(): Promise<void>
  send(text?: string): Promise<void>
  stop(): Promise<boolean>
  steer(text: string): Promise<void>
  queueInput(text: string): Promise<void>
  respondApproval(requestId: string, decision: string, guidance?: string): Promise<void>
  loadCommandCatalog(): Promise<boolean>
  setTurnOptionsProvider(provider: () => Record<string, unknown> | Promise<Record<string, unknown>>): void
  setShallowThinking(value: boolean): void
  setComposerCallbacks(callbacks: WorkbenchComposerCallbacks): void
  startTurn(
    threadId: string,
    input: CoreInputItem[],
    workRoot?: string,
    options?: Record<string, unknown>,
    clientMessageId?: string,
  ): Promise<void>
  interruptTurn(threadId: string, turnId?: string): Promise<void>
  forceResetTurn(threadId: string, turnId?: string): Promise<void>
  steerTurn(threadId: string, turnId: string, input: CoreInputItem[]): Promise<CoreSteerOutcome>
  updateQueueInput(threadId: string, itemId: string, text: string): Promise<void>
  deleteQueueInput(threadId: string, itemId: string): Promise<void>
  guideQueueInput(threadId: string, turnId: string, itemId: string, text?: string): Promise<{ applied: boolean; reason: string }>
  listCommands(workRoot?: string): Promise<unknown[]>
  executeCommand(threadId: string, command: string, workRoot?: string, argumentsText?: string): Promise<Record<string, unknown>>
  request(request: TransportHttpRequest): Promise<TransportHttpResponse>
  requestRpc(method: string, params?: Record<string, unknown>, timeoutMs?: number): Promise<Record<string, unknown>>
  requestJson<TResponse = unknown>(path: string, init?: RequestInit): Promise<TResponse>
  close(): void
}
