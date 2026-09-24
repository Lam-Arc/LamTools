import type {
  CoreAppInputItem,
  CoreAppSnapshot,
  CoreThinkingMode,
  LamToolsTransport,
  TransportConnectionState,
  TransportHttpRequest,
  TransportHttpResponse,
  TransportMessage,
  TransportRequest,
} from '@lamtools/ui'
import {
  CORE_EXECUTION_CONTROLS_STORAGE_KEYS,
  coreThinkingPayload,
  normalizeCoreThinkingMode,
  readStoredCoreThinkingMode,
} from '@lamtools/ui'
import b4a from 'b4a'
import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import { AttachmentRequestError, nativeAttachments, parseMultipartFile, type NativeAttachmentData } from '../native/attachments'
import type { LocalRepository, LocalThread } from '../storage'
import {
  callEmbeddedStudy,
  cancelEmbeddedSundayTurn,
  listEmbeddedSubAgents,
  listenEmbeddedSundayAgentStream,
  respondEmbeddedSubAgentApproval,
  resumeEmbeddedSundayTurn,
  runEmbeddedSundayTurn,
  type RustAgentImage,
  type RustAgentMessage,
  type RustAgentStreamEvent,
  type RustTurnContinuation,
  type RustTurnProgress,
  type RustTurnResult,
} from '../native/rustAgent'
import { StandaloneConfigStore, type StandaloneModel } from './StandaloneConfigStore'
import { StandaloneExtensionsStore } from './StandaloneExtensionsStore'
import { StandaloneArrangeStore } from './StandaloneArrangeStore'
import { createStandaloneProjectClient } from './StandaloneProjectClient'
import { createStandaloneProjectRoutes } from './StandaloneProjectRoutes'
import { searchStandaloneWorkspace } from './StandaloneWorkspaceSearch'
import { exportStandaloneSession } from './StandaloneSessionExport'
import { checkStandaloneUpdate } from './StandaloneUpdate'

type SnapshotWithSession = CoreAppSnapshot & {
  session?: { id: string; title: string; metadata: Record<string, unknown>; created_at: string; updated_at: string }
}

const MAX_MODEL_IMAGE_BYTES = 10 * 1024 * 1024
const MAX_MODEL_IMAGE_TOTAL_BYTES = 20 * 1024 * 1024
const MAX_MODEL_IMAGES = 8
const MODEL_IMAGE_MIME_TYPES = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp'])

type RunAgentTurn = (
  input: Parameters<typeof runEmbeddedSundayTurn>[0],
) => Promise<RustTurnProgress | RustTurnResult>

type ResumeAgentTurn = (
  input: Parameters<typeof resumeEmbeddedSundayTurn>[0],
) => Promise<RustTurnProgress>

type CancelAgentTurn = (turnId: string) => Promise<boolean>
type ListenTurnStage = (handler: (payload: unknown) => void) => Promise<() => void>
type ListenTurnStream = (handler: (payload: unknown) => void) => Promise<() => void>

const stageLabels: Record<string, string> = {
  js_preflight_start: '开始准备请求',
  js_model_lookup_start: '正在读取当前模型',
  js_model_lookup_done: '当前模型已就绪',
  js_snapshot_save_start: '正在保存请求',
  js_snapshot_save_done: '请求已保存',
  js_extensions_ready: '扩展配置已就绪',
  js_model_keys_ready: '模型密钥读取完成',
  js_settings_ready: '运行设置已就绪',
  js_subagent_ready: '子代理配置已就绪',
  js_models_ready: '模型配置已就绪',
  js_study_ready: '场景上下文已就绪',
  js_native_invoking: '正在调用原生运行时',
  js_native_returned: '原生运行时已返回',
  js_native_wait_35s: '界面仍在等待原生运行时（35秒）',
  js_native_wait_125s: '界面仍在等待原生运行时（125秒）',
  trace_listener_unavailable: '原生阶段监听暂不可用',
  native_received: '原生运行时已接收',
  native_registered: '任务已登记',
  native_project_ready: '工作区已就绪',
  native_hooks_ready: '运行钩子已就绪',
  native_mcp_start: '正在准备 MCP',
  native_mcp_ready: 'MCP 已就绪',
  native_mcp_partial: '部分 MCP 服务未能启动，请检查扩展配置',
  native_subagents_ready: '子代理已就绪',
  native_runtime_start: '开始执行代理',
  native_runtime_done: '代理执行结束',
  native_dreaming_done: '后台整理结束',
  runtime_compaction_start: '开始整理上下文',
  runtime_compaction_done: '上下文整理完成',
  runtime_hooks_start: '开始运行钩子',
  runtime_hooks_done: '运行钩子完成',
  runtime_model_start: '开始模型调用',
  runtime_model_done: '模型调用完成',
  http_send_start: '正在发送模型请求',
  http_request_built: '模型请求已构建',
  http_request_build_error: '模型请求构建失败',
  http_waiting_for_headers: '仍在等待模型响应头',
  http_connect_error: '连接模型服务失败',
  http_send_timeout: '等待模型响应超时',
  http_headers_received: '已收到模型响应头',
  http_body_received: '已收到模型响应内容',
  http_streaming: '正在生成回复',
  http_retry_wait: '等待重试模型请求',
  http_transport_error: '模型连接失败',
  http_provider_error: '模型服务返回错误',
}

const MOBILE_PROGRESS_KEY = 'mobile_turn_progress'
const TERMINAL_PROGRESS_MS = 1500

const defaultListenTurnStage: ListenTurnStage = async handler =>
  await listen('sunday-agent-stage', event => handler(event.payload))
const defaultListenTurnStream: ListenTurnStream = listenEmbeddedSundayAgentStream

/** The native Study boundary, injectable so the transport stays testable. */
export type StudyCall = <T = Record<string, unknown>>(
  call: Parameters<typeof callEmbeddedStudy>[0],
) => Promise<T>

export type WorkflowCall = (call: {
  method: string
  params: Record<string, unknown>
  projectId?: string
}) => Promise<Record<string, unknown>>

const callEmbeddedWorkflow: WorkflowCall = async call => await invoke<Record<string, unknown>>(
  'sunday_workflow_rpc', { payload: call },
)

export class StandaloneTransport implements LamToolsTransport {
  private state: TransportConnectionState = 'disconnected'
  private readonly stateListeners = new Set<(state: TransportConnectionState) => void>()
  private readonly messageListeners = new Set<(message: TransportMessage) => void>()
  private readonly aborts = new Map<string, AbortController>()
  private readonly generations = new Map<string, number>()
  private readonly snapshotSaves = new Map<string, Promise<void>>()
  private readonly snapshotRecoveries = new Map<string, Promise<void>>()
  private readonly activeStageListeners = new Map<string, () => void>()
  private readonly activeStreamListeners = new Map<string, () => void>()
  private readonly activeSnapshots = new Map<string, SnapshotWithSession>()
  private connecting: Promise<void> | null = null
  private readonly arrange: StandaloneArrangeStore
  private readonly projectRoutes: ReturnType<typeof createStandaloneProjectRoutes>

  constructor(
    private readonly repository: LocalRepository,
    private readonly config: StandaloneConfigStore = new StandaloneConfigStore(),
    private readonly runAgentTurn: RunAgentTurn = runEmbeddedSundayTurn,
    private readonly extensions: StandaloneExtensionsStore = new StandaloneExtensionsStore(),
    private readonly resumeAgentTurn: ResumeAgentTurn = resumeEmbeddedSundayTurn,
    private readonly callStudy: StudyCall = callEmbeddedStudy,
    private readonly cancelAgentTurn: CancelAgentTurn = cancelEmbeddedSundayTurn,
    private readonly callWorkflow: WorkflowCall = callEmbeddedWorkflow,
    private readonly listenTurnStage: ListenTurnStage = defaultListenTurnStage,
    private readonly listenTurnStream: ListenTurnStream = defaultListenTurnStream,
  ) {
    this.arrange = new StandaloneArrangeStore(repository)
    // Route and client share one implementation so the two access paths cannot
    // drift apart.
    this.projectRoutes = createStandaloneProjectRoutes(createStandaloneProjectClient(repository))
  }

  async connect(): Promise<void> {
    if (this.state === 'connected') return
    if (this.connecting) return await this.connecting
    const connecting = (async () => {
      await this.repository.init()
      const sessions = await this.repository.listSessions()
      await Promise.all(sessions.filter(session => session.status === 'running')
        .map(session => this.recoverOrphanedTurn(session.id)))
      // A WebView restart cancels the orphaned native turn above. Queued user
      // messages are durable and can continue once recovery has settled.
      await Promise.all(sessions.map(session => this.dispatchQueued(session.id)))
      this.setState('connected')
    })()
    this.connecting = connecting
    try { await connecting }
    finally { if (this.connecting === connecting) this.connecting = null }
  }

  async close(): Promise<void> {
    this.generations.clear()
    this.activeSnapshots.clear()
    for (const controller of this.aborts.values()) controller.abort()
    this.aborts.clear()
    for (const stop of this.activeStageListeners.values()) stop()
    for (const stop of this.activeStreamListeners.values()) stop()
    this.setState('disconnected')
  }

  async request<TResponse = unknown>(request: TransportRequest): Promise<TResponse> {
    await this.connect()
    const response = request.kind === 'http'
      ? await this.handleHttp(request)
      : await this.handleRpc(request.method, request.params || {})
    return response as TResponse
  }

  send(): void {}

  subscribe(handler: (message: TransportMessage) => void): () => void {
    this.messageListeners.add(handler)
    return () => this.messageListeners.delete(handler)
  }

  onState(handler: (state: TransportConnectionState) => void): () => void {
    this.stateListeners.add(handler)
    handler(this.state)
    return () => this.stateListeners.delete(handler)
  }

  getState(): TransportConnectionState { return this.state }

