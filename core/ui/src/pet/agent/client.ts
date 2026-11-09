/**
 * 桌宠覆盖层与 Sunday 后端之间的最薄一层桥。
 *
 * 复用现有能力：项目/会话走 Core 的 HTTP 接口，消息与审批走 App Server 的
 * JSON-RPC；不新增任何后端，也不自带第二套消息系统。
 */
import { createDirectTransport, type DirectTransport } from '@/transport/directTransport.ts'
import { createCoreProjectClient, type CoreProjectClient } from '@/projects/client.ts'
import { encodeMultipartFile } from '@/composer/upload.ts'
import { isInternalSessionId } from '@/sessions/visibility.ts'
import type { CoreAttachment, CoreInputItem } from '@/types.ts'

export interface PetScreenshotUpload {
  id: string
  path: string
  filename: string
  mimeType: string
  size: number
}

export interface PetProjectSession {
  id: string
  title: string
  projectId: string | null
  workRoot?: string
  /** 最近会话排序用（ISO 时间或毫秒时间戳）。 */
  updatedAt?: string | number
  /** 后端会话状态：running / waiting / completed / failed 等，桌宠守望按它判忙闲。 */
  status?: string
  /** 插件/内部编排会话：不能作为 Ping 目标。 */
  internal?: boolean
}

export interface PetAgentClient {
  apiBase: string
  transport: DirectTransport
  projects: CoreProjectClient
  listProjects(): Promise<{ id: string; name: string; workRoot: string }[]>
  listSessions(projectId: string): Promise<PetProjectSession[]>
  /**
   * 全局会话列表（跨项目，一条请求）。
   *
   * user:“改让桌宠盯所有会话 不只是一个会话”+(守望所有会话的发现源：
   *  按项目逐个拉会把请求数乘上项目数，后端本来就有全局 /sessions。）
   */
  listAllSessions(): Promise<PetProjectSession[]>
  createSession(projectId: string, title?: string): Promise<PetProjectSession>
  /** 兜底项目：My Project。从未绑定过时用它创建唯一一个默认会话。 */
  ensureFallbackSession(): Promise<{ projectId: string; sessionId: string; created: boolean }>
  /** Ping 默认会话：My Project 里名为 “ping” 的会话（没有才创建一次）。 */
  ensurePingSession(): Promise<{ projectId: string; sessionId: string; created: boolean }>
  ensureProjectSession(projectId: string): Promise<{ projectId: string; sessionId: string; created: boolean }>
  uploadScreenshot(
    sessionId: string,
    projectId: string | null,
    blob: Blob,
    filename: string,
  ): Promise<PetScreenshotUpload>
  attachmentInput(upload: PetScreenshotUpload): CoreInputItem
  close(): void
}

const FALLBACK_PROJECT_NAME = 'My Project'
/** Ping 默认会话的标题。 */
const PING_SESSION_TITLE = 'ping'

