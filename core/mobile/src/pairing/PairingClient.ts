import { saveTrustedDevice, type TrustedDevice } from './TrustedDevices'
import { loadOrCreateDeviceIdentity } from './DeviceIdentity'
import { pairSecure } from '../connection/NoiseSecureWire'
import { createLanDiscovery, type LanDevice, type LanDiscovery } from '../connection/LanDiscovery'
import type { AccountConnectionProvider } from '../account/AccountClient'

export interface PairingResolution {
  pairingId: string
  desktopDeviceId: string
  desktopPublicKey: string
  gatewayUrl: string
  relayUrl?: string
  relayTicket?: string
  expiresAtMs: number
  protocol: string
  version: number
}

export interface PairingClientOptions {
  /** Optional direct gateway URL entered by the user (LAN/VPN/manual route). */
  gatewayUrl?: string
  /** Native mDNS discovery adapter. Browser builds can leave this unset. */
  lanDiscovery?: LanDiscovery
  /** Authenticated account route for official Relay pairing. */
  account?: AccountConnectionProvider
}

const PAIRING_CODE_PATTERN = /^\d{6}$/

export function isPairingCode(value: string): boolean {
  return PAIRING_CODE_PATTERN.test(value.trim())
}

export function normalizePairingCode(value: string): string {
  return value.replace(/\D/g, '').slice(0, 6)
}

/** Derive the direct HTTP pairing-resolution endpoint from a gateway URL. */
export function pairingResolveEndpoint(gatewayEndpoint: string): string {
  const url = new URL(normalizeGatewayEndpoint(gatewayEndpoint))
  url.protocol = url.protocol === 'ws:' ? 'http:' : url.protocol === 'wss:' ? 'https:' : url.protocol
  url.pathname = '/_lamtools/pairing/resolve'
  url.search = ''
  url.hash = ''
  return url.toString()
}

export class PairingClient {
  private readonly gatewayUrl: string
  private readonly lanDiscovery: LanDiscovery
  private readonly account?: AccountConnectionProvider

  constructor(options: PairingClientOptions = {}) {
    this.gatewayUrl = options.gatewayUrl?.trim() || ''
    this.lanDiscovery = options.lanDiscovery || createLanDiscovery()
    this.account = options.account
  }

  async redeem(value: string): Promise<TrustedDevice> {
    const code = value.trim()
    if (!isPairingCode(code)) throw new Error('配对码必须是六位数字')

    const pairing = await this.resolve(code)
    const identity = await loadOrCreateDeviceIdentity()
    const relayEndpoint = pairing.relayTicket
      ? pairing.relayUrl || this.account?.getRelayEndpoint()
      : ''
    if (pairing.relayTicket && !relayEndpoint) throw new Error('账号未配置 Relay 地址')
    const result = await pairSecure({
      url: toWebSocketUrl(relayEndpoint || pairing.gatewayUrl),
      pairingId: pairing.pairingId,
      code,
      desktopPublicKey: pairing.desktopPublicKey,
      identity,
      ...(pairing.relayTicket
        ? {
            relay: {
              ticket: pairing.relayTicket,
              mobileDeviceId: identity.deviceId,
              targetDeviceId: pairing.desktopDeviceId,
            },
          }
        : {}),
    })
    const deviceId = typeof result.desktopDeviceId === 'string' ? result.desktopDeviceId : ''
    if (!deviceId) throw new Error('配对服务返回了无效设备')
    if (deviceId !== pairing.desktopDeviceId) {
      throw new Error('配对设备身份与网关返回的信息不一致')
    }
    const returnedPublicKey = typeof result.desktopPublicKey === 'string' ? result.desktopPublicKey : ''
    if (!returnedPublicKey || returnedPublicKey !== pairing.desktopPublicKey) {
      throw new Error('配对设备公钥与网关返回的信息不一致')
    }
    const accessToken = typeof result.accessToken === 'string' ? result.accessToken : ''
    if (!accessToken) throw new Error('配对服务未返回设备凭据')

    const gatewayUrl = typeof result.gatewayUrl === 'string' && result.gatewayUrl
      ? result.gatewayUrl
      : pairing.gatewayUrl
    const relayUrl = typeof result.relayUrl === 'string' && result.relayUrl
      ? result.relayUrl
      : pairing.relayUrl
    const device: TrustedDevice = {
      deviceId,
      name: typeof result.name === 'string' ? result.name : 'LamTools 电脑',
      publicKey: returnedPublicKey,
      gatewayUrl: toWebSocketUrl(gatewayUrl),
      ...(relayUrl ? { relayUrl } : {}),
      accessToken,
      lastConnectedAt: new Date().toISOString(),
    }
    await saveTrustedDevice(device)
    return device
  }

