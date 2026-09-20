import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CoreAppSnapshot, TransportMessage } from '@lamtools/ui'
import type { LocalDatabase } from '../src/storage/Database'
import { createLocalRepository, type LocalState } from '../src/storage'
import { MemorySecureStorage } from '../src/native/secureStorage'
import { createStandaloneProjectClient } from '../src/standalone/StandaloneProjectClient'
import { StandaloneConfigStore } from '../src/standalone/StandaloneConfigStore'
import { StandaloneTransport } from '../src/standalone/StandaloneTransport'

class MemoryDatabase implements LocalDatabase<LocalState> {
  value: LocalState | null = null
  async open() {}
  async read() { return this.value }
  async write(value: LocalState) { this.value = JSON.parse(JSON.stringify(value)) as LocalState }
  async close() {}
}

afterEach(() => vi.unstubAllGlobals())

describe('StandaloneTransport', () => {
  it('updates an existing standalone model by its record id', async () => {
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test',
      api_type: 'openai',
      base_url: 'https://model.invalid/v1',
      api_key: 'secret',
      models: [{ model_id: 'old-model', display_name: 'Old Model' }],
    })
    const before = await config.handleRpc('config.models.list', {})
    const recordId = String((before?.models as Array<{ id: string }>)[0]?.id || '')

    await config.handleRpc('config.models.upsert', {
      model_record_id: recordId,
      provider_id: 'test',
      model_id: 'new-model',
      display_name: 'New Model',
    })

    const after = await config.handleRpc('config.models.list', {})
    expect(after?.models).toEqual([expect.objectContaining({
      id: recordId,
      model_id: 'new-model',
      display_name: 'New Model',
    })])
  })

  it('creates local projects and completes a direct model turn without an account', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test',
      api_type: 'openai',
      base_url: 'https://model.invalid/v1',
      api_key: 'secret',
      models: [{ model_id: 'chat-model', display_name: 'Chat Model' }],
    })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      choices: [{ message: { content: '本地独立回复' } }],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))

    const projectClient = createStandaloneProjectClient(repository)
    const created = await projectClient.create({ name: '手机项目', work_root: '' })
    const transport = new StandaloneTransport(repository, config)
    const snapshots: CoreAppSnapshot[] = []
    transport.subscribe((message: TransportMessage) => {
      if (message.method === 'thread/snapshot' && message.params) snapshots.push(message.params as unknown as CoreAppSnapshot)
    })

    await transport.connect()
    await transport.request({ method: 'initialize', params: {} })
    await transport.request({
      method: 'turn/start',
      params: {
        thread_id: created.session.id,
        input: [{ type: 'text', text: '你好' }],
      },
    })

    await vi.waitFor(() => expect(snapshots.at(-1)?.status).toBe('completed'))
    const resumed = await transport.request<Record<string, unknown>>({
      method: 'thread/resume',
      params: { thread_id: created.session.id },
    })
    const snapshot = resumed.snapshot as CoreAppSnapshot
    const assistant = Object.values(snapshot.core?.items || {}).find((item) => item.payload?.type === 'agentMessage')
    expect(assistant?.payload?.content).toBe('本地独立回复')
    expect(await repository.listProjects()).toHaveLength(1)
    expect(await repository.listSessions(created.project.id)).toHaveLength(1)
  })

  it('rejects filesystem writes with the mobile device boundary message', async () => {
    const repository = createLocalRepository(new MemoryDatabase())
    const projectClient = createStandaloneProjectClient(repository)
    const created = await projectClient.create({ name: '手机项目', work_root: '' })
    await expect(projectClient.writeFile(created.project.id, 'a.txt', 'x'))
      .rejects.toThrow('设备拒绝了您的请求')
  })
})
