import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  coreThinkingModeOptions,
  coreThinkingPayload,
  type CoreExecutionModelSource,
} from '@lamtools/ui'
import { createLocalRepository, type LocalState } from '../src/storage'
import type { LocalDatabase } from '../src/storage/Database'
import { MemorySecureStorage } from '../src/native/secureStorage'
import { StandaloneConfigStore } from '../src/standalone/StandaloneConfigStore'
import { MemoryStandaloneStateStorage } from '../src/standalone/StandaloneStateStorage'
import { StandaloneTransport } from '../src/standalone/StandaloneTransport'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

// The host command this file exercises; the runtime-rs tests own the values it
// answers with, so the ladders below are the compiled profiles' own ladders.
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

/** What the host resolves for a profile id, mirroring `llm_adapters/*.jsonc`. */
const HOST_LADDERS: Record<string, { levels: Array<{ value: string; label: string }>; off_supported: boolean }> = {
  'deepseek-chat': {
    levels: [
      { value: 'max', label: '极高' },
      { value: 'high', label: '高' },
      { value: 'light', label: '轻' },
      { value: 'off', label: '关闭' },
    ],
    off_supported: true,
  },
  glm: {
    levels: [
      { value: 'max', label: '极高' },
      { value: 'high', label: '高' },
      { value: 'light', label: '轻' },
    ],
    off_supported: false,
  },
}

/** What the host answers for the profile a configuration names. */
function hostDeclaration(args: { config?: Record<string, any> } | undefined): unknown {
  // A model's own profile id wins over its provider's, the way the resolver
  // picks the profile the request will use.
  const profileId = args?.config?.modelExtra?.adapter_profile_id
    || args?.config?.providerExtra?.adapter_profile_id
  return HOST_LADDERS[profileId] ?? { levels: [], off_supported: true }
}

invokeMock.mockImplementation(async (command: string, args: { config?: Record<string, any> }) => {
  if (command !== 'sunday_model_reasoning_declaration') throw new Error(`unexpected command: ${command}`)
  return hostDeclaration(args)
})

/** The phone only talks to the host inside a Tauri window. */
function stubTauriRuntime(present: boolean): void {
  const scope = globalThis as { window?: unknown }
  if (!present) {
    delete scope.window
    return
  }
  scope.window = { __TAURI_INTERNALS__: {} }
}

afterEach(() => {
  stubTauriRuntime(false)
  invokeMock.mockClear()
})

