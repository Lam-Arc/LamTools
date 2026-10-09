import { createLamToolsRuntime, type LamToolsRuntime } from '@ui/app/runtime'
import type { CoreAppSnapshot, CoreAppTurn, CoreRuntimeItem, CoreRuntimeTurn } from '@ui/appServer'
import type {
  LamToolsTransport,
  TransportConnectionState,
  TransportHttpRequest,
  TransportHttpResponse,
  TransportMessage,
  TransportRequest,
} from '@ui/transport'

const PROJECT_ID = 'website-core'
const WORK_ROOT = 'E:\\LamTools'
const ACTIVE_SESSION_ID = 'website-session-active'
const DEMO_MODEL_ID = 'website-demo-model'
const DEMO_PROVIDER_ID = 'website-demo-provider'
const DEMO_TIME = '2026-09-17T08:00:00.000Z'

export interface WebsiteMockRequestLogEntry {
  kind: 'http' | 'rpc'
  method: string
  path?: string
  params?: Record<string, unknown>
}

export interface WebsiteMockRuntime extends LamToolsRuntime {
  /** In-memory requests made by the shared app; useful for smoke tests. */
  requestLog: WebsiteMockRequestLogEntry[]
}

interface WebsiteProject {
  id: string
  name: string
  work_root: string
  icon_key: string
  color_key: string
  created_at: string
  updated_at: string
}

interface WebsiteSession {
  id: string
  title: string
  status: string
  created_at: string
  updated_at: string
  metadata: Record<string, unknown>
}

interface DemoFile {
  name: string
  type: 'file' | 'directory'
  size: number
  ext: string
  content?: string
}

const PROJECT: WebsiteProject = {
  id: PROJECT_ID,
  name: 'LamTools Core',
  work_root: WORK_ROOT,
  icon_key: 'code',
  color_key: 'cyan',
  created_at: DEMO_TIME,
  updated_at: DEMO_TIME,
}

const INITIAL_SESSIONS: WebsiteSession[] = [
  {
    id: ACTIVE_SESSION_ID,
    title: '梳理 Core 的执行链路',
    status: 'completed',
    created_at: DEMO_TIME,
    updated_at: DEMO_TIME,
    metadata: {
      work_root: WORK_ROOT,
      model_id: DEMO_MODEL_ID,
      runtime_preferences: { permission_preset: 'ask' },
    },
  },
  {
    id: 'website-session-tools',
    title: '工具调用与审批记录',
    status: 'completed',
    created_at: '2026-09-16T09:30:00.000Z',
    updated_at: '2026-09-16T10:10:00.000Z',
    metadata: { work_root: WORK_ROOT, model_id: DEMO_MODEL_ID },
  },
  {
    id: 'website-session-empty',
    title: '新的工程任务',
    status: 'idle',
    created_at: '2026-09-15T14:20:00.000Z',
    updated_at: '2026-09-15T14:20:00.000Z',
    metadata: { work_root: WORK_ROOT, model_id: DEMO_MODEL_ID },
  },
]

const DEMO_FILES: Record<string, DemoFile> = {
  'README.md': {
    name: 'README.md',
    type: 'file',
    ext: 'md',
    content: '# LamTools\n\nSunday is a local-first Agent workspace.\n',
    size: 53,
  },
  'core': { name: 'core', type: 'directory', ext: '', size: 0 },
  'website': { name: 'website', type: 'directory', ext: '', size: 0 },
  'core/ui': { name: 'ui', type: 'directory', ext: '', size: 0 },
  'core/src': { name: 'src', type: 'directory', ext: '', size: 0 },
}

const DEMO_USER_TEXT = '请梳理一下 Core 的执行链路，并指出 UI 如何拿到实时状态。'
const DEMO_ANSWER =
  'Core 由 transport、App Server 状态投影与共享 UI 三层组成：transport 负责连接，App Server 将 turn 与 tool 事件归一化为快照，Workbench 再把快照投影成消息与运行状态。这样桌面端与网站展示可以复用同一套 LamToolsApp。'

/**
 * Create a self-contained website runtime for the real shared application.
 * Every boundary below is resolved in memory; no browser-origin request is
 * needed to render the product preview.
 */
