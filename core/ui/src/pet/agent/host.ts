/**
 * 会话路由与流式会话通道。
 *
 * user:“桌宠绑定与 Ping 绑定是两套独立会话路由”+
 * (每只桌宠有自己的默认项目+会话、可右键临时切换；Ping 通路独立维护目标。
 *  每个会话一个通道，通道复用主工作台的运行时控制器，所以流式更新、排队、
 *  审批回执都走 Sunday 原有实现，而不是简化版聊天。)
 */
import { computed, reactive, shallowRef, type ComputedRef, type Ref } from 'vue'
import { CoreAppServerClient } from '@/appServer/client.ts'
import type { CoreAppEvent, CoreAppSnapshot } from '@/appServer/protocol.ts'
import {
  createCoreAppServerRuntimeController,
  createCoreAppServerRuntimeState,
} from '@/appServer/store.ts'
import { selectTurnControl } from '@/appServer/selectors.ts'
import {
  selectLatestActiveTurnId,
} from '@/appServer/workbenchProjection.ts'
import { lockedMessageIdsBeforeCompaction } from '@/appServer/messageParts.ts'
import { selectVisiblePendingDecisions, type CorePendingDecision } from '@/appServer/pendingDecisions.ts'
import { type CoreDecisionSelectionPayload } from '@/appServer/workbenchActions.ts'
import { buildCoreComposerInputItems } from '@/composer/inputItems.ts'
import { useCoreApprovalController, type CoreApprovalHandlingResult } from '@/composables/useCoreApprovalController.ts'
import { useCoreWorkbenchProjectionController } from '@/composables/useCoreWorkbenchProjectionController.ts'
import { isInternalSessionId } from '@/sessions/visibility.ts'
import type { CoreInputItem, CoreMessage } from '@/types.ts'
import type { PetAgentClient } from './client.ts'

export interface SessionBinding {
  projectId: string | null
  sessionId: string | null
  /** 右键临时切换：只在本次运行有效，不落盘。 */
  temporaryProjectId?: string | null
  temporarySessionId?: string | null
}

export interface PetBindingsState {
  /** 每只宠物一个持久绑定；temporary* 只在本次运行有效，不落盘。 */
  pets: Record<string, SessionBinding>
  /** Ping 通路独立目标（工程决策：显式选择默认持久，便于下次继续）。 */
  ping: { projectId: string | null; sessionId: string | null }
}

export function emptyBindings(): PetBindingsState {
  return { pets: {}, ping: { projectId: null, sessionId: null } }
}

export interface SendResult {
  /** Ping 只走「开始新回合 / 引导当前回合」，永远不排队。 */
  status: 'started' | 'guided' | 'ignored'
  message: string
}

/** 审批提交中的请求集合在共享审批控制器装配前给投影控制器兜底（恒空）。 */
const EMPTY_SUBMITTING_REQUEST_IDS: Set<string> = new Set<string>()

export class SessionChannel {
  readonly sessionId: string
  readonly projectId: string | null
  workRoot: string | undefined
  private readonly runtime = reactive(createCoreAppServerRuntimeState()) as ReturnType<typeof createCoreAppServerRuntimeState> & { state: CoreAppSnapshot | null }
  private readonly controller: ReturnType<typeof createCoreAppServerRuntimeController>
  private opened = false
  private opening: Promise<void> | null = null
  lastError = ''
  /** 当前连接的 App Server 客户端（分叉/回退等通用 RPC 的入口）。 */
  private wireClient: CoreAppServerClient | null = null
  private readonly projection: ReturnType<typeof useCoreWorkbenchProjectionController>
  private readonly approval = shallowRef<ReturnType<typeof useCoreApprovalController> | null>(null)

