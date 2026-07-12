import type {
  CoreProject,
  CoreProjectAgents,
  CoreProjectCreatePayload,
  CoreProjectCreateResult,
  CoreProjectSession,
} from './types'

export interface CoreProjectClient {
  list(): Promise<CoreProject[]>
  create(payload: CoreProjectCreatePayload): Promise<CoreProjectCreateResult>
  get(projectId: string): Promise<CoreProject>
  rename(projectId: string, name: string): Promise<CoreProject>
  delete(projectId: string): Promise<void>
  listSessions(projectId: string): Promise<CoreProjectSession[]>
  readAgents(projectId: string): Promise<CoreProjectAgents>
  writeAgents(projectId: string, content: string): Promise<CoreProjectAgents>
}

type RawProject = {
  id: string
  name: string
  work_root: string
  created_at?: string
  updated_at?: string
}

type RawProjectSession = CoreProjectSession & {
  created_at?: string
  updated_at?: string
}

export function createCoreProjectClient(apiBase: string): CoreProjectClient {
  const base = apiBase.replace(/\/+$/, '')

  return {
    async list() {
      const response = await request<{ projects: RawProject[] }>(base, '/projects')
      return response.projects.map(toProject)
    },
    async create(payload) {
      const response = await request<{ project: RawProject; session: RawProjectSession }>(base, '/projects', {
        method: 'POST',
        body: payload,
      })
      return { project: toProject(response.project), session: toSession(response.session) }
    },
    async get(projectId) {
      return toProject(await request<RawProject>(base, projectPath(projectId)))
    },
    async rename(projectId, name) {
      return toProject(await request<RawProject>(base, projectPath(projectId), {
        method: 'PATCH',
        body: { name },
      }))
    },
    async delete(projectId) {
      await request(base, projectPath(projectId), { method: 'DELETE' })
    },
    async listSessions(projectId) {
      const response = await request<{ sessions: RawProjectSession[] }>(base, `${projectPath(projectId)}/sessions`)
      return response.sessions.map(toSession)
    },
    async readAgents(projectId) {
      return await request<CoreProjectAgents>(base, `${projectPath(projectId)}/agents-md`)
    },
    async writeAgents(projectId, content) {
      return await request<CoreProjectAgents>(base, `${projectPath(projectId)}/agents-md`, {
        method: 'PUT',
        body: { content },
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

async function request<T = undefined>(
  base: string,
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    method: options.method || 'GET',
    headers: options.body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `${response.status} ${response.statusText}`)
  }
  if (response.status === 204) return undefined as T
  return await response.json() as T
}