  private async handleRpc(method: string, params: Record<string, unknown>): Promise<Record<string, unknown>> {
    const configResult = await this.config.handleRpc(method, params)
    if (configResult) return configResult
    const extensionResult = await this.extensions.handleRpc(method, params)
    if (extensionResult) return extensionResult
    const studyResult = await this.handleStudyRpc(method, params)
    if (studyResult) return studyResult
    if (method.startsWith('workflow.')) return await this.handleWorkflowRpc(method, params)
    const arrangeResult = await this.arrange.handleRpc(method, params)
    if (arrangeResult) return arrangeResult
    if (method === 'workspace.search') return await searchStandaloneWorkspace(this.repository, params)
    if (method === 'update.check') return await checkStandaloneUpdate()
    if (method === 'project.list') {
      return { projects: (await this.repository.listProjects()).map(project => ({
        id: project.id, name: project.name, work_root: project.workRoot || project.path,
      })) }
    }
    if (method === 'project.sessions.list') {
      const projectId = String(params.project_id || '')
      if (!await this.repository.getLocalProject(projectId)) throw new Error('项目不存在')
      return { sessions: await this.repository.listSessions(projectId) }
    }
    if (method === 'initialize') return { protocol_version: 'core.app_server.v1', capabilities: { standalone: true } }
    if (method === 'thread/resume') {
      const threadId = String(params.thread_id || '')
      return { snapshot: await this.snapshotFor(threadId) }
    }
    if (method === 'thread.history') {
      const threadId = String(params.thread_id || '')
      return { snapshot_page: await this.snapshotFor(threadId) }
    }
    if (method === 'command.catalog') throw new Error('移动端独立模式尚不支持命令目录')
    if (method === 'sub_agent.list' || method === 'sub_agent.snapshot') {
      const threadId = String(params.thread_id || params.session_id || '')
      if (!threadId) throw new Error('会话不存在')
      return await listEmbeddedSubAgents(threadId)
    }
    if (method === 'sub_agent.approval.respond') {
      const threadId = String(params.thread_id || params.session_id || params.parent_thread_id || '')
      const name = String(params.name || params.agent_name || '')
      const requestId = String(params.request_id || '')
      if (!threadId || !name || !requestId) throw new Error('子代理审批请求不完整')
      return await respondEmbeddedSubAgentApproval({
        parentThreadId: threadId,
        name,
        requestId,
        decision: normalizeApprovalDecision(params.decision),
        guidance: String(params.guidance || ''),
      })
    }
    if (method === 'turn/start') return await this.startTurn(params)
    if (method === 'approval/respond') return await this.respondApproval(params)
    if (method === 'turn/interrupt' || method === 'turn/force_reset') {
      return await this.interruptTurn(String(params.thread_id || ''))
    }
    if (method.startsWith('queue/') || method === 'turn/steer') return await this.handleQueueRpc(method, params)
    if (method === 'session.permissions.set') {
      const threadId = String(params.thread_id || '')
      const permissionPreset = normalizePermissionPreset(params.permission_preset || params.approval)
      if (!threadId) throw new Error('会话不存在')
      const thread = await this.repository.updateLocalSession(threadId, {
        metadata: { permission_preset: permissionPreset },
      })
      return { ok: true, permission_preset: permissionPreset, session: toRawSession(thread) }
    }
    if (method === 'sync.start') return { ok: false, error: '本地模式无需同步' }
    // An unimplemented method has to fail loudly. Returning a soft `ok:false`
    // let a panel report success while nothing was saved, which is how a missing
    // surface stayed invisible; the desktop answers an unknown method with an
    // error, so the phone does too.
    throw new Error(`移动端独立模式不支持 ${method}`)
  }

  private async handleStudyRpc(method: string, params: Record<string, unknown>): Promise<Record<string, unknown> | null> {
    if (!method.startsWith('study.')) return null
    // Session creation and the selected-node teaching position stay in the
    // host because this transport owns the session store.
    if (method === 'study.session') return await this.openStudySession(params)
    if (method === 'study.current') return await this.selectStudyNode(params)
    if (method === 'study.text.cancel') return { cancelled: false }
    const activeModel = method === 'study.text'
      ? await this.config.activeModel(String(params.model_id || ''))
      : null
    const retryConfig = activeModel ? await this.config.settings('core.modelRetry') : undefined
    return await this.callStudy({
      method,
      params,
      sessionMetadata: await this.studySessionMetadata(params),
      sessionTargets: await this.studySessionTargets(),
      ...(retryConfig ? { retryConfig } : {}),
      ...(activeModel
        ? {
            provider: {
              provider: activeModel.provider,
              model: activeModel.model,
              apiKey: activeModel.apiKey,
            },
          }
        : {}),
    })
  }

  private async handleWorkflowRpc(method: string, params: Record<string, unknown>): Promise<Record<string, unknown>> {
    // The native command receives only a repository-verified project id.
    // Caller-supplied work_root is data and never becomes a filesystem path.
    const sessionId = String(params.session_id || params.thread_id || '')
    const session = sessionId
      ? (await this.repository.listSessions()).find(item => item.id === sessionId)
      : undefined
    if (sessionId && !session) throw new Error('会话不存在')
    const sessionProjectId = String(session?.metadata?.project_id || '')
    const requestedProjectId = String(params.project_id || params.projectId || '')
    if (sessionProjectId && requestedProjectId && sessionProjectId !== requestedProjectId) {
      throw new Error('工作流项目与会话不匹配')
    }
    const projectId = sessionProjectId || requestedProjectId
    if (projectId && !(await this.repository.getLocalProject(projectId))) throw new Error('项目不存在')
    return await this.callWorkflow({ method, params, ...(projectId ? { projectId } : {}) })
  }

  /** Host-owned Study session metadata; never taken from the request payload. */
  private async studySessionMetadata(
    params: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const sessionId = String(params.session_id || params.thread_id || '')
    if (!sessionId) return {}
    const threads = await this.repository.listSessions()
    return threads.find(thread => thread.id === sessionId)?.metadata || {}
  }

  /**
   * Pinnable Study sessions, resolved from this device's own session store.
   *
   * `study.pin` stores only stable ids and projects the titles at read time,
   * so a rename never leaves stale text behind.
   */
  private async studySessionTargets(): Promise<Record<string, { id: string; title: string }>> {
    const threads = await this.repository.listSessions()
    const targets: Record<string, { id: string; title: string }> = {}
    for (const thread of threads) {
      const metadata = thread.metadata || {}
      if (metadata.owner_plugin !== 'study') continue
      targets[thread.id] = { id: thread.id, title: thread.title || thread.id }
    }
    return targets
  }

  private async openStudySession(params: Record<string, unknown>): Promise<Record<string, unknown>> {
    const kind = String(params.scope || params.kind || 'map').trim().toLowerCase()
    if (!['map', 'notes', 'node'].includes(kind)) {
      throw new Error('Study session scope must be map, notes or node')
    }
    let subjectId = String(params.node_id || params.id || (kind === 'notes' ? 'notes' : 'map'))
    let nodeName = ''
    if (kind === 'node') {
      if (!subjectId || subjectId.length > 512 || /[\u0000-\u001f]/.test(subjectId)) {
        throw new Error('Invalid Study node id')
      }
      const node = await this.callStudy<{ node?: Record<string, unknown> }>({
        method: 'study.get',
        params: { node_id: subjectId },
      })
      const payload = (node.node || {}) as Record<string, unknown>
      if (payload.deleted_at) throw new Error(`Unknown node: ${subjectId}`)
      if (payload.learnable === false) throw new Error('GROUP_HAS_NO_SESSION')
      nodeName = String(payload.name || '')
    } else {
      subjectId = kind === 'notes' ? 'notes' : 'map'
    }

    const sessions = await this.repository.listSessions()
    let session = sessions.find(candidate => {
      const metadata = candidate.metadata || {}
      return metadata.owner_plugin === 'study'
        && metadata.study_scope === kind
        && String(metadata.study_node_id || (kind === 'notes' ? 'notes' : 'map')) === subjectId
    })
    let created = false
    if (!session) {
      const title = kind === 'notes' ? '学习笔记' : kind === 'node' ? `学习 · ${nodeName}` : '知识图谱'
      session = await this.repository.createLocalSession(undefined, title)
      session = await this.repository.updateLocalSession(session.id, {
        metadata: {
          owner_plugin: 'study',
          plugin_id: 'study',
          resource_type: 'study_session',
          resource_id: subjectId,
          study_scope: kind,
          ...(kind === 'node' ? { study_node_id: subjectId, study_node_name: nodeName } : {}),
          resource_work_root: '',
          project_independent: true,
        },
      })
      created = true
    }
    await this.callStudy({
      method: 'study.binding.ensure',
      params: {
        kind,
        session_id: session.id,
        ...(kind === 'node' ? { node_id: subjectId } : {}),
        replace_primary: params.replace_primary === true,
      },
    })
    return {
      session_id: session.id,
      scope: kind,
      node_id: kind === 'node' ? subjectId : undefined,
      ...(created && kind === 'node'
        ? { draft_prefill: `我想学 ${nodeName}，给我讲一下`, draft_prefill_only_if_empty: true }
        : {}),
    }
  }

  private async selectStudyNode(params: Record<string, unknown>): Promise<Record<string, unknown>> {
    const nodeId = String(params.node_id || '')
    const result = await this.callStudy<{ current?: Record<string, unknown> | null }>({
      method: 'study.current',
      params: { node_id: nodeId },
    })
    if (nodeId) {
      // The mutable teaching position belongs to the single map session, not
      // to mastery evidence.
      const primary = await this.callStudy<{ binding?: { session_id?: string } | null }>({
        method: 'study.binding.primary',
        params: { kind: 'map' },
      })
      const sessionId = String(primary.binding?.session_id || '')
      if (sessionId) {
        const current = (result.current || {}) as Record<string, unknown>
        await this.repository.updateLocalSession(sessionId, {
          metadata: {
            study_node_id: nodeId,
            study_node_name: String(current.name || ''),
            study_teaching_position:
              isRecord(params.teaching_position) && Object.keys(params.teaching_position).length
                ? params.teaching_position
                : { node_id: nodeId },
          },
        })
      }
    }
    return result
  }

  private async handleHttp(request: TransportHttpRequest): Promise<TransportHttpResponse> {
    const url = new URL(request.path, 'http://localhost')
    const segments = url.pathname.split('/').filter(Boolean)
    if (url.pathname === '/sessions' && request.method === 'GET') {
      return jsonResponse(await this.repository.listSessions())
    }
    if (url.pathname === '/sessions' && request.method === 'POST') {
      const body = decodeJson(request.body)
      const metadata = isRecord(body.metadata) ? body.metadata : {}
      const projectId = typeof metadata.project_id === 'string' ? metadata.project_id : undefined
      const thread = await this.repository.createLocalSession(projectId, String(body.title || '新会话'))
      return jsonResponse(toRawSession(thread), 201)
    }
    if (segments[0] === 'sessions' && segments[1]) {
      const threadId = decodeURIComponent(segments[1])
      if (segments.length === 3 && segments[2] === 'export' && request.method === 'POST') {
        return await exportStandaloneSession(this.repository, threadId, decodeJson(request.body))
      }
      if (segments.length === 2 && request.method === 'PATCH') {
        const body = decodeJson(request.body)
        const thread = await this.repository.updateLocalSession(threadId, {
          title: typeof body.title === 'string' ? body.title : undefined,
          metadata: isRecord(body.metadata) ? body.metadata : undefined,
          status: typeof body.status === 'string' ? body.status : undefined,
        })
        return jsonResponse(toRawSession(thread))
      }
      if (segments.length === 2 && request.method === 'DELETE') {
        await this.repository.deleteLocalSession(threadId)
        return jsonResponse({}, 204)
      }
      if (segments.length === 3 && segments[2] === 'attachments') {
        if (!await this.repository.listSessions().then(sessions => sessions.some(session => session.id === threadId))) {
          return jsonResponse({ error: '会话不存在' }, 404)
        }
        try {
          if (request.method === 'POST') {
            const contentType = Object.entries(request.headers || {})
              .find(([name]) => name.toLowerCase() === 'content-type')?.[1]
            const file = parseMultipartFile(request.body, contentType)
            const metadata = await nativeAttachments.save({ sessionId: threadId, ...file })
            return jsonResponse(metadata, 201)
          }
          if (request.method === 'GET') return jsonResponse(await nativeAttachments.list(threadId))
        } catch (error) { return attachmentErrorResponse(error) }
      }
    }
    if (segments[0] === 'attachments' && segments[1] && segments.length <= 3) {
      const id = decodeURIComponent(segments[1])
      try {
        if (segments.length === 2 && request.method === 'GET') {
          return jsonResponse((await nativeAttachments.read(id)).metadata)
        }
        if (segments.length === 2 && request.method === 'DELETE') {
          return (await nativeAttachments.delete(id))
            ? jsonResponse({}, 204) : jsonResponse({ error: '附件不存在' }, 404)
        }
        if (segments[2] === 'download' && request.method === 'GET') {
          const { metadata, bytes } = await nativeAttachments.read(id)
          return {
            status: 200,
            headers: {
              'Content-Type': metadata.mime_type,
              'Content-Disposition': `attachment; filename*=UTF-8''${encodeRfc5987Value(metadata.filename)}`,
            },
            body: bytes,
          }
        }
        if (segments[2] === 'preview' && request.method === 'GET') {
          const attachment = await nativeAttachments.read(id)
          return jsonResponse({
            id: attachment.metadata.id,
            filename: attachment.metadata.filename,
            preview_type: attachment.metadata.preview_type,
            mime_type: attachment.metadata.mime_type,
            text: attachment.metadata.preview_type === 'text' ? decodeAttachmentText(attachment) : null,
          })
        }
        if (segments[2] === 'open' && request.method === 'POST') {
          await nativeAttachments.open(id)
          return jsonResponse({ opened: true })
        }
      } catch (error) { return attachmentErrorResponse(error) }
    }
    const projectResponse = await this.projectRoutes(request)
    if (projectResponse) return projectResponse
    return jsonResponse({ error: '设备拒绝了您的请求' }, 403)
  }

