import { describe, expect, it, vi } from 'vitest'
import { BrowserSecureStorage, MemorySecureStorage } from '../src/native/secureStorage'
import { AccountClient, loadStoredAccount, normalizeProfile } from '../src/account'

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

  it('shares one refresh request across concurrent callers', async () => {
    const session = {
      serverId: 'server-1',
      baseUrl: 'https://private.example.test',
      accessToken: 'old-access',
      refreshToken: 'refresh-token',
      accessExpiresAtMs: Date.now() - 1,
      refreshExpiresAtMs: Date.now() + 86_400_000,
      username: 'alice',
      nodeId: 'mobile-1',
      publicKey: 'mobile-key',
    }
    const client = new AccountClient({
      profile: session.baseUrl,
      session,
      storage: new MemorySecureStorage(),
    })
    let resolveFetch!: (response: Response) => void
    let refreshCalls = 0
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      if (String(input).endsWith('/v1/auth/refresh')) {
        refreshCalls += 1
        return new Promise<Response>((resolve) => { resolveFetch = resolve })
      }
      return Promise.resolve(new Response('{}', { status: 200 }))
    }))

    const first = client.refresh()
    const second = client.refresh()
    expect(refreshCalls).toBe(1)
    resolveFetch(new Response(JSON.stringify({
      serverId: 'server-1',
      accessToken: 'new-access',
      refreshToken: 'new-refresh',
      accessExpiresAtMs: Date.now() + 60_000,
      refreshExpiresAtMs: Date.now() + 86_400_000,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))

    await expect(Promise.all([first, second])).resolves.toHaveLength(2)
    expect(client.session?.accessToken).toBe('new-access')
    vi.unstubAllGlobals()
  })

  it('does not resurrect a session when logout races refresh', async () => {
    const storage = new MemorySecureStorage()
    const session = {
      serverId: 'server-1',
      baseUrl: 'https://private.example.test',
      accessToken: 'old-access',
      refreshToken: 'refresh-token',
      accessExpiresAtMs: Date.now() - 1,
      refreshExpiresAtMs: Date.now() + 86_400_000,
      username: 'alice',
      nodeId: 'mobile-1',
      publicKey: 'mobile-key',
    }
    await storage.set('lamtools.mobile.account-session-v1', session)
    const client = new AccountClient({ profile: session.baseUrl, session, storage })
    let resolveRefresh!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      if (String(input).endsWith('/v1/auth/refresh')) {
        return new Promise<Response>((resolve) => { resolveRefresh = resolve })
      }
      return Promise.resolve(new Response('{}', { status: 200 }))
    }))

    const refresh = client.refresh()
    await client.logout()
    resolveRefresh(new Response(JSON.stringify({
      serverId: 'server-1',
      accessToken: 'new-access',
      refreshToken: 'new-refresh',
      accessExpiresAtMs: Date.now() + 60_000,
      refreshExpiresAtMs: Date.now() + 86_400_000,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))

    await expect(refresh).rejects.toThrow('账号会话已结束')
    expect(client.session).toBeNull()
    await expect(storage.get('lamtools.mobile.account-session-v1')).resolves.toBeNull()
    vi.unstubAllGlobals()
  })
})
