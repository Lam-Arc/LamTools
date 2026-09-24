import { afterEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

import { createLocalRepository, type LocalState } from '../src/storage'
import type { LocalDatabase } from '../src/storage/Database'
import { StandaloneTransport } from '../src/standalone/StandaloneTransport'
import { createStandaloneProjectRoutes } from '../src/standalone/StandaloneProjectRoutes'
import { createStandaloneProjectClient } from '../src/standalone/StandaloneProjectClient'

class MemoryDatabase implements LocalDatabase<LocalState> {
  value: LocalState | null = null
  async open() {}
  async read() { return this.value }
  async write(value: LocalState) { this.value = JSON.parse(JSON.stringify(value)) as LocalState }
  async close() {}
}

function jsonRequest(method: string, path: string, body?: unknown) {
  return {
    kind: 'http' as const,
    method,
    path,
    ...(body === undefined ? {} : { body: new TextEncoder().encode(JSON.stringify(body)) }),
  }
}

function decode(body: Uint8Array) {
  return body.length === 0 ? null : JSON.parse(new TextDecoder().decode(body)) as Record<string, unknown>
}

/** A client stub with the real interface, so route behavior is asserted on its own. */
function fakeClient(overrides: Partial<Record<keyof ReturnType<typeof createStandaloneProjectClient>, unknown>> = {}) {
  const calls: Array<{ method: string; args: unknown[] }> = []
  const record = <T>(method: string, value: T) => {
    calls.push({ method, args: [] })
    return value
  }
  const client = {
    list: vi.fn(() => record('list', Promise.resolve([]))),
    create: vi.fn(), get: vi.fn(), update: vi.fn(), rename: vi.fn(), delete: vi.fn(),
    createSession: vi.fn(), listSessions: vi.fn(),
    readAgents: vi.fn((projectId: string) => record('readAgents', Promise.resolve({ content: '# AGENTS', exists: true }))),
    writeAgents: vi.fn((projectId: string, content: string) => record('writeAgents', Promise.resolve({ content, exists: true }))),
    listFiles: vi.fn((projectId: string, path = '') => record('listFiles', Promise.resolve({
      path,
      entries: [
        { name: 'src', type: 'directory', size: 0, ext: '' },
        { name: '.git', type: 'directory', size: 0, ext: '' },
        { name: 'node_modules', type: 'directory', size: 0, ext: '' },
        { name: '.env', type: 'file', size: 3, ext: 'env' },
        { name: 'main.ts', type: 'file', size: 12, ext: 'ts' },
      ],
    }))),
    readFile: vi.fn((projectId: string, path: string) => record('readFile',
      path === 'gone.ts' || path === 'typo.ts'
        ? Promise.reject(new Error('文件不存在'))
        : Promise.resolve({ content: 'hello', path }))),
    writeFile: vi.fn((projectId: string, path: string, content: string) => record('writeFile', Promise.resolve({ content, path }))),
    readRawFile: vi.fn((projectId: string, path: string) => record('readRawFile', Promise.resolve({
      status: 200,
      headers: { 'Content-Type': 'image/png' },
      body: Uint8Array.of(137, 80, 78, 71),
    }))),
    browseDirectory: vi.fn((path = '') => record('browseDirectory', Promise.resolve({
      path: path || 'mobile://',
      entries: [
        { name: 'project-1', type: 'directory' as const, size: 0, ext: '' },
        { name: '.hidden', type: 'directory' as const, size: 0, ext: '' },
        { name: 'node_modules', type: 'directory' as const, size: 0, ext: '' },
        { name: 'notes.md', type: 'file' as const, size: 4, ext: 'md' },
      ],
    }))),
    ...overrides,
  }
  return { client: client as unknown as ReturnType<typeof createStandaloneProjectClient>, calls }
}

afterEach(() => { invokeMock.mockReset(); vi.unstubAllGlobals() })

describe('standalone project HTTP routes', () => {
  it('serves AGENTS.md for read and write, and rejects a write without content', async () => {
    const { client } = fakeClient()
    const handle = createStandaloneProjectRoutes(client)
    const read = await handle(jsonRequest('GET', '/projects/p1/agents-md'))
    expect(read).toMatchObject({ status: 200 })
    expect(decode(read!.body)).toEqual({ content: '# AGENTS', exists: true })
    const written = await handle(jsonRequest('PUT', '/projects/p1/agents-md', { content: '# 新' }))
    expect(decode(written!.body)).toEqual({ content: '# 新', exists: true })
    const missing = await handle(jsonRequest('PUT', '/projects/p1/agents-md', {}))
    expect(missing!.status).toBe(400)
  })

  it('hides build directories in the project file tree but keeps dotfiles', async () => {
    const { client } = fakeClient()
    const handle = createStandaloneProjectRoutes(client)
    const response = await handle(jsonRequest('GET', '/projects/p1/files?path=src'))
    expect(response!.status).toBe(200)
    const payload = decode(response!.body)!
    expect((payload.entries as Array<{ name: string }>).map(entry => entry.name)).toEqual(['src', '.env', 'main.ts'])
    expect(payload.path).toBe('src')
    expect(client.listFiles).toHaveBeenCalledWith('p1', 'src')
  })

  it('reads and writes file content and requires an existing path for writes', async () => {
    const { client } = fakeClient()
    const handle = createStandaloneProjectRoutes(client)
    const read = await handle(jsonRequest('GET', '/projects/p1/files/content?path=a%2Fb.ts'))
    expect(decode(read!.body)).toEqual({ content: 'hello', path: 'a/b.ts' })

    const written = await handle(jsonRequest('PUT', '/projects/p1/files/content?path=a%2Fb.ts', { content: 'next' }))
    expect(written!.status).toBe(200)
    expect(decode(written!.body)).toEqual({ content: 'next', path: 'a/b.ts' })
    expect(client.writeFile).toHaveBeenCalledWith('p1', 'a/b.ts', 'next')

    // Desktop refuses to create a file through this route; a typo stays a typo.
    const missing = await handle(jsonRequest('PUT', '/projects/p1/files/content?path=typo.ts', { content: 'x' }))
    expect(missing!.status).toBe(404)
    expect(client.writeFile).toHaveBeenCalledTimes(1)
  })

  it('reads raw bytes with the declared content type', async () => {
    const { client } = fakeClient()
    const handle = createStandaloneProjectRoutes(client)
    const response = await handle(jsonRequest('GET', '/projects/p1/files/raw?path=cover.png'))
    expect(response!.status).toBe(200)
    expect(response!.headers['Content-Type']).toBe('image/png')
    expect(Array.from(response!.body)).toEqual([137, 80, 78, 71])
  })

  it('lists the folder picker root and skips hidden and build entries', async () => {
    const { client } = fakeClient()
    const handle = createStandaloneProjectRoutes(client)
    const response = await handle(jsonRequest('GET', '/browse-directory'))
    expect(response!.status).toBe(200)
    const payload = decode(response!.body)!
    expect((payload.entries as Array<{ name: string }>).map(entry => entry.name)).toEqual(['project-1', 'notes.md'])
    expect(payload.path).toBe('mobile://')
  })

  it('maps failures to the desktop status codes and leaves other paths untouched', async () => {
    const { client } = fakeClient({
      readFile: vi.fn(() => Promise.reject(new Error('文件不存在'))) as never,
    })
    const handle = createStandaloneProjectRoutes(client)
    expect((await handle(jsonRequest('GET', '/projects/p1/files/content?path=gone.ts')))!.status).toBe(404)
    expect((await handle(jsonRequest('GET', '/projects/p1/files/content')))!.status).toBe(400)
    expect(await handle(jsonRequest('GET', '/sessions'))).toBeNull()
    expect(await handle(jsonRequest('POST', '/projects/p1/files'))).toBeNull()

    const escaping = fakeClient({
      listFiles: vi.fn(() => Promise.reject(new Error('path must stay inside the current project'))) as never,
    })
    expect((await createStandaloneProjectRoutes(escaping.client)(
      jsonRequest('GET', '/projects/p1/files?path=../../etc'),
    ))!.status).toBe(403)

    const undecodable = fakeClient({
      readFile: vi.fn(() => Promise.reject(new Error('stream did not contain valid UTF-8'))) as never,
    })
    expect((await createStandaloneProjectRoutes(undecodable.client)(
      jsonRequest('GET', '/projects/p1/files/content?path=blob.bin'),
    ))!.status).toBe(422)
  })
})

describe('standalone transport project routes', () => {
  it('answers project file requests through the native project store', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    const bytes = Uint8Array.of(137, 80, 78, 71, 13, 10, 26, 10)
    invokeMock.mockImplementation(async (command: string, args: Record<string, unknown>) => {
      if (command === 'project_agents_md') {
        return args.content === undefined
          ? { content: '# AGENTS', exists: true }
          : { content: args.content, exists: true }
      }
      if (command === 'project_file_read_raw') {
        return args.path === 'cover.png'
          ? { path: args.path, mimeType: 'image/png', dataBase64: Buffer.from(bytes).toString('base64') }
          : null
      }
      if (command === 'project_file_list') {
        return [{ name: 'cover.png', type: 'file', size: bytes.length, ext: 'png' }]
      }
      if (command === 'project_file_read') return null
      throw new Error(`unexpected ${command}`)
    })
    const repository = createLocalRepository(new MemoryDatabase())
    const transport = new StandaloneTransport(repository)
    await transport.connect()

    const agents = await transport.request<{ status: number; body: Uint8Array }>({
      kind: 'http', method: 'GET', path: '/projects/p1/agents-md',
    })
    expect(agents.status).toBe(200)
    expect(decode(agents.body)).toEqual({ content: '# AGENTS', exists: true })

    const listing = await transport.request<{ status: number; body: Uint8Array }>({
      kind: 'http', method: 'GET', path: '/projects/p1/files?path=',
    })
    expect(decode(listing.body)!.entries).toEqual([
      { name: 'cover.png', type: 'file', size: bytes.length, ext: 'png' },
    ])

    const raw = await transport.request<{ status: number; headers: Record<string, string>; body: Uint8Array }>({
      kind: 'http', method: 'GET', path: '/projects/p1/files/raw?path=cover.png',
    })
    expect(raw.headers['Content-Type']).toBe('image/png')
    expect(Array.from(raw.body)).toEqual(Array.from(bytes))

    const gone = await transport.request<{ status: number; body: Uint8Array }>({
      kind: 'http', method: 'GET', path: '/projects/p1/files/raw?path=missing.png',
    })
    expect(gone.status).toBe(404)
  })
})
