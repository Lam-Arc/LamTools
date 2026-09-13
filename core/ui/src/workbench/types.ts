import type { ComputedRef, Ref } from 'vue'
import type {
  CoreAppEvent,
  CoreAppServerRuntimeClient,
  CoreAppSnapshot,
} from '../appServer'
import type { CoreCommandCatalogItem, CoreInputItem, CoreMessage, CoreSessionListItem } from '../types'
import type { useComposerCommandPalette } from '../composables/useComposerCommandPalette'
import type { useCoreApprovalController } from '../composables/useCoreApprovalController'
import type { useCoreLiveComposerController } from '../composables/useCoreLiveComposerController'
import type { useCoreQueuedInputController } from '../composables/useCoreQueuedInputController'
import type { CoreQueuedInput } from '../appServer/workbenchProjection'
import type { LamToolsTransport, TransportHttpRequest, TransportHttpResponse } from '../transport'

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
  getTurnOptions?: () => Record<string, unknown>
  /** Shared UI controls the projection's shallow-thinking state. */
  shallowThinking?: Readonly<Ref<boolean>>
  /** Called when the live composer accepts a submission. */
  onSubmitStart?: () => void
  /** Optional host capability hook for command side effects. */
  onCommandResult?: (result: Record<string, unknown>) => void | Promise<void>
}

export interface WorkbenchComposerCallbacks {
  onError?: (message: string) => void
  onStatusText?: (message: string) => void
  onSubmitStart?: () => void
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
  actionMode: ComputedRef<'send' | 'stop'>
  handleComposerKeydown(event: KeyboardEvent): Promise<boolean>
  handleComposerKeyup(event: KeyboardEvent): Promise<boolean>
  selectCommand(command: CoreCommandCatalogItem): Promise<boolean>
  runCommand(command: string, argumentsText?: string): Promise<boolean>
  connect(threadId?: string): Promise<void>
  switchThread(threadId: string): Promise<void>
  disconnect(): void
  selectSession(id: string): Promise<void>
  createSession(input?: { title?: string; metadata?: Record<string, unknown> }): Promise<CoreSessionListItem | null>
  refreshSessions(): Promise<void>
  send(text?: string): Promise<void>
  stop(): Promise<boolean>
  steer(text: string): Promise<void>
  queueInput(text: string): Promise<void>
  respondApproval(requestId: string, decision: string, guidance?: string): Promise<void>
  loadCommandCatalog(): Promise<boolean>
  setTurnOptionsProvider(provider: () => Record<string, unknown>): void
  setShallowThinking(value: boolean): void
  setComposerCallbacks(callbacks: WorkbenchComposerCallbacks): void
  startTurn(threadId: string, input: CoreInputItem[], workRoot?: string, options?: Record<string, unknown>): Promise<void>
  interruptTurn(threadId: string, turnId?: string): Promise<void>
  forceResetTurn(threadId: string, turnId?: string): Promise<void>
  steerTurn(threadId: string, turnId: string, input: CoreInputItem[]): Promise<void>
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
