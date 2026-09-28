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
    setInterval: globalThis.setInterval,
    clearInterval: globalThis.clearInterval,
    visualViewport: undefined,
  })
}

/**
 * Minimal document stub: the module only reads `activeElement` and subscribes
 * to focus transitions, so the tests drive focus by flipping `activeElement`
 * and firing the captured handlers.
 */
function installFocusableDocument(): {
  focus(field: unknown): void
  blur(): void
} {
  const handlers = new Map<string, Array<() => void>>()
  vi.stubGlobal('document', {
    activeElement: null as unknown,
    addEventListener: (type: string, handler: () => void) => {
      handlers.set(type, [...(handlers.get(type) ?? []), handler])
    },
    removeEventListener: (type: string, handler: () => void) => {
      handlers.set(type, (handlers.get(type) ?? []).filter((entry) => entry !== handler))
    },
  })
  const fire = (type: string): void => {
    for (const handler of handlers.get(type) ?? []) handler()
  }
  return {
    focus(field: unknown): void {
      ;(globalThis.document as unknown as { activeElement: unknown }).activeElement = field
      fire('focusin')
    },
    blur(): void {
      ;(globalThis.document as unknown as { activeElement: unknown }).activeElement = null
      fire('focusout')
    },
  }
}

const editableField = { closest: () => ({}) }

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
      imeBottom: 0,
    })
  })

  it('reports the keyboard height the Android bridge adds to the payload', async () => {
    installTauriWindow()
    invokeMock.mockResolvedValue({ top: 24, imeBottom: 312.5 })

    await expect(readNativeWindowInsets()).resolves.toEqual({
      top: 24,
      right: 0,
      bottom: 0,
      left: 0,
      imeBottom: 312.5,
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

/**
 * Edge-to-edge keeps the Android WebView at full height while the keyboard is
 * up, so no viewport event announces the IME. The composer only learns about it
 * because a focused text field makes the bridge sample the native inset.
 */
describe('keyboard inset while a text field is focused', () => {
  it('picks up the keyboard height after focus and drops it on blur', async () => {
    vi.useFakeTimers()
    installTauriWindow()
    const focusable = installFocusableDocument()
    invokeMock.mockResolvedValue({ top: 24, imeBottom: 0 })

    const apply = vi.fn()
    const dispose = observeNativeWindowInsets(apply)
    await vi.advanceTimersByTimeAsync(0)
    expect(apply).toHaveBeenLastCalledWith(expect.objectContaining({ imeBottom: 0 }))

    invokeMock.mockResolvedValue({ top: 24, imeBottom: 320 })
    focusable.focus(editableField)
    await vi.advanceTimersByTimeAsync(220)
    expect(apply).toHaveBeenLastCalledWith(expect.objectContaining({ imeBottom: 320 }))

    invokeMock.mockResolvedValue({ top: 24, imeBottom: 0 })
    focusable.blur()
    await vi.advanceTimersByTimeAsync(60)
    expect(apply).toHaveBeenLastCalledWith(expect.objectContaining({ imeBottom: 0 }))

    dispose()
  })

  it('stops sampling once focus leaves, and never re-applies an unchanged read', async () => {
    vi.useFakeTimers()
    installTauriWindow()
    const focusable = installFocusableDocument()
    invokeMock.mockResolvedValue({ top: 24, imeBottom: 300 })

    const apply = vi.fn()
    const dispose = observeNativeWindowInsets(apply)
    await vi.advanceTimersByTimeAsync(0)
    expect(apply).toHaveBeenCalledTimes(1)

    focusable.focus(editableField)
    await vi.advanceTimersByTimeAsync(1_000)
    // The value never changed, so the sampler read it without re-applying.
    expect(apply).toHaveBeenCalledTimes(1)
    expect(invokeMock.mock.calls.length).toBeGreaterThan(3)

    focusable.blur()
    await vi.advanceTimersByTimeAsync(60)
    const readsAfterBlur = invokeMock.mock.calls.length
    await vi.advanceTimersByTimeAsync(1_000)
    expect(invokeMock.mock.calls.length).toBe(readsAfterBlur)

    dispose()
  })
})
