import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { LocalDatabase } from '../src/storage/Database'
import { createLocalRepository, type LocalState } from '../src/storage'
import type { StandaloneConfigStore } from '../src/standalone/StandaloneConfigStore'
import { StandaloneTransport } from '../src/standalone/StandaloneTransport'
import { parseMultipartFile, type NativeAttachmentMetadata } from '../src/native/attachments'
import b4a from 'b4a'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

class MemoryDatabase implements LocalDatabase<LocalState> {
  value: LocalState | null = null
  async open() {}
  async read() { return this.value }
  async write(value: LocalState) { this.value = JSON.parse(JSON.stringify(value)) as LocalState }
  async close() {}
}

function multipart(filename: string, mime: string, bytes: Uint8Array) {
  const boundary = '----LamToolsBoundaryFixture'
  const encoder = new TextEncoder()
  const head = encoder.encode(`--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${filename}"\r\nContent-Type: ${mime}\r\n\r\n`)
  const tail = encoder.encode(`\r\n--${boundary}--\r\n`)
  const body = new Uint8Array(head.length + bytes.length + tail.length)
  body.set(head)
  body.set(bytes, head.length)
  body.set(tail, head.length + bytes.length)
  return { body, headers: { 'Content-Type': `multipart/form-data; boundary=${boundary}` } }
}

function decode(body: Uint8Array) { return JSON.parse(new TextDecoder().decode(body)) }

beforeEach(() => { invokeMock.mockReset() })