  private async handleQueueRpc(method: string, params: Record<string, unknown>): Promise<Record<string, unknown>> {
    const threadId = String(params.thread_id || '')
    if (!threadId) throw new Error('会话不存在')
    const snapshot = this.activeSnapshots.get(threadId) || await this.snapshotFor(threadId)
    const active = Object.values(snapshot.core?.turns || {}).find(turn => turn.status === 'running' || turn.status === 'waiting')
    const queue = snapshot.queue || (snapshot.queue = [])
    const queueItemId = String(params.queue_item_id || '')
    const item = queue.find(value => value.queue_item_id === queueItemId && value.status === 'queued')
    if (method === 'queue/create' || method === 'turn/steer') {
      const input = Array.isArray(params.input) ? params.input as CoreAppInputItem[] : []
      if (!input.length) throw new Error('发送内容不能为空')
      if (method === 'turn/steer' && (!active || active.turn_id !== params.turn_id)) throw new Error('当前轮次已结束，无法引导')
      if (!active && method === 'queue/create') return await this.startTurn(params)
      const queued = {
        queue_item_id: globalThis.crypto?.randomUUID?.() || `queue-${Date.now()}`,
        status: 'queued', mode: method === 'turn/steer' ? 'steer_after_turn' : 'next_turn',
        input, created_at: new Date().toISOString(),
        runtime_options: { ...params, input: undefined, thread_id: undefined, turn_id: undefined },
      }
      if (method === 'turn/steer') queue.unshift(queued)
      else queue.push(queued)
      await this.saveSnapshot(snapshot)
      this.emitSnapshot(snapshot)
      return {
        snapshot, queue_item_id: queued.queue_item_id,
        ...(method === 'turn/steer' ? { applied: false, queued: true, reason: 'native_turn_cannot_steer_live' } : {}),
      }
    }
    if (method === 'queue/update') {
      if (!item) throw new Error('排队消息不存在')
      const text = String(params.text || '').trim()
      if (!text) throw new Error('排队消息不能为空')
      item.input = [{ type: 'text', text }]
    } else if (method === 'queue/delete') {
      if (!item) throw new Error('排队消息不存在')
      snapshot.queue = queue.filter(value => value.queue_item_id !== queueItemId)
    } else if (method === 'queue/guide') {
      if (!item || !active || active.turn_id !== params.turn_id) {
        return { applied: false, reason: 'queue_item_or_active_turn_unavailable', snapshot }
      }
      if (String(params.text || '').trim()) item.input = [{ type: 'text', text: String(params.text).trim() }]
      item.mode = 'steer_after_turn'
      snapshot.queue = [item, ...queue.filter(value => value !== item)]
      await this.saveSnapshot(snapshot)
      this.emitSnapshot(snapshot)
      return { applied: false, queued: true, reason: 'native_turn_cannot_steer_live', snapshot }
    } else throw new Error(`本机模式不支持 ${method}`)
    await this.saveSnapshot(snapshot)
    this.emitSnapshot(snapshot)
    return { snapshot }
  }

  private async dispatchQueued(threadId: string): Promise<void> {
    const snapshot = this.activeSnapshots.get(threadId) || await this.snapshotFor(threadId)
    const next = snapshot.queue?.find(item => item.status === 'queued')
    if (!next) return
    snapshot.queue = snapshot.queue?.filter(item => item.queue_item_id !== next.queue_item_id) || []
    await this.saveSnapshot(snapshot)
    this.emitSnapshot(snapshot)
    try {
      const options = isRecord(next.runtime_options) ? next.runtime_options : {}
      await this.startTurn({ ...options, thread_id: threadId, input: next.input })
    } catch (error) {
      // Keep the message available for editing/retry if a model or native
      // invocation fails before a turn was accepted.
      const latest = await this.snapshotFor(threadId)
      latest.queue = [next, ...(latest.queue || [])]
      await this.saveSnapshot(latest)
      this.emitSnapshot(latest)
      console.error('Failed to dispatch standalone queue item', error)
    }
  }

  private async startTurn(params: Record<string, unknown>): Promise<Record<string, unknown>> {
    const threadId = String(params.thread_id || '')
    if (!threadId) throw new Error('会话不存在')
    const prior = this.activeSnapshots.get(threadId) || await this.snapshotFor(threadId)
    if (Object.values(prior.core?.turns || {}).some(turn => turn.status === 'running' || turn.status === 'waiting')) {
      throw new Error('当前会话仍在运行，请使用排队发送')
    }
    const generation = (this.generations.get(threadId) || 0) + 1
    this.generations.set(threadId, generation)
    if (this.generations.get(threadId) !== generation) throw new Error('操作已取消')
    const input = Array.isArray(params.input) ? params.input as CoreAppInputItem[] : []
    const currentMessage = await inputMessage(input, threadId)
    const priorHistory = await conversationMessages(prior)
    if (this.generations.get(threadId) !== generation) throw new Error('操作已取消')
    const modelHistory = [...priorHistory, ...(currentMessage ? [currentMessage] : [])]
    validateConversationImageBudget(modelHistory)
    const snapshot = prior
    this.activeSnapshots.set(threadId, snapshot)
    const turnId = globalThis.crypto?.randomUUID?.() || `turn-${Date.now()}`
    const userItemId = `${turnId}:user`
    const assistantItemId = `${turnId}:assistant`
    let activeModel = null as Awaited<ReturnType<StandaloneConfigStore['activeModel']>> | null
    if (this.generations.get(threadId) !== generation) throw new Error('操作已取消')
    const reasoningLevel = resolveReasoningLevel(params.reasoning_level, null)
    const permissionPreset = normalizePermissionPreset(
      params.permission_preset
        || snapshot.session?.metadata?.permission_preset
        || (params.approval_policy === 'auto_approve' ? 'auto' : 'ask'),
    )
    const sessionApprovedTools = stringArray(snapshot.session?.metadata?.session_approved_tools)
    const sequence = Number(snapshot.snapshot_seq || 0) + 1
    const core = snapshot.core!
    core.turns = {
      ...(core.turns || {}),
      [turnId]: {
        turn_id: turnId,
        status: 'running',
        items: [userItemId, assistantItemId],
        seq: sequence,
        created_at: new Date().toISOString(),
        runtime_snapshot: {
          ...(activeModel ? {
            model_id: activeModel.model.model_id,
            model_record_id: activeModel.model.id,
          } : {}),
          ...(params.active_mode ? { active_mode: String(params.active_mode) } : {}),
          reasoning_level: reasoningLevel,
          ...(activeModel?.model.thinking_budget != null
            ? { thinking_budget: activeModel.model.thinking_budget } : {}),
          ...((finiteNumber(params.max_tokens) ?? activeModel?.model.max_output_tokens) != null
            ? { max_tokens: finiteNumber(params.max_tokens) ?? activeModel?.model.max_output_tokens } : {}),
          ...((finiteNumber(params.temperature) ?? activeModel?.model.temperature) != null
            ? { temperature: finiteNumber(params.temperature) ?? activeModel?.model.temperature } : {}),
          permission_preset: permissionPreset,
          session_approved_tools: sessionApprovedTools,
        },
      },
    }
    core.items = {
      ...(core.items || {}),
      [userItemId]: {
        item_id: userItemId,
        turn_id: turnId,
        kind: 'message',
        type: 'userMessage',
        status: 'completed',
        seq: sequence,
        payload: { type: 'userMessage', content: input },
      },
      [assistantItemId]: {
        item_id: assistantItemId,
        turn_id: turnId,
        kind: 'message',
        type: 'agentMessage',
        status: 'running',
        seq: sequence + 1,
        payload: { type: 'agentMessage', content: '' },
      },
    }
    core.item_order = [...(core.item_order || []), userItemId, assistantItemId]
    core.status = 'running'
    snapshot.status = 'running'
    snapshot.snapshot_seq = sequence + 1
    core.snapshot_seq = snapshot.snapshot_seq
    snapshot.revision = Number(snapshot.revision || 0) + 1
    core.revision = snapshot.revision
    const trace = await this.startTurnTrace(snapshot, turnId, assistantItemId, generation)
    {
      trace.record('js_model_lookup_start')
      this.emitSnapshot(snapshot)
      try {
        activeModel = await this.config.activeModel(String(params.model_id || ''))
        trace.record('js_model_lookup_done')
        if (this.generations.get(threadId) !== generation) throw new Error('操作已取消')
        const runtimeSnapshot = core.turns[turnId].runtime_snapshot as Record<string, unknown>
        runtimeSnapshot.model_id = activeModel.model.model_id
        runtimeSnapshot.model_record_id = activeModel.model.id
        // Refine the level once the model's thinking capability is known.
        runtimeSnapshot.reasoning_level = resolveReasoningLevel(params.reasoning_level, activeModel.model)
        if (activeModel.model.thinking_budget != null) runtimeSnapshot.thinking_budget = activeModel.model.thinking_budget
        if (runtimeSnapshot.max_tokens == null && activeModel.model.max_output_tokens != null) {
          runtimeSnapshot.max_tokens = activeModel.model.max_output_tokens
        }
        if (runtimeSnapshot.temperature == null && activeModel.model.temperature != null) {
          runtimeSnapshot.temperature = activeModel.model.temperature
        }
        trace.record('js_snapshot_save_start')
        await this.saveSnapshot(snapshot)
        trace.record('js_snapshot_save_done')
      } catch (error) {
        await trace.stop()
        if (this.generations.get(threadId) === generation) {
          this.finishSnapshot(snapshot, turnId, assistantItemId, {
            text: error instanceof Error ? error.message : String(error), runtimeModelId: '', toolRounds: 0,
          }, 'failed')
          void this.publishBackgroundSnapshot(snapshot, generation)
          this.activeSnapshots.delete(threadId)
        }
        throw error
      }
    }
    if (this.generations.get(threadId) !== generation) throw new Error('操作已取消')
    this.emitSnapshot(snapshot)

    void this.completeTurn(snapshot, turnId, assistantItemId, activeModel!, generation, trace, modelHistory)
      .catch(error => console.error('Failed to complete standalone turn', error))
    return { accepted: true, turn_id: turnId, revision: snapshot.revision }
  }