  constructor(private readonly client: PetAgentClient, options: {
    sessionId: string
    projectId: string | null
    workRoot?: string
  }) {
    this.sessionId = options.sessionId
    this.projectId = options.projectId
    this.workRoot = options.workRoot
    this.controller = createCoreAppServerRuntimeController(this.runtime as never, {
      createClient: ({ onEvent, onSnapshot, onSyncChange, onConnectionState }) => {
        const transport = this.client.transport.fork ? this.client.transport.fork() : this.client.transport
        const created = new CoreAppServerClient({
          transport,
          clientInfo: { name: 'sunday_pet', title: 'Sunday 桌宠', version: '1.0.0' },
          onEvent: (event: CoreAppEvent) => onEvent(event),
          onSnapshot: (snapshot) => onSnapshot(snapshot as never),
          onSyncChange,
          onConnectionState,
        })
        this.wireClient = created
        return created
      },
    })
    // user:“全部都不要新建，样式待会单独说明，现在先去给其他的对齐”
    // +(通道的消息投影与审批处理改用主内容区同一套共享实现：
    //   useCoreWorkbenchProjectionController 提供窗口化消息、过程展开记忆与
    //   回合结束收起语义；useCoreApprovalController 提供共享决策映射、重复
    //   提交去重与通道可用性检查——卡片与主界面只有一份行为。)
    this.projection = useCoreWorkbenchProjectionController({
      snapshot: computed(() => (this.runtime.state as CoreAppSnapshot | null) ?? undefined),
      activeThreadId: computed(() => this.sessionId),
      status: computed(() => String((this.runtime.state as CoreAppSnapshot | null)?.status || 'idle')),
      submittingApprovalRequestIds: computed<Set<string>>(() => this.approval.value?.submittingRequestIds.value || EMPTY_SUBMITTING_REQUEST_IDS),
      shallowThinkingPending: computed(() => false),
    })
    this.approval.value = useCoreApprovalController({
      messages: this.projection.messages,
      hasActiveThread: computed(() => Boolean(this.sessionId)),
      canRespondApproval: computed(() => Boolean(this.runtime.client)),
      ensureApprovalChannel: async () => {
        await this.open()
        return true
      },
      respondApproval: (requestId, decision, guidance) => this.respondApproval(requestId, decision, guidance),
      submitText: async (text) => {
        const result = await this.send(text)
        if (result.status === 'ignored') throw new Error(result.message)
      },
      deferText: () => {},
    })
  }

  get snapshot(): CoreAppSnapshot | null {
    return this.runtime.state as CoreAppSnapshot | null
  }

  get connectionState(): string {
    return this.runtime.connectionState
  }

  get ready(): boolean {
    return Boolean(this.runtime.state)
  }

  messages(): Ref<CoreMessage[]> {
    return this.projection.messages
  }

  /** 过程展开集合：与主内容区同一份共享投影状态。 */
  processExpandedIds(): Ref<Set<string>> {
    return this.projection.processExpandedIds
  }

  toggleProcess(messageId: string): void {
    this.projection.toggleProcess(messageId)
  }

  hasMoreHistory(): Ref<boolean> {
    return this.projection.hasMoreHistory
  }

  totalMessages(): Ref<number> {
    return this.projection.totalMessages
  }

  /** 滚动到顶部加载更早消息（与主界面历史窗口化行为一致）。 */
  loadMoreHistory(): void {
    this.projection.loadMoreHistory()
  }

  activeTurnId(): ComputedRef<string> {
    return computed(() => {
      const snapshot = this.runtime.state as CoreAppSnapshot | null
      return snapshot ? selectLatestActiveTurnId(snapshot) : ''
    })
  }

  lockedMessageIds(): ComputedRef<Set<string>> {
    return computed(() => lockedMessageIdsBeforeCompaction(this.projection.messages.value))
  }

  /** 决策提交走共享审批控制器（映射/去重/通道检查与主界面同源）。 */
  handleDecision(payload: CoreDecisionSelectionPayload): Promise<CoreApprovalHandlingResult> {
    const approval = this.approval.value
    if (!approval) throw new Error('审批控制器未就绪')
    return approval.handleDecision(payload)
  }

