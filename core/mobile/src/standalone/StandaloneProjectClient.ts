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
import {
  hasEmbeddedRustCore,
  listEmbeddedProjectFiles,
  readEmbeddedProjectFile,
  writeEmbeddedProjectFile,
} from '../native/rustAgent'

export function createStandaloneProjectClient(repository: LocalRepository): CoreProjectClient {
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
    async readAgents(projectId) {
      if (hasEmbeddedRustCore()) {
        let file = await readEmbeddedProjectFile(projectId, 'AGENTS.md')
        if (!file) {
          const legacy = await repository.readProjectFile(projectId, 'AGENTS.md')
          if (legacy) file = await writeEmbeddedProjectFile(projectId, legacy.path, legacy.content)
        }
        return { content: file?.content || '', exists: Boolean(file) }
      }
      const file = await repository.readProjectFile(projectId, 'AGENTS.md')
      return { content: file?.content || '', exists: Boolean(file) }
    },
    async writeAgents(projectId, content) {
      if (hasEmbeddedRustCore()) {
        await writeEmbeddedProjectFile(projectId, 'AGENTS.md', content)
        return { content, exists: true }
      }
      await repository.writeProjectFile(projectId, 'AGENTS.md', content)
      return { content, exists: true }
    },
    async listFiles(projectId, path = '') {
      if (hasEmbeddedRustCore()) {
        let files = await listEmbeddedProjectFiles(projectId, path)
        const nativePaths = new Set(files.map(file => file.path))
        const legacyFiles = await repository.listProjectFiles(projectId, path)
        for (const legacy of legacyFiles) {
          if (nativePaths.has(legacy.path)) continue
          await writeEmbeddedProjectFile(projectId, legacy.path, legacy.content)
        }
        if (legacyFiles.some(file => !nativePaths.has(file.path))) {
          files = await listEmbeddedProjectFiles(projectId, path)
        }
        return {
          path,
          entries: files.map(file => ({
            name: file.path,
            type: 'file' as const,
            size: file.size,
            ext: file.path.includes('.') ? file.path.split('.').pop() || '' : '',
          })),
        }
      }
      const files = await repository.listProjectFiles(projectId, path)
      return {
        path,
        entries: files.map(file => ({
          name: file.path,
          type: 'file' as const,
          size: new TextEncoder().encode(file.content).length,
          ext: file.path.includes('.') ? file.path.split('.').pop() || '' : '',
        })),
      }
    },
    async readFile(projectId, path) {
      if (hasEmbeddedRustCore()) {
        let file = await readEmbeddedProjectFile(projectId, path)
        if (!file) {
          const legacy = await repository.readProjectFile(projectId, path)
          if (legacy) file = await writeEmbeddedProjectFile(projectId, legacy.path, legacy.content)
        }
        if (!file) throw new Error('文件不存在')
        return file
      }
      const file = await repository.readProjectFile(projectId, path)
      if (!file) throw new Error('文件不存在')
      return { content: file.content, path: file.path }
    },
    async writeFile(projectId, path, content) {
      if (hasEmbeddedRustCore()) return await writeEmbeddedProjectFile(projectId, path, content)
      const file = await repository.writeProjectFile(projectId, path, content)
      return { content: file.content, path: file.path }
    },
    async readRawFile(projectId, path) {
      if (hasEmbeddedRustCore()) {
        let file = await readEmbeddedProjectFile(projectId, path)
        if (!file) {
          const legacy = await repository.readProjectFile(projectId, path)
          if (legacy) file = await writeEmbeddedProjectFile(projectId, legacy.path, legacy.content)
        }
        if (!file) return { status: 404, headers: {} as Record<string, string>, body: new Uint8Array() }
        return {
          status: 200,
          headers: { 'Content-Type': 'text/plain; charset=utf-8' },
          body: new TextEncoder().encode(file.content),
        }
      }
      const file = await repository.readProjectFile(projectId, path)
      if (!file) return { status: 404, headers: {} as Record<string, string>, body: new Uint8Array() }
      return { status: 200, headers: { 'Content-Type': 'text/plain; charset=utf-8' }, body: new TextEncoder().encode(file.content) }
    },
    async browseDirectory(path = '') { return { entries: [], path } },
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
