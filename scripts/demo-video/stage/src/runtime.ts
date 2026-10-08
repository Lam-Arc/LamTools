/* The stage's backend.
 *
 * Same trick the website's product preview uses: the real application is given
 * a transport that answers every boundary in memory, so the whole UI mounts
 * and behaves normally with no server behind it. The difference here is that
 * nothing is hard-coded — `setState` is called before every frame, and
 * `pushSnapshot` delivers the conversation as the product's own live-update
 * notification (`thread/snapshot`), which is the same path the real backend
 * uses while a turn is running.
 */

import { createLamToolsRuntime, type LamToolsRuntime } from '@ui/app/runtime'
import type {
  LamToolsTransport,
  TransportConnectionState,
  TransportHttpRequest,
  TransportHttpResponse,
  TransportMessage,
  TransportRequest,
} from '@ui/transport'
import { REAL_CATALOG, REAL_STATS } from './catalog.generated'
import { REAL_THUMBS } from './thumbs.generated'

export interface StageState {
  projects: Record<string, unknown>[]
  sessions: Record<string, unknown>[]
  models: Record<string, unknown>[]
  providers: Record<string, unknown>[]
  settings: Map<string, Record<string, unknown>>
  /** the newest snapshot, returned by thread/resume and thread/history */
  snapshot: unknown
  defaultModelId: string
}

export interface StageBackend {
  runtime: LamToolsRuntime
  state: StageState
  /** the app-server live update: replaces the thread state on screen */
  pushSnapshot(snapshot: unknown): void
  /** a session changed (title, status) outside a turn */
  pushSessionUpdate(session: Record<string, unknown>): void
  /** anything else the product listens for, e.g. session/created */
  push(method: string, params: Record<string, unknown>): void
  disconnect(): void
}

export function createStageBackend(): StageBackend {
  const state: StageState = {
    projects: [],
    sessions: [],
    models: [],
    providers: [],
    settings: new Map([
      ['core.runtimeControls', {
        permission_mode: 'full_edit',
        permission_preset: 'ask',
        allow_access_outside_workdir: false,
      }],
      ['core.onboarding', { completed: true, version: 1 }],
    ]),
    snapshot: null,
    defaultModelId: '',
  }

  const subscribers = new Set<(message: TransportMessage) => void>()
  const stateSubscribers = new Set<(value: TransportConnectionState) => void>()
  let connectionState: TransportConnectionState = 'disconnected'

  const publishState = (value: TransportConnectionState) => {
    connectionState = value
    for (const subscriber of stateSubscribers) subscriber(value)
  }

  const emit = (message: TransportMessage) => {
    for (const subscriber of subscribers) subscriber(message)
  }

  const transport: LamToolsTransport = {
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
        return (await handleHttp(request, state)) as TResponse
      }
      return (await handleRpc(request.method, request.params || {}, state)) as TResponse
    },
    send() {
      // Outbound notifications (queue guides, approvals) are accepted and
      // ignored: the picture is driven from the outside, never by the UI.
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

  const runtime = createLamToolsRuntime({
    transport,
    platform: 'web',
    capabilities: { filePicker: false, notifications: false, desktopWindow: false },
  })

  return {
    runtime,
    state,
    pushSnapshot(snapshot) {
      state.snapshot = snapshot
      emit({ type: 'notification', channel: 'rpc', method: 'thread/snapshot', params: snapshot as Record<string, unknown> })
    },
    pushSessionUpdate(session) {
      emit({ type: 'notification', channel: 'rpc', method: 'session/updated', params: { session } })
    },
    push(method, params) {
      emit({ type: 'notification', channel: 'rpc', method, params })
    },
    disconnect() {
      publishState('disconnected')
    },
  }
}

/* ------------------------------------------------------------------ rpc ---- */