  get approvalError(): string {
    return this.approval.value?.lastError.value || ''
  }

  decisions(): ComputedRef<CorePendingDecision[]> {
    return computed(() => {
      const snapshot = this.runtime.state as CoreAppSnapshot | null
      if (!snapshot) return []
      const pool = snapshot.interactions || snapshot.decisions || snapshot.core?.interactions
      // 审批池与卡片消息同源：都读共享投影，不再单独选一次消息。
      return selectVisiblePendingDecisions(
        this.projection.messages.value,
        pool,
        { requests: snapshot.core?.requests },
      )
    })
  }

  turnStatus(): ComputedRef<string> {
    return computed(() => String((this.runtime.state as CoreAppSnapshot | null)?.status || 'idle'))
  }

  turnActive(): ComputedRef<boolean> {
    return computed(() => {
      const status = this.turnStatus().value
      return status === 'running' || status === 'waiting' || status === 'interrupting'
    })
  }

  async open(): Promise<void> {
    if (this.opened) return
    if (this.opening) return await this.opening
    this.opening = (async () => {
      try {
        await this.controller.switchThread(this.sessionId, {
          lastSeenSeq: 0,
          includeSnapshot: true,
          preserveState: false,
          attachInBackground: true,
        })
        this.opened = true
        this.lastError = ''
      } catch (error) {
        this.lastError = error instanceof Error ? error.message : String(error)
        throw error
      } finally {
        this.opening = null
      }
    })()
    return await this.opening
  }

  /**
   * 发送一条消息。
   *
   * user:“pin 的所有东西都是按引导进去的，不是按排队进去的”+(Ping 永远不排队：
   * 有进行中的回合就作为引导插进去；没有就开始新回合；引导被拒时明确失败，
   * 绝不落到队列里。)
   */
  async send(
    text: string,
    attachments: CoreInputItem[] = [],
    // user:“输入框缺东西”+(卡片输入参数组与主界面同一套：模型/思考/模式/权限
    // 由 CoreExecutionControls 提供，发送时作为 turnOptions 交给同一条提交路径。)
    turnOptions: Record<string, unknown> = {},
  ): Promise<SendResult> {
    if (!this.opened) await this.open()
    const trimmed = text.trim()
    if (!trimmed && attachments.length === 0) return { status: 'ignored', message: '空消息' }
    const input = buildCoreComposerInputItems(trimmed, attachments, [])
    const status = this.turnStatus().value
    const active = status === 'running' || status === 'waiting' || status === 'interrupting'
    if (!active) {
      await this.controller.startTurn(this.sessionId, input, this.workRoot, turnOptions, undefined)
      return { status: 'started', message: '已发送' }
    }
    // 与 activeTurnId() 用同一个 selector：合并 snapshot.turns 与 core.turns 后按
    // seq 取最新活跃回合，不能依赖对象键的插入顺序。
    const activeTurnId = this.activeTurnId().value
    if (!activeTurnId) return { status: 'ignored', message: '当前任务还没有可引导的回合' }
    const outcome = await this.controller.steerTurn(this.sessionId, activeTurnId, input, undefined)
    if (outcome.applied) return { status: 'guided', message: '已作为引导发送给当前任务' }
    return { status: 'ignored', message: '当前任务暂时无法接收引导（不会排队）' }
  }

  /** 通用 RPC（卡片窗口复用主界面同一批配置接口：模型目录等）。 */
  async requestRpc(method: string, params: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    const client = await this.ensureWireClient()
    return await client.request(method, params)
  }

  /** 审批只回到原请求，绝不本地模拟成功。 */
  async respondApproval(requestId: string, decision: string, guidance = ''): Promise<void> {
    if (!requestId) throw new Error('缺少审批请求编号')
    if (!this.opened) await this.open()
    await this.controller.respondApproval(requestId, decision, guidance)
  }