  private async completeTurn(
    snapshot: SnapshotWithSession,
    turnId: string,
    assistantItemId: string,
    activeModel: Awaited<ReturnType<StandaloneConfigStore['activeModel']>>,
    generation: number,
    existingTrace?: { record: (stage: string) => void; stop: () => Promise<void> },
    preparedHistory?: RustAgentMessage[],
  ): Promise<void> {
    const threadId = snapshot.thread_id
    const controller = new AbortController()
    this.aborts.set(threadId, controller)
    const trace = existingTrace || await this.startTurnTrace(snapshot, turnId, assistantItemId, generation)
    try {
      const answer = asTurnProgress(await this.requestModel(
        snapshot, turnId, activeModel, controller.signal, trace.record, preparedHistory,
      ))
      await trace.stop()
      if (this.generations.get(threadId) !== generation) return
      if (answer.status === 'completed') {
        this.finishSnapshot(snapshot, turnId, assistantItemId, answer.result, 'completed')
        await this.persistSessionApprovals(snapshot, answer.result)
        if (this.generations.get(threadId) !== generation) return
        await this.persistRuntimeState(snapshot, turnId, answer.result)
        if (this.generations.get(threadId) !== generation) return
      } else {
        this.pauseForApproval(snapshot, turnId, assistantItemId, answer)
      }
    } catch (error) {
      await trace.stop()
      if (this.generations.get(threadId) !== generation) return
      const message = error instanceof Error ? error.message : String(error)
      this.finishSnapshot(
        snapshot,
        turnId,
        assistantItemId,
        { text: message, runtimeModelId: '', toolRounds: 0 },
        controller.signal.aborted || isNativeCancellationError(message) ? 'cancelled' : 'failed',
      )
    } finally {
      await trace.stop()
      if (this.aborts.get(threadId) === controller) this.aborts.delete(threadId)
    }
    if (this.generations.get(threadId) !== generation) return
    await this.publishBackgroundSnapshot(snapshot, generation)
    if (snapshot.status !== 'running' && snapshot.status !== 'waiting') {
      this.activeSnapshots.delete(threadId)
      await this.dispatchQueued(threadId)
    }
  }

  private pauseForApproval(
    snapshot: SnapshotWithSession,
    turnId: string,
    assistantItemId: string,
    progress: Extract<RustTurnProgress, { status: 'approval_required' }>,
  ): void {
    const core = snapshot.core!
    const requestId = progress.request.requestId
    const approvalItemId = `${requestId}:item`
    const turn = core.turns?.[turnId]
    const assistant = core.items?.[assistantItemId]
    if (assistant) {
      assistant.status = 'running'
      assistant.metadata = {
        ...(isRecord(assistant.metadata) ? assistant.metadata : {}),
        [MOBILE_PROGRESS_KEY]: { stage: 'approval_wait', label: '等待确认', status: 'running' },
      }
    }
    if (turn) {
      turn.status = 'waiting'
      turn.last_kind = 'approval_request'
      turn.items = [...(turn.items || []).filter(id => id !== approvalItemId), approvalItemId]
    }
    core.items = {
      ...(core.items || {}),
      [approvalItemId]: {
        item_id: approvalItemId,
        turn_id: turnId,
        kind: 'approval_request',
        type: 'serverRequest',
        status: 'waiting',
        seq: Number(assistant?.seq || 0) + 1,
        payload: {
          type: 'serverRequest',
          request_id: requestId,
          tool_name: progress.request.toolCall.name,
          question: progress.request.message,
          description: progress.request.message,
          arguments: progress.request.toolCall.arguments || {},
          options: [
            { id: 'approve_once', label: '允许一次' },
            { id: 'approve_for_session', label: '本会话允许' },
            { id: 'deny', label: '拒绝' },
          ],
        },
      },
    }
    core.item_order = [...(core.item_order || []).filter(id => id !== approvalItemId), approvalItemId]
    core.requests = {
      ...(core.requests || {}),
      [requestId]: {
        request_id: requestId,
        status: 'open',
        item_id: approvalItemId,
        turn_id: turnId,
        assistant_item_id: assistantItemId,
        model_record_id: progress.continuation.modelRecordId,
        project_id: String(snapshot.session?.metadata?.project_id || ''),
        continuation: withoutTransientImageBytes(progress.continuation),
      } as any,
    }
    core.status = 'waiting'
    snapshot.status = 'waiting'
    snapshot.snapshot_seq = Number(snapshot.snapshot_seq || 0) + 1
    core.snapshot_seq = snapshot.snapshot_seq
    snapshot.revision = Number(snapshot.revision || 0) + 1
    core.revision = snapshot.revision
  }

  private async persistSessionApprovals(
    snapshot: SnapshotWithSession,
    result: RustTurnResult,
  ): Promise<void> {
    const tools = stringArray(result.sessionApprovedTools)
    if (!tools.length) return
    snapshot.session = snapshot.session
      ? { ...snapshot.session, metadata: { ...snapshot.session.metadata, session_approved_tools: tools } }
      : snapshot.session
    await this.repository.updateLocalSession(snapshot.thread_id, {
      metadata: { session_approved_tools: tools },
    })
  }

  private async persistRuntimeState(
    snapshot: SnapshotWithSession,
    turnId: string,
    result: RustTurnResult,
  ): Promise<void> {
    if (!Array.isArray(result.runtimeHistory) || !result.runtimeHistory.length) return
    const metadata = {
      rust_runtime_history: jsonClone(withoutTransientImageBytes(result.runtimeHistory)),
      rust_runtime_history_turn_id: turnId,
      ...(result.compaction ? { rust_compaction: jsonClone(result.compaction) } : {}),
    }
    snapshot.session = snapshot.session
      ? { ...snapshot.session, metadata: { ...snapshot.session.metadata, ...metadata } }
      : snapshot.session
    await this.repository.updateLocalSession(snapshot.thread_id, { metadata })
  }

  private async respondApproval(params: Record<string, unknown>): Promise<Record<string, unknown>> {
    const threadId = String(params.thread_id || '')
    const requestId = String(params.request_id || '')
    if (!threadId || !requestId) throw new Error('审批请求不完整')
    const snapshot = this.activeSnapshots.get(threadId) || await this.snapshotFor(threadId)
    this.activeSnapshots.set(threadId, snapshot)
    const core = snapshot.core!
    const request = core.requests?.[requestId] as Record<string, any> | undefined
    if (!request || request.status !== 'open') throw new Error('审批请求已失效')
    const continuation = request.continuation as RustTurnContinuation | undefined
    if (!continuation) throw new Error('审批续传状态不存在')
    const decision = normalizeApprovalDecision(params.decision)
    const guidance = String(params.guidance || '')
    const turnId = String(request.turn_id || continuation.turnId || '')
    const assistantItemId = String(request.assistant_item_id || `${turnId}:assistant`)
    const approvalItemId = String(request.item_id || '')
    const generation = (this.generations.get(threadId) || 0) + 1
    this.generations.set(threadId, generation)
    const activeModel = await this.config.activeModel(String(request.model_record_id || continuation.modelRecordId))
    if (this.generations.get(threadId) !== generation) {
      throw new Error('审批请求已失效')
    }
    request.status = 'resolved'
    request.response = { decision, guidance }
    const approvalItem = core.items?.[approvalItemId]
    if (approvalItem) {
      approvalItem.status = 'completed'
      approvalItem.payload = {
        ...(isRecord(approvalItem.payload) ? approvalItem.payload : {}),
        response: { decision, guidance },
      }
    }
    const turn = core.turns?.[turnId]
    if (turn) turn.status = 'running'
    core.status = 'running'
    snapshot.status = 'running'
    snapshot.snapshot_seq = Number(snapshot.snapshot_seq || 0) + 1
    core.snapshot_seq = snapshot.snapshot_seq
    snapshot.revision = Number(snapshot.revision || 0) + 1
    core.revision = snapshot.revision
    await this.saveSnapshot(snapshot)
    if (this.generations.get(threadId) !== generation) {
      throw new Error('审批请求已失效')
    }
    this.emitSnapshot(snapshot)

    const projectId = String(request.project_id || snapshot.session?.metadata?.project_id || '')
    const workspaceId = projectId || `session-${threadId.replace(/[^a-zA-Z0-9_-]+/g, '-')}`
    void this.resumeApproval(
      snapshot,
      turnId,
      assistantItemId,
      activeModel,
      workspaceId,
      continuation,
      requestId,
      decision,
      guidance,
      generation,
    ).catch(error => console.error('Failed to resume standalone turn', error))
    return { accepted: true, request_id: requestId, snapshot }
  }

  private async resumeApproval(
    snapshot: SnapshotWithSession,
    turnId: string,
    assistantItemId: string,
    activeModel: Awaited<ReturnType<StandaloneConfigStore['activeModel']>>,
    projectId: string,
    continuation: RustTurnContinuation,
    requestId: string,
    decision: 'approve_once' | 'approve_for_session' | 'deny' | 'other_guidance',
    guidance: string,
    generation: number,
  ): Promise<void> {
    const threadId = snapshot.thread_id
    const controller = new AbortController()
    this.aborts.set(threadId, controller)
    const trace = await this.startTurnTrace(snapshot, turnId, assistantItemId, generation)
    try {
      trace.record('js_preflight_start')
      const hookState = await this.extensions.runtimeHooks()
      const skillState = await this.extensions.runtimeSkills()
      const savedOptions = snapshot.core?.turns?.[turnId]?.runtime_snapshot
      const studyEnabled = isStudySession(snapshot, isRecord(savedOptions) ? savedOptions : {})
      if (studyEnabled && !skillState.studyEnabled) throw new Error('Study 插件已禁用，请启用后重试')
      trace.record('js_extensions_ready')
      if (this.generations.get(threadId) !== generation) return
      const [models, dreaming, subAgent, retryConfig, loadContextConfig, imagegenConfig] = await Promise.all([
        this.config.runtimeModels().then(value => { trace.record('js_model_keys_ready'); return value }),
        this.config.settings('core.dreaming').then(value => { trace.record('js_settings_ready'); return value }),
        this.config.subAgentRuntime(projectId).then(value => { trace.record('js_subagent_ready'); return value }),
        this.config.settings('core.modelRetry'),
        this.config.settings('core.loadContext'),
        this.config.settings('core.imagegen'),
      ])
      trace.record('js_models_ready')
      if (this.generations.get(threadId) !== generation) return
      trace.record('js_study_ready')
      const hydratedContinuation = await hydrateContinuationImages(continuation, threadId)
      trace.record('js_native_invoking')
      const stopStream = await this.startTurnStream(snapshot, turnId, assistantItemId, generation)
      let progress: RustTurnProgress
      try {
        progress = await withNativeWaitMarkers(() => this.resumeAgentTurn({
          sessionId: threadId,
          projectId,
          provider: activeModel.provider,
          model: activeModel.model,
          apiKey: activeModel.apiKey,
          models,
          dreaming,
          subAgent,
          study: { enabled: studyEnabled },
          disabledSkillNames: skillState.disabledSkillNames,
          disabledPluginNames: skillState.disabledPluginNames,
          imagegenConfig,
          retryConfig,
          loadContextConfig,
          continuation: hydratedContinuation,
          requestId,
          decision,
          guidance,
          ...hookState,
        }), trace.record, controller.signal)
      } finally {
        stopStream()
      }
      trace.record('js_native_returned')
      await trace.stop()
      if (this.generations.get(threadId) !== generation) return
      if (progress.status === 'completed') {
        this.finishSnapshot(snapshot, turnId, assistantItemId, progress.result, 'completed')
        await this.persistSessionApprovals(snapshot, progress.result)
        if (this.generations.get(threadId) !== generation) return
        await this.persistRuntimeState(snapshot, turnId, progress.result)
        if (this.generations.get(threadId) !== generation) return
      } else {
        this.pauseForApproval(snapshot, turnId, assistantItemId, progress)
      }
    } catch (error) {
      await trace.stop()
      if (this.generations.get(threadId) !== generation) return
      const message = error instanceof Error ? error.message : String(error)
      this.finishSnapshot(
        snapshot,
        turnId,
        assistantItemId,
        { text: message, runtimeModelId: '', toolRounds: continuation.toolRounds },
        controller.signal.aborted || isNativeCancellationError(message) ? 'cancelled' : 'failed',
      )
    } finally {
      await trace.stop()
      if (this.aborts.get(threadId) === controller) this.aborts.delete(threadId)
    }
    if (this.generations.get(threadId) !== generation) return
    await this.publishBackgroundSnapshot(snapshot, generation)
    if (snapshot.status !== 'running' && snapshot.status !== 'waiting') {
      this.activeSnapshots.delete(threadId)
      await this.dispatchQueued(threadId)
    }
  }