async function presetConfig(storage: MemoryStandaloneStateStorage<any>): Promise<StandaloneConfigStore> {
  const config = new StandaloneConfigStore(new MemorySecureStorage(), storage)
  await config.handleRpc('config.provider.create', {
    name: 'DeepSeek',
    api_key: 'secret',
    base_url: 'https://api.deepseek.com/v1',
    extra: { adapter_profile_id: 'deepseek-chat' },
    models: [
      {
        model_id: 'deepseek-v4-flash',
        display_name: 'DeepSeek V4 Flash',
        thinking_supported: true,
        extra: { adapter_profile_id: 'deepseek-chat', capability: 'multimodal' },
      },
      {
        model_id: 'glm-5.3',
        display_name: 'GLM 5.3',
        thinking_supported: true,
        extra: { adapter_profile_id: 'glm' },
      },
    ],
  })
  return config
}

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
    expect(await config.settings('core.globalContext')).toEqual({
      instructions: '# Global rules',
    })

    const restored = new StandaloneConfigStore(secrets, storage)
    expect(await restored.handleRpc('config.agents_md.get', {})).toEqual({
      agents_md: { content: '# Global rules', exists: true },
    })
    await restored.handleRpc('config.agents_md.set', { content: '' })
    expect(await new StandaloneConfigStore(secrets, storage).settings('core.globalContext')).toEqual({
      instructions: '',
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
      model_stream_idle_timeout_seconds: 180,
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
      context: { modeContext: '', globalInstructions: 'Global instructions' },
    }))
    await transport.close()
  })

  it('gives a preset model the ladder the host resolves for its adapter profile', async () => {
    stubTauriRuntime(true)
    const storage = new MemoryStandaloneStateStorage<any>()
    const config = await presetConfig(storage)

    const listed = await config.handleRpc('config.models.list', {})
    const models = (listed?.models || []) as Array<Record<string, unknown>>
    const byModelId = new Map(models.map(model => [String(model.model_id), model]))

    // Both models were added from a preset: their configuration names an adapter
    // profile and declares no ladder of its own, and they still get the model's
    // real grades instead of the product ladder.
    expect(byModelId.get('deepseek-v4-flash')?.reasoning_levels).toEqual([
      { value: 'max', label: '极高' },
      { value: 'high', label: '高' },
      { value: 'light', label: '轻' },
      { value: 'off', label: '关闭' },
    ])
    expect(byModelId.get('deepseek-v4-flash')?.reasoning_off_supported).toBe(true)
    expect(byModelId.get('glm-5.3')?.reasoning_levels).toEqual([
      { value: 'max', label: '极高' },
      { value: 'high', label: '高' },
      { value: 'light', label: '轻' },
    ])
    expect(byModelId.get('glm-5.3')?.reasoning_off_supported).toBe(false)

    // The question carries the configuration the turn path sends, so the ladder
    // describes the profile the next request will actually use.
    expect(invokeMock).toHaveBeenCalledWith('sunday_model_reasoning_declaration', {
      config: expect.objectContaining({
        apiType: 'openai',
        baseUrl: 'https://api.deepseek.com/v1',
        apiModelId: 'deepseek-v4-flash',
        providerName: 'DeepSeek',
        providerExtra: expect.objectContaining({ adapter_profile_id: 'deepseek-chat' }),
        modelExtra: expect.objectContaining({ adapter_profile_id: 'deepseek-chat' }),
      }),
    })

    // The hop that matters: the shared Composer reads these objects directly, so
    // the model's grades — and only those — reach the thinking menu.
    const surface = (modelId: string) => coreThinkingModeOptions({
      model: byModelId.get(modelId) as CoreExecutionModelSource | undefined,
    })
    expect(surface('deepseek-v4-flash').map(option => option.value))
      .toEqual(['max', 'high', 'light', 'off'])
    expect(surface('deepseek-v4-flash').map(option => option.label))
      .toEqual(['极高', '高', '轻', '关闭'])
    expect(surface('glm-5.3').map(option => option.value)).toEqual(['max', 'high', 'light'])
    // Request side: a stored grade the model never declared becomes the strongest
    // one it does accept.
    expect(coreThinkingPayload({
      mode: 'xhigh',
      model: byModelId.get('glm-5.3') as CoreExecutionModelSource,
    }).reasoning_level).toBe('max')

    // The same ladder reaches the turn path and the create answer.
    const deepseekId = String(byModelId.get('deepseek-v4-flash')?.id || '')
    await config.handleRpc('config.models.set_default', { model_id: deepseekId })
    const active = await config.activeModel()
    expect(active.model.id).toBe(deepseekId)
    expect(active.model.reasoning_levels).toHaveLength(4)
    expect(active.model.reasoning_off_supported).toBe(true)

    const group = await config.handleRpc('config.model_group.create', { name: 'Created' })
    const created = await config.handleRpc('config.model.create_with_provider', {
      group_id: String(group?.group_id || ''),
      expected_revision: group?.revision,
      model: { model_id: 'glm-5.3-air', extra: { adapter_profile_id: 'glm' } },
      provider: {
        mode: 'existing',
        provider_id: String(byModelId.get('glm-5.3')?.provider_id || ''),
        base_url: 'https://api.deepseek.com/v1',
      },
    })
    expect(created?.model).toMatchObject({
      model_id: 'glm-5.3-air',
      reasoning_off_supported: false,
      reasoning_levels: [
        { value: 'max', label: '极高' },
        { value: 'high', label: '高' },
        { value: 'light', label: '轻' },
      ],
    })
  })

  it('keeps a ladder the model itself carries without asking the host', async () => {
    stubTauriRuntime(true)
    // A record that carries its own declared grades — written by an import or a
    // host version that pins them — is authoritative and needs no round trip.
    const storage = new MemoryStandaloneStateStorage<any>({
      providers: [],
      models: [{
        id: 'declaring:pinned',
        provider_id: 'declaring',
        model_id: 'pinned',
        display_name: 'Pinned',
        thinking_supported: true,
        reasoning_off_supported: false,
        reasoning_levels: [{ value: 'light', label: '轻' }],
      }],
      defaultModelId: 'declaring:pinned',
      settings: {},
    })
    const config = new StandaloneConfigStore(new MemorySecureStorage(), storage)
    await config.handleRpc('config.provider.create', {
      name: 'Declaring',
      api_key: 'secret',
      base_url: 'https://declaring.invalid/v1',
      extra: { adapter_profile_id: 'deepseek-chat' },
    })

    const listed = await config.handleRpc('config.models.list', {})
    const model = (listed?.models as Array<Record<string, unknown>>)[0]
    expect(model?.reasoning_levels).toEqual([{ value: 'light', label: '轻' }])
    expect(model?.reasoning_off_supported).toBe(false)
    expect(invokeMock).not.toHaveBeenCalled()
    expect(coreThinkingModeOptions({ model: model as CoreExecutionModelSource })
      .map(option => option.value)).toEqual(['light'])

    const active = await config.activeModel()
    expect(active.model.reasoning_levels).toEqual([{ value: 'light', label: '轻' }])
    expect(invokeMock).not.toHaveBeenCalled()
  })

  it('falls back to the product ladder when the host cannot answer', async () => {
    // 1. No embedded runtime (a build or platform without the host command): the
    //    catalog still loads and keeps the product ladder.
    stubTauriRuntime(false)
    const storage = new MemoryStandaloneStateStorage<any>()
    const config = await presetConfig(storage)
    const listed = await config.handleRpc('config.models.list', {})
    const models = (listed?.models || []) as Array<Record<string, unknown>>
    expect(models).toHaveLength(2)
    expect(models.every(model => Array.isArray(model.reasoning_levels))).toBe(true)
    expect(models.every(model => (model.reasoning_levels as unknown[]).length === 0)).toBe(true)
    expect(models.every(model => model.reasoning_off_supported === true)).toBe(true)
    expect(invokeMock).not.toHaveBeenCalled()
    expect(coreThinkingModeOptions({ model: models[0] as CoreExecutionModelSource })
      .map(option => option.value)).toEqual(['max', 'xhigh', 'high', 'medium', 'light', 'off'])

    // 2. A runtime whose command fails (this build does not register it, or the
    //    host errors): the model catalog must not surface the failure.
    stubTauriRuntime(true)
    invokeMock.mockRejectedValueOnce(new Error('command sunday_model_reasoning_declaration not found'))
    invokeMock.mockRejectedValueOnce(new Error('command sunday_model_reasoning_declaration not found'))
    const failed = await config.handleRpc('config.models.list', {})
    const failedModels = (failed?.models || []) as Array<Record<string, unknown>>
    expect(failedModels.map(model => model.reasoning_levels)).toEqual([[], []])
    expect(failedModels.map(model => model.reasoning_off_supported)).toEqual([true, true])

    // 3. An answer that is not a ladder at all is treated as no answer.
    invokeMock.mockResolvedValueOnce({ levels: 'max', off_supported: 'yes' })
    invokeMock.mockResolvedValueOnce({ levels: [] })
    const malformed = await config.handleRpc('config.models.list', {})
    const malformedModels = (malformed?.models || []) as Array<Record<string, unknown>>
    expect(malformedModels.map(model => model.reasoning_levels)).toEqual([[], []])
    expect(malformedModels.map(model => model.reasoning_off_supported)).toEqual([true, true])

    // The turn path degrades the same way instead of failing a request.
    invokeMock.mockRejectedValueOnce(new Error('command sunday_model_reasoning_declaration not found'))
    const active = await config.activeModel()
    expect(active.model.reasoning_levels).toEqual([])
    expect(active.model.reasoning_off_supported).toBe(true)
  })
})