  async stop(): Promise<void> {
    const snapshot = this.runtime.state as CoreAppSnapshot | null
    const turnId = snapshot ? selectTurnControl(snapshot).turnId : ''
    await this.controller.interruptTurn(this.sessionId, turnId)
  }

  /**
   * 分叉/回退与主界面同一条线协议（session.fork / session.rollback RPC），
   * 由卡片的 fork/回退/编辑入口复用。
   */
  async forkTurn(turnId: string): Promise<string> {
    const client = await this.ensureWireClient()
    const response = await client.request('session.fork', { session_id: this.sessionId, turn_id: turnId })
    return String(response?.session_id || '')
  }

  async rollbackTurn(turnId: string): Promise<void> {
    const client = await this.ensureWireClient()
    await client.request('session.rollback', { session_id: this.sessionId, turn_id: turnId })
    // 与主界面回退后刷新一致：重建连接，重新读取持久化线程。
    this.close()
    await this.open()
  }

  /** 暂停恢复：与主界面「继续运行」同一控制器方法（turn/resume）。 */
  async resumeTurn(input: CoreInputItem[] = []): Promise<void> {
    const snapshot = this.runtime.state as CoreAppSnapshot | null
    const control = snapshot ? selectTurnControl(snapshot) : null
    const lastTurnId = control?.pausedTurnId || control?.turnId || ''
    await this.controller.resumeTurn(this.sessionId, lastTurnId, input as never)
  }

  private async ensureWireClient(): Promise<CoreAppServerClient> {
    if (!this.opened) await this.open()
    const client = this.wireClient
    if (!client) throw new Error('会话通道未建立')
    return client
  }

  close(): void {
    this.controller.disconnect()
    this.opened = false
  }
}

/**
 * 会话路由：桌宠通道与 Ping 通道分开维护，切换任何一边都不影响另一边。
 */
export class PetAgentHost {
  private channels = new Map<string, SessionChannel>()
  readonly bindings: PetBindingsState
  private readonly persist: (bindings: PetBindingsState) => void
  private fallbackSession: { projectId: string; sessionId: string } | null = null
  private pingFallbackSession: { projectId: string; sessionId: string } | null = null
  lastRoute = ''

  constructor(
    private readonly client: PetAgentClient,
    bindings: PetBindingsState = emptyBindings(),
    persist: (bindings: PetBindingsState) => void = () => {},
  ) {
    this.bindings = reactive(bindings) as PetBindingsState
    this.persist = persist
  }

  private save(): void {
    this.persist({
      pets: { ...this.bindings.pets },
      ping: { ...this.bindings.ping },
    })
  }

  channel(projectId: string | null, sessionId: string, workRoot?: string): SessionChannel {
    const existing = this.channels.get(sessionId)
    if (existing) return existing
    const created = new SessionChannel(this.client, { sessionId, projectId, workRoot })
    this.channels.set(sessionId, created)
    void created.open().catch(error => {
      created.lastError = error instanceof Error ? error.message : String(error)
    })
    return created
  }

  get(sessionId: string): SessionChannel | undefined {
    return this.channels.get(sessionId)
  }

  private async fallback(): Promise<{ projectId: string; sessionId: string }> {
    if (this.fallbackSession) return this.fallbackSession
    const created = await this.client.ensureFallbackSession()
    this.fallbackSession = { projectId: created.projectId, sessionId: created.sessionId }
    return this.fallbackSession
  }

  /** Ping 的默认会话：My Project 里的 “ping”（没有才创建一次）。 */
  private async pingFallback(): Promise<{ projectId: string; sessionId: string }> {
    if (this.pingFallbackSession) return this.pingFallbackSession
    const created = await this.client.ensurePingSession()
    this.pingFallbackSession = { projectId: created.projectId, sessionId: created.sessionId }
    return this.pingFallbackSession
  }