  private finishSnapshot(
    snapshot: SnapshotWithSession,
    turnId: string,
    assistantItemId: string,
    result: RustTurnResult,
    status: 'completed' | 'failed' | 'cancelled',
  ): void {
    const core = snapshot.core!
    const item = core.items?.[assistantItemId]
    if (item) {
      item.status = status === 'completed' ? 'completed' : status
      item.content = result.text
      item.payload = {
        ...(isRecord(item.payload) ? item.payload : {}),
        type: 'agentMessage',
        content: result.text,
        ...(result.providerState != null ? { provider_state: result.providerState } : {}),
      }
      const metadata = isRecord(item.metadata) ? item.metadata : {}
      const previous = isRecord(metadata[MOBILE_PROGRESS_KEY])
        ? metadata[MOBILE_PROGRESS_KEY] as Record<string, unknown> : {}
      item.metadata = {
        ...(isRecord(item.metadata) ? item.metadata : {}),
        ...(result.runtimeWarnings?.length ? { mobile_runtime_warnings: result.runtimeWarnings } : {}),
        [MOBILE_PROGRESS_KEY]: {
          stage: String(previous.stage || 'js_native_returned'),
          label: status === 'completed' ? '已完成' : status === 'cancelled' ? '已取消' : '运行失败',
          status,
          expires_at: Date.now() + TERMINAL_PROGRESS_MS,
        },
      }
    }
    const turn = core.turns?.[turnId]
    if (turn) {
      turn.status = status
      if (result.runtimeModelId) {
        turn.runtime_snapshot = {
          ...(isRecord(turn.runtime_snapshot) ? turn.runtime_snapshot : {}),
          model_id: result.runtimeModelId,
        }
      }
    }
    const reasoning = String(result.reasoning || '').trim()
    if (reasoning && turn && core.items) {
      const reasoningItemId = `${turnId}:reasoning`
      const assistantSequence = Number(item?.seq || 0)
      core.items[reasoningItemId] = {
        item_id: reasoningItemId,
        turn_id: turnId,
        kind: 'thinking',
        type: 'reasoning',
        status,
        seq: assistantSequence,
        content: reasoning,
        payload: { type: 'reasoning', content: reasoning },
      }
      if (item) item.seq = assistantSequence + 1
      turn.items = [...(turn.items || []).filter((id) => id !== reasoningItemId), reasoningItemId]
      const assistantTurnIndex = turn.items.indexOf(assistantItemId)
      if (assistantTurnIndex >= 0) {
        turn.items.splice(assistantTurnIndex, 0, turn.items.pop()!)
      }
      core.item_order = (core.item_order || []).filter((id) => id !== reasoningItemId)
      const assistantOrderIndex = core.item_order.indexOf(assistantItemId)
      core.item_order.splice(
        assistantOrderIndex >= 0 ? assistantOrderIndex : core.item_order.length,
        0,
        reasoningItemId,
      )
    } else if (turn && core.items) {
      const reasoningItem = core.items[`${turnId}:reasoning`]
      if (reasoningItem?.status === 'running') reasoningItem.status = status
    }
    // A cancelled or failed turn can interrupt a tool step; leaving it running
    // would strand a spinner in the transcript.
    if (core.items) {
      const toolPrefix = `${turnId}:tool:`
      for (const [itemId, toolItem] of Object.entries(core.items)) {
        if (itemId.startsWith(toolPrefix) && toolItem?.status === 'running') toolItem.status = status
      }
    }
    core.status = status
    snapshot.status = status
    snapshot.snapshot_seq = Number(snapshot.snapshot_seq || 0) + 1
    core.snapshot_seq = snapshot.snapshot_seq
    snapshot.revision = Number(snapshot.revision || 0) + 1
    core.revision = snapshot.revision
  }

  private async interruptTurn(threadId: string): Promise<Record<string, unknown>> {
    const snapshot = await this.snapshotFor(threadId)
    const core = snapshot.core!
    const activeTurnIds = Object.values(core.turns || {})
      .filter(turn => turn.status === 'running' || turn.status === 'waiting')
      .map(turn => String(turn.turn_id || ''))
      .filter(Boolean)
    const generation = (this.generations.get(threadId) || 0) + 1
    this.generations.set(threadId, generation)
    this.activeStageListeners.get(threadId)?.()
    this.activeStreamListeners.get(threadId)?.()
    this.aborts.get(threadId)?.abort()
    this.aborts.delete(threadId)
    // Native cancellation must complete before this snapshot is published as
    // cancelled.  The turn id keeps a stale interrupt from touching a new
    // turn that starts in the same session.
    await Promise.all(activeTurnIds.map(turnId => this.cancelAgentTurn(turnId)))
    for (const turn of Object.values(core.turns || {})) {
      if (turn.status === 'running' || turn.status === 'waiting') turn.status = 'cancelled'
    }
    for (const item of Object.values(core.items || {})) {
      if (item.status === 'running') {
        item.status = 'cancelled'
        if (item.type === 'agentMessage') item.metadata = {
          ...(isRecord(item.metadata) ? item.metadata : {}),
          [MOBILE_PROGRESS_KEY]: {
            stage: 'cancelled', label: '已取消', status: 'cancelled',
            expires_at: Date.now() + TERMINAL_PROGRESS_MS,
          },
        }
      }
    }
    core.status = 'cancelled'
    snapshot.status = 'cancelled'
    snapshot.snapshot_seq = Number(snapshot.snapshot_seq || 0) + 1
    core.snapshot_seq = snapshot.snapshot_seq
    snapshot.revision = Number(snapshot.revision || 0) + 1
    core.revision = snapshot.revision
    await this.saveSnapshot(snapshot)
    if (this.generations.get(threadId) !== generation) return { snapshot }
    this.activeSnapshots.delete(threadId)
    this.emitSnapshot(snapshot)
    await this.dispatchQueued(threadId)
    return { snapshot }
  }

  private async requestModel(
    snapshot: SnapshotWithSession,
    turnId: string,
    activeModel: Awaited<ReturnType<StandaloneConfigStore['activeModel']>>,
    signal: AbortSignal,
    recordStage: (stage: string) => void = () => {},
    preparedHistory?: RustAgentMessage[],
  ): Promise<RustTurnProgress | RustTurnResult> {
    recordStage('js_preflight_start')
    const { provider, model, apiKey } = activeModel
    const history = preparedHistory || await conversationMessages(snapshot, turnId)
    const threadId = snapshot.thread_id
    const projectId = String(snapshot.session?.metadata?.project_id || '')
    const workspaceId = projectId || `session-${threadId.replace(/[^a-zA-Z0-9_-]+/g, '-')}`
    const runtimeSnapshot = snapshot.core?.turns?.[turnId]?.runtime_snapshot
    const options = isRecord(runtimeSnapshot) ? runtimeSnapshot : {}
    const hookState = await this.extensions.runtimeHooks()
    const skillState = await this.extensions.runtimeSkills()
    const studyEnabled = isStudySession(snapshot, options)
    if (studyEnabled && !skillState.studyEnabled) throw new Error('Study 插件已禁用，请启用后重试')
    recordStage('js_extensions_ready')
    const [models, [dreaming, contextCompaction], subAgent, retryConfig, globalContext, loadContextConfig, imagegenConfig] = await Promise.all([
      this.config.runtimeModels().then(value => { recordStage('js_model_keys_ready'); return value }),
      Promise.all([
        this.config.settings('core.dreaming'),
        this.config.settings('core.contextCompaction'),
      ]).then(value => { recordStage('js_settings_ready'); return value }),
      this.config.subAgentRuntime(workspaceId).then(value => { recordStage('js_subagent_ready'); return value }),
      this.config.settings('core.modelRetry'),
      this.config.settings('core.globalContext'),
      this.config.settings('core.loadContext'),
      // The image API is configured in the shared 设置 → 生图 panel, which writes
      // this namespace; the host resolves it so the runtime stays config-agnostic.
      this.config.settings('core.imagegen'),
    ])
    recordStage('js_models_ready')
    if (signal.aborted) throw new Error('操作已取消')
    const baseModeContext = await this.studyModeContext(snapshot, options)
    // The active mode is enforced by the runtime, which has to be told which mode
    // it is in and what that mode allows. Resolved here because the transport owns
    // configuration on this platform.
    const modePlan = await this.config.modePlan(String(options.active_mode || ''))
    const modeContext = [baseModeContext, modePlan.promptLine].filter(Boolean).join('\n\n')
    recordStage('js_study_ready')
    if (signal.aborted) throw new Error('操作已取消')
    recordStage('js_native_invoking')
    const assistantItemId = `${turnId}:assistant`
    const generation = this.generations.get(threadId) || 0
    const stopStream = await this.startTurnStream(snapshot, turnId, assistantItemId, generation)
    let result: RustTurnProgress | RustTurnResult
    try {
      result = await withNativeWaitMarkers(() => this.runAgentTurn({
        turnId,
        sessionId: threadId,
        projectId: workspaceId,
        modelRecordId: model.id,
        provider,
        model,
        apiKey,
        models,
        dreaming,
        contextCompaction,
        subAgent,
        study: { enabled: studyEnabled },
        disabledSkillNames: skillState.disabledSkillNames,
        disabledPluginNames: skillState.disabledPluginNames,
        imagegenConfig,
        retryConfig,
        loadContextConfig,
        history,
        reasoningLevel: resolveReasoningLevel(options.reasoning_level, model),
        thinkingBudget: finiteNumber(options.thinking_budget) ?? model.thinking_budget,
        maxOutputTokens: finiteNumber(options.max_tokens) ?? model.max_output_tokens,
        temperature: finiteNumber(options.temperature) ?? model.temperature,
        permissionPreset: normalizePermissionPreset(options.permission_preset),
        sessionApprovedTools: stringArray(options.session_approved_tools),
        activeMode: String(options.active_mode || ''),
        modeTools: modePlan.tools || undefined,
        ...hookState,
        context: {
          modeContext,
          ...(!studyEnabled ? {
            globalInstructions: String(globalContext.instructions || '').slice(0, 20_000),
            memory: String(globalContext.memory || '').slice(0, 20_000),
          } : {}),
        },
      }), recordStage, signal)
    } finally {
      stopStream()
    }
    recordStage('js_native_returned')
    if (signal.aborted) throw new Error('操作已取消')
    return result
  }