export function createWebsiteMockRuntime(): WebsiteMockRuntime {
  const requestLog: WebsiteMockRequestLogEntry[] = []
  const sessions = INITIAL_SESSIONS.map((session) => clone(session))
  const snapshots = new Map<string, CoreAppSnapshot>()
  const settings = new Map<string, Record<string, unknown>>([
    ['core.runtimeControls', {
      permission_mode: 'full_edit',
      permission_preset: 'ask',
      allow_access_outside_workdir: false,
    }],
    ['core.onboarding', { completed: true, version: 1 }],
  ])
  const providers: Array<Record<string, unknown>> = [{
    id: DEMO_PROVIDER_ID,
    name: 'Website demo provider',
    api_type: 'openai_compatible',
    base_url: '',
    has_api_key: false,
  }]
  const models: Array<Record<string, unknown>> = [{
    id: DEMO_MODEL_ID,
    provider_id: DEMO_PROVIDER_ID,
    model_id: DEMO_MODEL_ID,
    display_name: 'Sunday Demo Model',
    context_window: 1_048_576,
    max_output_tokens: 16_384,
    thinking_supported: true,
    thinking_budget: 8_192,
    reasoning_off_supported: true,
    temperature: 0.2,
  }]

  const transport = createWebsiteTransport({
    requestLog,
    sessions,
    providers,
    models,
    settings,
    snapshots,
  })

  const runtime = createLamToolsRuntime({
    transport,
    platform: 'web',
    capabilities: {
      filePicker: false,
      notifications: false,
      desktopWindow: false,
    },
  }) as WebsiteMockRuntime
  runtime.requestLog = requestLog
  return runtime
}

/** Alias for consumers that prefer a named website-preview constructor. */
export const createWebsitePreviewRuntime = createWebsiteMockRuntime

export default createWebsiteMockRuntime

interface WebsiteTransportState {
  requestLog: WebsiteMockRequestLogEntry[]
  sessions: WebsiteSession[]
  providers: Array<Record<string, unknown>>
  models: Array<Record<string, unknown>>
  settings: Map<string, Record<string, unknown>>
  snapshots: Map<string, CoreAppSnapshot>
}

function createWebsiteTransport(state: WebsiteTransportState): LamToolsTransport {
  let connectionState: TransportConnectionState = 'disconnected'
  const subscribers = new Set<(message: TransportMessage) => void>()
  const stateSubscribers = new Set<(value: TransportConnectionState) => void>()

  const publishState = (value: TransportConnectionState) => {
    connectionState = value
    for (const subscriber of stateSubscribers) subscriber(value)
  }

  return {
    async connect() {
      if (connectionState === 'connected') return
      publishState('connecting')
      publishState('connected')
    },
    close() {
      if (connectionState !== 'disconnected') publishState('disconnected')
    },
    async request<TResponse = unknown>(request: TransportRequest): Promise<TResponse> {
      if (request.kind === 'http') {
        state.requestLog.push({ kind: 'http', method: request.method, path: request.path })
        return await handleHttpRequest(request, state) as TResponse
      }
      state.requestLog.push({ kind: 'rpc', method: request.method, params: request.params })
      return await handleRpcRequest(request.method, request.params || {}, state) as TResponse
    },
    send(message) {
      // Outbound notifications are intentionally accepted as safe no-ops.
      for (const subscriber of subscribers) subscriber(message)
    },
    subscribe(handler) {
      subscribers.add(handler)
      return () => subscribers.delete(handler)
    },
    onState(handler) {
      stateSubscribers.add(handler)
      handler(connectionState)
      return () => stateSubscribers.delete(handler)
    },
    getState() {
      return connectionState
    },
  }
}

