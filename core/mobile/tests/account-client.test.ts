import { describe, expect, it } from 'vitest'
import { BrowserSecureStorage, MemorySecureStorage } from '../src/native/secureStorage'
import { loadStoredAccount, normalizeProfile } from '../src/account'

describe('account server profile', () => {
  it('persists browser Demo values across adapter instances', async () => {
    const values = new Map<string, string>()
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
        removeItem: (key: string) => values.delete(key),
      },
    })
    await new BrowserSecureStorage().set('session', { username: 'demo' })
    await expect(new BrowserSecureStorage().get('session')).resolves.toEqual({ username: 'demo' })
    await new BrowserSecureStorage().remove('session')
    await expect(new BrowserSecureStorage().get('session')).resolves.toBeNull()
  })

  it('normalizes custom server paths without losing the server origin', () => {
    expect(normalizeProfile('wss://relay.example.test/v1/relay?unused=1').baseUrl)
      .toBe('https://relay.example.test')
    expect(normalizeProfile('https://relay.example.test/').baseUrl)
      .toBe('https://relay.example.test')
  })

  it('restores a persisted account session with its custom server address', async () => {
    const storage = new MemorySecureStorage()
    await storage.set('lamtools.mobile.account-session-v1', {
      serverId: 'server-1',
      baseUrl: 'https://private.example.test',
      accessToken: 'access-token',
      refreshToken: 'refresh-token',
      accessExpiresAtMs: Date.now() + 60_000,
      refreshExpiresAtMs: Date.now() + 86_400_000,
      username: 'alice',
      nodeId: 'mobile-1',
      publicKey: 'mobile-key',
      selectedWorkspaceId: 'workspace-1',
    })

    const account = await loadStoredAccount(storage)

    expect(account?.authenticated).toBe(true)
    expect(account?.profile.baseUrl).toBe('https://private.example.test')
    expect(account?.session?.selectedWorkspaceId).toBe('workspace-1')
    expect(account?.getRelayEndpoint()).toBe('wss://private.example.test/v1/relay/connect')
  })
})
