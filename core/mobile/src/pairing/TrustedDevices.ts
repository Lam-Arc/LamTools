import { secureStorage, type SecureStorage } from '../native/secureStorage'

/** Public connection metadata. No secret is persisted in this record. */
export interface TrustedDeviceMetadata {
  deviceId: string
  name: string
  platform?: string
  publicKey?: string
  gatewayUrl?: string
  relayUrl?: string
  lastConnectedAt?: string
}

/** Optional per-device secret. Account Workspace views use the server Ticket
 * path and deliberately do not persist a pairing token here. */
export interface TrustedDeviceCredential {
  accessToken?: string
}

/** Runtime view assembled from metadata plus the separately stored secret. */
export interface TrustedDevice extends TrustedDeviceMetadata, TrustedDeviceCredential {}

/** Non-secret storage for device metadata (local config/localStorage). */
export interface TrustedDeviceMetadataStorage {
  get<T = string>(key: string): Promise<T | null>
  set<T = string>(key: string, value: T): Promise<void>
  remove(key: string): Promise<void>
  keys(prefix: string): Promise<string[]>
}

export interface TrustedDeviceStores {
  metadata: TrustedDeviceMetadataStorage
  secrets: SecureStorage
}

const METADATA_PREFIX = 'lamtools.mobile.trusted-device.metadata.'
const CREDENTIAL_PREFIX = 'lamtools.mobile.trusted-device.credential.'

export class MemoryTrustedDeviceMetadataStorage implements TrustedDeviceMetadataStorage {
  private readonly values = new Map<string, unknown>()

  async get<T>(key: string): Promise<T | null> {
    return (this.values.get(key) as T | undefined) ?? null
  }

  async set<T>(key: string, value: T): Promise<void> {
    this.values.set(key, value)
  }

  async remove(key: string): Promise<void> {
    this.values.delete(key)
  }

  async keys(prefix: string): Promise<string[]> {
    return [...this.values.keys()].filter((key) => key.startsWith(prefix))
  }
}

class LocalStorageTrustedDeviceMetadataStorage implements TrustedDeviceMetadataStorage {
  constructor(private readonly storage: Storage) {}

  async get<T>(key: string): Promise<T | null> {
    const raw = this.storage.getItem(key)
    if (raw === null) return null
    try {
      return JSON.parse(raw) as T
    } catch {
      return null
    }
  }

  async set<T>(key: string, value: T): Promise<void> {
    this.storage.setItem(key, JSON.stringify(value))
  }

  async remove(key: string): Promise<void> {
    this.storage.removeItem(key)
  }

  async keys(prefix: string): Promise<string[]> {
    const result: string[] = []
    for (let index = 0; index < this.storage.length; index += 1) {
      const key = this.storage.key(index)
      if (key?.startsWith(prefix)) result.push(key)
    }
    return result
  }
}

function createDefaultMetadataStorage(): TrustedDeviceMetadataStorage {
  try {
    if (typeof globalThis.localStorage !== 'undefined') {
      return new LocalStorageTrustedDeviceMetadataStorage(globalThis.localStorage)
    }
  } catch {
    // Sandboxed webviews can expose localStorage but reject access. The
    // in-memory fallback keeps development/tests functional without putting
    // metadata into the secure credential store.
  }
  return new MemoryTrustedDeviceMetadataStorage()
}

let metadataStorage: TrustedDeviceMetadataStorage = createDefaultMetadataStorage()

export function configureTrustedDeviceMetadataStorage(next: TrustedDeviceMetadataStorage): void {
  metadataStorage = next
}

export function trustedDeviceStores(): TrustedDeviceStores {
  return { metadata: metadataStorage, secrets: secureStorage() }
}

export async function listTrustedDevices(
  stores: TrustedDeviceStores = trustedDeviceStores(),
): Promise<TrustedDevice[]> {
  const keys = await stores.metadata.keys(METADATA_PREFIX)
  const devices = await Promise.all(keys.map(async (key) => {
    const metadata = await stores.metadata.get<TrustedDeviceMetadata>(key)
    if (!isTrustedDeviceMetadata(metadata)) return null
    const credential = await stores.secrets.get<TrustedDeviceCredential>(credentialKey(metadata.deviceId))
    if (!credential || !isTrustedDeviceCredential(credential)) return { ...metadata }
    return { ...metadata, ...credential }
  }))
  return devices.filter((device): device is TrustedDevice => device !== null)
}

export async function saveTrustedDevice(
  device: TrustedDevice,
  stores: TrustedDeviceStores = trustedDeviceStores(),
): Promise<void> {
  if (!isTrustedDevice(device)) throw new Error('trusted device metadata or credential is invalid')
  const metadata: TrustedDeviceMetadata = {
    deviceId: device.deviceId,
    name: device.name,
    ...(device.platform ? { platform: device.platform } : {}),
    ...(device.publicKey ? { publicKey: device.publicKey } : {}),
    ...(device.gatewayUrl ? { gatewayUrl: device.gatewayUrl } : {}),
    ...(device.relayUrl ? { relayUrl: device.relayUrl } : {}),
    ...(device.lastConnectedAt ? { lastConnectedAt: device.lastConnectedAt } : {}),
  }
  // Keep the token in its own secure-store entry. Metadata is intentionally
  // written to ordinary config storage, so adding devices cannot overflow a
  // platform credential-store value or expose tokens alongside UI metadata.
  await stores.metadata.set(metadataKey(device.deviceId), metadata)
  if (device.accessToken) {
    await stores.secrets.set(credentialKey(device.deviceId), { accessToken: device.accessToken })
  } else {
    await stores.secrets.remove(credentialKey(device.deviceId))
  }
}

export async function forgetTrustedDevice(
  deviceId: string,
  stores: TrustedDeviceStores = trustedDeviceStores(),
): Promise<void> {
  const normalized = deviceId.trim()
  if (!normalized) return
  await stores.secrets.remove(credentialKey(normalized))
  await stores.metadata.remove(metadataKey(normalized))
}

function metadataKey(deviceId: string): string {
  return `${METADATA_PREFIX}${encodeURIComponent(deviceId)}`
}

function credentialKey(deviceId: string): string {
  return `${CREDENTIAL_PREFIX}${encodeURIComponent(deviceId)}`
}

function isTrustedDeviceMetadata(value: unknown): value is TrustedDeviceMetadata {
  return Boolean(value)
    && typeof value === 'object'
    && typeof (value as TrustedDeviceMetadata).deviceId === 'string'
    && typeof (value as TrustedDeviceMetadata).name === 'string'
}

function isTrustedDeviceCredential(value: unknown): value is TrustedDeviceCredential {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const accessToken = (value as TrustedDeviceCredential).accessToken
  return typeof accessToken === 'undefined'
    || (typeof accessToken === 'string' && accessToken.length > 0)
}

function isTrustedDevice(value: unknown): value is TrustedDevice {
  return isTrustedDeviceMetadata(value)
    && (!('accessToken' in (value as unknown as Record<string, unknown>)) || isTrustedDeviceCredential(value))
}