describe('standalone attachment transport', () => {
  it('extracts exact binary bytes and per-file MIME, then waits for durable save before 201', async () => {
    const bytes = Uint8Array.of(0, 255, 13, 10, 45, 45, 0, 42)
    const request = multipart('picture.png', 'image/png', bytes)
    expect(parseMultipartFile(request.body, request.headers['Content-Type'])).toEqual({
      filename: 'picture.png', mime: 'image/png', bytes,
    })
    const repository = createLocalRepository(new MemoryDatabase())
    const session = await repository.createLocalSession(undefined, 'Attachments')
    let finishSave!: (value: NativeAttachmentMetadata) => void
    invokeMock.mockImplementation((command: string) => command === 'sunday_attachment_save'
      ? new Promise(resolve => { finishSave = resolve }) : Promise.reject(new Error(`unexpected ${command}`)))
    const transport = new StandaloneTransport(repository)
    const pending = transport.request<{ status: number; body: Uint8Array }>({
      kind: 'http', method: 'POST', path: `/sessions/${session.id}/attachments`, ...request,
    })
    await vi.waitFor(() => expect(invokeMock).toHaveBeenCalledWith('sunday_attachment_save', {
      sessionId: session.id, filename: 'picture.png', mime: 'image/png', bytes: Array.from(bytes),
    }))
    let settled = false
    void pending.then(() => { settled = true })
    await Promise.resolve()
    expect(settled).toBe(false)
    finishSave({ id: 'a'.repeat(32), session_id: session.id, filename: 'picture.png', mime_type: 'image/png', size: bytes.length, preview_type: 'image' })
    const response = await pending
    expect(response.status).toBe(201)
    expect(decode(response.body).size).toBe(bytes.length)
  })

  it('reads persisted list, metadata, download and preview, and opens with the system', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const session = await repository.createLocalSession(undefined, 'Attachments')
    const metadata = { id: 'b'.repeat(32), session_id: session.id, filename: "héllo's.txt", mime_type: 'text/plain', size: 5, preview_type: 'text' }
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'sunday_attachment_list') return [metadata]
      if (command === 'sunday_attachment_read') return { metadata, bytes: Array.from(new TextEncoder().encode('hello')) }
      if (command === 'sunday_attachment_delete') return true
      if (command === 'sunday_attachment_open') return undefined
      throw new Error(`unexpected ${command}`)
    })
    const transport = new StandaloneTransport(repository)
    const list = await transport.request<{ status: number; body: Uint8Array }>({ kind: 'http', method: 'GET', path: `/sessions/${session.id}/attachments` })
    expect(decode(list.body)).toEqual([metadata])
    const item = await transport.request<{ body: Uint8Array }>({ kind: 'http', method: 'GET', path: `/attachments/${metadata.id}` })
    expect(decode(item.body)).toEqual(metadata)
    const download = await transport.request<{ status: number; headers: Record<string, string>; body: Uint8Array }>({ kind: 'http', method: 'GET', path: `/attachments/${metadata.id}/download` })
    expect(download.headers['Content-Type']).toBe('text/plain')
    expect(download.headers['Content-Disposition']).toBe("attachment; filename*=UTF-8''h%C3%A9llo%27s.txt")
    expect(new TextDecoder().decode(download.body)).toBe('hello')
    const preview = await transport.request<{ body: Uint8Array }>({ kind: 'http', method: 'GET', path: `/attachments/${metadata.id}/preview` })
    expect(decode(preview.body).text).toBe('hello')
    const open = await transport.request<{ status: number }>({ kind: 'http', method: 'POST', path: `/attachments/${metadata.id}/open` })
    expect(open.status).toBe(200)
    expect(invokeMock).toHaveBeenCalledWith('sunday_attachment_open', { id: metadata.id })
    const removed = await transport.request<{ status: number }>({ kind: 'http', method: 'DELETE', path: `/attachments/${metadata.id}` })
    expect(removed.status).toBe(204)
  })

  it('returns client errors for malformed uploads and missing attachment files', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const session = await repository.createLocalSession(undefined, 'Attachments')
    const transport = new StandaloneTransport(repository)
    const malformed = await transport.request<{ status: number }>({
      kind: 'http', method: 'POST', path: `/sessions/${session.id}/attachments`,
      headers: { 'Content-Type': 'multipart/form-data' }, body: new Uint8Array([1, 2, 3]),
    })
    expect(malformed.status).toBe(400)

    invokeMock.mockRejectedValue(new Error('Invalid attachment filename'))
    const rejectedSave = await transport.request<{ status: number }>({
      kind: 'http', method: 'POST', path: `/sessions/${session.id}/attachments`,
      ...multipart('bad.txt', 'text/plain', new TextEncoder().encode('text')),
    })
    expect(rejectedSave.status).toBe(400)

    invokeMock.mockRejectedValue(new Error('The system cannot find the file specified. (os error 2)'))
    const missing = await transport.request<{ status: number }>({
      kind: 'http', method: 'GET', path: `/attachments/${'f'.repeat(32)}`,
    })
    expect(missing.status).toBe(404)
  })

  it('passes bounded text and real image bytes to the model, rehydrates image history, and rejects other binary before acceptance', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const session = await repository.createLocalSession(undefined, 'Attachments')
    const config = {
      handleRpc: async () => null,
      activeModel: async () => ({
        provider: { id: 'fixture-provider', name: 'Fixture', api_type: 'openai', base_url: 'https://model.invalid/v1' },
        model: { id: 'fixture-model', model_id: 'fixture-model', display_name: 'Fixture' },
        apiKey: 'secret',
      }),
      runtimeModels: async () => [],
      settings: async () => ({}),
      subAgentRuntime: async () => ({ enabled: false, guide: '' }),
    } as unknown as StandaloneConfigStore
    const textBytes = new TextEncoder().encode(`actual text${'x'.repeat(200_000)}TAIL-SENTINEL`)
    const textMetadata = { id: 'c'.repeat(32), session_id: session.id, filename: 'truth.txt', mime_type: 'text/plain', size: textBytes.length, preview_type: 'text' }
    const imageBase64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
    const imageBytes = b4a.from(imageBase64, 'base64') as Uint8Array
    const imageMetadata = { id: 'd'.repeat(32), session_id: session.id, filename: 'truth.png', mime_type: 'image/png', size: imageBytes.length, preview_type: 'image' }
    const pdfMetadata = { id: 'e'.repeat(32), session_id: session.id, filename: 'truth.pdf', mime_type: 'application/pdf', size: 4, preview_type: 'pdf' }
    invokeMock.mockImplementation(async (command: string, args: { id?: string }) => {
      if (command !== 'sunday_attachment_read') throw new Error(`unexpected ${command}`)
      return args.id === textMetadata.id
        ? { metadata: textMetadata, bytes: Array.from(textBytes) }
        : args.id === imageMetadata.id
          ? { metadata: imageMetadata, bytes: Array.from(imageBytes) }
          : { metadata: pdfMetadata, bytes: [0, 255, 0, 1] }
    })
    const runAgent = vi.fn(async (input: any) => ({
      text: 'done', runtimeModelId: 'fixture-model', toolRounds: 0,
      runtimeHistory: [...input.history, { role: 'assistant', content: 'done' }],
    }))
    const transport = new StandaloneTransport(repository, config, runAgent)
    const first = await transport.request<{ turn_id: string }>({ method: 'turn/start', params: {
      thread_id: session.id,
      input: [
        { type: 'attachment', attachment_id: textMetadata.id, filename: 'false-name.txt' },
        { type: 'attachment', attachment_id: imageMetadata.id, filename: 'image.png' },
      ],
    } })
    await vi.waitFor(() => expect(runAgent).toHaveBeenCalled())
    const content = String(runAgent.mock.calls[0][0].history.at(-1)?.content || '')
    expect(content).toContain('actual text')
    expect(content).toContain('truth.txt')
    expect(content).toContain('[附件文本已截断至前 200000 字节]')
    expect(content).not.toContain('TAIL-SENTINEL')
    expect(content).not.toContain('false-name.txt')
    expect(runAgent.mock.calls[0][0].history.at(-1)).toEqual(expect.objectContaining({
      role: 'user_multimodal',
      images: [{ attachment_id: imageMetadata.id, mime_type: 'image/png', data_base64: imageBase64 }],
    }))
    await vi.waitFor(async () => {
      expect((await repository.loadThreadSnapshot(session.id))?.core?.turns?.[first.turn_id]?.status).toBe('completed')
    })
    const persistedHistory = (await repository.listSessions()).find(item => item.id === session.id)?.metadata?.rust_runtime_history as any[]
    expect(persistedHistory?.find(message => message.role === 'user_multimodal')?.images).toEqual([{
      attachment_id: imageMetadata.id, mime_type: 'image/png',
    }])

    const second = await transport.request<{ turn_id: string }>({ method: 'turn/start', params: {
      thread_id: session.id, input: [{ type: 'text', text: 'Follow up' }],
    } })
    await vi.waitFor(() => expect(runAgent).toHaveBeenCalledTimes(2))
    await vi.waitFor(async () => {
      expect((await repository.loadThreadSnapshot(session.id))?.core?.turns?.[second.turn_id]?.status).toBe('completed')
    })
    expect(runAgent.mock.calls[1][0].history[0]).toEqual(expect.objectContaining({
      role: 'user_multimodal',
      images: [{ attachment_id: imageMetadata.id, mime_type: 'image/png', data_base64: imageBase64 }],
    }))

    const beforeUnsupported = await repository.loadThreadSnapshot(session.id)
    await expect(transport.request({ method: 'turn/start', params: {
      thread_id: session.id,
      input: [{ type: 'attachment', attachment_id: pdfMetadata.id, filename: pdfMetadata.filename }],
    } })).rejects.toThrow(/不支持附件 truth\.pdf/)
    expect(await repository.loadThreadSnapshot(session.id)).toEqual(beforeUnsupported)
    expect(runAgent).toHaveBeenCalledTimes(2)
  })
})
