import { Capacitor, registerPlugin } from '@capacitor/core'
import type { LanDevice } from '../connection/LanDiscovery'

interface NativeLanDiscoveryPlugin {
  discover(options: { timeoutMs: number }): Promise<{ devices: LanDevice[] }>
}

const plugin = registerPlugin<NativeLanDiscoveryPlugin>('LamToolsLanDiscovery')

export async function discoverNativeLanDevices(timeoutMs: number): Promise<LanDevice[]> {
  if (!Capacitor.isNativePlatform()) return []
  const result = await plugin.discover({ timeoutMs })
  return Array.isArray(result.devices) ? result.devices : []
}
