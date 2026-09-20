import { Capacitor, CapacitorHttp } from '@capacitor/core'
import type {
  CoreAppInputItem,
  CoreAppSnapshot,
  LamToolsTransport,
  TransportConnectionState,
  TransportHttpRequest,
  TransportHttpResponse,
  TransportMessage,
  TransportRequest,
} from '@lamtools/ui'
import type { LocalRepository, LocalThread } from '../storage'
import { StandaloneConfigStore } from './StandaloneConfigStore'

type SnapshotWithSession = CoreAppSnapshot & {
  session?: { id: string; title: string; metadata: Record<string, unknown>; created_at: string; updated_at: string }
}

export class StandaloneTransport implements LamToolsTransport {
  private state: TransportConnectionState = 'disconnected'
  private readonly stateListeners = new Set<(state: TransportConnectionState) => void>()
  private readonly messageListeners = new Set<(message: TransportMessage) => void>()
  private readonly aborts = new Map<string, AbortController>()
  private readonly generations = new Map<string, number>()

  constructor(
    private readonly repository: LocalRepository,
    private readonly config: StandaloneConfigStore = new StandaloneConfigStore(),
  ) {}

  async connect(): Promise<void> {
    await this.repository.init()
    this.setState('connected')
  }

  async close(): Promise<void> {
    for (const controller of this.aborts.values()) controller.abort()
    this.aborts.clear()
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
    if (method === 'initialize') return { protocol_version: 'core.app_server.v1', capabilities: { standalone: true } }
    if (method === 'thread/resume') {
      const threadId = String(params.thread_id || '')
      return { snapshot: await this.snapshotFor(threadId) }
    }
    if (method === 'thread.history') {
      const threadId = String(params.thread_id || '')
      return { snapshot_page: await this.snapshotFor(threadId) }
    }
    if (method === 'command.catalog') return { commands: [] }
    if (method === 'turn/start') return await this.startTurn(params)
    if (method === 'turn/interrupt' || method === 'turn/force_reset') {
      return await this.interruptTurn(String(params.thread_id || ''))
    }
    if (method === 'queue/create' || method === 'turn/steer') {
      throw new Error('移动端独立模式暂不支持该操作')
    }
    if (method === 'session.permissions.set') return { ok: true }
    if (method === 'sync.start') return { ok: false, error: '本地模式无需同步' }
    return { ok: false, error: `移动端独立模式不支持 ${method}` }
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
      if (segments[2] === 'attachments' && request.method === 'POST') {
        return jsonResponse({
          id: globalThis.crypto?.randomUUID?.() || `attachment-${Date.now()}`,
          filename: multipartFilename(request.body) || '移动端附件',
          mime_type: request.headers?.['Content-Type'] || 'application/octet-stream',
          size: request.body?.byteLength || 0,
          preview_type: 'file',
        }, 201)
      }
    }
    return jsonResponse({ error: '设备拒绝了您的请求' }, 403)
  }

  private async startTurn(params: Record<string, unknown>): Promise<Record<string, unknown>> {
    const threadId = String(params.thread_id || '')
    if (!threadId) throw new Error('会话不存在')
    const snapshot = await this.snapshotFor(threadId)
    const turnId = globalThis.crypto?.randomUUID?.() || `turn-${Date.now()}`
    const userItemId = `${turnId}:user`
    const assistantItemId = `${turnId}:assistant`
    const input = Array.isArray(params.input) ? params.input as CoreAppInputItem[] : []
    const sequence = Number(snapshot.snapshot_seq || 0) + 1
    const core = snapshot.core!
    core.turns = {
      ...(core.turns || {}),
      [turnId]: { turn_id: turnId, status: 'running', items: [userItemId, assistantItemId], seq: sequence },
    }
    core.items = {
      ...(core.items || {}),
      [userItemId]: {
        item_id: userItemId,
        turn_id: turnId,
        kind: 'message',
        status: 'completed',
        seq: sequence,
        payload: { type: 'userMessage', content: input },
      },
      [assistantItemId]: {
        item_id: assistantItemId,
        turn_id: turnId,
        kind: 'message',
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
    await this.repository.saveLocalSnapshot(snapshot)
    this.emitSnapshot(snapshot)

    const generation = (this.generations.get(threadId) || 0) + 1
    this.generations.set(threadId, generation)
    void this.completeTurn(snapshot, turnId, assistantItemId, String(params.model_id || ''), generation)
    return { accepted: true, turn_id: turnId, revision: snapshot.revision }
  }

  private async completeTurn(
    snapshot: SnapshotWithSession,
    turnId: string,
    assistantItemId: string,
    modelId: string,
    generation: number,
  ): Promise<void> {
    const threadId = snapshot.thread_id
    const controller = new AbortController()
    this.aborts.set(threadId, controller)
    try {
      const answer = await this.requestModel(snapshot, modelId, controller.signal)
      if (this.generations.get(threadId) !== generation) return
      this.finishSnapshot(snapshot, turnId, assistantItemId, answer, 'completed')
    } catch (error) {
      if (this.generations.get(threadId) !== generation) return
      const message = error instanceof Error ? error.message : String(error)
      this.finishSnapshot(snapshot, turnId, assistantItemId, message, controller.signal.aborted ? 'cancelled' : 'failed')
    } finally {
      if (this.aborts.get(threadId) === controller) this.aborts.delete(threadId)
    }
    await this.repository.saveLocalSnapshot(snapshot)
    this.emitSnapshot(snapshot)
  }

  private finishSnapshot(
    snapshot: SnapshotWithSession,
    turnId: string,
    assistantItemId: string,
    content: string,
    status: 'completed' | 'failed' | 'cancelled',
  ): void {
    const core = snapshot.core!
    const item = core.items?.[assistantItemId]
    if (item) {
      item.status = status === 'completed' ? 'completed' : status
      item.content = content
      item.payload = { ...(isRecord(item.payload) ? item.payload : {}), type: 'agentMessage', content }
    }
    const turn = core.turns?.[turnId]
    if (turn) turn.status = status
    core.status = status
    snapshot.status = status
    snapshot.snapshot_seq = Number(snapshot.snapshot_seq || 0) + 1
    core.snapshot_seq = snapshot.snapshot_seq
    snapshot.revision = Number(snapshot.revision || 0) + 1
    core.revision = snapshot.revision
  }

  private async interruptTurn(threadId: string): Promise<Record<string, unknown>> {
    this.generations.set(threadId, (this.generations.get(threadId) || 0) + 1)
    this.aborts.get(threadId)?.abort()
    this.aborts.delete(threadId)
    const snapshot = await this.snapshotFor(threadId)
    const core = snapshot.core!
    for (const turn of Object.values(core.turns || {})) {
      if (turn.status === 'running' || turn.status === 'waiting') turn.status = 'cancelled'
    }
    for (const item of Object.values(core.items || {})) {
      if (item.status === 'running') item.status = 'cancelled'
    }
    core.status = 'cancelled'
    snapshot.status = 'cancelled'
    snapshot.snapshot_seq = Number(snapshot.snapshot_seq || 0) + 1
    core.snapshot_seq = snapshot.snapshot_seq
    snapshot.revision = Number(snapshot.revision || 0) + 1
    core.revision = snapshot.revision
    await this.repository.saveLocalSnapshot(snapshot)
    this.emitSnapshot(snapshot)
    return { snapshot }
  }

  private async requestModel(snapshot: SnapshotWithSession, requestedModelId: string, signal: AbortSignal): Promise<string> {
    const { provider, model, apiKey } = await this.config.activeModel(requestedModelId)
    const messages = conversationMessages(snapshot)
    const baseUrl = provider.base_url.replace(/\/$/, '')
    const anthropic = provider.api_type.toLowerCase().includes('anthropic')
    const url = anthropic ? `${baseUrl}/messages` : `${baseUrl}/chat/completions`
    const headers: Record<string, string> = anthropic
      ? { 'Content-Type': 'application/json', 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' }
      : { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` }
    const body = anthropic
      ? { model: model.model_id, messages, max_tokens: model.max_output_tokens || 4096 }
      : { model: model.model_id, messages, stream: false, temperature: model.temperature }

    if (Capacitor.isNativePlatform()) {
      const response = await CapacitorHttp.post({ url, headers, data: body, connectTimeout: 30_000, readTimeout: 180_000 })
      if (response.status < 200 || response.status >= 300) throw new Error(apiError(response.data, response.status))
      return responseText(response.data, anthropic)
    }
    const response = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body), signal })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(apiError(data, response.status))
    return responseText(data, anthropic)
  }

  private async snapshotFor(threadId: string): Promise<SnapshotWithSession> {
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

function conversationMessages(snapshot: CoreAppSnapshot): Array<{ role: 'user' | 'assistant'; content: string }> {
  const core = snapshot.core
  if (!core) return []
  const messages: Array<{ role: 'user' | 'assistant'; content: string }> = []
  for (const id of core.item_order || []) {
    const item = core.items?.[id]
    const payload = isRecord(item?.payload) ? item.payload : {}
    if (payload.type === 'userMessage') {
      const input = Array.isArray(payload.content) ? payload.content : []
      const content = input.map((part) => {
        if (!isRecord(part)) return ''
        if (part.type === 'text') return String(part.text || '')
        if (part.type === 'attachment') return `[附件: ${String(part.filename || part.attachment_id || '')}]`
        return ''
      }).filter(Boolean).join('\n')
      if (content) messages.push({ role: 'user', content })
      continue
    }
    if (payload.type === 'agentMessage') {
      const content = String(payload.content || item?.content || '')
      if (content) messages.push({ role: 'assistant', content })
    }
  }
  return messages
}

function responseText(data: unknown, anthropic: boolean): string {
  if (!isRecord(data)) throw new Error('模型返回了无效响应')
  if (anthropic) {
    const content = Array.isArray(data.content) ? data.content : []
    const text = content.filter(isRecord).map((item) => String(item.text || '')).join('')
    if (text) return text
  } else {
    const choices = Array.isArray(data.choices) ? data.choices : []
    const first = choices.find(isRecord)
    const message = first && isRecord(first.message) ? first.message : {}
    const text = String(message.content || '')
    if (text) return text
  }
  throw new Error('模型未返回文本')
}

function apiError(data: unknown, status: number): string {
  if (isRecord(data)) {
    const error = isRecord(data.error) ? data.error : data
    if (error.message) return String(error.message)
  }
  return `模型请求失败（${status}）`
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

function decodeJson(body: Uint8Array | undefined): Record<string, unknown> {
  if (!body?.length) return {}
  try {
    const value = JSON.parse(new TextDecoder().decode(body))
    return isRecord(value) ? value : {}
  } catch {
    return {}
  }
}

function multipartFilename(body: Uint8Array | undefined): string {
  if (!body?.length) return ''
  const prefix = new TextDecoder().decode(body.slice(0, Math.min(body.length, 2048)))
  return /filename="([^"]+)"/.exec(prefix)?.[1] || ''
}

function isRecord(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function jsonClone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}
