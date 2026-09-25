import { describe, expect, it, vi } from 'vitest'
import { createLocalRepository, type LocalState } from '../src/storage'
import type { LocalDatabase } from '../src/storage/Database'
import { MemorySecureStorage } from '../src/native/secureStorage'
import { StandaloneConfigStore } from '../src/standalone/StandaloneConfigStore'
import { MemoryStandaloneStateStorage } from '../src/standalone/StandaloneStateStorage'
import { StandaloneArrangeStore, STANDALONE_ARRANGE_NOTICE } from '../src/standalone/StandaloneArrangeStore'
import { searchStandaloneWorkspace } from '../src/standalone/StandaloneWorkspaceSearch'
import { exportStandaloneSession } from '../src/standalone/StandaloneSessionExport'
import { StandaloneTransport } from '../src/standalone/StandaloneTransport'
import { checkStandaloneUpdate, MOBILE_UPDATE_MANIFEST } from '../src/standalone/StandaloneUpdate'

class MemoryDatabase implements LocalDatabase<LocalState> {
  value: LocalState | null = null
  async open() {}
  async read() { return this.value }
  async write(value: LocalState) { this.value = JSON.parse(JSON.stringify(value)) as LocalState }
  async close() {}
}

describe('standalone reachable RPCs', () => {
  it('checks the dedicated mobile manifest for current and newer APK versions', async () => {
    const manifest = {
      version: '0.1.7', download_url: 'https://example.test/downloads/Sunday-mobile-latest.apk',
      release_url: 'https://example.test/#download',
    }
    const fetcher = vi.fn(async (url: string) => {
      expect(url).toBe(MOBILE_UPDATE_MANIFEST)
      return { ok: true, json: async () => manifest }
    })
    vi.stubGlobal('fetch', fetcher)
    expect((await checkStandaloneUpdate('0.1.7')).status).toBe('up_to_date')
    manifest.version = '0.1.8'
    expect((await checkStandaloneUpdate('0.1.7')).status).toBe('update_available')
    manifest.download_url = 'http://insecure.test/app.apk'
    expect((await checkStandaloneUpdate('0.1.7')).status).toBe('check_failed')
    vi.unstubAllGlobals()
  })

  it('ranks a pre-release below its release, so beta installs still get updates', async () => {
    // 桌面的 compare_versions 与这里必须同语义：0.1.30-beta.1 < 0.1.30。
    const manifest = {
      version: '0.1.30-beta.1',
      download_url: 'https://example.test/downloads/Sunday-mobile-latest.apk',
      release_url: 'https://example.test/#download',
    }
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => manifest })))

    // 同版本预发布：已最新
    expect((await checkStandaloneUpdate('0.1.30-beta.1')).status).toBe('up_to_date')
    // 预发布用户看到正式版 → 有更新（旧实现把它判成"已是最新"）
    manifest.version = '0.1.30'
    expect((await checkStandaloneUpdate('0.1.30-beta.1')).status).toBe('update_available')
    // 正式版不会因为清单是预发布而"降级"
    manifest.version = '0.1.30-beta.1'
    expect((await checkStandaloneUpdate('0.1.30')).status).toBe('up_to_date')
    // 尾零补齐：相同版本的不同写法视为相等
    manifest.version = '0.1.30.0'
    expect((await checkStandaloneUpdate('0.1.30')).status).toBe('up_to_date')
    vi.unstubAllGlobals()
  })

  it('names the address that failed when the update manifest cannot be read', async () => {
    // Every one of these was the on-device result until the manifest was
    // actually published, so the error has to say where the app looked.
    const cases: Array<() => void> = [
      () => vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) }))),
      () => vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) }))),
      () => vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Network request failed') })),
      () => vi.stubGlobal('fetch', vi.fn(async () => ({
        ok: true, json: async () => { throw new SyntaxError('Unexpected token <') },
      }))),
    ]
    const failures: Array<Record<string, unknown>> = []
    for (const stub of cases) {
      stub()
      const result = await checkStandaloneUpdate('0.1.25')
      expect(result.status).toBe('check_failed')
      expect(result.current_version).toBe('0.1.25')
      failures.push(result)
      vi.unstubAllGlobals()
    }
    expect(String(failures[0].error)).toContain('HTTP 404')
    expect(String(failures[1].error)).toContain('HTTP 500')
    expect(String(failures[2].error)).toContain('不可达')
    expect(String(failures[3].error)).toContain('Unexpected token')
    for (const failure of failures) {
      expect(String(failure.error)).toContain(MOBILE_UPDATE_MANIFEST)
    }
  })

  it('persists model notes and can clear them explicitly', async () => {
    const storage = new MemoryStandaloneStateStorage<any>()
    const secrets = new MemorySecureStorage()
    const config = new StandaloneConfigStore(secrets, storage)
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_key: 'secret', models: [{ model_id: 'm1', notes: 'Use for code' }],
    })
    const restored = new StandaloneConfigStore(secrets, storage)
    expect((await restored.activeModel()).model.notes).toBe('Use for code')
    await restored.handleRpc('config.models.upsert', { model_record_id: 'test:m1', provider_id: 'test', model_id: 'm1', notes: '' })
    expect((await new StandaloneConfigStore(secrets, storage).activeModel()).model.notes).toBe('')
  })

  it('searches local project names and content, and rejects empty queries', async () => {
    const repo = createLocalRepository(new MemoryDatabase())
    await repo.init()
    const { project } = await repo.createLocalProject({ name: 'P' })
    await repo.writeProjectFile(project.id, 'notes/alpha.txt', 'one\nneedle here\nthree')
    expect((await searchStandaloneWorkspace(repo, { mode: 'files', query: 'alpha' })).results)
      .toEqual([{ path: 'notes/alpha.txt' }])
    expect((await searchStandaloneWorkspace(repo, { mode: 'content', query: 'needle' })).results)
      .toEqual([{ path: 'notes/alpha.txt', line: 2, content: 'needle here' }])
    await expect(searchStandaloneWorkspace(repo, { query: ' ' })).rejects.toThrow('query 不能为空')
  })

  it('exports transcript and a valid full ZIP from a persisted snapshot', async () => {
    const repo = createLocalRepository(new MemoryDatabase())
    await repo.init()
    const thread = await repo.createLocalSession(undefined, 'Export')
    await repo.saveLocalSnapshot({
      thread_id: thread.id, snapshot_seq: 1, revision: 1, status: 'completed',
      turns: {}, items: {}, item_order: [], requests: {}, artifacts: {}, queue: [],
      core: {
        thread_id: thread.id, snapshot_seq: 1, revision: 1, status: 'completed',
        turns: { t1: { turn_id: 't1', status: 'completed', items: ['u1', 'a1'], seq: 1, created_at: '2026-09-23T00:00:00Z' } },
        items: {
          u1: { item_id: 'u1', turn_id: 't1', kind: 'message', type: 'userMessage', status: 'completed', seq: 1, payload: { type: 'userMessage', content: [{ type: 'text', text: '你好' }] } },
          a1: { item_id: 'a1', turn_id: 't1', kind: 'message', type: 'agentMessage', status: 'completed', seq: 2, payload: { type: 'agentMessage', content: '您好' } },
        }, item_order: ['u1', 'a1'], requests: {}, artifacts: {},
      },
    } as any)
    const markdown = await exportStandaloneSession(repo, thread.id, { mode: 'transcript', format: 'markdown' })
    expect(markdown.status).toBe(200)
    expect(new TextDecoder().decode(markdown.body)).toContain('您好')
    const attachmentId = 'a'.repeat(32)
    const attachmentBytes = Uint8Array.of(0, 255, 1, 2)
    const attachment = {
      id: attachmentId, session_id: thread.id, filename: 'proof.bin', mime_type: 'application/octet-stream',
      size: attachmentBytes.length, preview_type: 'external',
    }
    const zip = await exportStandaloneSession(repo, thread.id, { mode: 'full', format: 'zip' }, {
      list: async () => [attachment],
      read: async () => ({ metadata: attachment, bytes: attachmentBytes }),
    })
    expect(zip.status).toBe(200)
    const JSZip = (await import('jszip')).default
    const archive = await JSZip.loadAsync(zip.body)
    expect(await archive.file('session.json')?.async('string')).toContain('Export')
    expect(await archive.file('snapshot.json')?.async('string')).toContain('您好')
    expect(await archive.file(`attachments/${attachmentId}/content.bin`)?.async('uint8array')).toEqual(attachmentBytes)
    expect(await archive.file('attachments.jsonl')?.async('string')).toContain(attachmentId)
  })

  it('persists Arrange drafts as paused and refuses false resume success', async () => {
    const repo = createLocalRepository(new MemoryDatabase())
    await repo.init()
    const { project } = await repo.createLocalProject({ name: 'P' })
    const storage = new MemoryStandaloneStateStorage<any>()
    const store = new StandaloneArrangeStore(repo, storage)
    const created = await store.handleRpc('arrange.create', {
      work_root: project.workRoot || project.path, kind: 'routine', operation: 'turn.start',
      payload: { message: 'hello' }, trigger: { type: 'interval', every_seconds: 60 },
    })
    const id = (created?.job as { id: string }).id
    expect(created?.job).toEqual(expect.objectContaining({ status: 'paused', last_error: STANDALONE_ARRANGE_NOTICE }))
    const restored = new StandaloneArrangeStore(repo, storage)
    expect((await restored.handleRpc('arrange.list', {}))?.jobs).toHaveLength(1)
    expect((await restored.handleRpc('arrange.occurrence.list', { job_id: id }))?.occurrences).toEqual([])
    await expect(restored.handleRpc('arrange.resume', { job_id: id })).rejects.toThrow('后台调度器')
    expect((await restored.handleRpc('arrange.cancel', { job_id: id }))?.job).toEqual(expect.objectContaining({ status: 'cancelled' }))
  })

  it('dispatches queued input after the active native turn finishes', async () => {
    const repo = createLocalRepository(new MemoryDatabase())
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', { name: 'Test', api_key: 'secret', models: [{ model_id: 'm1' }] })
    await repo.init()
    const thread = await repo.createLocalSession()
    let finishFirst!: (value: any) => void
    const first = new Promise<any>(resolve => { finishFirst = resolve })
    const run = vi.fn().mockImplementationOnce(() => first).mockResolvedValue({ text: 'second done', runtimeModelId: 'm1', toolRounds: 0 })
    const transport = new StandaloneTransport(repo, config, run)
    await transport.request({ method: 'turn/start', params: { thread_id: thread.id, input: [{ type: 'text', text: 'first' }] } })
    const queued = await transport.request<any>({ method: 'queue/create', params: { thread_id: thread.id, input: [{ type: 'text', text: 'second' }] } })
    expect(queued.snapshot.queue).toHaveLength(1)
    finishFirst({ text: 'first done', runtimeModelId: 'm1', toolRounds: 0 })
    await vi.waitFor(() => expect(run).toHaveBeenCalledTimes(2))
    await vi.waitFor(async () => expect((await transport.request<any>({ method: 'thread/resume', params: { thread_id: thread.id } })).snapshot.queue).toHaveLength(0))
  })

  it('answers an idle queue/create with the queue envelope and sends the message', async () => {
    const repo = createLocalRepository(new MemoryDatabase())
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', { name: 'Test', api_key: 'secret', models: [{ model_id: 'm1' }] })
    await repo.init()
    const thread = await repo.createLocalSession()
    const run = vi.fn().mockResolvedValue({ text: 'done', runtimeModelId: 'm1', toolRounds: 0 })
    const transport = new StandaloneTransport(repo, config, run)

    const response = await transport.request<any>({ method: 'queue/create', params: {
      thread_id: thread.id, input: [{ type: 'text', text: 'hello' }],
    } })
    // This used to answer with turn/start's {accepted, turn_id, revision}, which
    // is another method's contract applied as a queue response.
    expect(response.accepted).toBeUndefined()
    expect(typeof response.queue_item_id).toBe('string')
    expect(Array.isArray(response.snapshot.queue)).toBe(true)

    // With nothing running there is no dispatcher to wait for, so the item must
    // have gone out by the time the call answers.
    await vi.waitFor(() => expect(run).toHaveBeenCalledTimes(1))
    await vi.waitFor(async () => {
      const snapshot = await repo.loadThreadSnapshot(thread.id)
      expect(snapshot?.status).toBe('completed')
      expect(snapshot?.queue || []).toHaveLength(0)
    })
    expect(String(run.mock.calls[0][0].history.at(-1)?.content)).toContain('hello')
  })

  it('refuses to steer a thread with no active turn', async () => {
    const repo = createLocalRepository(new MemoryDatabase())
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', { name: 'Test', api_key: 'secret', models: [{ model_id: 'm1' }] })
    await repo.init()
    const thread = await repo.createLocalSession()
    const run = vi.fn().mockResolvedValue({ text: 'done', runtimeModelId: 'm1', toolRounds: 0 })
    const transport = new StandaloneTransport(repo, config, run)

    await expect(transport.request({ method: 'turn/steer', params: {
      thread_id: thread.id, turn_id: 'turn-that-never-existed', input: [{ type: 'text', text: 'steer' }],
    } })).rejects.toThrow('当前轮次已结束，无法引导')
    // A refused steer must not have queued or sent anything.
    expect(run).not.toHaveBeenCalled()
    expect((await repo.loadThreadSnapshot(thread.id))?.queue || []).toHaveLength(0)
  })
})
