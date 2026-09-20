import { ref, type Ref } from 'vue'
import { Network, type NetworkPlugin } from '@capacitor/network'
import type { PluginListenerHandle } from '@capacitor/core'
import type { LamToolsTransport, TransportConnectionState } from '@lamtools/ui/transport'
import { createLanDiscovery, type LanDiscovery } from './LanDiscovery'
import type { TunnelWire } from './TunnelTransport'
import type { TrustedDevice } from '../pairing/TrustedDevices'
import type { AccountConnectionProvider } from '../account/AccountClient'
import { loadOrCreateDeviceIdentity, type DeviceIdentity } from '../pairing/DeviceIdentity'
import { createTrustedSecureWire, createRelaySecureWire } from './NoiseSecureWire'
import {
  createRemoteTransport,
  type RemoteTransport,
} from './RemoteTransport'
import type { RemoteDiagnosticSink } from './TunnelTransport'
import {
  CONNECTION_LABELS,
  type ConnectionPath,
  type ConnectionSnapshot,
  type ConnectionState,
} from './ConnectionState'

export interface ConnectionManagerOptions {
  deviceId?: string
  lanDiscovery?: LanDiscovery
  trustedDevice?: TrustedDevice
  relayEndpoint?: string
  account?: AccountConnectionProvider
  workspaceId?: string
  networkMonitor?: NetworkPlugin
  diagnosticSink?: RemoteDiagnosticSink
  /** Host-independent wire construction hook used by native adapters/tests. */
  wireFactory?: (context: ConnectionWireContext) => TunnelWire | Promise<TunnelWire>
}

export interface ConnectionWireContext {
  path: Exclude<ConnectionPath, null>
  identity: DeviceIdentity
  trustedDevice: TrustedDevice
  lanDevice?: Awaited<ReturnType<LanDiscovery['discover']>>[number]
}

export interface ConnectionContext {
  account: AccountConnectionProvider | null
  workspaceId: string
  trustedDevice: TrustedDevice | null
}

/**
 * Mobile networking owns one stable RemoteTransport.  It chooses a secure
 * wire when that transport is opened; the shared UI never sees the selected
 * route and never needs to recreate a client for LAN/relay changes.
 */
export class ConnectionManager {
  readonly state: Ref<ConnectionState> = ref('idle')
  readonly path: Ref<ConnectionPath> = ref(null)
  readonly message: Ref<string> = ref(CONNECTION_LABELS.idle)
  readonly lastError = ref('')
  readonly transport: RemoteTransport

  private readonly lanDiscovery: LanDiscovery
  private lanFailed = false
  private deviceId = ''
  private trustedDevice: TrustedDevice | null = null
  private account: AccountConnectionProvider | null = null
  private workspaceId = ''
  private readonly networkMonitor: NetworkPlugin
  private networkListener: PluginListenerHandle | null = null
  private networkMonitorGeneration = 0
  private removeTransportState: (() => void) | null = null
  private contextGeneration = 0

  constructor(private readonly options: ConnectionManagerOptions) {
    this.lanDiscovery = options.lanDiscovery || createLanDiscovery()
    this.deviceId = options.deviceId || ''
    this.trustedDevice = options.trustedDevice || null
    this.account = options.account || null
    this.workspaceId = options.workspaceId || ''
    this.networkMonitor = options.networkMonitor || Network
    this.transport = createRemoteTransport(() => this.createWire(), options.diagnosticSink)
    this.removeTransportState = this.transport.onState((state) => this.handleTransportState(state))
  }

  setDeviceId(deviceId: string): void {
    this.deviceId = deviceId.trim()
  }

  setTrustedDevice(device: TrustedDevice | null): void {
    const changed = !sameConnectionCredentials(this.trustedDevice, device)
    this.trustedDevice = device
    if (changed) {
      this.contextGeneration += 1
      void this.transport.close()
    }
  }

  setWorkspace(workspaceId: string): void {
    const next = workspaceId.trim()
    if (this.workspaceId === next) return
    this.workspaceId = next
    this.contextGeneration += 1
    void this.transport.close()
  }

  setAccount(account: AccountConnectionProvider | null): void {
    if (this.account === account) return
    this.account = account
    this.contextGeneration += 1
    void this.transport.close()
  }

