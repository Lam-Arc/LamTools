import { describe, expect, it, vi } from 'vitest'
import { createLocalRepository, type LocalState } from '../src/storage'
import type { LocalDatabase } from '../src/storage/Database'
import { MemorySecureStorage } from '../src/native/secureStorage'
import { StandaloneConfigStore } from '../src/standalone/StandaloneConfigStore'
import { MemoryStandaloneStateStorage } from '../src/standalone/StandaloneStateStorage'
import { StandaloneTransport } from '../src/standalone/StandaloneTransport'

class MemoryDatabase implements LocalDatabase<LocalState> {
  value: LocalState | null = null
  async open() {}
  async read() { return this.value }
  async write(value: LocalState) { this.value = JSON.parse(JSON.stringify(value)) as LocalState }
  async close() {}
}

describe('standalone named config operations', () => {
  it('stores global AGENTS and memory content in the host-consumed global context shape', async () => {
    const storage = new MemoryStandaloneStateStorage<any>()
    const secrets = new MemorySecureStorage()
    const config = new StandaloneConfigStore(secrets, storage)

    expect(await config.handleRpc('config.agents_md.get', {})).toEqual({
      agents_md: { content: '', exists: false },
    })
    await config.handleRpc('config.agents_md.set', { content: '# Global rules' })
    await config.handleRpc('config.memory.set', { content: 'Remember this' })
    expect(await config.settings('core.globalContext')).toEqual({
      instructions: '# Global rules',
      memory: 'Remember this',
    })

    const restored = new StandaloneConfigStore(secrets, storage)
    expect(await restored.handleRpc('config.agents_md.get', {})).toEqual({
      agents_md: { content: '# Global rules', exists: true },
    })
    expect(await restored.handleRpc('config.memory.get', {})).toEqual({ content: 'Remember this', exists: true })
    await restored.handleRpc('config.agents_md.set', { content: '' })
    expect(await new StandaloneConfigStore(secrets, storage).settings('core.globalContext')).toEqual({
      instructions: '',
      memory: 'Remember this',
    })
  })

  it('validates and persists load-context named operations in the runtime settings shape', async () => {
    const storage = new MemoryStandaloneStateStorage<any>()
    const config = new StandaloneConfigStore(new MemorySecureStorage(), storage)
    await expect(config.handleRpc('config.load_context.set', { addition: [], except: 'AGENTS.md' }))
      .rejects.toThrow('addition (list) and except (list) are required')
    await expect(config.handleRpc('config.load_context.set', {
      addition: [{ name: 4 }], except: [],
    })).rejects.toThrow('addition items must be objects with a string name')

    const saved = await config.handleRpc('config.load_context.set', {
      addition: [{ name: ' TEAM.md ', priority: 12.7, kind: 'memory' }, { name: 'OTHER.md' }],
      except: [' AGENTS.md ', 3, ''],
    })
    expect(saved).toEqual({
      addition: [
        { name: 'TEAM.md', priority: 12, kind: 'memory' },
        { name: 'OTHER.md', priority: 50, kind: 'system' },
      ],
      except: ['AGENTS.md'],
      exists: true,
    })
    const restored = new StandaloneConfigStore(new MemorySecureStorage(), storage)
    expect(await restored.settings('core.loadContext')).toEqual({
      addition: [
        { name: 'TEAM.md', priority: 12, kind: 'memory' },
        { name: 'OTHER.md', priority: 50, kind: 'system' },
      ],
      except: ['AGENTS.md'],
    })
    expect(await restored.handleRpc('config.load_context.get', {})).toEqual(saved)
  })

  it('keeps model-group CRUD, revisions, model membership, and provider-created models durable', async () => {
    const storage = new MemoryStandaloneStateStorage<any>()
    const secrets = new MemorySecureStorage()
    const config = new StandaloneConfigStore(secrets, storage)
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_key: 'secret', models: [{ model_id: 'm1' }, { model_id: 'm2' }],
    })
    const firstModelIds = ['test:m1', 'test:m2']

    const first = await config.handleRpc('config.model_group.create', {
      name: 'Coding', model_ids: firstModelIds, expected_revision: 0,
    })
    expect(first).toMatchObject({ group_id: expect.any(String), revision: 1 })
    const firstGroupId = String(first?.group_id)
    const second = await config.handleRpc('config.model_group.create', { name: 'Writing' })
    const secondGroupId = String(second?.group_id)
    await expect(config.handleRpc('config.model_group.create', { name: 'coding' })).rejects.toThrow('already exists')
    await expect(config.handleRpc('config.model_group.update', {
      group_id: firstGroupId, name: 'Stale', expected_revision: 0,
    })).rejects.toThrow('revision conflict')

    const changed = await config.handleRpc('config.model_group.members.set', {
      group_id: firstGroupId, model_ids: ['test:m2', 'test:m1', 'test:m2'], expected_revision: 2,
    })
    expect(changed?.groups).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: firstGroupId, model_ids: ['test:m2', 'test:m1'] }),
    ]))
    await expect(config.handleRpc('config.model_group.members.set', {
      group_id: firstGroupId, model_ids: ['missing'],
    })).rejects.toThrow('model not found: missing')

    const reordered = await config.handleRpc('config.model_groups.reorder', {
      group_ids: [secondGroupId, firstGroupId],
    })
    expect((reordered?.groups as Array<Record<string, unknown>>).map(group => group.id))
      .toEqual([secondGroupId, firstGroupId])
    await expect(config.handleRpc('config.model_groups.reorder', { group_ids: [firstGroupId] }))
      .rejects.toThrow('every model group exactly once')

    const created = await config.handleRpc('config.model.create_with_provider', {
      group_id: firstGroupId,
      expected_revision: reordered?.revision,
      model: { model_id: 'm3', display_name: 'Third', notes: 'for tests' },
      provider: {
        mode: 'new', name: 'Gateway', base_url: 'https://gateway.example/v1/', api_key: 'new-secret',
      },
    })
    expect(created).toMatchObject({
      created_provider: true,
      provider: { id: 'gateway', api_key: '********', has_api_key: true },
      model: { model_id: 'm3', display_name: 'Third', notes: 'for tests' },
    })
    const restored = new StandaloneConfigStore(secrets, storage)
    const catalog = await restored.handleRpc('config.model_groups.list', {})
    expect(catalog?.revision).toBe(Number(reordered?.revision) + 1)
    expect((catalog?.groups as Array<Record<string, any>>).find(group => group.id === firstGroupId)?.model_ids)
      .toEqual(['test:m2', 'test:m1', 'gateway:m3'])
    expect((catalog?.memberships as Array<Record<string, unknown>>).every(item => item.available === true)).toBe(true)

    await restored.handleRpc('config.model_group.delete', { group_id: secondGroupId })
    await restored.handleRpc('config.models.delete', { model_id: 'test:m1' })
    const afterDelete = await new StandaloneConfigStore(secrets, storage).handleRpc('config.model_groups.list', {})
    expect((afterDelete?.groups as Array<Record<string, any>>).find(group => group.id === firstGroupId)?.model_ids)
      .toEqual(['test:m2', 'gateway:m3'])
    await new StandaloneConfigStore(secrets, storage).handleRpc('config.provider.delete', { provider_id: 'gateway' })
    const afterProviderDelete = await new StandaloneConfigStore(secrets, storage).handleRpc('config.model_groups.list', {})
    expect((afterProviderDelete?.groups as Array<Record<string, any>>).find(group => group.id === firstGroupId)?.model_ids)
      .toEqual(['test:m2'])
  })

  it('normalizes core.modelRetry defaults and rejects values the native RetryPolicy cannot consume', async () => {
    const storage = new MemoryStandaloneStateStorage<any>()
    const config = new StandaloneConfigStore(new MemorySecureStorage(), storage)
    const initial = await config.handleRpc('settings.get', { namespace: 'core.modelRetry' })
    expect(initial?.value).toEqual({
      retry_delays_seconds: [1, 1, 2, 5, 5],
      model_retries: 10,
      model_timeout_seconds: 360,
      model_stream_idle_timeout_seconds: 120,
      empty_response_retries: 3,
      jitter: true,
    })
    const saved = await config.handleRpc('settings.update', {
      namespace: 'core.modelRetry',
      value: { model_retries: 4, model_stream_idle_timeout_seconds: null, retry_delays_seconds: [0, 0.5] },
    })
    expect(saved?.value).toEqual({
      retry_delays_seconds: [0, 0.5],
      model_retries: 4,
      model_timeout_seconds: 360,
      model_stream_idle_timeout_seconds: null,
      empty_response_retries: 3,
      jitter: true,
    })
    await expect(config.handleRpc('settings.update', {
      namespace: 'core.modelRetry', value: { model_retries: 0 },
    })).rejects.toThrow('model_retries must be a positive integer')
    await expect(config.handleRpc('settings.update', {
      namespace: 'core.modelRetry', value: { unsupported: true },
    })).rejects.toThrow('unsupported model retry setting')
    expect((await new StandaloneConfigStore(new MemorySecureStorage(), storage).settings('core.modelRetry')).model_retries)
      .toBe(4)
  })

  it('passes saved retry and global context settings to the next standalone model request', async () => {
    const config = new StandaloneConfigStore(new MemorySecureStorage())
    await config.handleRpc('config.provider.create', {
      name: 'Test', api_key: 'secret', models: [{ model_id: 'm1' }],
    })
    await config.handleRpc('settings.update', {
      namespace: 'core.modelRetry',
      value: { model_retries: 4, retry_delays_seconds: [0.1], model_stream_idle_timeout_seconds: null },
    })
    await config.handleRpc('config.agents_md.set', { content: 'Global instructions' })
    await config.handleRpc('config.memory.set', { content: 'Global memory' })
    await config.handleRpc('config.load_context.set', {
      addition: [{ name: 'TEAM.md', priority: 20, kind: 'system' }], except: ['CLAUDE.md'],
    })

    const repository = createLocalRepository(new MemoryDatabase())
    await repository.init()
    const thread = await repository.createLocalSession()
    const runAgent = vi.fn(async () => ({ text: 'done', runtimeModelId: 'test:m1', toolRounds: 0 }))
    const transport = new StandaloneTransport(repository, config, runAgent)
    await transport.request({ method: 'turn/start', params: {
      thread_id: thread.id,
      input: [{ type: 'text', text: 'hello' }],
    } })

    await vi.waitFor(() => expect(runAgent).toHaveBeenCalledTimes(1))
    expect(runAgent).toHaveBeenCalledWith(expect.objectContaining({
      retryConfig: expect.objectContaining({
        model_retries: 4,
        retry_delays_seconds: [0.1],
        model_stream_idle_timeout_seconds: null,
      }),
      loadContextConfig: { addition: [{ name: 'TEAM.md', priority: 20, kind: 'system' }], except: ['CLAUDE.md'] },
      context: { modeContext: '', globalInstructions: 'Global instructions', memory: 'Global memory' },
    }))
    await transport.close()
  })
})
