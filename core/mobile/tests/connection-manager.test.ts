import { describe, expect, it } from 'vitest'
import type { PluginListenerHandle } from '@capacitor/core'
import type { ConnectionStatus } from '@capacitor/network'
import type { TransportConnectionState } from '@lamtools/ui/transport'
import { ConnectionManager } from '../src/connection/ConnectionManager'
import type { TunnelWire } from '../src/connection/TunnelTransport'

class FakeWire implements TunnelWire {
  private readonly dataListeners = new Set<(data: Uint8Array) => void>()
  private readonly stateListeners = new Set<(state: TransportConnectionState) => void>()
  private state: TransportConnectionState = 'disconnected'

  constructor(private readonly failure?: Error) {}

  async connect(): Promise<void> {
    if (this.failure) throw this.failure
    this.state = 'connected'
    for (const listener of this.stateListeners) listener(this.state)
  }

  send(_data: Uint8Array): void {}

  onData(listener: (data: Uint8Array) => void): () => void {
    this.dataListeners.add(listener)
    return () => this.dataListeners.delete(listener)
  }

  onState(listener: (state: TransportConnectionState) => void): () => void {
    this.stateListeners.add(listener)
    listener(this.state)
    return () => this.stateListeners.delete(listener)
  }

  close(): void {
    this.state = 'disconnected'
    for (const listener of this.stateListeners) listener(this.state)
  }
}

const trustedDevice = {
  deviceId: 'desktop-1',
  name: 'LamTools Desktop',
  publicKey: 'desktop-public-key',
  accessToken: 'desktop-access-token',
}

function fakeAccount(targetHostNodeId = 'desktop-1') {
  return {
    async getConnectionTicket(workspaceId: string) {
      return {
        ticket: `ticket-for-${workspaceId}`,
        workspaceId,
        sourceNodeId: 'mobile-1',
        targetHostNodeId,
        expiresAtMs: Date.now() + 60_000,
      }
    },
    getRelayEndpoint() {
      return 'ws://relay.example.test/v1/relay'
    },
  }
}

class FakeNetworkMonitor {
  private listener: ((status: ConnectionStatus) => void) | null = null

  async addListener(
    _eventName: 'networkStatusChange',
    listener: (status: ConnectionStatus) => void,
  ): Promise<PluginListenerHandle> {
    this.listener = listener
    return { remove: async () => { this.listener = null } }
  }

  async getStatus(): Promise<ConnectionStatus> {
    return { connected: true, connectionType: 'wifi' }
  }

  emit(status: ConnectionStatus): void {
    this.listener?.(status)
  }
}

describe('ConnectionManager route selection', () => {
  it('only selects a LAN advertisement belonging to the paired desktop', async () => {
    const paths: string[] = []
    const manager = new ConnectionManager({
      trustedDevice: { ...trustedDevice, gatewayUrl: 'ws://127.0.0.1:4000/_lamtools/tunnel' },
      lanDiscovery: {
        async discover() {
          return [
            { deviceId: 'untrusted-desktop', host: '192.168.1.20', port: 4000 },
            { deviceId: 'desktop-1', host: '192.168.1.21', port: 4001 },
          ]
        },
      },
      wireFactory: ({ path }) => {
        paths.push(path)
        return new FakeWire()
      },
    })

    await manager.transport.connect()

    expect(paths).toEqual(['lan'])
    expect(manager.path.value).toBe('lan')
    expect(manager.state.value).toBe('connected_lan')
    manager.close()
  })

  it('falls back to Relay in the same attempt after the paired LAN route fails', async () => {
    const paths: string[] = []
    let attempt = 0
    const manager = new ConnectionManager({
      trustedDevice,
      relayEndpoint: 'ws://relay.example.test/v1/relay',
      account: fakeAccount(),
      workspaceId: 'workspace-1',
      lanDiscovery: {
        async discover() {
          return [{ deviceId: 'desktop-1', host: '192.168.1.21', port: 4001 }]
        },
      },
      wireFactory: ({ path }) => {
        paths.push(path)
        attempt += 1
        return attempt === 1 ? new FakeWire(new Error('LAN unavailable')) : new FakeWire()
      },
    })

    await manager.transport.connect()

    expect(paths).toEqual(['lan', 'relay'])
    expect(manager.path.value).toBe('relay')
    expect(manager.state.value).toBe('connected_remote')
    manager.close()
  })

  it('falls back to Relay when a saved direct gateway is unreachable', async () => {
    const paths: string[] = []
    const manager = new ConnectionManager({
      trustedDevice: {
        ...trustedDevice,
        gatewayUrl: 'ws://10.0.0.2:4000/_lamtools/tunnel',
        relayUrl: 'wss://relay.example.test/v1/relay',
      },
      account: fakeAccount(),
      workspaceId: 'workspace-1',
      lanDiscovery: { async discover() { return [] } },
      wireFactory: ({ path }) => {
        paths.push(path)
        return new FakeWire(path === 'lan' ? new Error('direct unavailable') : undefined)
      },
    })

    await manager.transport.connect()

    expect(paths).toEqual(['lan', 'relay'])
    expect(manager.path.value).toBe('relay')
    expect(manager.state.value).toBe('connected_remote')
    manager.close()
  })

  it('does not close a live Relay transport on a connected network event', async () => {
    const network = new FakeNetworkMonitor()
    const manager = new ConnectionManager({
      trustedDevice,
      relayEndpoint: 'ws://relay.example.test/v1/relay',
      account: fakeAccount(),
      workspaceId: 'workspace-1',
      lanDiscovery: { async discover() { return [] } },
      networkMonitor: network,
      wireFactory: () => new FakeWire(),
    })

    await manager.startNetworkMonitoring()
    await manager.transport.connect()
    expect(manager.transport.getState()).toBe('connected')

    network.emit({ connected: true, connectionType: 'wifi' })

    expect(manager.transport.getState()).toBe('connected')
    manager.close()
  })

  it('applies an account workspace route as one connection-context update', async () => {
    const manager = new ConnectionManager({
      lanDiscovery: { async discover() { return [] } },
      wireFactory: () => new FakeWire(),
    })
    const account = fakeAccount()

    await manager.setConnectionContext({
      account,
      workspaceId: 'workspace-1',
      trustedDevice,
    })
    await manager.transport.connect()

    expect(manager.path.value).toBe('relay')
    expect(manager.transport.getState()).toBe('connected')
    manager.close()
  })

  it('invalidates a live wire when the app resumes', async () => {
    const manager = new ConnectionManager({
      trustedDevice: { ...trustedDevice, gatewayUrl: 'ws://127.0.0.1:4000/_lamtools/tunnel' },
      lanDiscovery: { async discover() { return [] } },
      wireFactory: () => new FakeWire(),
    })

    await manager.transport.connect()
    expect(manager.transport.getState()).toBe('connected')
    manager.prepareForResume()
    await Promise.resolve()

    expect(manager.transport.getState()).toBe('disconnected')
    expect(manager.state.value).toBe('reconnecting')
    manager.close()
  })
})