  private async snapshotFor(threadId: string): Promise<SnapshotWithSession> {
    await this.recoverOrphanedTurn(threadId)
    const saved = await this.repository.loadThreadSnapshot(threadId) as SnapshotWithSession | null
    const thread = (await this.repository.listSessions()).find((candidate) => candidate.id === threadId)
    const snapshot = saved ? jsonClone(saved) as SnapshotWithSession : emptySnapshot(threadId)
    const now = new Date().toISOString()
    snapshot.session = {
      id: threadId,
      title: thread?.title || '新会话',
      metadata: thread?.metadata || {},
      created_at: thread?.createdAt || now,
      updated_at: thread?.updatedAt || now,
    }
    return snapshot
  }

  private async startTurnTrace(
    snapshot: SnapshotWithSession,
    turnId: string,
    assistantItemId: string,
    generation: number,
  ): Promise<{ record: (stage: string) => void; stop: () => Promise<void> }> {
    let active = true
    const record = (stage: string) => {
      if (!active || this.generations.get(snapshot.thread_id) !== generation) return
      if (!Object.hasOwn(stageLabels, stage)) return
      const item = snapshot.core?.items?.[assistantItemId]
      if (!item || item.status !== 'running') return
      item.metadata = {
        ...(isRecord(item.metadata) ? item.metadata : {}),
        [MOBILE_PROGRESS_KEY]: { stage, label: stageLabels[stage], status: 'running' },
      }
      snapshot.snapshot_seq = Number(snapshot.snapshot_seq || 0) + 1
      snapshot.core!.snapshot_seq = snapshot.snapshot_seq
      snapshot.revision = Number(snapshot.revision || 0) + 1
      snapshot.core!.revision = snapshot.revision
      this.emitSnapshot(snapshot)
    }
    let unlisten: () => void = () => {}
    const stopListening = () => {
      active = false
      unlisten()
      if (this.activeStageListeners.get(snapshot.thread_id) === stopListening) {
        this.activeStageListeners.delete(snapshot.thread_id)
      }
    }
    this.activeStageListeners.get(snapshot.thread_id)?.()
    this.activeStageListeners.set(snapshot.thread_id, stopListening)
    try {
      const registration = this.listenTurnStage(payload => {
        if (!isRecord(payload) || payload.turnId !== turnId || typeof payload.stage !== 'string') return
        record(payload.stage)
      })
      const ready = registration.then(stopListening => {
        if (active) unlisten = stopListening
        else stopListening()
        return true
      }).catch(() => {
        console.error('Failed to listen for standalone turn stages')
        return false
      })
      if (!await waitForTraceTask(ready, 1000)) record('trace_listener_unavailable')
    } catch {
      console.error('Failed to listen for standalone turn stages')
      record('trace_listener_unavailable')
    }
    return {
      record,
      stop: async () => {
        if (!active) return
        active = false
        try { stopListening() } catch {
          console.error('Failed to stop standalone turn trace')
        }
      },
    }
  }

  private async startTurnStream(
    snapshot: SnapshotWithSession,
    turnId: string,
    assistantItemId: string,
    generation: number,
  ): Promise<() => void> {
    const threadId = snapshot.thread_id
    let active = true
    let text = ''
    let reasoning = ''
    let timer: ReturnType<typeof setTimeout> | undefined
    let unlisten = () => {}
    // One turn can run several model rounds when the model keeps calling tools.
    // Each round's narration and thinking are archived before the next round
    // starts, so the transcript keeps what was already shown instead of only
    // ever displaying the newest round.
    let round = 1
    const liveReasoningId = `${turnId}:reasoning`

    const archiveRound = () => {
      const core = snapshot.core
      const turn = core?.turns?.[turnId]
      if (!core?.items || !turn) return
      const sequence = Number(core.items[assistantItemId]?.seq || 0)
      if (reasoning) {
        const archivedId = `${turnId}:reasoning:${round}`
        core.items[archivedId] = {
          item_id: archivedId, turn_id: turnId, kind: 'thinking', type: 'reasoning',
          status: 'completed', seq: sequence, content: reasoning,
          payload: { type: 'reasoning', content: reasoning },
        }
        insertItemBeforeLive(core, turnId, assistantItemId, archivedId)
      }
      if (core.items[liveReasoningId]) {
        delete core.items[liveReasoningId]
        turn.items = (turn.items || []).filter(id => id !== liveReasoningId)
        core.item_order = (core.item_order || []).filter(id => id !== liveReasoningId)
      }
      if (text) {
        const narrationId = `${turnId}:narration:${round}`
        core.items[narrationId] = {
          item_id: narrationId, turn_id: turnId, kind: 'message', type: 'agentMessage',
          status: 'completed', seq: sequence, content: text,
          // Intermediate narration is process, not this turn's answer.
          payload: { type: 'agentMessage', content: text, final_response: false },
        }
        insertItemBeforeLive(core, turnId, assistantItemId, narrationId)
      }
      round += 1
    }

    const flush = () => {
      timer = undefined
      if (!active || this.generations.get(threadId) !== generation) return
      const core = snapshot.core
      const turn = core?.turns?.[turnId]
      const assistant = core?.items?.[assistantItemId]
      if (!core || !turn || turn.status !== 'running' || !assistant || assistant.status !== 'running') return
      assistant.content = text
      assistant.payload = { ...(isRecord(assistant.payload) ? assistant.payload : {}), type: 'agentMessage', content: text }
      if (reasoning) {
        const existingReasoning = core.items?.[liveReasoningId]
        const sequence = Number(existingReasoning?.seq ?? assistant.seq ?? 0)
        core.items![liveReasoningId] = {
          item_id: liveReasoningId, turn_id: turnId, kind: 'thinking', type: 'reasoning',
          status: 'running', seq: sequence, content: reasoning,
          payload: { type: 'reasoning', content: reasoning },
        }
        insertItemBeforeLive(core, turnId, assistantItemId, liveReasoningId)
      } else if (core.items?.[liveReasoningId]) {
        delete core.items[liveReasoningId]
        turn.items = (turn.items || []).filter(id => id !== liveReasoningId)
        core.item_order = (core.item_order || []).filter(id => id !== liveReasoningId)
      }
      snapshot.snapshot_seq = Number(snapshot.snapshot_seq || 0) + 1
      core.snapshot_seq = snapshot.snapshot_seq
      snapshot.revision = Number(snapshot.revision || 0) + 1
      core.revision = snapshot.revision
      this.emitSnapshot(snapshot)
    }
    const stopListening = () => {
      if (!active) return
      active = false
      if (timer != null) clearTimeout(timer)
      timer = undefined
      unlisten()
      if (this.activeStreamListeners.get(threadId) === stopListening) this.activeStreamListeners.delete(threadId)
    }
    const scheduleFlush = () => {
      if (timer == null) timer = setTimeout(flush, 50)
    }
    // Tool steps are their own transcript items so the work stays visible
    // instead of being summarised away by the next round.
    const applyToolStep = (data: Record<string, unknown>, finished: boolean) => {
      const core = snapshot.core
      const turn = core?.turns?.[turnId]
      if (!core?.items || !turn || turn.status !== 'running') return
      const callId = String(data.id || '')
      if (!callId) return
      const itemId = `${turnId}:tool:${callId}`
      const existing = core.items[itemId]
      const name = String(data.name || existing?.tool_name || 'tool')
      const preview = typeof data.preview === 'string' ? data.preview : ''
      const ok = data.ok !== false
      const args = existing?.arguments ?? parseToolArguments(data.arguments)
      const argsPreview = typeof data.arguments === 'string' ? data.arguments : ''
      const outcome = finished
        ? ok ? { tool_result: preview } : { error: preview }
        : { message: argsPreview }
      // The shared process card builds its row from the item payload, so every
      // display field has to live there as well as on the item itself.
      const payload: Record<string, unknown> = {
        ...(isRecord(existing?.payload) ? existing.payload : {}),
        type: 'dynamicToolCall',
        tool_name: name,
        ...(args === undefined ? {} : { arguments: args }),
        ...outcome,
      }
      core.items[itemId] = {
        ...(existing || {}),
        item_id: itemId,
        turn_id: turnId,
        kind: 'tool_call',
        type: 'dynamicToolCall',
        status: finished ? 'completed' : 'running',
        seq: Number(existing?.seq ?? core.items[assistantItemId]?.seq ?? 0),
        tool_name: name,
        arguments: args,
        ...outcome,
        payload,
      }
      if (!existing) insertItemBeforeLive(core, turnId, assistantItemId, itemId)
      snapshot.snapshot_seq = Number(snapshot.snapshot_seq || 0) + 1
      core.snapshot_seq = snapshot.snapshot_seq
      snapshot.revision = Number(snapshot.revision || 0) + 1
      core.revision = snapshot.revision
      this.emitSnapshot(snapshot)
    }
    this.activeStreamListeners.get(threadId)?.()
    this.activeStreamListeners.set(threadId, stopListening)
    try {
      unlisten = await this.listenTurnStream(payload => {
        if (!active || this.generations.get(threadId) !== generation || !isRecord(payload)) return
        if (payload.turnId !== turnId) return
        const event = payload as unknown as RustAgentStreamEvent
        if (event.kind === 'reset') {
          if (timer != null) clearTimeout(timer)
          timer = undefined
          archiveRound()
          text = ''
          reasoning = ''
          flush()
        } else if (event.kind === 'text_delta' && typeof event.delta === 'string') {
          text += event.delta
          scheduleFlush()
        } else if (event.kind === 'reasoning_delta' && typeof event.delta === 'string') {
          reasoning += event.delta
          scheduleFlush()
        } else if (event.kind === 'tool_call' && isRecord(event.data)) {
          applyToolStep(event.data, false)
        } else if (event.kind === 'tool_result' && isRecord(event.data)) {
          applyToolStep(event.data, true)
        }
      })
      if (!active) unlisten()
    } catch {
      if (this.activeStreamListeners.get(threadId) === stopListening) this.activeStreamListeners.delete(threadId)
      active = false
      console.error('Failed to listen for standalone turn stream')
    }
    return stopListening
  }

  private async recoverOrphanedTurn(threadId: string): Promise<void> {
    if (this.generations.has(threadId)) return
    const pending = this.snapshotRecoveries.get(threadId)
    if (pending) return await pending
    const recovery = (async () => {
      const saved = await this.repository.loadThreadSnapshot(threadId) as SnapshotWithSession | null
      if (!saved || saved.status !== 'running' || this.generations.has(threadId)) return
      const activeTurnIds = Object.values(saved.core?.turns || {})
        .filter(turn => turn.status === 'running')
        .map(turn => String(turn.turn_id || ''))
        .filter(Boolean)
      // A WebView reload can leave native execution alive. Bound cancellation
      // so a lost native reply cannot keep the restored UI stuck on running.
      await Promise.all(activeTurnIds.map(async turnId => {
        let timer: ReturnType<typeof setTimeout> | undefined
        try {
          await Promise.race([
            this.cancelAgentTurn(turnId).catch(error => {
              console.error('Failed to cancel orphaned standalone turn', error)
            }),
            new Promise<void>(resolve => { timer = setTimeout(resolve, 1500) }),
          ])
        } finally {
          if (timer) clearTimeout(timer)
        }
      }))
      if (this.generations.has(threadId)) return
      const latest = await this.repository.loadThreadSnapshot(threadId) as SnapshotWithSession | null
      if (!latest || latest.status !== 'running' || this.generations.has(threadId)) return
      const core = latest.core
      if (!core) return
      for (const turn of Object.values(core.turns || {})) {
        if (turn.status === 'running') turn.status = 'cancelled'
      }
      for (const item of Object.values(core.items || {})) {
        if (item.status === 'running') {
          item.status = 'cancelled'
          if (item.type === 'agentMessage') item.metadata = {
            ...(isRecord(item.metadata) ? item.metadata : {}),
            [MOBILE_PROGRESS_KEY]: {
              stage: 'cancelled', label: '已取消', status: 'cancelled',
              expires_at: Date.now() + TERMINAL_PROGRESS_MS,
            },
          }
        }
      }
      core.status = 'cancelled'
      latest.status = 'cancelled'
      latest.snapshot_seq = Number(latest.snapshot_seq || 0) + 1
      core.snapshot_seq = latest.snapshot_seq
      latest.revision = Number(latest.revision || 0) + 1
      core.revision = latest.revision
      await this.saveSnapshot(latest)
      this.emitSnapshot(latest)
    })()
    this.snapshotRecoveries.set(threadId, recovery)
    try {
      await recovery
    } finally {
      if (this.snapshotRecoveries.get(threadId) === recovery) this.snapshotRecoveries.delete(threadId)
    }
  }

