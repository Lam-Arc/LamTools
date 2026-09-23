import { describe, expect, it } from 'vitest'
import { MemorySecureStorage } from '../src/native/secureStorage'
import { StandaloneConfigStore } from '../src/standalone/StandaloneConfigStore'

const provider = { name: 'Credential Test', api_type: 'openai', base_url: 'https://example.invalid/v1', models: [{ model_id: 'test' }] }

describe('mobile provider credentials', () => {
  it.each(['test-token', ' Bearer test-token ', 'Authorization: Bearer test-token'])('passes a bare credential to the native runtime for %s', async api_key => {
    const store = new StandaloneConfigStore(new MemorySecureStorage())
    await store.handleRpc('config.provider.create', { ...provider, api_key })
    expect((await store.activeModel()).apiKey).toBe('test-token')
    expect((await store.runtimeModels())[0].apiKey).toBe('test-token')
  })

  it('normalizes credentials already saved by older builds without replacing them', async () => {
    const secrets = new MemorySecureStorage()
    const store = new StandaloneConfigStore(secrets)
    await store.handleRpc('config.provider.create', { ...provider, api_key: 'test-token' })
    const originalGet = secrets.get.bind(secrets)
    secrets.get = async <T>(key: string) => {
      const value = await originalGet<T>(key)
      return value === 'test-token' ? 'Bearer test-token' as T : value
    }
    expect((await store.activeModel()).apiKey).toBe('test-token')
    expect((await store.runtimeModels())[0].apiKey).toBe('test-token')
  })

  it('does not replace a saved key with a masked editor value', async () => {
    const store = new StandaloneConfigStore(new MemorySecureStorage())
    const created = await store.handleRpc('config.provider.create', { ...provider, api_key: 'test-token' })
    const id = (created?.provider as { id: string }).id
    await store.handleRpc('config.provider.update', { provider_id: id, api_key: '********' })
    expect((await store.activeModel()).apiKey).toBe('test-token')
    await expect(store.handleRpc('config.provider.update', { provider_id: id, api_key: 'Bearer ********' })).rejects.toThrow('API Key')
    expect((await store.activeModel()).apiKey).toBe('test-token')
  })

  it.each(['********', 'Bearer ********', 'Bearer ', 'bad\ncredential'])('rejects unusable credentials before saving or sending: %s', async api_key => {
    const store = new StandaloneConfigStore(new MemorySecureStorage())
    await expect(store.handleRpc('config.provider.create', { ...provider, api_key })).rejects.toThrow('API Key')
    expect((await store.handleRpc('config.providers.list', {}))?.providers).toEqual([])
  })
})
