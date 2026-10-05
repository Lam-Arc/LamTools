import {
  CORE_PROJECT_COLOR_KEYS,
  CORE_PROJECT_ICON_KEYS,
  DEFAULT_CORE_PROJECT_COLOR_KEY,
  DEFAULT_CORE_PROJECT_ICON_KEY,
  type CorePlanLibraryFolder,
  type CoreProject,
  type CoreProjectClient,
  type CoreProjectColorKey,
  type CoreProjectIconKey,
} from '@lamtools/ui'
import type { LocalProject, LocalRepository, LocalThread } from '../storage'
import {
  hasEmbeddedRustCore,
  browseEmbeddedProjectDirectory,
  createEmbeddedProjectDirectory,
  deleteEmbeddedProjectDirectory,
  deleteEmbeddedProjectFile,
  listEmbeddedProjectFiles,
  readEmbeddedProjectAgents,
  readEmbeddedProjectFile,
  readEmbeddedProjectFileRaw,
  writeEmbeddedProjectAgents,
  writeEmbeddedProjectFile,
} from '../native/rustAgent'
import {
  PLAN_LIBRARY_DIRNAME,
  type PlanLibraryScanEntry,
  isPlanLibraryPath,
  parsePlanDocument,
  planPath,
  sortPlanEntries,
  upsertPlanFrontmatterField,
} from './planLibraryScan'

