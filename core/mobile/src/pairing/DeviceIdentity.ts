import { secureStorage, type SecureStorage } from '../native/secureStorage'
import { generateKeyPair } from 'noise-handshake/dh'
import b4a from 'b4a'

export interface DeviceIdentity {
  deviceId: string
  publicKey: string
  privateKey: string
  createdAt: string
}

const STORAGE_KEY = 'lamtools.mobile.device-identity'
const ACCOUNT_STORAGE_PREFIX = 'lamtools.mobile.account-device-identity:'

/**
 * Loads the mobile identity from the injected secure-store adapter or creates
 * one for the current installation. The default development adapter is
 * in-memory; native builds must provide a Keychain/Keystore implementation.
 */
export async function loadOrCreateDeviceIdentity(storage: SecureStorage = secureStorage()): Promise<DeviceIdentity> {
  return await loadOrCreateIdentityAt(STORAGE_KEY, storage)
}

export async function loadOrCreateAccountDeviceIdentity(
  serverId: string,
  username: string,
  storage: SecureStorage = secureStorage(),
): Promise<DeviceIdentity> {
  const scope = `${encodeURIComponent(serverId.trim())}:${encodeURIComponent(username.trim().toLowerCase())}`
  return await loadOrCreateIdentityAt(`${ACCOUNT_STORAGE_PREFIX}${scope}`, storage)
}

async function loadOrCreateIdentityAt(key: string, storage: SecureStorage): Promise<DeviceIdentity> {
  const existing = await storage.get<DeviceIdentity>(key)
  if (existing && isIdentity(existing)) return existing

  const identity: DeviceIdentity = {
    deviceId: crypto.randomUUID(),
    ...(await generateIdentityKeyPair()),
    createdAt: new Date().toISOString(),
  }
  await storage.set(key, identity)
  return identity
}

async function generateIdentityKeyPair(): Promise<{ publicKey: string; privateKey: string }> {
  const pair = generateKeyPair()
  return {
    publicKey: toBase64Url(pair.publicKey),
    privateKey: toBase64Url(pair.secretKey),
  }
}

function toBase64Url(value: Uint8Array): string {
  return b4a.toString(value, 'base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

function isIdentity(value: unknown): value is DeviceIdentity {
  if (!value || typeof value !== 'object') return false
  const identity = value as DeviceIdentity
  return typeof identity.deviceId === 'string'
    && typeof identity.publicKey === 'string'
    && typeof identity.privateKey === 'string'
    && typeof identity.createdAt === 'string'
}
