import { invoke } from '@tauri-apps/api/core'

export interface StandaloneStateStorage<T> {
  read(): Promise<T | null>
  write(value: T): Promise<void>
}

export function createStandaloneStateStorage<T>(options: {
  database: string
  scope: string
  legacyKey: string
}): StandaloneStateStorage<T> {
  if (isTauriRuntime()) return new TauriStandaloneStateStorage<T>(options)
  return new LocalStorageStandaloneStateStorage<T>(options.legacyKey)
}

export class MemoryStandaloneStateStorage<T> implements StandaloneStateStorage<T> {
  constructor(private value: T | null = null) {}

  async read(): Promise<T | null> {
    return clone(this.value)
  }

  async write(value: T): Promise<void> {
    this.value = clone(value)
  }
}

class TauriStandaloneStateStorage<T> implements StandaloneStateStorage<T> {
  constructor(private readonly options: { database: string; scope: string; legacyKey: string }) {}

  async read(): Promise<T | null> {
    const native = await invoke<T | null>('local_state_read', {
      database: this.options.database,
      scope: this.options.scope,
    })
    if (native != null) return native

    const legacy = readLegacyValue<T>(this.options.legacyKey)
    if (legacy != null) await this.write(legacy)
    return legacy
  }

  async write(value: T): Promise<void> {
    await invoke('local_state_write', {
      database: this.options.database,
      scope: this.options.scope,
      state: value,
    })
  }
}

class LocalStorageStandaloneStateStorage<T> implements StandaloneStateStorage<T> {
  constructor(private readonly key: string) {}

  async read(): Promise<T | null> {
    return readLegacyValue<T>(this.key)
  }

  async write(value: T): Promise<void> {
    globalThis.localStorage?.setItem(this.key, JSON.stringify(value))
  }
}

function readLegacyValue<T>(key: string): T | null {
  const raw = globalThis.localStorage?.getItem(key)
  if (!raw) return null
  try {
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

function isTauriRuntime(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

function clone<T>(value: T | null): T | null {
  return value == null ? null : JSON.parse(JSON.stringify(value)) as T
}
