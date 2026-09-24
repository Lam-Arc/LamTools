import { afterEach, describe, expect, it, vi } from 'vitest'

const { invokeMock, hasEmbeddedRustCoreMock } = vi.hoisted(() => ({
  invokeMock: vi.fn(),
  hasEmbeddedRustCoreMock: vi.fn(),
}))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))
vi.mock('../src/native/rustAgent', () => ({ hasEmbeddedRustCore: hasEmbeddedRustCoreMock }))

import { exportMobileDiagnostics } from '../src/diagnostics/exportDiagnostics'

afterEach(() => {
  invokeMock.mockReset()
  hasEmbeddedRustCoreMock.mockReset()
  vi.unstubAllGlobals()
})

describe('mobile diagnostics exporter', () => {
  it('sends bounded Android Tauri exports to the native share command', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    vi.stubGlobal('navigator', { userAgent: 'Android WebView' })
    hasEmbeddedRustCoreMock.mockReturnValue(true)
    invokeMock.mockResolvedValue({ shared: true })

    await expect(exportMobileDiagnostics('{"schema":"lamtools.mobile-diagnostics"}')).resolves.toBe('android-share')
    expect(invokeMock).toHaveBeenCalledWith('mobile_diagnostics_share', {
      contents: '{"schema":"lamtools.mobile-diagnostics"}',
    })
  })

  it('uses a generic failure message when native sharing fails', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    vi.stubGlobal('navigator', { userAgent: 'Android WebView' })
    hasEmbeddedRustCoreMock.mockReturnValue(true)
    invokeMock.mockRejectedValue(new Error('private cache path /data/user/0/private'))

    await expect(exportMobileDiagnostics('{}')).rejects.toThrow('无法打开 Android 分享面板')
    await expect(exportMobileDiagnostics('{}')).rejects.not.toThrow('/data/user/0/private')
  })
})