  /** 桌宠通道：持久默认 → 右键临时 → 首次兜底（My Project 只建一个）。 */
  async petTarget(petId: string): Promise<{ projectId: string; sessionId: string; source: string }> {
    const binding = this.bindings.pets[petId]
    if (binding?.temporarySessionId) {
      this.lastRoute = `桌宠 ${petId} 临时会话 ${binding.temporarySessionId}`
      return {
        projectId: binding.temporaryProjectId || binding.projectId || '',
        sessionId: binding.temporarySessionId,
        source: 'temporary',
      }
    }
    if (binding?.sessionId) {
      this.lastRoute = `桌宠 ${petId} 默认会话 ${binding.sessionId}`
      return { projectId: binding.projectId || '', sessionId: binding.sessionId, source: 'default' }
    }
    const fallback = await this.fallback()
    this.bindings.pets[petId] = { projectId: fallback.projectId, sessionId: fallback.sessionId }
    this.save()
    this.lastRoute = `桌宠 ${petId} 首次使用，在 My Project 建立默认会话 ${fallback.sessionId}`
    return { ...fallback, source: 'fallback' }
  }

  async petChannel(petId: string): Promise<SessionChannel> {
    const target = await this.petTarget(petId)
    return this.channel(target.projectId || null, target.sessionId)
  }

  /**
   * Ping 通道：持久目标 → 默认 “ping” 会话。
   *
   * user:“在 My project 里建一个新会话作为默认会话，默认会话的名字就叫“ping””+
   * (插件/内部会话不能当目标：历史上存进去的 workflow 会话会被丢弃并重建默认值。
   *  环里切换会话后由调用方写回并持久化。)
   */
  async pingTarget(): Promise<{ projectId: string; sessionId: string; source: string }> {
    if (this.bindings.ping.sessionId && !isInternalSessionId(this.bindings.ping.sessionId)) {
      this.lastRoute = `Ping 目标会话 ${this.bindings.ping.sessionId}`
      return {
        projectId: this.bindings.ping.projectId || '',
        sessionId: this.bindings.ping.sessionId,
        source: 'explicit',
      }
    }
    if (this.bindings.ping.sessionId) {
      // 旧配置里存的是插件会话：清掉，回到默认 “ping”。
      this.bindings.ping = { projectId: null, sessionId: null }
      this.save()
    }
    const fallback = await this.pingFallback()
    this.bindings.ping = { projectId: fallback.projectId, sessionId: fallback.sessionId }
    this.save()
    this.lastRoute = `Ping 默认会话 ${fallback.sessionId}`
    return { ...fallback, source: 'fallback' }
  }

  async pingChannel(): Promise<SessionChannel> {
    const target = await this.pingTarget()
    return this.channel(target.projectId || null, target.sessionId)
  }

  /** 设置持久默认绑定。 */
  setPetDefault(petId: string, projectId: string, sessionId: string): void {
    this.bindings.pets[petId] = { projectId, sessionId }
    this.save()
    this.lastRoute = `桌宠 ${petId} 默认会话改为 ${sessionId}`
  }

  /** 右键临时切换：立即生效，不落盘。 */
  setPetTemporary(petId: string, projectId: string, sessionId: string): void {
    const current = this.bindings.pets[petId] || { projectId: null, sessionId: null }
    this.bindings.pets[petId] = {
      projectId: current.projectId,
      sessionId: current.sessionId,
      temporaryProjectId: projectId,
      temporarySessionId: sessionId,
    }
    this.lastRoute = `桌宠 ${petId} 临时切换到 ${sessionId}（重启恢复默认）`
  }

  clearPetTemporary(petId: string): void {
    const current = this.bindings.pets[petId]
    if (!current) return
    this.bindings.pets[petId] = { projectId: current.projectId, sessionId: current.sessionId }
  }

  setPingTarget(projectId: string, sessionId: string): void {
    this.bindings.ping = { projectId, sessionId }
    this.save()
    this.lastRoute = `Ping 目标会话改为 ${sessionId}`
  }

  close(): void {
    for (const channel of this.channels.values()) channel.close()
    this.channels.clear()
    this.client.close()
  }
}
