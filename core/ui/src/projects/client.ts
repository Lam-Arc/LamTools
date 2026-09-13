import type {
  CoreProject,
  CoreProjectAgents,
  CoreProjectCreatePayload,
  CoreProjectCreateResult,
  CoreProjectSession,
  CoreProjectUpdatePayload,
} from './types'
import {
  CORE_PROJECT_COLOR_KEYS,
  CORE_PROJECT_ICON_KEYS,
  DEFAULT_CORE_PROJECT_COLOR_KEY,
  DEFAULT_CORE_PROJECT_ICON_KEY,
} from './types'
import type { LamToolsTransport, TransportHttpResponse } from '../transport'

export interface CoreFileEntry {
  name: string
  type: 'directory' | 'file'
  size: number
  ext: string
}

export interface CoreProjectClient {
  list(): Promise<CoreProject[]>
  create(payload: CoreProjectCreatePayload): Promise<CoreProjectCreateResult>
  get(projectId: string): Promise<CoreProject>
  update(projectId: string, payload: CoreProjectUpdatePayload): Promise<CoreProject>
  rename(projectId: string, name: string): Promise<CoreProject>
  delete(projectId: string): Promise<void>
  createSession(projectId: string, title?: string): Promise<CoreProjectSession>
  listSessions(projectId: string): Promise<CoreProjectSession[]>
  readAgents(projectId: string): Promise<CoreProjectAgents>
  writeAgents(projectId: string, content: string): Promise<CoreProjectAgents>
  listFiles(projectId: string, path?: string): Promise<{ entries: CoreFileEntry[]; path: string }>
  readFile(projectId: string, path: string): Promise<{ content: string; path: string }>
  writeFile(projectId: string, path: string, content: string): Promise<{ content: string; path: string }>
  readRawFile(projectId: string, path: string): Promise<TransportHttpResponse>
  browseDirectory(path?: string): Promise<{ entries: CoreFileEntry[]; path: string }>
}

type RawProject = {
  id: string
  name: string
  work_root: string
  icon_key?: string
  color_key?: string
  created_at?: string
  updated_at?: string
}

type RawProjectSession = CoreProjectSession & {
  created_at?: string
  updated_at?: string
}

export function createCoreProjectClient(transport: LamToolsTransport): CoreProjectClient {
  return {
    async list() {
      const response = await requestJson<{ projects: RawProject[] }>(transport, '/projects')
      return response.projects.map(toProject)
    },
    async create(payload) {
      const response = await requestJson<{ project: RawProject; session: RawProjectSession }>(transport, '/projects', {
        method: 'POST',
        body: payload,
      })
      return { project: toProject(response.project), session: toSession(response.session) }
    },
    async get(projectId) {
      return toProject(await requestJson<RawProject>(transport, projectPath(projectId)))
    },
    async update(projectId, payload) {
      return toProject(await requestJson<RawProject>(transport, projectPath(projectId), {
        method: 'PATCH',
        body: payload,
      }))
    },
    async rename(projectId, name) {
      return toProject(await requestJson<RawProject>(transport, projectPath(projectId), {
        method: 'PATCH',
        body: { name },
      }))
    },
    async delete(projectId) {
      await requestJson(transport, projectPath(projectId), { method: 'DELETE' })
    },
    async createSession(projectId, title = 'New Session') {
      return toSession(await requestJson<RawProjectSession>(transport, `${projectPath(projectId)}/sessions`, {
        method: 'POST',
        body: { title },
      }))
    },
    async listSessions(projectId) {
      const response = await requestJson<{ sessions: RawProjectSession[] }>(transport, `${projectPath(projectId)}/sessions`)
      return response.sessions.map(toSession)
    },
    async readAgents(projectId) {
      return await requestJson<CoreProjectAgents>(transport, `${projectPath(projectId)}/agents-md`)
    },
    async writeAgents(projectId, content) {
      return await requestJson<CoreProjectAgents>(transport, `${projectPath(projectId)}/agents-md`, {
        method: 'PUT',
        body: { content },
      })
    },
    async listFiles(projectId, path = '') {
      const query = path ? `?path=${encodeURIComponent(path)}` : ''
      return await requestJson<{ entries: CoreFileEntry[]; path: string }>(transport, `${projectPath(projectId)}/files${query}`)
    },
    async readFile(projectId, path) {
      const query = `?path=${encodeURIComponent(path)}`
      return await requestJson<{ content: string; path: string }>(transport, `${projectPath(projectId)}/files/content${query}`)
    },
    async writeFile(projectId, path, content) {
      const query = `?path=${encodeURIComponent(path)}`
      return await requestJson<{ content: string; path: string }>(transport, `${projectPath(projectId)}/files/content${query}`, {
        method: 'PUT',
        body: { content },
      })
    },
    async readRawFile(projectId, path) {
      const query = `?path=${encodeURIComponent(path)}`
      return await requestBytes(transport, `${projectPath(projectId)}/files/raw${query}`)
    },
    async browseDirectory(path = '') {
      const query = path ? `?path=${encodeURIComponent(path)}` : ''
      return await requestJson<{ entries: CoreFileEntry[]; path: string }>(transport, `/browse-directory${query}`)
    },
  }
}

function projectPath(projectId: string): string {
  return `/projects/${encodeURIComponent(projectId)}`
}

function toProject(project: RawProject): CoreProject {
  return {
    id: project.id,
    name: project.name,
    workRoot: project.work_root,
    iconKey: CORE_PROJECT_ICON_KEYS.includes(project.icon_key as typeof CORE_PROJECT_ICON_KEYS[number])
      ? project.icon_key as typeof CORE_PROJECT_ICON_KEYS[number]
      : DEFAULT_CORE_PROJECT_ICON_KEY,
    colorKey: CORE_PROJECT_COLOR_KEYS.includes(project.color_key as typeof CORE_PROJECT_COLOR_KEYS[number])
      ? project.color_key as typeof CORE_PROJECT_COLOR_KEYS[number]
      : DEFAULT_CORE_PROJECT_COLOR_KEY,
    createdAt: project.created_at,
    updatedAt: project.updated_at,
  }
}

function toSession(session: RawProjectSession): CoreProjectSession {
  return {
    ...session,
    createdAt: session.createdAt || session.created_at,
    updatedAt: session.updatedAt || session.updated_at,
  }
}

async function requestBytes(
  transport: LamToolsTransport,
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<TransportHttpResponse> {
  const body = options.body === undefined ? undefined : new TextEncoder().encode(JSON.stringify(options.body))
  const response = await transport.request<TransportHttpResponse>({
    kind: 'http',
    method: options.method || 'GET',
    path,
    headers: options.body === undefined ? {} : { 'Content-Type': 'application/json' },
    ...(body ? { body } : {}),
  })
  if (response.status < 200 || response.status >= 300) {
    const text = new TextDecoder().decode(response.body)
    throw new Error(text || `请求失败（${response.status}）`)
  }
  return response
}

async function requestJson<T = undefined>(
  transport: LamToolsTransport,
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const response = await requestBytes(transport, path, options)
  if (response.status === 204 || response.body.length === 0) return undefined as T
  return JSON.parse(new TextDecoder().decode(response.body)) as T
}
