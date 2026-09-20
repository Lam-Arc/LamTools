import { Capacitor } from '@capacitor/core'
import { secureStorage, type SecureStorage } from '../native/secureStorage'
import { loadOrCreateAccountDeviceIdentity, type DeviceIdentity } from '../pairing/DeviceIdentity'

export interface ServerProfile {
  baseUrl: string
  serverId?: string
  displayName?: string
}

export interface AccountTokens {
  serverId: string
  accessToken: string
  refreshToken: string
  accessExpiresAtMs: number
  refreshExpiresAtMs: number
}

export interface AccountSession extends AccountTokens {
  /** Persisted so custom/self-hosted servers can be restored after restart. */
  baseUrl: string
  username: string
  nodeId: string
  publicKey: string
  selectedWorkspaceId?: string
}

export interface AccountNode {
  nodeId: string
  displayName: string
  platform: string
  publicKey: string
  capabilities: string[]
  createdAtMs: number
  lastSeenAtMs?: number
  revokedAtMs?: number
}

export interface AccountWorkspace {
  workspaceId: string
  hostNodeId: string
  ownerUserId: string
  displayName: string
  online: boolean
  host?: AccountNode | null
  role: 'owner' | 'access' | string
  createdAtMs: number
}

export interface ConnectionTicket {
  ticket: string
  workspaceId: string
  sourceNodeId: string
  targetHostNodeId: string
  expiresAtMs: number
}

export interface AccountPairingResolution {
  pairingId: string
  desktopDeviceId: string
  desktopPublicKey: string
  gatewayUrl: string
  relayUrl?: string
  relayTicket: string
  expiresAtMs: number
  protocol: string
  version: number
}

export interface AccountClientOptions {
  profile: ServerProfile | string
  storage?: SecureStorage
  session?: AccountSession | null
  identity?: DeviceIdentity
}

export interface AccountConnectionProvider {
  getConnectionTicket(workspaceId: string): Promise<ConnectionTicket>
  getRelayEndpoint(): string
  resolvePairing?(code: string): Promise<AccountPairingResolution>
  getDeviceIdentity?(): Promise<DeviceIdentity>
}

const ACCOUNT_SESSION_KEY = 'lamtools.mobile.account-session-v1'
const ACCESS_REFRESH_SKEW_MS = 30_000

type JsonRequestInit = Omit<RequestInit, 'body'> & { body?: unknown }

/**
 * Server control-plane client for the mobile shell.
 *
 * This client intentionally never stores a password and never exposes a
 * deployment-wide relay credential.  A login session is upgraded to a
 * device-bound Node session immediately after authentication; Relay access
 * then uses a short-lived workspace Connection Ticket.
 */
export class AccountClient implements AccountConnectionProvider {
  readonly profile: ServerProfile

  private readonly storage: SecureStorage
  private identity: DeviceIdentity | null
  private sessionValue: AccountSession | null
  private sessionGeneration = 0
  private refreshPromise: Promise<AccountSession> | null = null
  private refreshPromiseGeneration = -1
  private refreshPromiseSession: AccountSession | null = null

  constructor(options: AccountClientOptions) {
    this.profile = normalizeProfile(options.profile)
    this.storage = options.storage || secureStorage()
    this.identity = options.identity || null
    this.sessionValue = options.session || null
  }

  get session(): AccountSession | null {
    return this.sessionValue
  }

  get authenticated(): boolean {
    return Boolean(this.sessionValue?.accessToken && this.sessionValue?.refreshToken)
  }

  getRelayEndpoint(): string {
    return endpointFor(this.profile.baseUrl, '/v1/relay/connect', 'ws')
  }

  async getDeviceIdentity(): Promise<DeviceIdentity> {
    if (this.identity) return this.identity
    const session = this.requireSession()
    this.identity = await loadOrCreateAccountDeviceIdentity(session.serverId, session.username, this.storage)
    return this.identity
  }

  async register(username: string, password: string): Promise<AccountSession> {
    const tokens = parseTokens(await this.requestPublic('/v1/auth/register', {
      method: 'POST',
      body: { username, password },
    }))
    return await this.finishAuthentication(tokens, username)
  }