  private async publishBackgroundSnapshot(snapshot: SnapshotWithSession, generation: number): Promise<void> {
    if (this.generations.get(snapshot.thread_id) !== generation) return
    const save = this.saveSnapshot(snapshot).catch(error => {
      console.error('Failed to save standalone turn snapshot', error)
    })
    if (import.meta.env.VITE_MOBILE_TRACE_TURNS === '1') {
      if (!await waitForTraceTask(save.then(() => true), 1000)) {
        console.error('Standalone turn snapshot save timed out')
      }
    } else await save
    if (this.generations.get(snapshot.thread_id) !== generation) return
    this.emitSnapshot(snapshot)
  }

  private async saveSnapshot(snapshot: SnapshotWithSession): Promise<void> {
    const threadId = snapshot.thread_id
    // The repository normalizes only the top level. Capture this revision now
    // so a running turn cannot mutate a previously persisted snapshot by ref.
    const persisted = jsonClone(snapshot) as SnapshotWithSession
    const previous = this.snapshotSaves.get(threadId) || Promise.resolve()
    const pending = previous.catch(() => {}).then(() => this.repository.saveLocalSnapshot(persisted))
    this.snapshotSaves.set(threadId, pending)
    try {
      await pending
    } finally {
      if (this.snapshotSaves.get(threadId) === pending) this.snapshotSaves.delete(threadId)
    }
  }

  private emitSnapshot(snapshot: CoreAppSnapshot): void {
    const message: TransportMessage = {
      type: 'notification',
      channel: 'rpc',
      method: 'thread/snapshot',
      params: jsonClone(snapshot) as unknown as Record<string, unknown>,
    }
    for (const listener of this.messageListeners) listener(message)
  }

  private setState(state: TransportConnectionState): void {
    if (this.state === state) return
    this.state = state
    for (const listener of this.stateListeners) listener(state)
  }
  /**
   * Build the Study mode context from the shared runtime.
   *
   * The bundled plugin owns the Study system prompt; this host only supplies
   * its own session metadata.  A Study context failure is reported inside the
   * turn instead of being hidden or blocking the conversation.
   */
  private async studyModeContext(
    snapshot: SnapshotWithSession,
    options: Record<string, unknown> = {},
  ): Promise<string> {
    const metadata = snapshot.session?.metadata || {}
    const activeMode = String(options.active_mode || metadata.owner_plugin || metadata.plugin_id || '').trim()
    if (!isStudySession(snapshot, options)) {
      return activeMode ? `Active application mode: ${activeMode}.` : ''
    }
    try {
      const context = await this.callStudy<{
        instructions?: string
        request_local_late_context?: string
      }>({
        method: 'study.context',
        params: {
          session_id: snapshot.thread_id,
          study_scope: metadata.study_scope,
          node_id: metadata.study_node_id,
        },
        sessionMetadata: metadata,
      })
      return [String(context.instructions || ''), String(context.request_local_late_context || '')]
        .map(part => part.trim())
        .filter(Boolean)
        .join('\n\n')
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause)
      return `Active application mode: Study.\n[Study context unavailable] ${message}`
    }
  }
}

function isStudySession(
  snapshot: SnapshotWithSession,
  options: Record<string, unknown> = {},
): boolean {
  const metadata = snapshot.session?.metadata || {}
  const activeMode = String(options.active_mode || metadata.owner_plugin || metadata.plugin_id || '').trim()
  return activeMode === 'study' || activeMode === 'study:study'
}

function emptySnapshot(threadId: string): SnapshotWithSession {
  return {
    thread_id: threadId,
    snapshot_seq: 0,
    revision: 0,
    status: 'idle',
    turns: {},
    items: {},
    item_order: [],
    requests: {},
    artifacts: {},
    queue: [],
    core: {
      thread_id: threadId,
      snapshot_seq: 0,
      revision: 0,
      status: 'idle',
      turns: {},
      items: {},
      item_order: [],
      requests: {},
      artifacts: {},
    },
  }
}

async function waitForTraceTask(task: Promise<boolean>, timeoutMs: number): Promise<boolean> {
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      task,
      new Promise<boolean>(resolve => { timer = setTimeout(() => resolve(false), timeoutMs) }),
    ])
  } finally {
    if (timer) clearTimeout(timer)
  }
}

async function withNativeWaitMarkers<T>(
  operation: () => Promise<T>,
  recordStage: (stage: string) => void,
  signal: AbortSignal,
): Promise<T> {
  if (import.meta.env.VITE_MOBILE_TRACE_TURNS !== '1') return await operation()

  let active = true
  const timers: ReturnType<typeof setTimeout>[] = []
  const stop = () => {
    if (!active) return
    active = false
    for (const timer of timers) clearTimeout(timer)
    signal.removeEventListener('abort', stop)
  }
  signal.addEventListener('abort', stop, { once: true })
  if (!signal.aborted) {
    timers.push(setTimeout(() => {
      if (active) recordStage('js_native_wait_35s')
    }, 35_000))
    timers.push(setTimeout(() => {
      if (active) recordStage('js_native_wait_125s')
    }, 125_000))
  } else {
    stop()
  }

  try {
    return await operation()
  } finally {
    stop()
  }
}

async function conversationMessages(snapshot: SnapshotWithSession, activeTurnId = ''): Promise<RustAgentMessage[]> {
  const core = snapshot.core
  if (!core) return []
  const persisted = snapshot.session?.metadata?.rust_runtime_history
  const sourceTurnId = snapshot.session?.metadata?.rust_runtime_history_turn_id
  const previousTurns = Object.values(core.turns || {})
    .filter(turn => turn.turn_id !== activeTurnId)
    .sort((left, right) => Number(left.seq || 0) - Number(right.seq || 0))
  const latestTurn = previousTurns.at(-1)
  const persistedBelongsToLatestCompletedTurn = latestTurn?.status === 'completed'
    && (sourceTurnId == null || sourceTurnId === latestTurn.turn_id)
  if (Array.isArray(persisted) && persisted.every(isRustAgentMessage) && persistedBelongsToLatestCompletedTurn) {
    const history = await hydrateImageMessages(jsonClone(persisted) as RustAgentMessage[], snapshot.thread_id)
    if (!activeTurnId) return history
    const current = core.turns?.[activeTurnId]
    const currentUser = (current?.items || [])
      .map(id => core.items?.[id])
      .find(item => isRecord(item?.payload) && item.payload.type === 'userMessage')
    const payload = isRecord(currentUser?.payload) ? currentUser.payload : {}
    const message = await inputMessage(payload.content, snapshot.thread_id)
    return [...history, ...(message ? [message] : [])]
  }
  const messages: RustAgentMessage[] = []
  for (const id of core.item_order || []) {
    const item = core.items?.[id]
    const payload = isRecord(item?.payload) ? item.payload : {}
    if (payload.type === 'userMessage') {
      const message = await inputMessage(payload.content, snapshot.thread_id)
      if (message) messages.push(message)
      continue
    }
    if (payload.type === 'agentMessage') {
      if (item?.status === 'cancelled') continue
      // A tool round's narration is not a separate assistant message: the
      // durable runtime history already replays it, so adding it here would
      // duplicate the text on the next request.
      if (payload.final_response === false) continue
      // Older snapshots stored diagnostics in content; keep only their saved answer in model history.
      const content = typeof payload.turn_trace_answer === 'string'
        ? payload.turn_trace_answer
        : String(payload.content || item?.content || '')
      if (content) messages.push({
        role: 'assistant',
        content,
        ...(payload.provider_state != null ? { providerState: payload.provider_state } : {}),
      })
    }
  }
  return messages
}

/** Place a finished item directly before its turn's live answer item. */
function insertItemBeforeLive(
  core: NonNullable<CoreAppSnapshot['core']>,
  turnId: string,
  assistantItemId: string,
  itemId: string,
): void {
  const turn = core.turns?.[turnId]
  if (!turn) return
  turn.items = (turn.items || []).filter(id => id !== itemId)
  const assistantIndex = turn.items.indexOf(assistantItemId)
  if (assistantIndex >= 0) turn.items.splice(assistantIndex, 0, itemId)
  else turn.items.push(itemId)
  core.item_order = (core.item_order || []).filter(id => id !== itemId)
  const orderIndex = core.item_order.indexOf(assistantItemId)
  core.item_order.splice(orderIndex >= 0 ? orderIndex : core.item_order.length, 0, itemId)
}

/**
 * Tool arguments arrive as a bounded text preview. The shared process card reads
 * a structured object (path, command, query, …), so recover it when the preview
 * is still valid JSON and let a truncated preview fall back to plain text.
 */
function parseToolArguments(preview: unknown): Record<string, unknown> | undefined {
  if (typeof preview !== 'string' || !preview.trim()) return undefined
  try {
    const parsed = JSON.parse(preview)
    return isRecord(parsed) ? parsed : undefined
  } catch {
    return undefined
  }
}

async function inputMessage(value: unknown, sessionId: string): Promise<RustAgentMessage | null> {
  const input = Array.isArray(value) ? value : []
  const content: string[] = []
  const images: RustAgentImage[] = []
  let imageBytes = 0
  for (const part of input) {
    if (!isRecord(part)) continue
    if (part.type === 'text') { content.push(String(part.text || '')); continue }
    if (part.type !== 'attachment') continue
    const id = String(part.attachment_id || '')
    if (!id) throw new Error('附件缺少有效 ID，无法读取内容')
    const attachment = await nativeAttachments.read(id)
    if (attachment.metadata.session_id !== sessionId) throw new Error('附件不属于当前会话')
    const filename = attachment.metadata.filename
    if (attachment.metadata.preview_type === 'text') {
      content.push(`[附件 ${filename} 的文本内容]\n${decodeAttachmentText(attachment)}\n[附件内容结束]`)
    } else if (MODEL_IMAGE_MIME_TYPES.has(attachment.metadata.mime_type)) {
      if (attachment.bytes.length > MAX_MODEL_IMAGE_BYTES) {
        throw new Error(`图片 ${filename} 超过每张 10 MiB 的模型输入限制`)
      }
      if (!imageBytesMatchMime(attachment.metadata.mime_type, attachment.bytes)) {
        throw new Error(`附件 ${filename} 的实际内容与声明的图片类型 ${attachment.metadata.mime_type} 不符`)
      }
      if (images.length >= MAX_MODEL_IMAGES) {
        throw new Error(`单条消息最多支持 ${MAX_MODEL_IMAGES} 张图片`)
      }
      imageBytes += attachment.bytes.length
      if (imageBytes > MAX_MODEL_IMAGE_TOTAL_BYTES) {
        throw new Error('单条消息中的图片总大小超过 20 MiB 模型输入限制')
      }
      images.push({
        attachment_id: id,
        mime_type: attachment.metadata.mime_type,
        data_base64: b4a.toString(attachment.bytes, 'base64'),
      })
      content.push(`[附件图片：${filename}]`)
    } else {
      throw new Error(
        `移动端当前模型输入不支持附件 ${filename}（${attachment.metadata.mime_type}）；请先转换为文本或 JPEG、PNG、GIF、WebP 图片`,
      )
    }
  }
  const text = content.filter(Boolean).join('\n')
  if (images.length) return { role: 'user_multimodal', content: text, images }
  return text ? { role: 'user', content: text } : null
}

