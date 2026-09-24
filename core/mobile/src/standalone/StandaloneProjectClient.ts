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
  browseEmbeddedProjectDirectory,
  listEmbeddedProjectFiles,
  readEmbeddedProjectAgents,
  readEmbeddedProjectFile,
  readEmbeddedProjectFileRaw,
  writeEmbeddedProjectAgents,
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
        let agents = await readEmbeddedProjectAgents(projectId)
        if (!agents.exists) {
          // One-time migration of AGENTS.md written by the legacy store.
          const legacy = await repository.readProjectFile(projectId, 'AGENTS.md')
          if (legacy) agents = await writeEmbeddedProjectAgents(projectId, legacy.content)
        }
        return agents
      }
      const file = await repository.readProjectFile(projectId, 'AGENTS.md')
      return { content: file?.content || '', exists: Boolean(file) }
    },
    async writeAgents(projectId, content) {
      if (hasEmbeddedRustCore()) return await writeEmbeddedProjectAgents(projectId, content)
      await repository.writeProjectFile(projectId, 'AGENTS.md', content)
      return { content, exists: true }
    },
    async listFiles(projectId, path = '') {
      if (hasEmbeddedRustCore()) {
        const legacyFiles = await repository.listProjectFiles(projectId, path)
        // The native listing is one level deep. Probe full legacy paths before
        // migrating so an older snapshot cannot replace a newer native edit.
        for (const legacy of legacyFiles) {
          let existing
          try { existing = await readEmbeddedProjectFile(projectId, legacy.path) }
          catch { continue } // An unreadable native file must never be replaced by legacy text.
          if (!existing) await writeEmbeddedProjectFile(projectId, legacy.path, legacy.content)
        }
        return { path, entries: await listEmbeddedProjectFiles(projectId, path) }
      }
      const files = await repository.listProjectFiles(projectId, path)
      return { path, entries: immediateLegacyEntries(files, path) }
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
        let raw = await readEmbeddedProjectFileRaw(projectId, path)
        if (!raw) {
          // One-time migration of a file that only exists in the legacy store.
          const legacy = await repository.readProjectFile(projectId, path)
          if (legacy) {
            await writeEmbeddedProjectFile(projectId, legacy.path, legacy.content)
            raw = await readEmbeddedProjectFileRaw(projectId, path)
          }
        }
        if (!raw) return { status: 404, headers: {} as Record<string, string>, body: new Uint8Array() }
        return {
          status: 200,
          headers: {
            'Content-Type': raw.mimeType,
            'Content-Length': String(raw.bytes.length),
          },
          body: raw.bytes,
        }
      }
      const file = await repository.readProjectFile(projectId, path)
      if (!file) return { status: 404, headers: {} as Record<string, string>, body: new Uint8Array() }
      return { status: 200, headers: { 'Content-Type': 'text/plain; charset=utf-8' }, body: new TextEncoder().encode(file.content) }
    },
    async browseDirectory(path = '') {
      const projects = await repository.listProjects()
      const relative = path.replace(/^mobile:\/\//, '').replace(/^\/+|\/+$/g, '')
      if (!relative) {
        return {
          path: 'mobile://',
          entries: projects.map(project => ({ name: project.id, type: 'directory' as const, size: 0, ext: '' })),
        }
      }
      const [projectId, ...parts] = relative.split('/')
      if (!projects.some(project => project.id === projectId)) throw new Error('项目不存在')
      const projectPath = parts.join('/')
      if (hasEmbeddedRustCore()) {
        if (!projectPath) await listEmbeddedProjectFiles(projectId, '')
        return await browseEmbeddedProjectDirectory(`mobile://${relative}`)
      }
      const files = await repository.listProjectFiles(projectId, projectPath)
      return { path: `mobile://${relative}`, entries: immediateLegacyEntries(files, projectPath) }
    },
  }
}

function immediateLegacyEntries(files: Array<{ path: string; content: string }>, path: string) {
  const prefix = path.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')
  const entries = new Map<string, { name: string; type: 'directory' | 'file'; size: number; ext: string }>()
  for (const file of files) {
    const relative = prefix ? file.path.slice(prefix.length + 1) : file.path
    if (!relative || (prefix && !file.path.startsWith(`${prefix}/`))) continue
    const [name, ...rest] = relative.split('/')
    if (rest.length) {
      entries.set(name, { name, type: 'directory', size: 0, ext: '' })
    } else if (!entries.has(name)) {
      entries.set(name, {
        name,
        type: 'file',
        size: new TextEncoder().encode(file.content).length,
        ext: name.includes('.') ? name.split('.').pop()?.toLowerCase() || '' : '',
      })
    }
  }
  return [...entries.values()].sort((left, right) =>
    Number(right.type === 'directory') - Number(left.type === 'directory')
      || left.name.toLowerCase().localeCompare(right.name.toLowerCase())
      || left.name.localeCompare(right.name),
  )
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