  async login(username: string, password: string): Promise<AccountSession> {
    const tokens = parseTokens(await this.requestPublic('/v1/auth/login', {
      method: 'POST',
      body: { username, password },
    }))
    return await this.finishAuthentication(tokens, username)
  }

  async restore(): Promise<AccountSession | null> {
    const stored = await this.storage.get<AccountSession>(ACCOUNT_SESSION_KEY)
    if (!isAccountSession(stored)) return null
    if (stored.serverId !== this.profile.serverId && this.profile.serverId) return null
    // A restore can race an earlier refresh on an instance that is reused by
    // an embedding shell. Invalidate that refresh before replacing the
    // session, otherwise its response could overwrite the restored account.
    this.sessionGeneration += 1
    this.sessionValue = stored
    return stored
  }

  async refresh(): Promise<AccountSession> {
    const current = this.requireSession()
    if (
      this.refreshPromise
      && this.refreshPromiseGeneration === this.sessionGeneration
      && this.refreshPromiseSession === current
    ) {
      return await this.refreshPromise
    }

    const generation = this.sessionGeneration
    const promise = (async (): Promise<AccountSession> => {
      const tokens = parseTokens(await this.requestPublic('/v1/auth/refresh', {
        method: 'POST',
        body: { refreshToken: current.refreshToken },
      }))
      // Logout or a newer authentication must win over an older refresh
      // response. Do not resurrect the signed-out session in secure storage.
      if (this.sessionGeneration !== generation || this.sessionValue !== current) {
        throw new Error('账号会话已结束')
      }
      const next = { ...current, ...tokens }
      this.sessionValue = next
      await this.persist()
      return next
    })()
    this.refreshPromise = promise
    this.refreshPromiseGeneration = generation
    this.refreshPromiseSession = current
    try {
      return await promise
    } finally {
      if (this.refreshPromise === promise) {
        this.refreshPromise = null
        this.refreshPromiseGeneration = -1
        this.refreshPromiseSession = null
      }
    }
  }

