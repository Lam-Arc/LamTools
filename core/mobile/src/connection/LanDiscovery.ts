export interface LanDevice {
  deviceId: string
  name?: string
  host: string
  port: number
  protocolVersion?: string
}

export interface LanDiscovery {
  discover(timeoutMs?: number): Promise<LanDevice[]>
}

/**
 * Browser-safe discovery adapter. Native mDNS implementations can satisfy
 * this interface later; the web/dev runtime simply returns no devices and
 * lets ConnectionManager use the configured direct/relay path.
 */
export class BrowserLanDiscovery implements LanDiscovery {
  async discover(_timeoutMs = 1200): Promise<LanDevice[]> {
    return []
  }
}

export function createLanDiscovery(): LanDiscovery {
  return {
    async discover(timeoutMs = 1200): Promise<LanDevice[]> {
      const { discoverNativeLanDevices } = await import('../native/lanDiscovery')
      return await discoverNativeLanDevices(timeoutMs)
    },
  }
}