async function handleRpc(
  method: string,
  params: Record<string, unknown>,
  state: StageState,
): Promise<Record<string, unknown>> {
  if (method === 'initialize') {
    return {
      protocolVersion: 'core.app_server.v1',
      serverInfo: { name: 'Sunday stage', version: '0.0.0' },
    }
  }

  const threadId = stringValue(params.thread_id || params.threadId) || stringValue(state.sessions[0]?.id)
  if (method === 'thread/resume' || method === 'thread/read') {
    return {
      thread: { thread_id: threadId, status: 'idle' },
      events: [],
      has_more: false,
      next_after_seq: 0,
      snapshot: state.snapshot,
    }
  }
  if (method === 'thread/history') return { snapshot_page: state.snapshot }

  if (method === 'command.catalog') return { commands: [] }
  if (method === 'plugin.ui.list' || method === 'plugin.widget.list') {
    return { modes: [], widgets: [], entries: [] }
  }
  if (method === 'config.providers.list') return { providers: clone(state.providers) }
  if (method === 'config.models.list') {
    return { models: clone(state.models), default_model_id: state.defaultModelId }
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

  if (method === 'goal.list') return { goals: [] }
  if (method === 'goal.update') return { goal: null }
  if (method === 'sub_agent.list' || method === 'sub_agent.snapshot') return { runs: [] }
  // 定时任务那一屏：给一条任务，让产品自己把卡片、时间与状态画出来
  if (method === 'arrange.list') {
    return {
      jobs: [{
        id: 'film-arrange-1',
        thread_id: 'film-arrange-thread',
        source_thread_id: 'film-arrange-thread',
        project_id: 'lamtools-core',
        work_root: 'E:\LamTools',
        kind: 'routine',
        operation: 'message',
        payload: { message: '每天 09:00 看一遍代码改动，有阻塞就直接汇报' },
        trigger: { type: 'calendar', frequency: 'daily', time: '09:00', timezone: 'Asia/Shanghai' },
        title: '看一遍代码改动',
        session_strategy: 'new',
        model_id: 'demo-model',
        status: 'scheduled',
        next_run_at: '2026-10-08T09:00:00+08:00',
        run_count: 12,
        max_runs: null,
        created_at: '2026-09-21T09:00:00+08:00',
        updated_at: '2026-10-07T09:00:00+08:00',
      }],
      scheduler_notice: '',
    }
  }
  if (method === 'arrange.occurrence.list') {
    return {
      occurrences: [
        { id: 'occ-3', status: 'scheduled', scheduled_at: '2026-10-08T09:00:00+08:00', attempt_count: 0 },
        { id: 'occ-2', status: 'completed', scheduled_at: '2026-10-07T09:00:00+08:00', started_at: '2026-10-07T09:00:02+08:00', completed_at: '2026-10-07T09:03:41+08:00', attempt_count: 1 },
        { id: 'occ-1', status: 'completed', scheduled_at: '2026-10-06T09:00:00+08:00', started_at: '2026-10-06T09:00:01+08:00', completed_at: '2026-10-06T09:02:07+08:00', attempt_count: 1 },
      ],
    }
  }
  if (method === 'websearch.config.get') return { content: '{"provider":"baidu"}' }
  if (method === 'websearch.config.update') return { ok: true }
  if (method === 'websearch.widget.snapshot') {
    return { snapshot: { state: 'disabled', summary: '', blocks: [] } }
  }
  if (method === 'websearch.widget.health') return { state: 'disabled' }
  if (method === 'rag.docs.search') return { results: [] }
  // 资料库那几屏用演示库里真实的条目来渲染（导出的静态副本，见 catalog.generated.ts）
  if (method === 'artifact.list') return { artifacts: REAL_CATALOG }
  if (method === 'artifact.stats') return REAL_STATS
  if (method === 'memory.list') return { entries: [] }
  if (method === 'update.check') {
    return { status: 'up_to_date', current_version: '0.0.0', latest_version: '0.0.0', source: 'github' }
  }

  // Anything that would mutate server state still answers with the current
  // snapshot, so a stray interaction never surfaces a connection error.
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
    return { ok: true, applied: false, snapshot: state.snapshot }
  }

  return { ok: true }
}

/* ----------------------------------------------------------------- http ---- */

