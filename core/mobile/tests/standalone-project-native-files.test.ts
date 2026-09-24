import { afterEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

import type { LocalDatabase } from '../src/storage/Database'
import { createLocalRepository, type LocalState } from '../src/storage'
import { createStandaloneProjectClient } from '../src/standalone/StandaloneProjectClient'
import { searchStandaloneWorkspace } from '../src/standalone/StandaloneWorkspaceSearch'

class MemoryDatabase implements LocalDatabase<LocalState> {
  value: LocalState | null = null
  async open() {}
  async read() { return this.value }
  async write(value: LocalState) { this.value = JSON.parse(JSON.stringify(value)) as LocalState }
  async close() {}
}

afterEach(() => {
  invokeMock.mockReset()
  vi.unstubAllGlobals()
})

describe('standalone project native files', () => {
  it('routes UI reads and writes to the same Rust project directory used by Agent tools', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    const nativeFiles = new Map<string, string>()
    invokeMock.mockImplementation(async (command: string, args: Record<string, unknown>) => {
      const key = `${String(args.projectId)}:${String(args.path || '')}`
      if (command === 'project_file_write') {
        nativeFiles.set(key, String(args.content || ''))
        return { path: args.path, content: args.content }
      }
      if (command === 'project_file_read') {
        return nativeFiles.has(key) ? { path: args.path, content: nativeFiles.get(key) } : null
      }
      if (command === 'project_file_list') {
        const prefix = `${String(args.projectId)}:`
        const path = String(args.path || '')
        const children = new Map<string, { name: string; type: 'directory' | 'file'; size: number; ext: string }>()
        for (const [entry, content] of [...nativeFiles.entries()]
          .filter(([entry]) => entry.startsWith(prefix))
        ) {
          const filePath = entry.slice(prefix.length)
          if (path && !filePath.startsWith(`${path}/`)) continue
          const relative = path ? filePath.slice(path.length + 1) : filePath
          const [name, ...remaining] = relative.split('/')
          children.set(name, remaining.length
            ? { name, type: 'directory', size: 0, ext: '' }
            : { name, type: 'file', size: new TextEncoder().encode(content).length, ext: name.split('.').at(-1) || '' })
        }
        return [...children.values()]
      }
      if (command === 'project_directory_browse') {
        const path = String(args.path || 'mobile://')
        const relative = path.replace(/^mobile:\/\//, '').replace(/^\/+|\/+$/g, '')
        if (!relative) return { path: 'mobile://', entries: [] }
        const [projectId, ...parts] = relative.split('/')
        return { path: `mobile://${relative}`, entries: await invokeMock('project_file_list', { projectId, path: parts.join('/') }) }
      }
      throw new Error(`unexpected command ${command}`)
    })

    const repository = createLocalRepository(new MemoryDatabase())
    const client = createStandaloneProjectClient(repository)
    const created = await client.create({ name: 'Native files', work_root: '' })
    await client.writeFile(created.project.id, 'notes/a.txt', 'hello')
    await repository.writeProjectFile(created.project.id, 'notes/a.txt', 'stale legacy')

    await expect(client.readFile(created.project.id, 'notes/a.txt')).resolves.toEqual({
      path: 'notes/a.txt',
      content: 'hello',
    })
    await expect(client.listFiles(created.project.id)).resolves.toEqual({
      path: '',
      entries: [{ name: 'notes', type: 'directory', size: 0, ext: '' }],
    })
    await expect(client.listFiles(created.project.id, 'notes')).resolves.toEqual({
      path: 'notes',
      entries: [{ name: 'a.txt', type: 'file', size: 5, ext: 'txt' }],
    })
    await expect(client.readFile(created.project.id, 'notes/a.txt')).resolves.toEqual({
      path: 'notes/a.txt', content: 'hello',
    })
    await expect(client.browseDirectory()).resolves.toEqual({
      path: 'mobile://',
      entries: [{ name: created.project.id, type: 'directory', size: 0, ext: '' }],
    })
    await expect(client.browseDirectory(`mobile://${created.project.id}/notes`)).resolves.toEqual({
      path: `mobile://${created.project.id}/notes`,
      entries: [{ name: 'a.txt', type: 'file', size: 5, ext: 'txt' }],
    })
    expect((await searchStandaloneWorkspace(repository, { mode: 'content', query: 'hello' })).results)
      .toEqual([{ path: 'notes/a.txt', line: 1, content: 'hello' }])
    expect(invokeMock).toHaveBeenCalledWith('project_file_write', expect.objectContaining({
      projectId: created.project.id,
      path: 'notes/a.txt',
      content: 'hello',
    }))
  })

  it('builds the same immediate hierarchy from legacy project files', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const client = createStandaloneProjectClient(repository)
    const created = await client.create({ name: 'Legacy', work_root: '' })
    const id = created.project.id
    await client.writeFile(id, 'notes/a.txt', 'hello')
    await client.writeFile(id, 'notes/deep/b.md', 'world')
    await client.writeFile(id, 'README.md', 'root')

    await expect(client.listFiles(id)).resolves.toEqual({
      path: '',
      entries: [
        { name: 'notes', type: 'directory', size: 0, ext: '' },
        { name: 'README.md', type: 'file', size: 4, ext: 'md' },
      ],
    })
    await expect(client.listFiles(id, 'notes')).resolves.toEqual({
      path: 'notes',
      entries: [
        { name: 'deep', type: 'directory', size: 0, ext: '' },
        { name: 'a.txt', type: 'file', size: 5, ext: 'txt' },
      ],
    })
    await expect(client.browseDirectory(`mobile://${id}/notes/deep`)).resolves.toEqual({
      path: `mobile://${id}/notes/deep`,
      entries: [{ name: 'b.md', type: 'file', size: 5, ext: 'md' }],
    })
  })
})