export function createPetAgentClient(apiBase: string): PetAgentClient {
  const transport = createDirectTransport({ apiBase: `${apiBase}/api/core` })
  const projects = createCoreProjectClient(transport)

  async function listProjects() {
    const list = await projects.list()
    return list.map(project => ({ id: project.id, name: project.name, workRoot: project.workRoot }))
  }

  async function listSessions(projectId: string): Promise<PetProjectSession[]> {
    const list = await projects.listSessions(projectId)
    return list.map(session => ({
      id: String(session.id),
      title: String(session.title || session.id),
      projectId,
      workRoot: typeof session.metadata?.work_root === 'string' ? session.metadata.work_root : undefined,
      updatedAt: session.updatedAt,
      internal: Boolean(session.metadata?.owner_plugin) || isInternalSessionId(String(session.id)),
    }))
  }

  async function listAllSessions(): Promise<PetProjectSession[]> {
    // 失败必须抛：调用方靠“空列表”和“读不到”区分是否要拆掉现有订阅。
    const response = await transport.request<{ status: number; body: Uint8Array }>({
      kind: 'http',
      method: 'GET',
      path: '/sessions',
      timeoutMs: 30_000,
    })
    if (response.status < 200 || response.status >= 300) {
      throw new Error(`会话列表读取失败（${response.status}）`)
    }
    return parseAllSessions(new TextDecoder().decode(response.body))
  }

  async function createSession(projectId: string, title = '桌宠会话'): Promise<PetProjectSession> {
    const created = await projects.createSession(projectId, title)
    return {
      id: String(created.id),
      title: String(created.title || title),
      projectId,
      workRoot: typeof created.metadata?.work_root === 'string' ? created.metadata.work_root : undefined,
    }
  }

  /**
   * user:“从未设置默认绑定的桌宠首次需要 Agent 会话时，在 My Project 仅新建一个
   * 会话并保存为默认，后续复用、不重复创建”+
   * (已有会话就复用最近一个；没有才建一个。绝不每次启动都建空会话。)
   */
  async function ensureProjectSession(projectId: string) {
    const latest = pickLatestPetSession(await listSessions(projectId))
    if (latest) return { projectId, sessionId: latest.id, created: false }
    const created = await createSession(projectId)
    return { projectId, sessionId: created.id, created: true }
  }

  async function ensureFallbackSession() {
    const existing = findFallbackProject(await listProjects())
    if (existing) return await ensureProjectSession(existing.id)
    const workRoot = await resolveFallbackWorkRoot()
    const created = await projects.create({ name: FALLBACK_PROJECT_NAME, work_root: workRoot })
    return await ensureProjectSession(created.project.id)
  }

  /**
   * Ping 的默认目标会话：My Project 里一条名为 “ping” 的普通会话。
   *
   * user:“在 My project 里建一个新会话作为默认会话，默认会话的名字就叫“ping””+
   * (首次使用/原目标失效时创建；已有同名会话就复用，避免重复建空会话。
   *   插件/内部编排会话永远不作为候选。)
   */
  async function ensurePingSession() {
    const existing = findFallbackProject(await listProjects())
    let projectId: string
    if (existing) {
      projectId = existing.id
    } else {
      const workRoot = await resolveFallbackWorkRoot()
      const createdProject = await projects.create({ name: FALLBACK_PROJECT_NAME, work_root: workRoot })
      projectId = createdProject.project.id
    }
    const sessions = (await listSessions(projectId)).filter(session => !session.internal)
    const pingSession = sessions.find(
      session => session.title.trim().toLowerCase() === PING_SESSION_TITLE,
    )
    if (pingSession) return { projectId, sessionId: pingSession.id, created: false }
    const created = await createSession(projectId, PING_SESSION_TITLE)
    return { projectId, sessionId: created.id, created: true }
  }

  async function uploadScreenshot(
    sessionId: string,
    projectId: string | null,
    blob: Blob,
    filename: string,
  ): Promise<PetScreenshotUpload> {
    const file = new File([blob], filename, { type: blob.type || 'image/png' })
    const multipart = await encodeMultipartFile(file)
    const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
    const response = await transport.request<{ status: number; body: Uint8Array }>({
      kind: 'http',
      method: 'POST',
      path: `/sessions/${encodeURIComponent(sessionId)}/attachments${query}`,
      headers: { 'Content-Type': multipart.contentType },
      body: multipart.body,
      timeoutMs: 60_000,
    })
    if (response.status < 200 || response.status >= 300) {
      throw new Error(new TextDecoder().decode(response.body) || `截图上传失败（${response.status}）`)
    }
    const parsed = JSON.parse(new TextDecoder().decode(response.body)) as CoreAttachment
    if (!parsed.id) throw new Error('截图上传没有返回附件编号')
    return {
      id: parsed.id,
      path: parsed.path || '',
      filename: parsed.filename || filename,
      mimeType: parsed.mime_type || 'image/png',
      size: parsed.size || blob.size,
    }
  }

  return {
    apiBase,
    transport,
    projects,
    listProjects,
    listSessions,
    listAllSessions,
    createSession,
    ensureFallbackSession,
    ensurePingSession,
    ensureProjectSession,
    uploadScreenshot,
    attachmentInput(upload) {
      return {
        type: 'attachment',
        attachment_id: upload.id,
        filename: upload.filename,
        mime_type: upload.mimeType,
      }
    },
    close() {
      void transport.close()
    },
  }
}

