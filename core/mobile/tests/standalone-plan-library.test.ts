import { afterEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

import { createLocalRepository, type LocalState } from '../src/storage'
import type { LocalDatabase } from '../src/storage/Database'
import { createStandaloneProjectClient } from '../src/standalone/StandaloneProjectClient'

/**
 * The phone's 资料库 over 「方案/」: the same folder business the desktop serves
 * from Python, answered here for both of the standalone client's storage modes.
 *
 * The legacy mode keeps the offline cache's flat path map; the embedded mode
 * runs against the real project tree through the native commands — including
 * creating and deleting the folders themselves, which is what the library's
 * 「新建文件夹」 needs on a phone that has no local HTTP server.
 */

class MemoryDatabase implements LocalDatabase<LocalState> {
  value: LocalState | null = null
  async open() {}
  async read() { return this.value }
  async write(value: LocalState) { this.value = JSON.parse(JSON.stringify(value)) as LocalState }
  async close() {}
}

async function legacyClient() {
  const repository = createLocalRepository(new MemoryDatabase())
  const created = await repository.createLocalProject({ name: '离线项目' })
  return { client: createStandaloneProjectClient(repository), projectId: created.project.id }
}

/** A tiny project tree behind the native commands, mirroring the Rust layer. */
function embeddedClient() {
  const directories = new Set<string>()
  const files = new Map<string, string>()
  const normalize = (path: string) => path.replace(/^\/+|\/+$/g, '')

  const ensureDirectory = (path: string) => {
    let current = ''
    for (const part of normalize(path).split('/').filter(Boolean)) {
      current = current ? `${current}/${part}` : part
      directories.add(current)
    }
  }

  vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
  invokeMock.mockImplementation(async (command: string, args: Record<string, any> = {}) => {
    const path = normalize(String(args.path ?? ''))
    if (command === 'project_file_list') {
      // 和原生层一样：目录不存在时 read_dir 直接失败。
      if (path && !directories.has(path)) throw new Error(`not found: ${path}`)
      const prefix = path ? `${path}/` : ''
      const names = new Map<string, { name: string; type: 'directory' | 'file'; size: number; ext: string; mtime: number }>()
      for (const directory of directories) {
        if (directory === path || !directory.startsWith(prefix)) continue
        const rest = directory.slice(prefix.length)
        if (rest.includes('/')) continue
        names.set(rest, { name: rest, type: 'directory', size: 0, ext: '', mtime: 0 })
      }
      for (const [filePath, content] of files) {
        if (!filePath.startsWith(prefix)) continue
        const rest = filePath.slice(prefix.length)
        if (!rest || rest.includes('/')) continue
        names.set(rest, {
          name: rest,
          type: 'file',
          size: content.length,
          ext: rest.includes('.') ? rest.split('.').pop()!.toLowerCase() : '',
          mtime: 1700000000,
        })
      }
      return [...names.values()]
    }
    if (command === 'project_file_read') {
      const content = files.get(path)
      return content === undefined ? null : { path, content }
    }
    if (command === 'project_file_write') {
      ensureDirectory(path.slice(0, path.lastIndexOf('/')))
      files.set(path, String(args.content ?? ''))
      return { path, content: String(args.content ?? '') }
    }
    if (command === 'project_file_delete') {
      if (!files.delete(path)) throw new Error(`文件不存在: ${path}`)
      return null
    }
    if (command === 'project_directory_create') {
      if (directories.has(path) || files.has(path)) throw new Error(`同名文件夹已存在: ${path}`)
      ensureDirectory(path)
      return null
    }
    if (command === 'project_directory_delete') {
      const prefix = `${path}/`
      const occupied = [...files.keys()].some(filePath => filePath.startsWith(prefix))
        || [...directories].some(directory => directory.startsWith(prefix))
      if (occupied) throw new Error('directory not empty')
      if (!directories.delete(path)) throw new Error(`文件夹不存在: ${path}`)
      return null
    }
    throw new Error(`unexpected ${command}`)
  })
  return { client: createStandaloneProjectClient(createLocalRepository(new MemoryDatabase())), projectId: 'p1' }
}

afterEach(() => { invokeMock.mockReset(); vi.unstubAllGlobals() })

describe.each([
  ['离线缓存', legacyClient],
  ['原生项目树', embeddedClient],
] as const)('standalone 资料库 (%s)', (_label, build) => {
  it('creates a folder, keeps it in the listing and refuses a duplicate', async () => {
    const { client, projectId } = await build()

    const created = await client.createPlanLibraryFolder(projectId, '归档')
    expect(created.folder).toMatchObject({ name: '归档', path: '方案/归档', count: 0 })

    const listed = await client.listPlanLibrary(projectId)
    expect(listed.dir).toBe('方案')
    expect(listed.folders.map(folder => folder.name)).toEqual(['归档'])

    await expect(client.createPlanLibraryFolder(projectId, '归档')).rejects.toThrow()
    await expect(client.createPlanLibraryFolder(projectId, '嵌套/不行')).rejects.toThrow()
    await expect(client.createPlanLibraryFolder(projectId, '   ')).rejects.toThrow()
  })

  it('creates, moves, renames, stars and deletes plans inside a folder', async () => {
    const { client, projectId } = await build()
    await client.createPlanLibraryFolder(projectId, '归档')

    const created = await client.createPlanLibraryFile(projectId, '实验方案', '归档')
    expect(created.entry).toMatchObject({
      path: '方案/归档/实验方案.md',
      folder: '归档',
      status: 'draft',
      title: '实验方案',
    })
    await expect(client.createPlanLibraryFile(projectId, '实验方案', '归档')).rejects.toThrow()

    const withCount = await client.listPlanLibrary(projectId)
    expect(withCount.folders[0].count).toBe(1)
    expect(withCount.entries.map(entry => entry.folder)).toEqual(['归档'])

    const starred = await client.favoritePlanLibraryFile(projectId, created.entry.path, true)
    expect(starred.entry.favorite).toBe(true)

    const renamed = await client.renamePlanLibraryFile(projectId, created.entry.path, '改名后')
    expect(renamed.entry.path).toBe('方案/归档/改名后.md')
    expect(renamed.entry.folder).toBe('归档')

    const moved = await client.movePlanLibraryFile(projectId, renamed.entry.path, '')
    expect(moved.entry).toMatchObject({ path: '方案/改名后.md', folder: '' })
    expect((await client.listPlanLibrary(projectId)).folders[0].count).toBe(0)

    const rejected = await client.movePlanLibraryFile(projectId, moved.entry.path, '归档')
    expect(rejected.entry.folder).toBe('归档')
    await expect(client.movePlanLibraryFile(projectId, '方案/没有.md', '归档')).rejects.toThrow()
    await expect(client.renamePlanLibraryFile(projectId, 'AGENTS.md', 'x')).rejects.toThrow()
  })

  it('only deletes an empty folder, and never leaves the library', async () => {
    const { client, projectId } = await build()
    const folder = (await client.createPlanLibraryFolder(projectId, '空夹')).folder

    const listed = await client.listPlanLibrary(projectId)
    expect(listed.folders.map(item => item.name)).toEqual(['空夹'])

    await client.deletePlanLibraryFolder(projectId, folder.path)
    expect((await client.listPlanLibrary(projectId)).folders).toEqual([])

    await client.createPlanLibraryFolder(projectId, '非空')
    await client.createPlanLibraryFile(projectId, '里面的方案', '非空')
    await expect(client.deletePlanLibraryFolder(projectId, '方案/非空')).rejects.toThrow()

    await expect(client.deletePlanLibraryFolder(projectId, 'AGENTS.md')).rejects.toThrow()
    await expect(client.deletePlanLibraryFolder(projectId, '方案/../AGENTS.md')).rejects.toThrow()
    await expect(client.deletePlanLibraryFolder(projectId, '方案/非空/更深')).rejects.toThrow()
  })

  it('reads an untouched project as an empty library instead of failing', async () => {
    const { client, projectId } = await build()

    // 新项目里「方案/」还不存在；资料库该是空的，不是一个报错。
    const listed = await client.listPlanLibrary(projectId)
    expect(listed.dir).toBe('方案')
    expect(listed.entries).toEqual([])
    expect(listed.folders).toEqual([])
  })

  it('nests folders and reports each level', async () => {
    const { client, projectId } = await build()
    await client.createPlanLibraryFolder(projectId, '归档')
    await client.createPlanLibraryFolder(projectId, '归档/这一期')

    const nested = await client.listPlanLibrary(projectId)
    const byDir = Object.fromEntries(nested.folders.map(folder => [folder.dir, folder]))
    expect(Object.keys(byDir).sort()).toEqual(['归档', '归档/这一期'])
    expect(byDir['归档'].parent).toBe('')
    expect(byDir['归档/这一期'].parent).toBe('归档')
    expect(byDir['归档/这一期'].path).toBe('方案/归档/这一期')

    const plan = (await client.createPlanLibraryFile(projectId, '深层方案', '归档/这一期')).entry
    expect(plan).toMatchObject({ path: '方案/归档/这一期/深层方案.md', folder: '归档/这一期' })

    // 每一层的计数把更深处也算进来。
    const counted = await client.listPlanLibrary(projectId)
    expect(Object.fromEntries(counted.folders.map(folder => [folder.dir, folder.count]))).toEqual({
      归档: 1, '归档/这一期': 1,
    })

    // 上级不存在时不隐式造目录。
    await expect(client.createPlanLibraryFolder(projectId, '还没建/子目录')).rejects.toThrow()
    await expect(client.createPlanLibraryFile(projectId, '无处安放', '还没建')).rejects.toThrow()

    // 挪回根、再挪进另一层；目标不存在要拒绝。
    const movedOut = await client.movePlanLibraryFile(projectId, plan.path, '')
    expect(movedOut.entry.folder).toBe('')
    const movedIn = await client.movePlanLibraryFile(projectId, movedOut.entry.path, '归档')
    expect(movedIn.entry.folder).toBe('归档')
    await expect(client.movePlanLibraryFile(projectId, movedIn.entry.path, '还没建')).rejects.toThrow()

    // 非空的那一层删不掉；清空后可以删。
    await expect(client.deletePlanLibraryFolder(projectId, '方案/归档')).rejects.toThrow()
    await client.deletePlanLibraryFile(projectId, movedIn.entry.path)
    await client.deletePlanLibraryFolder(projectId, '方案/归档/这一期')
    const after = await client.listPlanLibrary(projectId)
    expect(after.folders.map(folder => folder.dir)).toEqual(['归档'])
  })

  it('deletes one plan and answers the same library shape the desktop serves', async () => {
    const { client, projectId } = await build()
    await client.createPlanLibraryFolder(projectId, '归档')
    const entry = (await client.createPlanLibraryFile(projectId, '要删的方案', '归档')).entry

    const listed = await client.listPlanLibrary(projectId)
    expect(Object.keys(listed).sort()).toEqual(['dir', 'entries', 'folders'])
    expect(listed.entries[0].path).toBe(entry.path)

    await client.deletePlanLibraryFile(projectId, entry.path)
    const after = await client.listPlanLibrary(projectId)
    expect(after.entries).toEqual([])
    expect(after.folders[0].count).toBe(0)
  })
})
