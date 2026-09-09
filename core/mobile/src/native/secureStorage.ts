export interface SecureStorage {
  get<T = string>(key: string): Promise<T | null>
  set<T = string>(key: string, value: T): Promise<void>
  remove(key: string): Promise<void>
}

/**
 * Development fallback. Native Capacitor builds use the Keychain/Keystore
 * adapter below; browser tests deliberately keep credentials in memory only.
 */
export class MemorySecureStorage implements SecureStorage {
  private readonly values = new Map<string, unknown>()
  async get<T>(key: string): Promise<T | null> {
    return (this.values.get(key) as T | undefined) ?? null
  }
  async set<T>(key: string, value: T): Promise<void> { this.values.set(key, value) }
  async remove(key: string): Promise<void> { this.values.delete(key) }
}

/**
 * Browser Demo persistence. The native app continues to use the platform
 * Keychain/Keystore adapter; this adapter only keeps the browser Demo signed
 * in across reloads so its reconnect lifecycle can be tested realistically.
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

let storage: SecureStorage = Capacitor.isNativePlatform()
  ? new CapacitorSecureStorage()
  : new BrowserSecureStorage()

export function configureSecureStorage(next: SecureStorage): void { storage = next }
export function secureStorage(): SecureStorage { return storage }
import { Capacitor } from '@capacitor/core'
import {
  KeychainAccess,
  SecureStorage as NativeSecureStorage,
  type DataType,
} from '@aparajita/capacitor-secure-storage'