  /** Apply one logical route change and invalidate the previous wire once. */
  async setConnectionContext(context: ConnectionContext): Promise<void> {
    const workspaceId = context.workspaceId.trim()
    const changed = this.account !== context.account
      || this.workspaceId !== workspaceId
      || !sameConnectionCredentials(this.trustedDevice, context.trustedDevice)
    this.account = context.account
    this.workspaceId = workspaceId
    this.trustedDevice = context.trustedDevice
    if (changed) {
      this.contextGeneration += 1
      await this.transport.close()
    }
  }

  snapshot(): ConnectionSnapshot {
    return {
      state: this.state.value,
      path: this.path.value,
      message: this.message.value,
      ...(this.lastError.value ? { lastError: this.lastError.value } : {}),
    }
  }

  getTransport(): RemoteTransport {
    return this.transport
  }

  /** Re-evaluate the physical route after the app returns to the foreground. */
  prepareForResume(): void {
    this.lanFailed = false
    this.lastError.value = ''
    if (this.trustedDevice) {
      // A foreground transition can leave a WebSocket-looking transport in a
      // stale connected state after the OS suspended its socket. Force a new
      // route/handshake so the next RPC cannot silently reuse that dead wire.
      this.contextGeneration += 1
      void this.transport.close()
    }
    if (this.trustedDevice && this.state.value !== 'offline') {
      this.state.value = 'reconnecting'
      this.message.value = CONNECTION_LABELS.reconnecting
    }
  }

  async startNetworkMonitoring(): Promise<void> {
    if (this.networkListener) return
    const generation = ++this.networkMonitorGeneration
    const listener = await this.networkMonitor.addListener('networkStatusChange', ({ connected }) => {
      if (generation !== this.networkMonitorGeneration) return
      if (!connected) {
        this.state.value = 'offline'
        this.message.value = CONNECTION_LABELS.offline
        void this.transport.close()
        return
      }
      if (this.state.value === 'offline' || this.state.value === 'error') {
        this.lanFailed = false
        this.state.value = 'reconnecting'
        this.message.value = CONNECTION_LABELS.reconnecting
        void this.transport.close()
      }
    })
    if (generation !== this.networkMonitorGeneration) {
      await listener.remove()
      return
    }
    this.networkListener = listener
    const status = await this.networkMonitor.getStatus()
    if (generation !== this.networkMonitorGeneration) return
    if (!status.connected) {
      this.state.value = 'offline'
      this.message.value = CONNECTION_LABELS.offline
    }
  }

  close(): void {
    this.contextGeneration += 1
    this.networkMonitorGeneration += 1
    void this.networkListener?.remove()
    this.networkListener = null
    this.removeTransportState?.()
    this.removeTransportState = null
    void this.transport.close()
    this.state.value = 'idle'
    this.path.value = null
    this.message.value = CONNECTION_LABELS.idle
  }

