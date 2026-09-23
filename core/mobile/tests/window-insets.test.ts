import { afterEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

import { observeNativeWindowInsets, readNativeWindowInsets } from '../src/native/windowInsets'

function installTauriWindow(): void {
  vi.stubGlobal('window', {
    __TAURI_INTERNALS__: {},
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout,
    visualViewport: undefined,
  })
}

afterEach(() => {
  vi.useRealTimers()
  invokeMock.mockReset()
  vi.unstubAllGlobals()
})

describe('native window inset startup recovery', () => {
  it('retries when the native view has no inset payload yet', async () => {
    vi.useFakeTimers()
    installTauriWindow()
    invokeMock
      .mockResolvedValueOnce({ top: null })
      .mockResolvedValueOnce({ top: 24 })

    const apply = vi.fn()
    const dispose = observeNativeWindowInsets(apply)
    await vi.advanceTimersByTimeAsync(0)
    expect(invokeMock).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(50)
    expect(invokeMock).toHaveBeenCalledTimes(2)
    expect(apply).toHaveBeenCalledWith(expect.objectContaining({ top: 24 }))
    dispose()
  })

  it('keeps a real zero inset distinct from an unavailable inset', async () => {
    vi.useFakeTimers()
    installTauriWindow()
    invokeMock.mockResolvedValue({ top: 0 })

    await expect(readNativeWindowInsets()).resolves.toEqual({
      top: 0,
      right: 0,
      bottom: 0,
      left: 0,
    })
  })

  it('continues startup reads after a provisional zero until the status inset arrives', async () => {
    vi.useFakeTimers()
    installTauriWindow()
    invokeMock
      .mockResolvedValueOnce({ top: 0 })
      .mockResolvedValueOnce({ top: 28 })

    const apply = vi.fn()
    const dispose = observeNativeWindowInsets(apply)
    await vi.advanceTimersByTimeAsync(0)
    expect(apply).toHaveBeenCalledWith(expect.objectContaining({ top: 0 }))

    await vi.advanceTimersByTimeAsync(50)
    expect(apply).toHaveBeenLastCalledWith(expect.objectContaining({ top: 28 }))
    expect(invokeMock).toHaveBeenCalledTimes(2)
    dispose()
  })

  it('bounds retries when the native view never becomes ready', async () => {
    vi.useFakeTimers()
    installTauriWindow()
    invokeMock.mockResolvedValue({ top: null })

    const dispose = observeNativeWindowInsets(vi.fn())
    await vi.advanceTimersByTimeAsync(5_000)

    // One initial read plus the eight bounded startup retries.
    expect(invokeMock).toHaveBeenCalledTimes(9)
    dispose()
  })
})