async function handleHttp(
  request: TransportHttpRequest,
  state: StageState,
): Promise<TransportHttpResponse> {
  const [rawPath, rawQuery = ''] = request.path.split('?', 2)
  const path = rawPath.replace(/\/+$/, '') || '/'
  const query = new URLSearchParams(rawQuery)
  const body = parseJsonBody(request.body)

  // 资料库卡片要的缩略图：按真实文件缩小后内嵌，取不到就让它退回类型图标
  const thumbMatch = path.match(/^\/projects\/[^/]+\/artifacts\/([^/]+)\/file$/)
  if (request.method === 'GET' && thumbMatch) {
    const dataUrl = REAL_THUMBS[decodeURIComponent(thumbMatch[1])]
    if (dataUrl) {
      const base64 = dataUrl.slice(dataUrl.indexOf(',') + 1)
      const bytes = Uint8Array.from(atob(base64), (ch) => ch.charCodeAt(0))
      return {
        status: 200,
        headers: { 'content-type': 'image/jpeg' },
        body: bytes,
      }
    }
    return { status: 404, headers: {}, body: new Uint8Array() }
  }
  if (request.method === 'GET' && path === '/projects') {
    return json({ projects: clone(state.projects) })
  }
  if (request.method === 'GET' && path === '/sessions') return json(clone(state.sessions))
  if (path === '/browse-directory') {
    return json({ path: query.get('path') || '', entries: [] })
  }

  const projectMatch = path.match(/^\/projects\/([^/]+)(?:\/(.*))?$/)
  if (projectMatch) {
    const projectId = decodeURIComponent(projectMatch[1])
    const suffix = projectMatch[2] || ''
    const project = state.projects.find((item) => item.id === projectId)
    if (!project) return json({ error: '项目不存在' }, 404)
    if (!suffix && request.method === 'GET') return json(clone(project))
    if (!suffix && (request.method === 'PATCH' || request.method === 'PUT')) {
      Object.assign(project, body)
      return json(clone(project))
    }
    if (!suffix && request.method === 'DELETE') return empty()
    if (suffix === 'sessions' && request.method === 'GET') {
      return json({ sessions: clone(state.sessions) })
    }
    if (suffix === 'sessions' && request.method === 'POST') {
      const session = {
        id: `stage-session-${state.sessions.length + 1}`,
        title: typeof body.title === 'string' ? body.title : '新的会话',
        status: 'idle',
        created_at: stringValue(project.updated_at),
        updated_at: stringValue(project.updated_at),
        metadata: { work_root: stringValue(project.work_root) },
      }
      state.sessions.push(session)
      return json(session, 201)
    }
    if (suffix === 'agents-md') {
      return json({ content: '', exists: false })
    }
    if (suffix === 'files' || suffix === 'files/content' || suffix === 'files/raw') {
      return suffix === 'files' ? json({ path: query.get('path') || '', entries: [] }) : json({ error: '文件不存在' }, 404)
    }
  }

  const sessionMatch = path.match(/^\/sessions\/([^/]+)$/)
  if (sessionMatch) {
    const sessionId = decodeURIComponent(sessionMatch[1])
    const session = state.sessions.find((item) => item.id === sessionId)
    if (!session) return json({ error: '会话不存在' }, 404)
    if (request.method === 'GET') return json(clone(session))
    if (request.method === 'PATCH' || request.method === 'PUT') {
      Object.assign(session, body)
      return json(clone(session))
    }
    if (request.method === 'DELETE') {
      state.sessions.splice(state.sessions.indexOf(session), 1)
      return empty()
    }
  }

  return json({ ok: true })
}

function json(value: unknown, status = 200): TransportHttpResponse {
  return {
    status,
    headers: { 'content-type': 'application/json' },
    body: new TextEncoder().encode(JSON.stringify(value)),
  }
}

function empty(): TransportHttpResponse {
  return { status: 204, headers: {}, body: new Uint8Array() }
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

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function clone<T>(value: T): T {
  if (value === undefined || value === null) return value
  return JSON.parse(JSON.stringify(value)) as T
}
