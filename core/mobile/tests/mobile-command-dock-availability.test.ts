import { describe, expect, it, vi } from 'vitest'

import { createMobileCommandDockAvailability } from '../src/useMobileCommandDockAvailability'

describe('mobile command dock availability', () => {
  it('tracks narrow and wide viewport changes and removes its listener when stopped', () => {
    let matches = true
    let listener: ((event: MediaQueryListEvent) => void) | undefined
    const addEventListener = vi.fn((_type: string, callback: (event: MediaQueryListEvent) => void) => {
      listener = callback
    })
    const removeEventListener = vi.fn()
    const state = createMobileCommandDockAvailability({
        get matches() { return matches },
        addEventListener,
        removeEventListener,
      } as unknown as MediaQueryList)

    expect(state.available.value).toBe(true)
    state.start()
    expect(addEventListener).toHaveBeenCalledOnce()
    matches = false
    listener?.({ matches } as MediaQueryListEvent)
    expect(state.available.value).toBe(false)
    matches = true
    listener?.({ matches } as MediaQueryListEvent)
    expect(state.available.value).toBe(true)

    state.stop()
    expect(removeEventListener).toHaveBeenCalledOnce()
    expect(removeEventListener).toHaveBeenCalledWith('change', listener)
  })
})