async function handleRpcRequest(
  method: string,
  params: Record<string, unknown>,
  state: WebsiteTransportState,
): Promise<Record<string, unknown>> {
  if (method === 'initialize') {
    return {
      protocolVersion: 'core.app_server.v1',
      serverInfo: { name: 'Sunday website preview', version: '0.3.12' },
    }
  }

  const threadId = stringValue(params.thread_id || params.threadId) || ACTIVE_SESSION_ID
  if (method === 'thread/resume' || method === 'thread/read') {
    const snapshot = getSnapshot(threadId, state.snapshots)
    return {
      thread: { thread_id: threadId, status: snapshot.status },
      events: [],
      has_more: false,
      next_after_seq: snapshot.snapshot_seq,
      snapshot,
    }
  }
  if (method === 'thread/history') {
    const snapshot = getSnapshot(threadId, state.snapshots)
    return { snapshot_page: snapshot }
  }
  if (method === 'command.catalog') return { commands: [] }
  if (method === 'plugin.ui.list' || method === 'plugin.widget.list') {
    return { modes: [], widgets: [], entries: [] }
  }
  if (method === 'config.providers.list') return { providers: state.providers.map(clone) }
  if (method === 'config.models.list') {
    return { models: state.models.map(clone), default_model_id: DEMO_MODEL_ID }
  }
  if (method === 'settings.get') {
    const namespace = stringValue(params.namespace)
    return { namespace, value: clone(state.settings.get(namespace) || {}) }
  }
  if (method === 'settings.update') {
    const namespace = stringValue(params.namespace)
    const value = isRecord(params.value) ? clone(params.value) : {}
    state.settings.set(namespace, value)
    return { namespace, value }
  }
  if (method === 'session.permissions.set') return updateSessionPermissions(params, state)
  if (method === 'config.provider.create') return createProvider(params, state)
  if (method === 'config.provider.update') return updateProvider(params, state)
  if (method === 'config.provider.delete') return deleteProvider(params, state)
  if (method === 'config.models.upsert') return upsertModel(params, state)
  if (method === 'config.models.delete') return deleteModel(params, state)
  if (method === 'config.models.set_default') return { ok: true, default_model_id: params.model_id }

  if (method === 'goal.list') return { goals: [] }
  if (method === 'goal.update') return { goal: null }
  if (method === 'sub_agent.list' || method === 'sub_agent.snapshot') return { runs: [] }
  if (method === 'arrange.list' || method === 'arrange.occurrence.list') {
    return method.endsWith('occurrence.list') ? { occurrences: [] } : { jobs: [] }
  }
  if (method === 'websearch.config.get') return { content: '{"provider":"baidu"}' }
  if (method === 'websearch.config.update') return { ok: true }
  if (method === 'websearch.widget.snapshot') {
    return { snapshot: { state: 'disabled', summary: '网站预览未连接搜索服务。', blocks: [] } }
  }
  if (method === 'websearch.widget.health') return { state: 'disabled', error: '网站预览未连接搜索服务。' }
  if (method === 'rag.docs.search') return { results: [] }
  if (method === 'artifact.list') return { artifacts: [] }
  if (method === 'update.check') return {
    status: 'up_to_date',
    current_version: '0.3.12',
    latest_version: '0.3.12',
    source: 'github',
  }

  // Mutating App Server calls remain harmless and return the current state so
  // accidental interaction in the preview never surfaces a connection error.
  if (
    method === 'thread/start'
    || method === 'turn/start'
    || method === 'turn/steer'
    || method === 'turn/interrupt'
    || method === 'turn/force_reset'
    || method === 'approval/respond'
    || method === 'queue/create'
    || method === 'queue/update'
    || method === 'queue/delete'
    || method === 'queue/guide'
    || method === 'command.execute'
    || method.startsWith('session.')
  ) {
    return { ok: true, applied: false, snapshot: getSnapshot(threadId, state.snapshots) }
  }

  return { ok: true }
}

