import { afterEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

import { createStandaloneStateStorage } from '../src/standalone/StandaloneStateStorage'

afterEach(() => {
  invokeMock.mockReset()
  vi.unstubAllGlobals()
})

describe('standalone native settings persistence', () => {
  it('imports legacy WebView settings once and writes them through Rust SQLite', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => key === 'legacy' ? '{"enabled":true}' : null,
      setItem: vi.fn(),
    })
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'local_state_read') return null
      if (command === 'local_state_write') return null
      throw new Error(`unexpected command ${command}`)
    })

    const storage = createStandaloneStateStorage<{ enabled: boolean }>({
      database: 'lamtools-mobile-config',
      scope: 'extensions',
      legacyKey: 'legacy',
    })
    await expect(storage.read()).resolves.toEqual({ enabled: true })
    expect(invokeMock).toHaveBeenLastCalledWith('local_state_write', {
      database: 'lamtools-mobile-config',
      scope: 'extensions',
      state: { enabled: true },
    })
  })

  it('surfaces native persistence failures instead of falling back to WebView storage', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    vi.stubGlobal('localStorage', {
      getItem: () => '{"unsafeFallback":true}',
      setItem: vi.fn(),
    })
    invokeMock.mockRejectedValue(new Error('sqlite unavailable'))

    const storage = createStandaloneStateStorage<Record<string, unknown>>({
      database: 'lamtools-mobile-config',
      scope: 'config',
      legacyKey: 'legacy',
    })
    await expect(storage.read()).rejects.toThrow('sqlite unavailable')
  })
})
