// ============================================================
// LamWriter API Module — centralized fetch wrapper
// All endpoints typed. Vite dev proxy handles /api -> backend.
// ============================================================

import { appServerUrl, WriterAppServerClient } from '@/appServer/client'
import { normalizeProjectAgents, requireProjectCreateResult, type ProjectAgents } from './project-contract'
import type {
  Project,
  ProjectCreate,
  ProjectUpdate,
  Session,
  SessionCreate,
  SessionForkOptions,
  SessionRollbackResult,
  SessionUpdate,
  Provider,
  ProviderCreate,
  ProviderUpdate,
  Model,
  ModelCreate,
  ModelUpdate,
  ResolvedConfig,
  RuntimeCapabilities,
  AppSetting,
  AdapterProfile,
  GitVersionGraph,
  SessionChanges,
  SessionCheckpoint,
  CommitReview,
  CommitReviewDecision,
  Attachment,
  AttachmentPreview,
  AgentBranch,
} from '@/types'

declare global {
  interface Window {
    lamwriterDesktop?: {
      apiBase?: string
      selectDirectory?: () => Promise<string>
    }
  }
}

export const API_BASE = window.lamwriterDesktop?.apiBase
  || import.meta.env.VITE_API_BASE
  || ''

// --- Generic fetch helpers ---

class ApiError extends Error {
  status: number
  body: unknown

