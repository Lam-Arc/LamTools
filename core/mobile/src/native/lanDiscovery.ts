import { Capacitor, registerPlugin } from '@capacitor/core'
import { invoke } from '@tauri-apps/api/core'
import type { LanDevice } from '../connection/LanDiscovery'

interface NativeLanDiscoveryPlugin {
  discover(options: { timeoutMs: number }): Promise<{ devices: LanDevice[] }>
}

const plugin = registerPlugin<NativeLanDiscoveryPlugin>('LamToolsLanDiscovery')
const MIN_TIMEOUT_MS = 250
const MAX_TIMEOUT_MS = 5000

export async function discoverNativeLanDevices(timeoutMs: number): Promise<LanDevice[]> {
  const boundedTimeoutMs = clampTimeout(timeoutMs)

  if (Capacitor.isNativePlatform()) {
    return normalizeDevices(await plugin.discover({ timeoutMs: boundedTimeoutMs }))
  }

  // The shipped Android shell is Tauri, where Capacitor reports false. Keep
  // the existing Capacitor path for legacy/iOS builds and use Tauri's native
  // Android NSD plugin when running inside the embedded Rust host.
  if (typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window) {
    const result = await invoke<{ devices?: unknown }>(
      'plugin:lamtools-lan-discovery|discover',
      { timeoutMs: boundedTimeoutMs },
    )
    return normalizeDevices(result)
  }

  return []
}

function clampTimeout(value: number): number {
  const timeout = Number.isFinite(value) ? Math.floor(value) : 1200
  return Math.min(MAX_TIMEOUT_MS, Math.max(MIN_TIMEOUT_MS, timeout))
}

function normalizeDevices(value: unknown): LanDevice[] {
  if (!value || typeof value !== 'object' || !Array.isArray((value as { devices?: unknown }).devices)) {
    return []
  }

  return (value as { devices: unknown[] }).devices.flatMap((candidate) => {
    if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) return []
    const device = candidate as Record<string, unknown>
    if (
      typeof device.deviceId !== 'string'
      || !device.deviceId.trim()
      || typeof device.host !== 'string'
      || !device.host.trim()
      || !Number.isInteger(device.port)
      || Number(device.port) < 1
      || Number(device.port) > 65535
    ) return []

    return [{
      deviceId: device.deviceId,
      host: device.host,
      port: Number(device.port),
      ...(typeof device.name === 'string' ? { name: device.name } : {}),
      ...(typeof device.protocolVersion === 'string'
        ? { protocolVersion: device.protocolVersion }
        : {}),
    }]
  })
}
