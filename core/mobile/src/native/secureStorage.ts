export interface SecureStorage {
  get<T = string>(key: string): Promise<T | null>
  set<T = string>(key: string, value: T): Promise<void>
  remove(key: string): Promise<void>
}

/** In-memory fallback used by tests and non-native builds. */
export class MemorySecureStorage implements SecureStorage {
  private readonly values = new Map<string, unknown>()
  async get<T>(key: string): Promise<T | null> {
    return (this.values.get(key) as T | undefined) ?? null
  }
  async set<T>(key: string, value: T): Promise<void> { this.values.set(key, value) }
  async remove(key: string): Promise<void> { this.values.delete(key) }
}

/**
 * Explicit browser persistence adapter for callers that opt into it. The
 * default non-native adapter below is memory-only so credentials are never
 * silently written to ordinary localStorage.
 */
export class BrowserSecureStorage implements SecureStorage {
  private readonly prefix = 'lamtools.mobile.secure.'

  async get<T>(key: string): Promise<T | null> {
    try {
      const value = globalThis.localStorage?.getItem(`${this.prefix}${key}`)
      return value ? JSON.parse(value) as T : null
    } catch {
      return null
    }
  }

  async set<T>(key: string, value: T): Promise<void> {
    globalThis.localStorage?.setItem(`${this.prefix}${key}`, JSON.stringify(value))
  }

  async remove(key: string): Promise<void> {
    globalThis.localStorage?.removeItem(`${this.prefix}${key}`)
  }
}

export class CapacitorSecureStorage implements SecureStorage {
  private readonly ready: Promise<void>

  constructor() {
    this.ready = Promise.all([
      NativeSecureStorage.setKeyPrefix('lamtools.mobile.'),
      NativeSecureStorage.setDefaultKeychainAccess(KeychainAccess.afterFirstUnlockThisDeviceOnly),
    ]).then(() => undefined)
  }

  async get<T>(key: string): Promise<T | null> {
    await this.ready
    return await NativeSecureStorage.get(key, false, false) as T | null
  }

  async set<T>(key: string, value: T): Promise<void> {
    await this.ready
    await NativeSecureStorage.set(key, value as DataType, false, false, KeychainAccess.afterFirstUnlockThisDeviceOnly)
  }

  async remove(key: string): Promise<void> {
    await this.ready
    await NativeSecureStorage.remove(key, false)
  }
}

/** Tauri adapter backed by the same Android Keystore aliases and encrypted
 * SharedPreferences file as the previous Capacitor host. */
export class TauriSecureStorage implements SecureStorage {
  private readonly prefix = 'lamtools.mobile.'

  async get<T>(key: string): Promise<T | null> {
    let raw: string | null
    try {
      raw = await invoke<string | null>('secure_storage_get', { key: `${this.prefix}${key}` })
    } catch (error) {
      // AndroidKeyStore keys do not survive cloud/device restore. The old
      // ciphertext cannot be recovered; clear only that invalid entry so the
      // device identity can be recreated and pairing can continue.
      if (!String(error).includes('SECURE_STORAGE_KEY_INVALIDATED')) throw error
      await this.remove(key)
      globalThis.dispatchEvent?.(new Event('lamtools:secure-storage-recovered'))
      return null
    }
    if (raw == null) return null
    return JSON.parse(raw) as T
  }

  async set<T>(key: string, value: T): Promise<void> {
    await invoke('secure_storage_set', { key: `${this.prefix}${key}`, value: JSON.stringify(value) })
  }

  async remove(key: string): Promise<void> {
    await invoke('secure_storage_remove', { key: `${this.prefix}${key}` })
  }
}

let storage: SecureStorage = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
  ? new TauriSecureStorage()
  : Capacitor.isNativePlatform()
    ? new CapacitorSecureStorage()
    : new MemorySecureStorage()

export function configureSecureStorage(next: SecureStorage): void { storage = next }
export function secureStorage(): SecureStorage { return storage }
import { Capacitor } from '@capacitor/core'
import {
  KeychainAccess,
  SecureStorage as NativeSecureStorage,
  type DataType,
} from '@aparajita/capacitor-secure-storage'
import { invoke } from '@tauri-apps/api/core'