export function createStandaloneProjectClient(repository: LocalRepository): CoreProjectClient {
  /** Read one project file in either storage mode, normalized for the plan ops. */
  async function readPlanSource(projectId: string, path: string): Promise<{ content: string; mtime: number } | null> {
    if (hasEmbeddedRustCore()) {
      const file = await readEmbeddedProjectFile(projectId, path)
      return file ? { content: file.content, mtime: Date.now() / 1000 } : null
    }
    const file = await repository.readProjectFile(projectId, path)
    return file ? { content: file.content, mtime: Date.parse(file.updatedAt) / 1000 || 0 } : null
  }
  async function writePlanSource(projectId: string, path: string, content: string): Promise<void> {
    if (hasEmbeddedRustCore()) await writeEmbeddedProjectFile(projectId, path, content)
    else await repository.writeProjectFile(projectId, path, content)
  }
  async function deletePlanSource(projectId: string, path: string): Promise<void> {
    if (hasEmbeddedRustCore()) await deleteEmbeddedProjectFile(projectId, path)
    else await repository.deleteProjectFile(projectId, path)
  }

  /** Immediate child directories of one project path, in either storage mode. */
  async function listChildDirectories(projectId: string, path: string): Promise<string[]> {
    if (hasEmbeddedRustCore()) {
      const listing = await listEmbeddedProjectFiles(projectId, path).catch((error: unknown) => {
        // 目录还不存在（例如新项目里的「方案/」）就是空的，不是错误。
        if (isMissingPath(error)) return []
        throw error
      })
      return listing.filter(entry => entry.type === 'directory').map(entry => entry.name)
    }
    const directories = await repository.listProjectDirectories(projectId, path)
    return directories.map(directory => directory.path.split('/').pop() || directory.path)
  }

  /** The .md files directly inside one project directory, newest data included. */
  async function listPlanFiles(
    projectId: string,
    path: string,
  ): Promise<{ name: string; path: string; updatedAt: number }[]> {
    const prefix = `${path}/`
    if (hasEmbeddedRustCore()) {
      const listing = await listEmbeddedProjectFiles(projectId, path).catch((error: unknown) => {
        if (isMissingPath(error)) return []
        throw error
      })
      return listing
        .filter(entry => entry.type === 'file' && entry.name.toLowerCase().endsWith('.md'))
        .map(entry => ({ name: entry.name, path: `${prefix}${entry.name}`, updatedAt: entry.mtime }))
    }
    const files = await repository.listProjectFiles(projectId, path)
    return files
      .filter(file => file.path.startsWith(prefix) && !file.path.slice(prefix.length).includes('/'))
      .filter(file => file.path.toLowerCase().endsWith('.md'))
      .map(file => ({
        name: file.path.slice(prefix.length),
        path: file.path,
        updatedAt: Date.parse(file.updatedAt) / 1000 || 0,
      }))
  }

  /** Whether one folder inside 「方案/」 is already there. */
  async function planFolderExists(projectId: string, dir: string): Promise<boolean> {
    const parent = dir.includes('/') ? dir.slice(0, dir.lastIndexOf('/')) : ''
    const parentPath = parent ? `${PLAN_LIBRARY_DIRNAME}/${parent}` : PLAN_LIBRARY_DIRNAME
    const name = dir.split('/').pop() || dir
    return (await listChildDirectories(projectId, parentPath)).includes(name)
  }

  /** 目标文件夹必须已经在那儿：不做隐式建父目录，和桌面端一致。 */
  async function requirePlanFolder(projectId: string, dir: string): Promise<void> {
    if (!dir) return
    if (!(await planFolderExists(projectId, dir))) throw new Error('目标文件夹不存在')
  }

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
    async listPlanLibrary(projectId) {
      const root = PLAN_LIBRARY_DIRNAME
      const entries: PlanLibraryScanEntry[] = []
      const folders: CorePlanLibraryFolder[] = []

      // 逐层走完整棵树：文件夹可以嵌套，目录结构就是索引。
      const pending: string[] = ['']
      while (pending.length) {
        const parent = pending.shift()!
        const directory = parent ? `${root}/${parent}` : root
        for (const file of await listPlanFiles(projectId, directory)) {
          const source = await readPlanSource(projectId, file.path)
          if (source) entries.push(parsePlanDocument(source.content, file.name, file.updatedAt, file.path))
        }
        for (const name of await listChildDirectories(projectId, directory)) {
          const dir = parent ? `${parent}/${name}` : name
          pending.push(dir)
          folders.push({ name, path: `${root}/${dir}`, dir, parent, count: 0 })
        }
      }
      // 每一层的计数把更深处也算进来，和桌面端一致。
      const counts = new Map<string, number>()
      for (const entry of entries) {
        const parts = entry.folder ? entry.folder.split('/') : []
        for (let depth = 1; depth <= parts.length; depth += 1) {
          const dir = parts.slice(0, depth).join('/')
          counts.set(dir, (counts.get(dir) || 0) + 1)
        }
      }
      for (const folder of folders) folder.count = counts.get(folder.dir) || 0
      folders.sort((left, right) => left.dir.localeCompare(right.dir))
      return { dir: root, entries: sortPlanEntries(entries), folders }
    },
    async createPlanLibraryFile(projectId, name, folder = '') {
      const cleaned = cleanPlanSegment(name, '方案')
      const dir = folder ? cleanPlanFolderPath(folder) : ''
      await requirePlanFolder(projectId, dir)
      const parent = dir ? planPath(dir) : PLAN_LIBRARY_DIRNAME
      const fileName = cleaned.toLowerCase().endsWith('.md') ? cleaned : `${cleaned}.md`
      const path = `${parent}/${fileName}`
      const existing = await readPlanSource(projectId, path)
      if (existing) throw new Error('同名方案已存在')
      const skeleton = `---\n状态: 草稿\n摘要:\n---\n\n# ${fileName.slice(0, -3)}\n\n（在这里写下方案内容。就绪后对助手说「可以开工了」。）\n`
      await writePlanSource(projectId, path, skeleton)
      const written = await readPlanSource(projectId, path)
      if (!written) throw new Error('方案创建失败')
      return { entry: parsePlanDocument(written.content, fileName, written.mtime, path) }
    },
    async createPlanLibraryFolder(projectId, path) {
      const dir = cleanPlanFolderPath(path)
      // 一级文件夹的父级就是「方案/」，可以随第一次建夹产生；更深一层要求上级已在。
      await requirePlanFolder(projectId, dir.includes('/') ? dir.slice(0, dir.lastIndexOf('/')) : '')
      const full = planPath(dir)
      if (hasEmbeddedRustCore()) await createEmbeddedProjectDirectory(projectId, full)
      else await repository.createProjectDirectory(projectId, full)
      return {
        folder: {
          name: dir.split('/').pop() || dir,
          path: full,
          dir,
          parent: dir.includes('/') ? dir.slice(0, dir.lastIndexOf('/')) : '',
          count: 0,
        },
      }
    },
    async deletePlanLibraryFolder(projectId, path) {
      if (!isPlanLibraryPath(path) || path === PLAN_LIBRARY_DIRNAME) throw new Error('路径越出资料库')
      if (hasEmbeddedRustCore()) {
        let inner
        try { inner = await listEmbeddedProjectFiles(projectId, path) }
        catch (error) { if (isMissingPath(error)) throw new Error('文件夹不存在'); throw error }
        if (inner.length) throw new Error('文件夹不是空的，先移走或删除里面的内容')
        await deleteEmbeddedProjectDirectory(projectId, path)
      } else {
        await repository.deleteProjectDirectory(projectId, path)
      }
      return { deleted: path }
    },
    async renamePlanLibraryFile(projectId, path, name) {
      if (!isPlanLibraryPath(path)) throw new Error('路径越出资料库')
      const cleaned = cleanPlanSegment(name, '方案')
      const fileName = cleaned.toLowerCase().endsWith('.md') ? cleaned : `${cleaned}.md`
      const renamedPath = `${path.slice(0, path.lastIndexOf('/') + 1)}${fileName}`
      const source = await readPlanSource(projectId, path)
      if (!source) throw new Error('方案不存在')
      if (renamedPath !== path) {
        const clash = await readPlanSource(projectId, renamedPath)
        if (clash) throw new Error('同名方案已存在')
        await writePlanSource(projectId, renamedPath, source.content)
        await deletePlanSource(projectId, path)
      }
      return { entry: parsePlanDocument(source.content, fileName, source.mtime, renamedPath) }
    },
    async movePlanLibraryFile(projectId, path, folder) {
      if (!isPlanLibraryPath(path)) throw new Error('路径越出资料库')
      const source = await readPlanSource(projectId, path)
      if (!source) throw new Error('方案不存在')
      const dir = folder ? cleanPlanFolderPath(folder) : ''
      await requirePlanFolder(projectId, dir)
      const name = path.split('/').pop() || path
      const parent = dir ? planPath(dir) : PLAN_LIBRARY_DIRNAME
      const destination = `${parent}/${name}`
      if (destination !== path) {
        const clash = await readPlanSource(projectId, destination)
        if (clash) throw new Error('目标文件夹里有同名方案')
        await writePlanSource(projectId, destination, source.content)
        await deletePlanSource(projectId, path)
      }
      return { entry: parsePlanDocument(source.content, name, source.mtime, destination) }
    },
    async favoritePlanLibraryFile(projectId, path, favorite) {
      if (!isPlanLibraryPath(path)) throw new Error('路径越出资料库')
      const source = await readPlanSource(projectId, path)
      if (!source) throw new Error('方案不存在')
      const updated = upsertPlanFrontmatterField(source.content, '收藏', favorite ? 'true' : null)
      if (updated !== source.content) await writePlanSource(projectId, path, updated)
      return { entry: parsePlanDocument(
        updated,
        path.split('/').pop() ?? path,
        Date.now() / 1000,
        path,
      ) }
    },
    async deletePlanLibraryFile(projectId, path) {
      if (!isPlanLibraryPath(path)) throw new Error('路径越出资料库')
      if (!path.toLowerCase().endsWith('.md')) throw new Error('只能删除方案文档（.md）')
      if (hasEmbeddedRustCore()) {
        await deleteEmbeddedProjectFile(projectId, path)
      } else {
        await repository.deleteProjectFile(projectId, path)
      }
      return { deleted: path }
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

/** One on-disk path segment — a plan name or a folder name, validated like the desktop scan. */
function cleanPlanSegment(name: string, kind: string): string {
  const cleaned = (name || '').trim().replace(/^\.+|\.+$/g, '')
  if (!cleaned) throw new Error(`${kind}名称不能为空`)
  if (cleaned === '.' || cleaned === '..' || /[\\/:*?"<>|]/.test(cleaned)) {
    throw new Error(`${kind}名称不能包含路径分隔符或保留字符`)
  }
  return cleaned
}

/** A folder path inside 「方案/」: one or more segments, each validated on its own. */
function cleanPlanFolderPath(path: string): string {
  const segments = (path || '').replace(/\\/g, '/').split('/').filter(segment => segment.trim())
  if (!segments.length) throw new Error('文件夹名称不能为空')
  return segments.map(segment => cleanPlanSegment(segment, '文件夹')).join('/')
}

/** A directory that is simply not there yet reads the same as an empty one. */
function isMissingPath(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error)
  return /not found|no such file|cannot find|does not exist|不存在|os error 2\b/i.test(message)
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
