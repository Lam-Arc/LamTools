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

/** One plan document in the project's 「方案/」 folder, as the scan reports it. */
export interface CorePlanLibraryEntry {
  name: string
  path: string
  /** Directory inside 「方案/」 the file lives in ('' = top level). */
  folder: string
  title: string
  status: 'draft' | 'ready' | 'executing' | 'done'
  summary: string
  favorite: boolean
  size: number
  updated_at: number
}

/** One folder inside 「方案/」, at any depth. */
export interface CorePlanLibraryFolder {
  name: string
  /** Library path, e.g. `方案/归档/这一期`. */
  path: string
  /** Directory relative to 「方案/」 ('' = the library root), matching entry.folder. */
  dir: string
  /** The `dir` of the folder holding this one ('' for a top-level folder). */
  parent: string
  /** Plans at any depth under this folder. */
  count: number
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
  listPlanLibrary(projectId: string): Promise<{ dir: string; entries: CorePlanLibraryEntry[]; folders: CorePlanLibraryFolder[] }>
  createPlanLibraryFile(projectId: string, name: string, folder?: string): Promise<{ entry: CorePlanLibraryEntry }>
  createPlanLibraryFolder(projectId: string, path: string): Promise<{ folder: CorePlanLibraryFolder }>
  deletePlanLibraryFolder(projectId: string, path: string): Promise<{ deleted: string }>
  renamePlanLibraryFile(projectId: string, path: string, name: string): Promise<{ entry: CorePlanLibraryEntry }>
  movePlanLibraryFile(projectId: string, path: string, folder: string): Promise<{ entry: CorePlanLibraryEntry }>
  favoritePlanLibraryFile(projectId: string, path: string, favorite: boolean): Promise<{ entry: CorePlanLibraryEntry }>
  deletePlanLibraryFile(projectId: string, path: string): Promise<{ deleted: string }>
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
    async listPlanLibrary(projectId) {
      return await requestJson<{ dir: string; entries: CorePlanLibraryEntry[]; folders: CorePlanLibraryFolder[] }>(
        transport,
        `${projectPath(projectId)}/plan-library`,
      )
    },
    async createPlanLibraryFile(projectId, name, folder = '') {
      return await requestJson<{ entry: CorePlanLibraryEntry }>(transport, `${projectPath(projectId)}/plan-library/files`, {
        method: 'POST',
        body: { name, folder },
      })
    },
    async createPlanLibraryFolder(projectId, path) {
      return await requestJson<{ folder: CorePlanLibraryFolder }>(transport, `${projectPath(projectId)}/plan-library/folders`, {
        method: 'POST',
        body: { path },
      })
    },
    async deletePlanLibraryFolder(projectId, path) {
      const query = `?path=${encodeURIComponent(path)}`
      return await requestJson<{ deleted: string }>(transport, `${projectPath(projectId)}/plan-library/folders${query}`, {
        method: 'DELETE',
      })
    },
    async renamePlanLibraryFile(projectId, path, name) {
      return await requestJson<{ entry: CorePlanLibraryEntry }>(transport, `${projectPath(projectId)}/plan-library/rename`, {
        method: 'POST',
        body: { path, name },
      })
    },
    async movePlanLibraryFile(projectId, path, folder) {
      return await requestJson<{ entry: CorePlanLibraryEntry }>(transport, `${projectPath(projectId)}/plan-library/move`, {
        method: 'POST',
        body: { path, folder },
      })
    },
    async favoritePlanLibraryFile(projectId, path, favorite) {
      return await requestJson<{ entry: CorePlanLibraryEntry }>(transport, `${projectPath(projectId)}/plan-library/favorite`, {
        method: 'POST',
        body: { path, favorite },
      })
    },
    async deletePlanLibraryFile(projectId, path) {
      const query = `?path=${encodeURIComponent(path)}`
      return await requestJson<{ deleted: string }>(transport, `${projectPath(projectId)}/plan-library${query}`, {
        method: 'DELETE',
      })
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