async function hydrateImageMessages(
  messages: RustAgentMessage[],
  sessionId: string,
): Promise<RustAgentMessage[]> {
  return await Promise.all(messages.map(async message => {
    if (message.role !== 'user_multimodal') return message
    const images = await Promise.all(message.images.map(image => hydrateModelImage(image, sessionId)))
    return { ...message, images }
  }))
}

async function hydrateContinuationImages(
  continuation: RustTurnContinuation,
  sessionId: string,
): Promise<RustTurnContinuation> {
  const messages = await Promise.all(continuation.messages.map(async value => {
    if (!isRecord(value) || value.role !== 'user_multimodal' || !Array.isArray(value.images)) return value
    const images = await Promise.all(value.images.map(image => hydrateModelImage(image as RustAgentImage, sessionId)))
    return { ...value, images }
  }))
  validateConversationImageBudget(messages.filter(isRustAgentMessage))
  return { ...continuation, messages }
}

async function hydrateModelImage(image: RustAgentImage, sessionId: string): Promise<RustAgentImage> {
  if (!image.attachment_id) throw new Error('历史图片缺少有效附件 ID，无法重放')
  const attachment = await nativeAttachments.read(image.attachment_id)
  if (attachment.metadata.session_id !== sessionId) throw new Error('历史图片不属于当前会话')
  if (attachment.metadata.mime_type !== image.mime_type) throw new Error('历史图片类型与已保存附件不一致')
  if (!MODEL_IMAGE_MIME_TYPES.has(attachment.metadata.mime_type)) {
    throw new Error(`历史图片类型 ${attachment.metadata.mime_type} 不受模型支持`)
  }
  if (attachment.bytes.length > MAX_MODEL_IMAGE_BYTES) {
    throw new Error(`历史图片超过每张 10 MiB 的模型输入限制`)
  }
  if (!imageBytesMatchMime(attachment.metadata.mime_type, attachment.bytes)) {
    throw new Error(`历史图片内容与保存的类型 ${attachment.metadata.mime_type} 不符`)
  }
  return { ...image, data_base64: b4a.toString(attachment.bytes, 'base64') }
}

function imageBytesMatchMime(mime: string, bytes: Uint8Array): boolean {
  const startsWith = (...signature: number[]) => signature.every((byte, index) => bytes[index] === byte)
  switch (mime) {
    case 'image/jpeg': return startsWith(0xff, 0xd8, 0xff)
    case 'image/png': return startsWith(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)
    case 'image/gif': return startsWith(0x47, 0x49, 0x46, 0x38) && (bytes[4] === 0x37 || bytes[4] === 0x39) && bytes[5] === 0x61
    case 'image/webp': return startsWith(0x52, 0x49, 0x46, 0x46) && bytes.length >= 12
      && bytes[8] === 0x57 && bytes[9] === 0x45 && bytes[10] === 0x42 && bytes[11] === 0x50
    default: return false
  }
}

function validateConversationImageBudget(messages: RustAgentMessage[]): void {
  let totalBytes = 0
  for (const message of messages) {
    if (message.role !== 'user_multimodal') continue
    if (message.images.length === 0 || message.images.length > MAX_MODEL_IMAGES) {
      throw new Error(`单条消息最多支持 ${MAX_MODEL_IMAGES} 张图片`)
    }
    for (const image of message.images) {
      if (!MODEL_IMAGE_MIME_TYPES.has(image.mime_type)) {
        throw new Error(`模型输入不支持图片类型 ${image.mime_type}`)
      }
      const byteLength = decodedBase64Length(image.data_base64 || '')
      if (byteLength == null || byteLength > MAX_MODEL_IMAGE_BYTES) {
        throw new Error('图片缺少有效内容，或超过每张 10 MiB 的模型输入限制')
      }
      totalBytes += byteLength
      if (totalBytes > MAX_MODEL_IMAGE_TOTAL_BYTES) {
        throw new Error('当前对话图片总大小超过 20 MiB 模型输入限制')
      }
    }
  }
}

function decodedBase64Length(value: string): number | null {
  if (!value || value.length % 4 !== 0 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) {
    return null
  }
  const padding = value.endsWith('==') ? 2 : value.endsWith('=') ? 1 : 0
  return (value.length / 4) * 3 - padding
}

function withoutTransientImageBytes<T>(value: T): T {
  if (Array.isArray(value)) return value.map(item => withoutTransientImageBytes(item)) as T
  if (!isRecord(value)) return value
  if (value.role === 'user_multimodal' && Array.isArray(value.images)) {
    return {
      ...value,
      images: value.images.map((image: unknown) => {
        if (!isRecord(image)) return image
        const { data_base64: _transientBytes, ...reference } = image
        return reference
      }),
    } as T
  }
  return value
}

function isRustAgentMessage(value: unknown): value is RustAgentMessage {
  if (!isRecord(value) || typeof value.role !== 'string') return false
  if (value.role === 'user_multimodal') {
    return typeof value.content === 'string' && Array.isArray(value.images)
      && value.images.length > 0 && value.images.every((image: unknown) => isRecord(image)
        && typeof image.attachment_id === 'string' && typeof image.mime_type === 'string'
        && (image.data_base64 == null || typeof image.data_base64 === 'string'))
  }
  if (value.role === 'assistant_tool_calls') return Array.isArray(value.calls)
  if (value.role === 'tool') return typeof value.tool_call_id === 'string' && typeof value.content === 'string'
  return ['system', 'user', 'assistant'].includes(value.role) && typeof value.content === 'string'
}

function toRawSession(thread: LocalThread) {
  return {
    id: thread.id,
    title: thread.title,
    status: thread.status,
    created_at: thread.createdAt,
    updated_at: thread.updatedAt,
    metadata: thread.metadata,
  }
}

function jsonResponse(value: unknown, status = 200): TransportHttpResponse {
  return {
    status,
    headers: { 'Content-Type': 'application/json' },
    body: status === 204 ? new Uint8Array() : new TextEncoder().encode(JSON.stringify(value)),
  }
}

function attachmentErrorResponse(error: unknown): TransportHttpResponse {
  const message = error instanceof Error ? error.message : String(error)
  const status = error instanceof AttachmentRequestError ? error.status
    : /not found|no such file|cannot find|does not exist|不存在/i.test(message) ? 404
    : /exceeds the 50 mib limit/i.test(message) ? 413
    : /invalid attachment (?:id|session id|filename|mime type)/i.test(message) ? 400
    : 500
  return jsonResponse({ error: message }, status)
}

function decodeAttachmentText(attachment: NativeAttachmentData): string {
  const limit = Math.min(attachment.bytes.length, 200_000)
  const bytes = attachment.bytes.subarray(0, limit)
  let text: string
  try {
    text = decodeTextBytes(bytes)
  } catch {
    // Match desktop preview behavior for malformed text: keep the readable
    // portions and replace invalid byte sequences instead of losing the file.
    text = new TextDecoder('utf-8').decode(bytes)
  }
  return attachment.bytes.length > limit ? `${text}\n[附件文本已截断至前 200000 字节]` : text
}

function decodeTextBytes(bytes: Uint8Array): string {
  for (const [encoding, maxTrim] of [['utf-8', 3], ['gb18030', 3], ['utf-16', 1]] as const) {
    let decoder: TextDecoder
    try { decoder = new TextDecoder(encoding, { fatal: true }) }
    catch { continue }
    for (let trim = 0; trim <= Math.min(maxTrim, bytes.length); trim++) {
      try { return decoder.decode(bytes.subarray(0, bytes.length - trim)) }
      catch { /* Try a shorter suffix, then the next desktop-compatible encoding. */ }
    }
  }
  throw new Error('Attachment text is not valid in a supported encoding')
}

function encodeRfc5987Value(value: string): string {
  return encodeURIComponent(value).replace(/[!'()*]/g, character =>
    `%${character.charCodeAt(0).toString(16).toUpperCase()}`)
}

function decodeJson(body: Uint8Array | undefined): Record<string, unknown> {
  if (!body?.length) return {}
  try {
    const value = JSON.parse(new TextDecoder().decode(body))
    return isRecord(value) ? value : {}
  } catch {
    return {}
  }
}

function isRecord(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function finiteNumber(value: unknown): number | undefined {
  if (value == null || value === '') return undefined
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

/**
 * Resolve a turn's thinking level the way the desktop execution controls do.
 *
 * An explicit per-turn `reasoning_level` wins; otherwise the shared stored
 * thinking mode applies, and with nothing stored the desktop default is used.
 * Model capability still downgrades the result, so a model without thinking
 * support stays at `off` while one that cannot disable thinking never reports
 * `off`. Mobile has no level picker of its own, so this keeps it aligned with
 * the desktop rather than silently running every turn with thinking disabled.
 */
function resolveReasoningLevel(
  choice: unknown,
  model: StandaloneModel | null | undefined,
): CoreThinkingMode {
  const mode = normalizeCoreThinkingMode(choice ?? storedThinkingMode())
  // Without a resolved model there is no capability to honour, so keep the
  // chosen level and let the model-aware pass refine it.
  return model ? coreThinkingPayload({ mode, model }).reasoning_level : mode
}

/** Shared desktop thinking-mode key, defaulting to the desktop default. */
function storedThinkingMode(): CoreThinkingMode {
  let storage: Pick<Storage, 'getItem'> | undefined
  try {
    storage = globalThis.localStorage
  } catch {
    storage = undefined
  }
  return readStoredCoreThinkingMode(storage, CORE_EXECUTION_CONTROLS_STORAGE_KEYS.thinkingMode)
}

function normalizePermissionPreset(value: unknown): 'ask' | 'auto' | 'full_access' {
  const normalized = String(value || '').trim().toLowerCase()
  if (normalized === 'auto' || normalized === 'full_access') return normalized
  return 'ask'
}

function normalizeApprovalDecision(
  value: unknown,
): 'approve_once' | 'approve_for_session' | 'deny' | 'other_guidance' {
  const normalized = String(value || '').trim().toLowerCase()
  if (normalized === 'approve_once' || normalized === 'approve' || normalized === 'accept') return 'approve_once'
  if (normalized === 'approve_for_session' || normalized === 'acceptforsession') return 'approve_for_session'
  if (normalized === 'deny' || normalized === 'decline' || normalized === 'cancel') return 'deny'
  return 'other_guidance'
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? [...new Set(value.map(item => String(item || '').trim()).filter(Boolean))]
    : []
}

function asTurnProgress(value: RustTurnProgress | RustTurnResult): RustTurnProgress {
  if (isRecord(value) && ('status' in value)
    && (value.status === 'completed' || value.status === 'approval_required')) {
    return value as RustTurnProgress
  }
  return { status: 'completed', result: value as RustTurnResult }
}

function isNativeCancellationError(message: string): boolean {
  return message.trim().toLowerCase() === 'turn cancelled'
}

function jsonClone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}
