import { beforeEach, describe, expect, it, vi } from 'vitest'

const native = vi.hoisted(() => {
  const events: string[] = []
  const db = {
    isDBOpen: vi.fn(async () => ({ result: false })),
    isTransactionActive: vi.fn(async () => ({ result: false })),
    open: vi.fn(async () => undefined),
    rollbackTransaction: vi.fn(async () => ({ changes: { changes: 0 } })),
    execute: vi.fn(async () => ({ changes: { changes: 0 } })),
    query: vi.fn(async () => ({ values: [] })),
    run: vi.fn(async () => ({ changes: { changes: 0 } })),
    close: vi.fn(async () => undefined),
  }
  const connection = {
    checkConnectionsConsistency: vi.fn(async () => {
      events.push('check')
      return { result: false }
    }),
    isConnection: vi.fn(async () => {
      events.push('isConnection')
      return { result: false }
    }),
    retrieveConnection: vi.fn(async () => {
      events.push('retrieve')
      return db
    }),
    createConnection: vi.fn(async () => {
      events.push('create')
      if (!events.includes('check')) throw new Error('Connection lamtools-mobile already exists')
      return db
    }),
    closeConnection: vi.fn(async () => undefined),
  }
  return { events, db, connection }
})

vi.mock('@capacitor/core', () => ({
  Capacitor: { isNativePlatform: () => true },
}))

vi.mock('@capacitor-community/sqlite', () => ({
  CapacitorSQLite: {},
  SQLiteConnection: class {
    checkConnectionsConsistency = native.connection.checkConnectionsConsistency
    isConnection = native.connection.isConnection
    retrieveConnection = native.connection.retrieveConnection
    createConnection = native.connection.createConnection
    closeConnection = native.connection.closeConnection
  },
}))

import { createLocalDatabase } from '../src/storage/Database'

describe('native local database connection lifecycle', () => {
  beforeEach(() => {
    native.events.length = 0
    vi.clearAllMocks()
    native.db.isDBOpen.mockResolvedValue({ result: false })
    native.db.isTransactionActive.mockResolvedValue({ result: false })
    native.connection.isConnection.mockImplementation(async () => {
      native.events.push('isConnection')
      return { result: false }
    })
  })

  it('reconciles stale native connections before creating a database', async () => {
    const database = createLocalDatabase<Record<string, unknown>>('lamtools-mobile')

    await database.open()

    expect(native.events.slice(0, 3)).toEqual(['check', 'isConnection', 'create'])
    expect(native.db.open).toHaveBeenCalledOnce()
    expect(native.db.execute).toHaveBeenCalledOnce()
  })

  it('rolls back a transaction abandoned by a previous renderer', async () => {
    native.db.isTransactionActive.mockResolvedValue({ result: true })
    const database = createLocalDatabase<Record<string, unknown>>('lamtools-mobile')

    await database.open()

    expect(native.db.rollbackTransaction).toHaveBeenCalledOnce()
    expect(native.db.execute).toHaveBeenCalledOnce()
  })

  it('reuses an existing JavaScript connection without reopening it', async () => {
    native.connection.isConnection.mockImplementation(async () => {
      native.events.push('isConnection')
      return { result: true }
    })
    native.db.isDBOpen.mockResolvedValue({ result: true })
    const database = createLocalDatabase<Record<string, unknown>>('lamtools-mobile')

    await database.open()

    expect(native.events.slice(0, 3)).toEqual(['check', 'isConnection', 'retrieve'])
    expect(native.db.open).not.toHaveBeenCalled()
    expect(native.db.execute).toHaveBeenCalledOnce()
  })

  it('surfaces native SQLite startup failures instead of using volatile memory', async () => {
    native.connection.createConnection.mockRejectedValueOnce(new Error('SQLite unavailable'))
    const database = createLocalDatabase<Record<string, unknown>>('lamtools-mobile')

    await expect(database.open()).rejects.toThrow('SQLite unavailable')
  })
})