  private async createWire(): Promise<TunnelWire> {
    const generation = this.contextGeneration
    const trusted = this.trustedDevice
    if (!trusted?.publicKey) {
      throw new Error('请先配对一台 LamTools 电脑')
    }
    const canUseDirectTrust = Boolean(trusted.accessToken)

    const identity = this.account?.getDeviceIdentity && this.workspaceId
      ? await this.account.getDeviceIdentity()
      : await loadOrCreateDeviceIdentity()
    this.assertCurrent(generation)
    this.path.value = null
    this.state.value = 'discovering'
    this.message.value = CONNECTION_LABELS.discovering
    let devices: Awaited<ReturnType<LanDiscovery['discover']>> = []
    try {
      devices = await this.lanDiscovery.discover()
    } catch (error) {
      this.assertCurrent(generation)
      this.lastError.value = error instanceof Error ? error.message : String(error)
    }
    this.assertCurrent(generation)
    // Discovery is only a locator.  Never connect to an arbitrary first
    // advertisement: the paired desktop identity is the trust boundary.
    const lan = devices.find((device) => device.deviceId === trusted.deviceId)
    if (lan && canUseDirectTrust) {
      this.setRouteState(generation, 'lan', 'connecting_lan')
      try {
        return await this.buildWire(
          { path: 'lan', identity, trustedDevice: trusted, lanDevice: lan },
          () => createTrustedSecureWire(`ws://${lan.host}:${lan.port}/_lamtools/tunnel`, trusted, identity),
          generation,
        )
      } catch (error) {
        if (generation !== this.contextGeneration) throw error
        this.lanFailed = true
        this.lastError.value = error instanceof Error ? error.message : String(error)
      }
    }

    if (trusted.gatewayUrl && canUseDirectTrust) {
      this.setRouteState(generation, 'lan', 'connecting_lan')
      try {
        return await this.buildWire(
          { path: 'lan', identity, trustedDevice: trusted },
          () => createTrustedSecureWire(trusted.gatewayUrl!, trusted, identity, this.options.diagnosticSink),
          generation,
        )
      } catch (error) {
        if (generation !== this.contextGeneration) throw error
        this.lanFailed = true
        this.lastError.value = error instanceof Error ? error.message : String(error)
      }
    }

    const account = this.account
    if (!account || !this.workspaceId) {
      throw new Error('局域网/手动地址不可用；官方 Relay 需要先登录并选择工作环境')
    }
    const ticket = await account.getConnectionTicket(this.workspaceId)
    this.assertCurrent(generation)
    if (ticket.targetHostNodeId !== trusted.deviceId) {
      throw new Error('工作环境 Host 与连接目标不一致')
    }
    const relayEndpoint = account.getRelayEndpoint() || trusted.relayUrl || this.options.relayEndpoint
    if (!relayEndpoint) throw new Error('账号未配置 Relay 地址')
    this.setRouteState(generation, 'relay', 'connecting_remote')
    return await this.buildWire(
      { path: 'relay', identity, trustedDevice: trusted },
      () => createRelaySecureWire(relayEndpoint, ticket.ticket, trusted, identity, this.options.diagnosticSink),
      generation,
    )
  }

  private async buildWire(
    context: ConnectionWireContext,
    fallback: () => TunnelWire,
    generation: number,
  ): Promise<TunnelWire> {
    const wire = await (this.options.wireFactory?.(context) || fallback())
    if (generation !== this.contextGeneration) {
      wire.close()
      throw new Error('连接已取消')
    }
    try {
      // Route selection must include the actual socket + Noise handshake.
      // Merely constructing a wire cannot prove that a LAN/direct endpoint is
      // reachable, and would prevent this method from falling through to the
      // Relay candidate in the same connection attempt.
      await wire.connect()
      if (generation !== this.contextGeneration) {
        wire.close()
        throw new Error('连接已取消')
      }
      return wire
    } catch (error) {
      wire.close()
      throw error
    }
  }

  private assertCurrent(generation: number): void {
    if (generation !== this.contextGeneration) throw new Error('连接已取消')
  }

  private setRouteState(
    generation: number,
    path: Exclude<ConnectionPath, null>,
    state: ConnectionState,
  ): void {
    this.assertCurrent(generation)
    this.path.value = path
    this.state.value = state
    this.message.value = CONNECTION_LABELS[state]
  }

  private handleTransportState(state: TransportConnectionState): void {
    if (state === 'connected') {
      this.lanFailed = false
      this.state.value = this.path.value === 'relay' ? 'connected_remote' : 'connected_lan'
      this.message.value = CONNECTION_LABELS[this.state.value]
      this.lastError.value = ''
      return
    }
    if (state === 'connecting' || state === 'reconnecting') {
      this.state.value = this.path.value === 'relay' ? 'connecting_remote' : 'connecting_lan'
      this.message.value = CONNECTION_LABELS[this.state.value]
      return
    }
    if (state === 'failed') {
      if (this.path.value === 'lan') this.lanFailed = true
      this.state.value = 'error'
      this.message.value = CONNECTION_LABELS.error
      return
    }
    if (state === 'disconnected' && this.state.value !== 'idle' && this.state.value !== 'offline') {
      this.state.value = 'reconnecting'
      this.message.value = CONNECTION_LABELS.reconnecting
    }
  }
}

function sameConnectionCredentials(left: TrustedDevice | null, right: TrustedDevice | null): boolean {
  if (left === right) return true
  if (!left || !right) return false
  // Display metadata (name/platform/lastConnectedAt) may change while the
  // active connection remains valid. Recreate the transport only when the
  // authenticated peer or one of its route credentials changes.
  return left.deviceId === right.deviceId
    && left.accessToken === right.accessToken
    && left.publicKey === right.publicKey
    && left.gatewayUrl === right.gatewayUrl
    && left.relayUrl === right.relayUrl
}