  constructor(status: number, body: unknown) {
    super(`API ${status}: ${typeof body === 'string' ? body : JSON.stringify(body)}`)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

async function requestForm<T>(path: string, formData: FormData, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE}${path}`
  const res = await fetch(url, {
    ...options,
    method: options.method || 'POST',
    body: formData,
  })

  if (!res.ok) {
    const text = await res.text()
    let body: unknown
    try {
      body = JSON.parse(text)
    } catch {
      body = text
    }
    throw new ApiError(res.status, body)
  }

  return res.json()
}

async function appServerOperation<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  const client = new WriterAppServerClient({
    url: appServerUrl(API_BASE),
    clientInfo: { name: 'writer_frontend_config', title: 'Writer Config', version: '0.1.0' },
  })
  try {
    await client.connect()
    return await client.request(method, params) as T
  } finally {
    client.close()
  }
}

// --- Projects ---

export function listProjects(): Promise<Project[]> {
  return appServerOperation<{ projects?: Project[] }>('project.list')
    .then((result) => result.projects ?? [])
}

export interface WriterProjectCreateResult {
  project: Project
  session: Session
}

export function createProject(data: ProjectCreate): Promise<WriterProjectCreateResult> {
  return appServerOperation<{ project?: Project; session?: Session }>('project.create', { ...data })
    .then(requireProjectCreateResult)
}

export function pickProjectDirectory(): Promise<string> {
  return appServerOperation<{ path?: string }>('project.directory.pick')
    .then((result) => result.path ?? '')
}

export function getProject(id: string): Promise<Project> {
  return appServerOperation<{ project?: Project }>('project.get', { project_id: id })
    .then((result) => {
      if (!result.project) throw new Error('project.get response is missing project')
      return result.project
    })
}

export function updateProject(id: string, data: ProjectUpdate): Promise<Project> {
  return appServerOperation<{ project?: Project }>('project.update', { project_id: id, ...data })
    .then((result) => {
      if (!result.project) throw new Error('project.update response is missing project')
      return result.project
    })
}

export function deleteProject(id: string): Promise<void> {
  return appServerOperation<{ deleted?: boolean }>('project.delete', { project_id: id }).then(() => undefined)
}

export function getAgentsMd(id: string): Promise<ProjectAgents> {
  return appServerOperation<{ agents_md?: unknown }>('project.agents_md.get', { project_id: id })
    .then(normalizeProjectAgents)
}

export function updateAgentsMd(id: string, content: string): Promise<ProjectAgents> {
  return appServerOperation<{ agents_md?: unknown }>('project.agents_md.update', { project_id: id, content })
    .then(normalizeProjectAgents)
}

export function listProjectSessions(projectId: string): Promise<Session[]> {
  return appServerOperation<{ sessions?: Session[] }>('project.sessions.list', { project_id: projectId })
    .then((result) => result.sessions ?? [])
}

export function createProjectSession(projectId: string, title = 'New Session'): Promise<Session> {
  return appServerOperation<{ session?: Session }>('project.sessions.create', { project_id: projectId, title })
    .then((result) => {
      if (!result.session) throw new Error('project.sessions.create response is missing session')
      return result.session
    })
}

// --- Sessions ---

export function listSessions(): Promise<Session[]> {
  return appServerOperation<{ sessions?: Session[] }>('session.list')
    .then((result) => result.sessions ?? [])
}

export function createSession(data: SessionCreate): Promise<Session> {
  return appServerOperation<{ session?: Session }>('session.create', { ...data })
    .then((result) => {
      if (!result.session) throw new Error('session.create response is missing session')
      return result.session
    })
}

export function getSession(id: string): Promise<Session> {
  return appServerOperation<{ session?: Session }>('session.get', { session_id: id })
    .then((result) => {
      if (!result.session) throw new Error('session.get response is missing session')
      return result.session
    })
}

export function updateSession(id: string, data: SessionUpdate): Promise<Session> {
  return appServerOperation<{ session?: Session }>('session.update', { session_id: id, ...data })
    .then((result) => {
      if (!result.session) throw new Error('session.update response is missing session')
      return result.session
    })
}

export function deleteSession(id: string): Promise<void> {
  return appServerOperation<{ ok?: boolean }>('session.delete', { session_id: id }).then(() => undefined)
}

export function forkSession(id: string, options: SessionForkOptions = {}): Promise<Session> {
  return appServerOperation<{ session?: Session }>('session.fork', {
    session_id: id,
    ...options,
  }).then((result) => {
    if (!result.session) throw new Error('session.fork response is missing session')
    return result.session
  })
}

export function rollbackSessionTurn(sessionId: string, turnId?: string, reason = ''): Promise<SessionRollbackResult> {
  return appServerOperation<SessionRollbackResult>('session.rollback_turn', {
    session_id: sessionId,
    ...(turnId ? { turn_id: turnId } : {}),
    ...(reason ? { reason } : {}),
  })
}

export function getGitGraph(sessionId: string): Promise<GitVersionGraph> {
  return appServerOperation<{ graph?: GitVersionGraph }>('session.git_graph.get', { session_id: sessionId })
    .then((result) => {
      if (!result.graph) throw new Error('session.git_graph.get response is missing graph')
      return result.graph
    })
}

export function getSessionChanges(sessionId: string): Promise<SessionChanges> {
  return appServerOperation<{ changes?: SessionChanges }>('session.changes.get', { session_id: sessionId })
    .then((result) => {
      if (!result.changes) throw new Error('session.changes.get response is missing changes')
      return result.changes
    })
}

export function listSessionCheckpoints(sessionId: string): Promise<SessionCheckpoint[]> {
  return appServerOperation<{ checkpoints?: SessionCheckpoint[] }>('session.checkpoints.list', { session_id: sessionId })
    .then((result) => result.checkpoints ?? [])
}

export function createSessionCheckpoint(sessionId: string, reason: string = '手动保存检查点'): Promise<SessionCheckpoint> {
  return appServerOperation<{ checkpoint?: SessionCheckpoint }>('session.checkpoint.create', {
    session_id: sessionId,
    label: 'checkpoint',
    reason,
    allow_empty: true,
  }).then((result) => {
    if (!result.checkpoint) throw new Error('session.checkpoint.create response is missing checkpoint')
    return result.checkpoint
  })
}

export function restoreSessionCheckpoint(sessionId: string, commit: string): Promise<{ status: string; source: string; ref: string | null; paths: string[]; message: string }> {
  return appServerOperation<{ status?: string; source?: string; ref?: string | null; paths?: string[]; message?: string }>(
    'session.checkpoint.restore',
    { session_id: sessionId, commit },
  ).then((result) => ({
    status: result.status ?? '',
    source: result.source ?? '',
    ref: result.ref ?? null,
    paths: result.paths ?? [],
    message: result.message ?? '',
  }))
}

export function getCommitReview(sessionId: string): Promise<CommitReview> {
  return appServerOperation<{ review?: CommitReview }>('session.commit_review.get', { session_id: sessionId })
    .then((result) => {
      if (!result.review) throw new Error('session.commit_review.get response is missing review')
      return result.review
    })
}

export function decideCommitReview(sessionId: string, data: CommitReviewDecision): Promise<CommitReview> {
  return appServerOperation<{ review?: CommitReview }>('session.commit_review.decide', {
    session_id: sessionId,
    ...data,
  }).then((result) => {
    if (!result.review) throw new Error('session.commit_review.decide response is missing review')
    return result.review
  })
}

export function undoSessionChanges(sessionId: string): Promise<{ status: string; source: string; ref: string | null; paths: string[]; message: string }> {
  return appServerOperation<{ status?: string; source?: string; ref?: string | null; paths?: string[]; message?: string }>(
    'session.changes.undo',
    { session_id: sessionId },
  ).then((result) => ({
    status: result.status ?? '',
    source: result.source ?? '',
    ref: result.ref ?? null,
    paths: result.paths ?? [],
    message: result.message ?? '',
  }))
}

export function undoSessionFileChange(sessionId: string, path: string): Promise<{ status: string; source: string; ref: string | null; paths: string[]; message: string }> {
  return appServerOperation<{ status?: string; source?: string; ref?: string | null; paths?: string[]; message?: string }>(
    'session.change_file.undo',
    { session_id: sessionId, path },
  ).then((result) => ({
    status: result.status ?? '',
    source: result.source ?? '',
    ref: result.ref ?? null,
    paths: result.paths ?? [],
    message: result.message ?? '',
  }))
}

export function openSessionChangeFile(sessionId: string, path: string): Promise<{ status: string; path: string; opened_with: string }> {
  return appServerOperation<{ status?: string; path?: string; opened_with?: string }>(
    'session.change_file.open',
    { session_id: sessionId, path },
  ).then((result) => ({
    status: result.status ?? '',
    path: result.path ?? path,
    opened_with: result.opened_with ?? '',
  }))
}

export function listAgentBranches(sessionId: string): Promise<AgentBranch[]> {
  return appServerOperation<{ branches?: AgentBranch[] }>('session.agent_branches.list', { session_id: sessionId })
    .then((result) => result.branches ?? [])
}

export function getAgentBranchDiff(sessionId: string, branch: string): Promise<{ branch: string; diff: string }> {
  return appServerOperation<{ branch?: string; diff?: string }>('session.agent_branch.diff', { session_id: sessionId, branch })
    .then((result) => ({ branch: result.branch ?? branch, diff: result.diff ?? '' }))
}

export function mergeAgentBranch(sessionId: string, branch: string): Promise<{ status: string; branch: string; message: string; strategy: string }> {
  return appServerOperation<{ status?: string; branch?: string; message?: string; strategy?: string }>(
    'session.agent_branch.merge',
    { session_id: sessionId, branch },
  ).then((result) => ({
    status: result.status ?? '',
    branch: result.branch ?? branch,
    message: result.message ?? '',
    strategy: result.strategy ?? '',
  }))
}

export function abandonAgentBranch(sessionId: string, branch: string): Promise<{ status: string; branch: string; message: string }> {
  return appServerOperation<{ status?: string; branch?: string; message?: string }>(
    'session.agent_branch.abandon',
    { session_id: sessionId, branch },
  ).then((result) => ({
    status: result.status ?? '',
    branch: result.branch ?? branch,
    message: result.message ?? '',
  }))
}

// --- Attachments ---

export function uploadAttachment(sessionId: string, file: File): Promise<Attachment> {
  const formData = new FormData()
  formData.append('file', file)
  return requestForm<Attachment>(`/api/core/sessions/${sessionId}/attachments`, formData)
}

export function listAttachments(sessionId: string): Promise<Attachment[]> {
  return appServerOperation<{ attachments?: Attachment[] }>('attachment.list', { session_id: sessionId })
    .then((result) => result.attachments ?? [])
}

export function getAttachment(id: string): Promise<Attachment> {
  return appServerOperation<{ attachment?: Attachment }>('attachment.get', { attachment_id: id })
    .then((result) => {
      if (!result.attachment) throw new Error('attachment.get response is missing attachment')
      return result.attachment
    })
}

export function previewAttachment(id: string): Promise<AttachmentPreview> {
  return appServerOperation<{ preview?: AttachmentPreview }>('attachment.preview', { attachment_id: id })
    .then((result) => {
      if (!result.preview) throw new Error('attachment.preview response is missing preview')
      return result.preview
    })
}

export function openAttachment(id: string): Promise<{ status: string; id: string }> {
  return appServerOperation<{ status?: string; id?: string }>('attachment.open', { attachment_id: id })
    .then((result) => ({ status: result.status ?? '', id: result.id ?? id }))
}

export function listCommands(workRoot?: string): Promise<unknown[]> {
  return appServerOperation<{ commands?: unknown[] }>('command.catalog', {
    ...(workRoot ? { work_root: workRoot } : {}),
  }).then((result) => result.commands ?? [])
}

export function executeCommand(sessionId: string, command: string, workRoot?: string): Promise<Record<string, unknown>> {
  return appServerOperation<{ result?: Record<string, unknown> }>('command.execute', {
    session_id: sessionId,
    command,
    ...(workRoot ? { work_root: workRoot } : {}),
  }).then((result) => result.result ?? {})
}

// --- Config: Providers ---

export function listProviders(): Promise<Provider[]> {
  return appServerOperation<{ providers?: Provider[] }>('config.providers.list')
    .then((result) => result.providers ?? [])
}

export function createProvider(data: ProviderCreate): Promise<Provider> {
  return appServerOperation<{ provider?: Provider }>('config.provider.create', { ...data })
    .then((result) => {
      if (!result.provider) throw new Error('config.provider.create response is missing provider')
      return result.provider
    })
}

export function updateProvider(id: string, data: ProviderUpdate): Promise<Provider> {
  // Strip api_key if empty or masked — backend ignores "" and "********"
  const payload = { ...data }
  if (payload.api_key === '' || payload.api_key === undefined || payload.api_key?.startsWith('****')) {
    delete payload.api_key
  }
  return appServerOperation<{ provider?: Provider }>('config.provider.update', { provider_id: id, ...payload })
    .then((result) => {
      if (!result.provider) throw new Error('config.provider.update response is missing provider')
      return result.provider
    })
}

export function deleteProvider(id: string): Promise<void> {
  return appServerOperation<{ ok?: boolean }>('config.provider.delete', { provider_id: id }).then(() => undefined)
}

export function importEnvConfig(): Promise<{ provider: Provider; model: Model; route_updated: boolean }> {
  return appServerOperation<{ provider?: Provider; model?: Model; route_updated?: boolean }>('config.import_env')
    .then((result) => {
      if (!result.provider || !result.model) throw new Error('config.import_env response is missing provider or model')
      return {
        provider: result.provider,
        model: result.model,
        route_updated: Boolean(result.route_updated),
      }
    })
}

// --- Config: Models ---

export function listModels(providerId?: string): Promise<Model[]> {
  return appServerOperation<{ models?: Model[] }>('config.models.list', providerId ? { provider_id: providerId } : {})
    .then((result) => result.models ?? [])
}

export function createModel(data: ModelCreate): Promise<Model> {
  return appServerOperation<{ model?: Model }>('config.model.create', { ...data })
    .then((result) => {
      if (!result.model) throw new Error('config.model.create response is missing model')
      return result.model
    })
}

export function updateModel(id: string, data: ModelUpdate): Promise<Model> {
  return appServerOperation<{ model?: Model }>('config.model.update', { model_record_id: id, ...data })
    .then((result) => {
      if (!result.model) throw new Error('config.model.update response is missing model')
      return result.model
    })
}

export function deleteModel(id: string): Promise<void> {
  return appServerOperation<{ ok?: boolean }>('config.model.delete', { model_record_id: id }).then(() => undefined)
}

export function getResolvedConfig(taskType: string = 'default'): Promise<ResolvedConfig> {
  return appServerOperation<{ resolved?: ResolvedConfig }>('config.resolved.get', { task_type: taskType })
    .then((result) => {
      if (!result.resolved) throw new Error('config.resolved.get response is missing resolved config')
      return result.resolved
    })
}

export function getRuntimeCapabilities(workRoot?: string): Promise<RuntimeCapabilities> {
  const params = workRoot ? { work_root: workRoot } : {}
  return appServerOperation<{ runtime_capabilities?: RuntimeCapabilities }>('config.runtime_capabilities.get', params)
    .then((result) => {
      if (!result.runtime_capabilities) throw new Error('config.runtime_capabilities.get response is missing runtime capabilities')
      return result.runtime_capabilities
    })
}

export function listAdapterProfiles(): Promise<AdapterProfile[]> {
  return appServerOperation<{ adapter_profiles?: AdapterProfile[] }>('config.adapter_profiles.list')
    .then((result) => result.adapter_profiles ?? [])
}

export function getAppSetting(namespace: string): Promise<AppSetting> {
  return appServerOperation<{ setting?: AppSetting }>('settings.get', { namespace })
    .then((result) => {
      if (!result.setting) throw new Error('settings.get response is missing setting')
      return result.setting
    })
}

export function putAppSetting(namespace: string, value: Record<string, unknown>): Promise<AppSetting> {
  return appServerOperation<{ setting?: AppSetting }>('settings.update', { namespace, value })
    .then((result) => {
      if (!result.setting) throw new Error('settings.update response is missing setting')
      return result.setting
    })
}