  private async resolve(code: string): Promise<PairingResolution> {
    if (this.account?.resolvePairing) {
      const pairing = await this.account.resolvePairing(code)
      if (pairing.expiresAtMs <= Date.now()) throw new Error('配对码已过期，请在电脑端重新生成')
      return pairing
    }
    const candidates = await this.candidates()
    if (!candidates.length) {
      throw new Error('未发现局域网网关，请输入电脑端网关地址或确认手机与电脑在同一网络')
    }
    let lastError: unknown = null
    for (const candidate of candidates) {
      try {
        const response = await fetch(pairingResolveEndpoint(candidate), {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Cache-Control': 'no-store',
            'Content-Type': 'application/json',
          },
          cache: 'no-store',
          body: JSON.stringify({ code }),
        })
        const payload = await response.json().catch(() => null) as unknown
        if (!response.ok) {
          lastError = new Error(apiErrorMessage(payload, '配对码无效、已过期或电脑未连接'))
          continue
        }
        if (!isPairingResolution(payload)) {
          lastError = new Error('网关返回了无效的配对信息')
          continue
        }
        if (payload.expiresAtMs <= Date.now()) {
          lastError = new Error('配对码已过期，请在电脑端重新生成')
          continue
        }
        // The resolved metadata is an identity assertion. Keep the candidate
        // that actually answered as the socket route so VPN/manual addresses
        // do not get replaced by an unreachable LAN address advertised by the
        // desktop.
        return { ...payload, gatewayUrl: normalizeGatewayEndpoint(candidate) }
      } catch (error) {
        lastError = error
      }
    }
    if (lastError instanceof Error && candidates.length === 1) {
      throw new Error(`无法连接电脑：${lastError.message}`)
    }
    throw new Error('未找到匹配的配对码，请确认数字码和电脑端网关地址')
  }

  private async candidates(): Promise<string[]> {
    if (this.gatewayUrl) return [this.gatewayUrl]
    let devices: LanDevice[]
    try {
      devices = await this.lanDiscovery.discover()
    } catch (error) {
      throw new Error(`局域网发现失败：${formatError(error)}`)
    }
    return devices
      .filter((device) => device.host && Number.isInteger(device.port) && device.port > 0)
      .map((device) => normalizeGatewayEndpoint(`http://${formatHost(device.host)}:${device.port}`))
  }
}

export function normalizeGatewayEndpoint(value: string): string {
  const raw = value.trim()
  if (!raw) throw new Error('网关地址不能为空')
  const withProtocol = /^[a-z][a-z\d+.-]*:\/\//i.test(raw) ? raw : `http://${raw}`
  const url = new URL(withProtocol)
  if (!['ws:', 'wss:', 'http:', 'https:'].includes(url.protocol)) {
    throw new Error('网关地址协议无效')
  }
  url.pathname = '/_lamtools/tunnel'
  url.search = ''
  url.hash = ''
  return url.toString()
}

function isPairingResolution(value: unknown): value is PairingResolution {
  if (!isRecord(value)) return false
  return typeof value.pairingId === 'string'
    && value.pairingId.length > 0
    && typeof value.desktopDeviceId === 'string'
    && value.desktopDeviceId.length > 0
    && typeof value.desktopPublicKey === 'string'
    && value.desktopPublicKey.length > 0
    && typeof value.gatewayUrl === 'string'
    && value.gatewayUrl.length > 0
    && typeof value.expiresAtMs === 'number'
    && Number.isFinite(value.expiresAtMs)
    && typeof value.protocol === 'string'
    && typeof value.version === 'number'
}

function toWebSocketUrl(value: string): string {
  const url = new URL(value)
  if (url.protocol === 'http:') url.protocol = 'ws:'
  if (url.protocol === 'https:') url.protocol = 'wss:'
  if (url.protocol !== 'ws:' && url.protocol !== 'wss:') throw new Error('网关返回了无效地址')
  return url.toString()
}

function formatHost(host: string): string {
  const value = host.trim()
  return value.includes(':') && !value.startsWith('[') ? `[${value}]` : value
}

function apiErrorMessage(value: unknown, fallback: string): string {
  if (!isRecord(value)) return fallback
  return typeof value.message === 'string'
    ? value.message
    : typeof value.error === 'string' ? value.error : fallback
}

function isRecord(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function formatError(value: unknown): string {
  return value instanceof Error ? value.message : String(value)
}