async function handleHttpRequest(
  request: TransportHttpRequest,
  state: WebsiteTransportState,
): Promise<TransportHttpResponse> {
  const [rawPath, rawQuery = ''] = request.path.split('?', 2)
  const path = rawPath.replace(/\/+$/, '') || '/'
  const query = new URLSearchParams(rawQuery)
  const body = parseJsonBody(request.body)

  if (request.method === 'GET' && path === '/projects') return jsonResponse({ projects: [clone(PROJECT)] })
  if (request.method === 'GET' && path === '/sessions') return jsonResponse(state.sessions.map(clone))
  if (path === '/browse-directory') {
    return jsonResponse({ path: query.get('path') || '', entries: listFiles('') })
  }

  const projectMatch = path.match(/^\/projects\/([^/]+)(?:\/(.*))?$/)
  if (projectMatch) {
    const projectId = decodeURIComponent(projectMatch[1])
    const suffix = projectMatch[2] || ''
    if (projectId !== PROJECT_ID) return jsonResponse({ error: '项目不存在' }, 404)
    if (!suffix && request.method === 'GET') return jsonResponse(clone(PROJECT))
    if (!suffix && (request.method === 'PATCH' || request.method === 'PUT')) {
      if (typeof body.name === 'string') PROJECT.name = body.name
      if (typeof body.icon_key === 'string') PROJECT.icon_key = body.icon_key
      if (typeof body.color_key === 'string') PROJECT.color_key = body.color_key
      return jsonResponse(clone(PROJECT))
    }
    if (!suffix && request.method === 'DELETE') return emptyResponse()
    if (suffix === 'sessions' && request.method === 'GET') {
      return jsonResponse({ sessions: state.sessions.filter(session => session.metadata.work_root === WORK_ROOT).map(clone) })
    }
    if (suffix === 'sessions' && request.method === 'POST') {
      const session = createSession(typeof body.title === 'string' ? body.title : 'New Session', state)
      return jsonResponse(session, 201)
    }
    if (suffix === 'agents-md' && request.method === 'GET') {
      return jsonResponse({ content: '# Website preview\n', exists: true })
    }
    if (suffix === 'agents-md' && request.method === 'PUT') {
      return jsonResponse({ content: typeof body.content === 'string' ? body.content : '', exists: true })
    }
    if (suffix === 'files' && request.method === 'GET') {
      return jsonResponse({ path: query.get('path') || '', entries: listFiles(query.get('path') || '') })
    }
    if (suffix === 'files/content' && request.method === 'GET') {
      const file = DEMO_FILES[query.get('path') || '']
      return file ? jsonResponse({ path: query.get('path') || '', content: file.content || '' }) : jsonResponse({ error: '文件不存在' }, 404)
    }
    if (suffix === 'files/content' && (request.method === 'PUT' || request.method === 'PATCH')) {
      const filePath = query.get('path') || ''
      const content = typeof body.content === 'string' ? body.content : ''
      DEMO_FILES[filePath] = { name: filePath.split('/').pop() || filePath, type: 'file', ext: extension(filePath), size: content.length, content }
      return jsonResponse({ path: filePath, content })
    }
    if (suffix === 'files/raw' && request.method === 'GET') {
      const file = DEMO_FILES[query.get('path') || '']
      return file ? bytesResponse(file.content || '') : jsonResponse({ error: '文件不存在' }, 404)
    }
  }

  const sessionMatch = path.match(/^\/sessions\/([^/]+)$/)
  if (sessionMatch) {
    const sessionId = decodeURIComponent(sessionMatch[1])
    const session = state.sessions.find(item => item.id === sessionId)
    if (!session) return jsonResponse({ error: '会话不存在' }, 404)
    if (request.method === 'GET') return jsonResponse(clone(session))
    if (request.method === 'PATCH' || request.method === 'PUT') {
      if (typeof body.title === 'string') session.title = body.title
      if (isRecord(body.metadata)) session.metadata = { ...session.metadata, ...clone(body.metadata) }
      session.updated_at = DEMO_TIME
      return jsonResponse(clone(session))
    }
    if (request.method === 'DELETE') {
      state.sessions.splice(state.sessions.indexOf(session), 1)
      return emptyResponse()
    }
  }

  return jsonResponse({ ok: true })
}

function getSnapshot(threadId: string, snapshots: Map<string, CoreAppSnapshot>): CoreAppSnapshot {
  const existing = snapshots.get(threadId)
  if (existing) return existing
  const snapshot = buildDemoSnapshot(threadId)
  snapshots.set(threadId, snapshot)
  return snapshot
}

