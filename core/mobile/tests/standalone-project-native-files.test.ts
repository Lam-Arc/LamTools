import { afterEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

import type { LocalDatabase } from '../src/storage/Database'
import { createLocalRepository, type LocalState } from '../src/storage'
import { createStandaloneProjectClient } from '../src/standalone/StandaloneProjectClient'

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
        return [...nativeFiles.entries()]
          .filter(([entry]) => entry.startsWith(prefix))
          .map(([entry, content]) => ({
            path: entry.slice(prefix.length),
            size: new TextEncoder().encode(content).length,
          }))
      }
      throw new Error(`unexpected command ${command}`)
    })

    const repository = createLocalRepository(new MemoryDatabase())
    const client = createStandaloneProjectClient(repository)
    const created = await client.create({ name: 'Native files', work_root: '' })
    await client.writeFile(created.project.id, 'notes/a.txt', 'hello')

    await expect(client.readFile(created.project.id, 'notes/a.txt')).resolves.toEqual({
      path: 'notes/a.txt',
      content: 'hello',
    })
    await expect(client.listFiles(created.project.id)).resolves.toEqual({
      path: '',
      entries: [{ name: 'notes/a.txt', type: 'file', size: 5, ext: 'txt' }],
    })
    expect(invokeMock).toHaveBeenCalledWith('project_file_write', expect.objectContaining({
      projectId: created.project.id,
      path: 'notes/a.txt',
      content: 'hello',
    }))
  })
})