/**
 * 默认会话选谁：最近的普通会话。
 *
 * user:“也没有触发审批”+(首次兜底会把默认会话绑成“最近一个”，
 *  不能按后端返回顺序碰运气，也不能绑到插件/内部编排会话上：
 *  那些会话不会有人给它发审批，绑了等于没绑。)
 */
export function pickLatestPetSession(sessions: PetProjectSession[]): PetProjectSession | undefined {
  const candidates = sessions.filter(session => session && !session.internal)
  if (candidates.length === 0) return undefined
  const stamp = (value: string | number | undefined): number => {
    if (typeof value === 'number') return Number.isFinite(value) ? value : 0
    if (typeof value === 'string' && value) {
      const parsed = Date.parse(value)
      if (Number.isFinite(parsed)) return parsed
    }
    return 0
  }
  return [...candidates].sort((a, b) => stamp(b.updatedAt) - stamp(a.updatedAt))[0] ?? candidates[0]
}

async function resolveFallbackWorkRoot(): Promise<string> {
  const runtime = globalThis as { __TAURI_INTERNALS__?: unknown }
  if (runtime.__TAURI_INTERNALS__) {
    const { invoke } = await import('@tauri-apps/api/core')
    return await invoke<string>('pet_default_work_root')
  }
  // 纯浏览器调试：交给后端用当前工作目录推导（它会把同名项目合并）。
  return 'MyProject'
}

type PetProjectSummary = { id: string; name: string; workRoot: string }

/**
 * 全局 /sessions 的响应 → 桌宠可用的会话条目。
 *
 * 后端两种外形都出现过：裸数组和 `{ sessions: [...] }`；字段也同时有蛇形与驼峰。
 * 解析失败必须抛，调用方靠它区分“真的没有会话”和“这次没读到”。
 */
export function parseAllSessions(text: string): PetProjectSession[] {
  const parsed = (() => {
    try { return JSON.parse(text) as unknown } catch { return null }
  })()
  if (parsed === null) throw new Error('会话列表解析失败')
  const rows = Array.isArray(parsed)
    ? parsed
    : parsed && typeof parsed === 'object' && Array.isArray((parsed as { sessions?: unknown }).sessions)
      ? ((parsed as { sessions: unknown[] }).sessions)
      : []
  return rows.flatMap(row => {
    const item = (row || {}) as RawAllSession
    const id = item.id ? String(item.id) : ''
    if (!id) return []
    const metadata = item.metadata && typeof item.metadata === 'object' ? item.metadata : undefined
    const workRoot = typeof metadata?.work_root === 'string' ? metadata.work_root : undefined
    return [{
      id,
      title: String(item.title || id),
      projectId: item.project_id ? String(item.project_id) : null,
      workRoot,
      updatedAt: item.updated_at || item.updatedAt,
      status: typeof item.status === 'string' ? item.status : undefined,
      internal: Boolean(metadata?.owner_plugin) || isInternalSessionId(id),
    }]
  })
}

/** 全局 /sessions 的原始行：兼容蛇形与驼峰两套字段。 */
type RawAllSession = {
  id?: string
  title?: string
  status?: string
  project_id?: string
  updated_at?: string
  updatedAt?: string
  metadata?: Record<string, unknown>
}

/** “My Project” 的三种识别方式：精确名、含 My Project、工作区以 MyProject 结尾。 */
function findFallbackProject(projects: PetProjectSummary[]): PetProjectSummary | undefined {
  return projects.find(project => project.name.trim().toLowerCase() === FALLBACK_PROJECT_NAME.toLowerCase())
    || projects.find(project => /my\s*project/i.test(project.name))
    || projects.find(project => /[\\/]MyProject$/i.test(project.workRoot))
}