function buildDemoSnapshot(threadId: string): CoreAppSnapshot {
  const turnId = `${threadId}:turn:demo`
  const userId = `${threadId}:user:demo`
  const reasoningId = `${threadId}:reasoning:demo`
  const toolId = `${threadId}:tool:demo`
  const commandId = `${threadId}:command:demo`
  const answerId = `${threadId}:answer:demo`
  const userItem = {
    item_id: userId,
    turn_id: turnId,
    type: 'userMessage',
    status: 'completed',
    seq: 1,
    content: [{ type: 'text', text: DEMO_USER_TEXT }],
  }
  const reasoning: CoreRuntimeItem = {
    item_id: reasoningId,
    turn_id: turnId,
    kind: 'thinking',
    status: 'completed',
    seq: 2,
    content: '先看 transport、快照投影与 UI 挂载边界，再串起一条可读的执行链路。',
    payload: { type: 'reasoning' },
  }
  const tool: CoreRuntimeItem = {
    item_id: toolId,
    turn_id: turnId,
    kind: 'tool_call',
    status: 'completed',
    seq: 3,
    content: 'README.md 与 core/ui/src/appServer',
    payload: {
      type: 'dynamicToolCall',
      tool_name: 'read_file',
      arguments: { path: 'README.md' },
      metadata: { title: '读取项目说明' },
    },
  }
  const command: CoreRuntimeItem = {
    item_id: commandId,
    turn_id: turnId,
    kind: 'tool_call',
    status: 'completed',
    seq: 4,
    content: 'core/ui/src/appServer → runtime projection',
    payload: {
      type: 'commandExecution',
      tool_name: 'run_command',
      arguments: { command: 'tree core/ui/src/appServer' },
    },
  }
  const answer: CoreRuntimeItem = {
    item_id: answerId,
    turn_id: turnId,
    kind: 'agentMessage',
    status: 'completed',
    seq: 5,
    content: DEMO_ANSWER,
    payload: {
      type: 'agentMessage',
      metadata: { final: true },
    },
  }
  const coreItems: Record<string, CoreRuntimeItem> = {
    [reasoningId]: reasoning,
    [toolId]: tool,
    [commandId]: command,
    [answerId]: answer,
  }
  const input = [{ type: 'text' as const, text: DEMO_USER_TEXT }]
  const turn: CoreAppTurn = {
    turn_id: turnId,
    status: 'completed',
    seq: 1,
    last_seq: 5,
    items: [userId],
    created_at: DEMO_TIME,
    input,
    context_metrics: {
      estimated_prompt_tokens: 4_812,
      context_window_tokens: 1_048_576,
      model_id: DEMO_MODEL_ID,
    },
    runtime_snapshot: {
      model_id: DEMO_MODEL_ID,
      active_mode: 'execute',
      reasoning_level: 'high',
      permission_preset: 'ask',
      context_window_tokens: 1_048_576,
    },
  }
  return {
    thread_id: threadId,
    snapshot_seq: 5,
    revision: 1,
    seen_event_ids: [],
    turns: { [turnId]: turn },
    items: { [userId]: userItem },
    item_order: [userId],
    queue: [],
    requests: {},
    artifacts: {},
    status: 'completed',
    history_page: {
      char_limit: 200_000,
      character_count: DEMO_USER_TEXT.length + DEMO_ANSWER.length,
      turn_limit: 10,
      turn_count: 1,
      item_count: 5,
      total_items: 5,
      has_more: false,
      next_before_item_id: null,
      next_before_seq: null,
    },
    core: {
      thread_id: threadId,
      snapshot_seq: 5,
      revision: 1,
      seen_event_ids: [],
      turns: { [turnId]: { ...turn, items: [reasoningId, toolId, commandId, answerId] } satisfies CoreRuntimeTurn },
      items: coreItems,
      item_order: [reasoningId, toolId, commandId, answerId],
      requests: {},
      artifacts: {},
      status: 'completed',
    },
  }
}

function createSession(title: string, state: WebsiteTransportState): WebsiteSession {
  const session: WebsiteSession = {
    id: `website-session-${state.sessions.length + 1}`,
    title,
    status: 'idle',
    created_at: DEMO_TIME,
    updated_at: DEMO_TIME,
    metadata: { work_root: WORK_ROOT, model_id: DEMO_MODEL_ID },
  }
  state.sessions.push(session)
  return session
}

