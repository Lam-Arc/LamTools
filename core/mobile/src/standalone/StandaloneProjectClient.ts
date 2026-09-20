import {
  CORE_PROJECT_COLOR_KEYS,
  CORE_PROJECT_ICON_KEYS,
  DEFAULT_CORE_PROJECT_COLOR_KEY,
  DEFAULT_CORE_PROJECT_ICON_KEY,
  type CoreProject,
  type CoreProjectClient,
  type CoreProjectColorKey,
  type CoreProjectIconKey,
} from '@lamtools/ui'
import type { LocalProject, LocalRepository, LocalThread } from '../storage'
import { DEVICE_REQUEST_DENIED_MESSAGE } from '../native/filePicker'

export function createStandaloneProjectClient(repository: LocalRepository): CoreProjectClient {
  const denied = async (): Promise<never> => { throw new Error(DEVICE_REQUEST_DENIED_MESSAGE) }
  return {
    async list() {
      return (await repository.listProjects()).map(toProject)
    },
    async create(payload) {
      const created = await repository.createLocalProject({
        name: payload.name,
        workRoot: payload.work_root,
        iconKey: payload.icon_key,
        colorKey: payload.color_key,
      })
      return { project: toProject(created.project), session: toSession(created.thread) }
    },
    async get(projectId) {
      const project = await repository.getLocalProject(projectId)
      if (!project) throw new Error('项目不存在')
      return toProject(project)
    },
    async update(projectId, payload) {
      return toProject(await repository.updateLocalProject(projectId, {
        name: payload.name,
        iconKey: payload.icon_key,
        colorKey: payload.color_key,
      }))
    },
    async rename(projectId, name) {
      return toProject(await repository.updateLocalProject(projectId, { name }))
    },
    async delete(projectId) {
      await repository.deleteLocalProject(projectId)
    },
    async createSession(projectId, title = '新会话') {
      return toSession(await repository.createLocalSession(projectId, title))
    },
    async listSessions(projectId) {
      return await repository.listSessions(projectId)
    },
    async readAgents() { return { content: '', exists: false } },
    writeAgents: denied,
    async listFiles() { return { entries: [], path: '' } },
    readFile: denied,
    writeFile: denied,
    readRawFile: denied,
    async browseDirectory() { return { entries: [], path: '' } },
  }
}

function toProject(project: LocalProject): CoreProject {
  return {
    id: project.id,
    name: project.name,
    workRoot: project.workRoot || project.path,
    iconKey: CORE_PROJECT_ICON_KEYS.includes(project.iconKey as CoreProjectIconKey)
      ? project.iconKey as CoreProjectIconKey
      : DEFAULT_CORE_PROJECT_ICON_KEY,
    colorKey: CORE_PROJECT_COLOR_KEYS.includes(project.colorKey as CoreProjectColorKey)
      ? project.colorKey as CoreProjectColorKey
      : DEFAULT_CORE_PROJECT_COLOR_KEY,
    createdAt: project.createdAt,
    updatedAt: project.updatedAt,
  }
}

function toSession(thread: LocalThread) {
  return {
    id: thread.id,
    title: thread.title,
    status: thread.status,
    createdAt: thread.createdAt,
    updatedAt: thread.updatedAt,
    metadata: thread.metadata,
  }
}
