import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const native = vi.hoisted(() => ({
  isNativePlatform: vi.fn(),
  capacitorDiscover: vi.fn(),
  invoke: vi.fn(),
}))

vi.mock('@capacitor/core', () => ({
  Capacitor: { isNativePlatform: native.isNativePlatform },
  registerPlugin: vi.fn(() => ({ discover: native.capacitorDiscover })),
}))
vi.mock('@tauri-apps/api/core', () => ({ invoke: native.invoke }))

import { discoverNativeLanDevices } from '../src/native/lanDiscovery'

describe('native LAN discovery adapters', () => {
  beforeEach(() => {
    native.isNativePlatform.mockReset().mockReturnValue(false)
    native.capacitorDiscover.mockReset()
    native.invoke.mockReset()
  })

  afterEach(() => vi.unstubAllGlobals())

  it('uses the Tauri Android NSD plugin with a bounded timeout and valid candidates', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    native.invoke.mockResolvedValue({
      devices: [
        { deviceId: 'desktop-a', host: '192.168.1.10', port: 55791, protocolVersion: '1' },
        { deviceId: 'missing-port', host: '192.168.1.11' },
      ],
    })

    await expect(discoverNativeLanDevices(50)).resolves.toEqual([
      { deviceId: 'desktop-a', host: '192.168.1.10', port: 55791, protocolVersion: '1' },
    ])
    expect(native.invoke).toHaveBeenCalledWith(
      'plugin:lamtools-lan-discovery|discover',
      { timeoutMs: 250 },
    )
  })

  it('keeps the existing Capacitor discovery path', async () => {
    native.isNativePlatform.mockReturnValue(true)
    native.capacitorDiscover.mockResolvedValue({
      devices: [{ deviceId: 'desktop-b', host: '10.0.0.8', port: 55791 }],
    })

    await expect(discoverNativeLanDevices(9000)).resolves.toEqual([
      { deviceId: 'desktop-b', host: '10.0.0.8', port: 55791 },
    ])
    expect(native.capacitorDiscover).toHaveBeenCalledWith({ timeoutMs: 5000 })
    expect(native.invoke).not.toHaveBeenCalled()
  })

  it('returns no devices in a regular browser', async () => {
    vi.stubGlobal('window', {})

    await expect(discoverNativeLanDevices(1200)).resolves.toEqual([])
    expect(native.invoke).not.toHaveBeenCalled()
    expect(native.capacitorDiscover).not.toHaveBeenCalled()
  })
})