  async logout(): Promise<void> {
    const current = this.sessionValue
    this.sessionGeneration += 1
    this.sessionValue = null
    await this.storage.remove(ACCOUNT_SESSION_KEY)
    if (!current) return
    try {
      await fetch(this.url('/v1/auth/logout'), {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          Authorization: `Bearer ${current.accessToken}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ refreshToken: current.refreshToken }),
        cache: 'no-store',
      })
    } catch {
      // Local sign-out is authoritative even when the server is unavailable.
    }
  }

  async listNodes(): Promise<AccountNode[]> {
    const payload = await this.requestAuthenticated('/v1/nodes')
    return arrayOfRecords(payload.nodes).flatMap((value) => {
      const node = toNode(value)
      return node ? [node] : []
    })
  }

  async listWorkspaces(): Promise<AccountWorkspace[]> {
    const payload = await this.requestAuthenticated('/v1/workspaces')
    return arrayOfRecords(payload.workspaces).flatMap((value) => {
      const workspace = toWorkspace(value)
      return workspace ? [workspace] : []
    })
  }

  async getConnectionTicket(workspaceId: string): Promise<ConnectionTicket> {
    const normalized = workspaceId.trim()
    if (!normalized) throw new Error('工作环境 ID 不能为空')
    const payload = await this.requestAuthenticated(
      `/v1/workspaces/${encodeURIComponent(normalized)}/connect-ticket`,
      { method: 'POST' },
    )
    const ticket = toTicket(payload)
    if (!ticket) throw new Error('服务器返回了无效的连接 Ticket')
    return ticket
  }

  async resolvePairing(code: string): Promise<AccountPairingResolution> {
    const normalized = code.trim()
    if (!/^\d{6}$/.test(normalized)) throw new Error('配对码必须是六位数字')
    const payload = await this.requestAuthenticated('/v1/pairing/resolve', {
      method: 'POST',
      body: { code: normalized },
    })
    const pairing = toAccountPairingResolution(payload)
    if (!pairing) throw new Error('服务器返回了无效的配对信息')
    return {
      ...pairing,
      relayUrl: pairing.relayUrl || this.getRelayEndpoint(),
    }
  }

  async selectWorkspace(workspaceId: string): Promise<void> {
    const current = this.requireSession()
    this.sessionValue = { ...current, selectedWorkspaceId: workspaceId.trim() || undefined }
    await this.persist()
  }

  private async finishAuthentication(tokens: AccountTokens, username: string): Promise<AccountSession> {
    this.identity = this.identity || await loadOrCreateAccountDeviceIdentity(tokens.serverId, username, this.storage)
    const registration = await this.requestWithToken('/v1/nodes/register', tokens.accessToken, {
      method: 'POST',
      body: {
        nodeId: this.identity.deviceId,
        publicKey: this.identity.publicKey,
        displayName: 'LamTools Mobile',
        // Capacitor reports `web` for the browser Demo. Keep that Node in the
        // mobile category so Relay never mistakes the browser client for a
        // desktop Workspace host.
        platform: Capacitor.isNativePlatform()
          ? (Capacitor.getPlatform() || 'mobile')
          : 'mobile-web',
        capabilities: ['workspace_client', 'local_cache'],
      },
    })
    const node = toNode(registration.node)
    if (!node) throw new Error('服务器未返回有效的移动端 Node')
    const boundTokens = isRecord(registration.tokens) ? parseTokens(registration.tokens) : tokens
    const session: AccountSession = {
      ...boundTokens,
      baseUrl: this.profile.baseUrl,
      username: username.trim(),
      nodeId: node.nodeId,
      publicKey: node.publicKey,
    }
    this.sessionValue = session
    this.sessionGeneration += 1
    await this.persist()
    return session
  }

  private async requestAuthenticated(path: string, init: JsonRequestInit = {}): Promise<Record<string, unknown>> {
    const current = this.requireSession()
    if (current.accessExpiresAtMs <= Date.now() + ACCESS_REFRESH_SKEW_MS) await this.refresh()
    const refreshed = this.requireSession()
    try {
      return await this.requestWithToken(path, refreshed.accessToken, init)
    } catch (error) {
      if (!isAuthError(error)) throw error
      await this.refresh()
      return await this.requestWithToken(path, this.requireSession().accessToken, init)
    }
  }

  private async requestPublic(path: string, init: JsonRequestInit = {}): Promise<Record<string, unknown>> {
    return await this.requestWithToken(path, undefined, {
      method: init.method,
      body: init.body,
    })
  }

  private async requestWithToken(path: string, token: string | undefined, init: JsonRequestInit = {}): Promise<Record<string, unknown>> {
    const headers = new Headers(init.headers)
    headers.set('Accept', 'application/json')
    headers.set('Cache-Control', 'no-store')
    const { body: _body, ...requestOptions } = init
    const requestInit: RequestInit = { ...requestOptions, headers, cache: 'no-store' }
    if (init.body !== undefined && typeof init.body !== 'string') {
      headers.set('Content-Type', 'application/json')
      requestInit.body = JSON.stringify(init.body)
    } else if (typeof init.body === 'string') {
      requestInit.body = init.body
    }
    if (token) headers.set('Authorization', `Bearer ${token}`)
    let response: Response
    try {
      response = await fetch(this.url(path), requestInit)
    } catch (error) {
      throw new Error(`无法连接服务器：${formatError(error)}`)
    }
    const payload = await response.json().catch(() => null) as unknown
    if (!response.ok) throw new AccountApiError(response.status, payload)
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return {}
    return payload as Record<string, unknown>
  }

  private requireSession(): AccountSession {
    if (!this.sessionValue?.accessToken || !this.sessionValue.refreshToken) {
      throw new Error('请先登录服务器账号')
    }
    return this.sessionValue
  }

  private async persist(): Promise<void> {
    if (this.sessionValue) await this.storage.set(ACCOUNT_SESSION_KEY, this.sessionValue)
  }

  private url(path: string): string {
    return endpointFor(this.profile.baseUrl, path, 'http')
  }
}

export class AccountApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, payload: unknown) {
    const record = isRecord(payload) ? payload : {}
    const code = typeof record.code === 'string' ? record.code : 'SERVER_REQUEST_FAILED'
    const message = typeof record.message === 'string'
      ? record.message
      : typeof record.error === 'string' ? record.error : `服务器请求失败（${status}）`
    super(message)
    this.name = 'AccountApiError'
    this.status = status
    this.code = code
  }
}

export async function loadStoredAccount(storage: SecureStorage = secureStorage()): Promise<AccountClient | null> {
  const stored = await storage.get<AccountSession>(ACCOUNT_SESSION_KEY)
  if (!isAccountSession(stored)) return null
  const client = new AccountClient({
    profile: { baseUrl: storedServerBase(stored), serverId: stored.serverId },
    storage,
    session: stored,
  })
  return client
}

export function normalizeProfile(value: ServerProfile | string): ServerProfile {
  const raw = typeof value === 'string' ? value : value.baseUrl
  const input = raw.trim()
  if (!input) throw new Error('服务器地址不能为空')
  let url: URL
  try {
    url = new URL(input)
  } catch {
    throw new Error('服务器地址格式无效')
  }
  if (!['http:', 'https:', 'ws:', 'wss:'].includes(url.protocol)) {
    throw new Error('服务器地址协议无效')
  }
  if (url.protocol === 'ws:') url.protocol = 'http:'
  if (url.protocol === 'wss:') url.protocol = 'https:'
  const path = url.pathname.replace(/\/+$/, '')
  const marker = path.indexOf('/v1/')
  url.pathname = marker >= 0 ? path.slice(0, marker) || '/' : path || '/'
  url.search = ''
  url.hash = ''
  return {
    ...(typeof value === 'string' ? {} : value),
    baseUrl: url.toString().replace(/\/$/, ''),
  }
}

function endpointFor(baseUrl: string, path: string, protocol: 'http' | 'ws'): string {
  const base = normalizeProfile(baseUrl).baseUrl
  const url = new URL(`${base}${path.startsWith('/') ? path : `/${path}`}`)
  url.protocol = protocol === 'ws'
    ? (url.protocol === 'https:' ? 'wss:' : 'ws:')
    : (url.protocol === 'wss:' || url.protocol === 'ws:' ? 'https:' : url.protocol)
  return url.toString()
}

function parseTokens(value: Record<string, unknown>): AccountTokens {
  const tokens = isRecord(value.tokens) ? value.tokens : value
  const accessToken = stringValue(tokens.accessToken || tokens.access_token)
  const refreshToken = stringValue(tokens.refreshToken || tokens.refresh_token)
  const serverId = stringValue(tokens.serverId || tokens.server_id)
  const accessExpiresAtMs = numberValue(tokens.accessExpiresAtMs || tokens.access_expires_at_ms)
  const refreshExpiresAtMs = numberValue(tokens.refreshExpiresAtMs || tokens.refresh_expires_at_ms)
  if (!accessToken || !refreshToken || !serverId || !accessExpiresAtMs || !refreshExpiresAtMs) {
    throw new Error('服务器返回了无效的登录凭据')
  }
  return { serverId, accessToken, refreshToken, accessExpiresAtMs, refreshExpiresAtMs }
}

function toNode(value: unknown): AccountNode | null {
  if (!isRecord(value)) return null
  const nodeId = stringValue(value.nodeId || value.node_id)
  const publicKey = stringValue(value.publicKey || value.public_key)
  if (!nodeId || !publicKey) return null
  return {
    nodeId,
    publicKey,
    displayName: stringValue(value.displayName || value.display_name) || nodeId,
    platform: stringValue(value.platform) || 'unknown',
    capabilities: arrayOfStrings(value.capabilities),
    createdAtMs: numberValue(value.createdAtMs || value.created_at_ms),
    ...(numberOrUndefined(value.lastSeenAtMs || value.last_seen_at_ms) === undefined
      ? {} : { lastSeenAtMs: numberOrUndefined(value.lastSeenAtMs || value.last_seen_at_ms) }),
    ...(numberOrUndefined(value.revokedAtMs || value.revoked_at_ms) === undefined
      ? {} : { revokedAtMs: numberOrUndefined(value.revokedAtMs || value.revoked_at_ms) }),
  }
}

function toWorkspace(value: unknown): AccountWorkspace | null {
  if (!isRecord(value)) return null
  const workspaceId = stringValue(value.workspaceId || value.workspace_id)
  const hostNodeId = stringValue(value.hostNodeId || value.host_node_id)
  if (!workspaceId || !hostNodeId) return null
  return {
    workspaceId,
    hostNodeId,
    ownerUserId: stringValue(value.ownerUserId || value.owner_user_id),
    displayName: stringValue(value.displayName || value.display_name) || hostNodeId,
    online: value.online === true,
    host: toNode(value.host),
    role: stringValue(value.role) || 'access',
    createdAtMs: numberValue(value.createdAtMs || value.created_at_ms),
  }
}

function toTicket(value: Record<string, unknown>): ConnectionTicket | null {
  const ticket = stringValue(value.ticket)
  const workspaceId = stringValue(value.workspaceId || value.workspace_id)
  const sourceNodeId = stringValue(value.sourceNodeId || value.source_node_id)
  const targetHostNodeId = stringValue(value.targetHostNodeId || value.target_host_node_id)
  const expiresAtMs = numberValue(value.expiresAtMs || value.expires_at_ms)
  if (!ticket || !workspaceId || !sourceNodeId || !targetHostNodeId || !expiresAtMs) return null
  return { ticket, workspaceId, sourceNodeId, targetHostNodeId, expiresAtMs }
}

function toAccountPairingResolution(value: Record<string, unknown>): AccountPairingResolution | null {
  const pairingId = stringValue(value.pairingId || value.pairing_id)
  const desktopDeviceId = stringValue(value.desktopDeviceId || value.desktop_device_id)
  const desktopPublicKey = stringValue(value.desktopPublicKey || value.desktop_public_key)
  const gatewayUrl = stringValue(value.gatewayUrl || value.gateway_url)
  const relayTicket = stringValue(value.relayTicket || value.relay_ticket)
  const expiresAtMs = numberValue(value.expiresAtMs || value.expires_at_ms)
  const protocol = stringValue(value.protocol)
  const version = numberValue(value.version)
  if (!pairingId || !desktopDeviceId || !desktopPublicKey || !gatewayUrl || !relayTicket || !expiresAtMs || !protocol || !version) return null
  const relayUrl = stringValue(value.relayUrl || value.relay_url)
  return {
    pairingId,
    desktopDeviceId,
    desktopPublicKey,
    gatewayUrl,
    ...(relayUrl ? { relayUrl } : {}),
    relayTicket,
    expiresAtMs,
    protocol,
    version,
  }
}

function isAccountSession(value: unknown): value is AccountSession {
  if (!isRecord(value)) return false
  return Boolean(
    normalizeStoredBaseUrl(value.baseUrl)
      && stringValue(value.serverId)
      && stringValue(value.accessToken)
      && stringValue(value.refreshToken)
      && stringValue(value.username)
      && stringValue(value.nodeId)
      && stringValue(value.publicKey),
  )
}

function storedServerBase(session: AccountSession): string {
  return session.baseUrl
}

function normalizeStoredBaseUrl(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return ''
  try {
    return normalizeProfile(value).baseUrl
  } catch {
    return ''
  }
}

function isAuthError(error: unknown): boolean {
  return error instanceof AccountApiError && (error.status === 401 || error.code === 'AUTH_INVALID')
}

function arrayOfRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : []
}

function arrayOfStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function isRecord(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function numberValue(value: unknown): number {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

function numberOrUndefined(value: unknown): number | undefined {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? number : undefined
}

function formatError(value: unknown): string {
  return value instanceof Error ? value.message : String(value)
}
