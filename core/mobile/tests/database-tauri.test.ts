import { afterEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

import { createLocalDatabase } from '../src/storage/Database'

afterEach(() => {
  invokeMock.mockReset()
  vi.unstubAllGlobals()
})

describe('Tauri native local database', () => {
  it('persists active and scoped state only through Rust commands', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    const scopes = new Map<string, unknown>()
    let active: unknown = null
    invokeMock.mockImplementation(async (command: string, args: Record<string, unknown>) => {
      if (command === 'local_state_read') {
        return args.scope == null ? active : scopes.get(String(args.scope)) ?? null
      }
      if (command === 'local_state_write') {
        scopes.set(String(args.scope), args.state)
        active = args.state
        return null
      }
      throw new Error(`unexpected command ${command}`)
    })

    const database = createLocalDatabase<Record<string, unknown>>('lamtools-mobile-local')
    await database.open()
    await database.writeScope?.('workspace:a', { value: 'A' })
    await database.writeScope?.('workspace:b', { value: 'B' })

    await expect(database.readScope?.('workspace:a')).resolves.toEqual({ value: 'A' })
    await expect(database.readScope?.('workspace:b')).resolves.toEqual({ value: 'B' })
    await expect(database.read()).resolves.toEqual({ value: 'B' })
    expect(invokeMock).toHaveBeenCalledWith('local_state_write', {
      database: 'lamtools-mobile-local',
      scope: 'workspace:a',
      state: { value: 'A' },
    })
  })
})