function updateSessionPermissions(params: Record<string, unknown>, state: WebsiteTransportState): Record<string, unknown> {
  const threadId = stringValue(params.thread_id)
  const session = state.sessions.find(item => item.id === threadId)
  if (!session) return { ok: true }
  const runtimePreferences = isRecord(session.metadata.runtime_preferences)
    ? session.metadata.runtime_preferences
    : {}
  session.metadata.runtime_preferences = {
    ...runtimePreferences,
    permission_preset: stringValue(params.permission_preset) || 'ask',
  }
  return { session: clone(session) }
}

function createProvider(params: Record<string, unknown>, state: WebsiteTransportState): Record<string, unknown> {
  const provider = {
    id: stringValue(params.id) || `website-provider-${state.providers.length + 1}`,
    name: stringValue(params.name) || 'Website provider',
    api_type: stringValue(params.api_type) || 'openai_compatible',
    base_url: stringValue(params.base_url),
    has_api_key: Boolean(params.api_key),
  }
  state.providers.push(provider)
  return { provider }
}

function updateProvider(params: Record<string, unknown>, state: WebsiteTransportState): Record<string, unknown> {
  const id = stringValue(params.provider_id || params.id)
  const provider = state.providers.find(item => item.id === id)
  if (provider) Object.assign(provider, params)
  return { provider: provider || params }
}

function deleteProvider(params: Record<string, unknown>, state: WebsiteTransportState): Record<string, unknown> {
  const id = stringValue(params.provider_id || params.id)
  const index = state.providers.findIndex(item => item.id === id)
  if (index >= 0) state.providers.splice(index, 1)
  return { ok: true }
}

function upsertModel(params: Record<string, unknown>, state: WebsiteTransportState): Record<string, unknown> {
  const id = stringValue(params.model_id || params.id) || `website-model-${state.models.length + 1}`
  const model = { ...params, id, model_id: id }
  const index = state.models.findIndex(item => item.id === id)
  if (index >= 0) state.models[index] = model
  else state.models.push(model)
  return { model }
}

function deleteModel(params: Record<string, unknown>, state: WebsiteTransportState): Record<string, unknown> {
  const id = stringValue(params.model_id || params.id)
  const index = state.models.findIndex(item => item.id === id)
  if (index >= 0) state.models.splice(index, 1)
  return { ok: true }
}

function listFiles(path: string): DemoFile[] {
  const prefix = path ? `${path.replace(/\/+$/, '')}/` : ''
  const seen = new Set<string>()
  const entries: DemoFile[] = []
  for (const [filePath, file] of Object.entries(DEMO_FILES)) {
    if (!filePath.startsWith(prefix)) continue
    const remainder = filePath.slice(prefix.length)
    const name = remainder.split('/')[0]
    if (seen.has(name)) continue
    seen.add(name)
    const child = filePath === `${prefix}${name}` ? file : { name, type: 'directory' as const, size: 0, ext: '' }
    entries.push({ ...child, name })
  }
  return entries.sort((a, b) => Number(b.type === 'directory') - Number(a.type === 'directory') || a.name.localeCompare(b.name))
}

function parseJsonBody(body: Uint8Array | undefined): Record<string, unknown> {
  if (!body?.length) return {}
  try {
    const value: unknown = JSON.parse(new TextDecoder().decode(body))
    return isRecord(value) ? value : {}
  } catch {
    return {}
  }
}

function jsonResponse(value: unknown, status = 200): TransportHttpResponse {
  return {
    status,
    headers: { 'content-type': 'application/json' },
    body: new TextEncoder().encode(JSON.stringify(value)),
  }
}

function bytesResponse(value: string): TransportHttpResponse {
  return {
    status: 200,
    headers: { 'content-type': 'text/plain; charset=utf-8' },
    body: new TextEncoder().encode(value),
  }
}

function emptyResponse(): TransportHttpResponse {
  return { status: 204, headers: {}, body: new Uint8Array() }
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function extension(path: string): string {
  const value = path.split('/').pop() || ''
  const index = value.lastIndexOf('.')
  return index > 0 ? value.slice(index + 1).toLowerCase() : ''
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function clone<T>(value: T): T {
  if (value === undefined || value === null) return value
  return JSON.parse(JSON.stringify(value)) as T
}
