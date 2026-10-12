import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useCoreUiPreferences } from '../src/composables/useCoreUiPreferences'

const STORAGE_KEY = 'lamtools.core.ui.preferences'

function mountPreferences() {
  let api: ReturnType<typeof useCoreUiPreferences> | null = null
  const host = defineComponent({
    setup() {
      api = useCoreUiPreferences(STORAGE_KEY)
      return () => null
    },
  })
  const wrapper = mount(host)
  return { wrapper, api: api! }
}

beforeEach(() => {
  localStorage.clear()
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  localStorage.clear()
})

describe('useCoreUiPreferences theme schedule', () => {
  it('follows the stored schedule and repaints when the clock crosses a switch time', async () => {
    vi.setSystemTime(new Date(2026, 6, 1, 18, 59))
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      themeMode: 'scheduled',
      themeSchedule: { lightFrom: '07:00', darkFrom: '19:00' },
    }))
    const { wrapper, api } = mountPreferences()
    await api.load()

    expect(api.themeMode.value).toBe('scheduled')
    expect(api.effectiveThemeMode.value).toBe('light')

    vi.setSystemTime(new Date(2026, 6, 1, 19, 0))
    vi.advanceTimersByTime(30_000)
    expect(api.effectiveThemeMode.value).toBe('dark')

    // The dark stretch runs through the night until the light switch.
    vi.setSystemTime(new Date(2026, 6, 2, 6, 59))
    vi.advanceTimersByTime(30_000)
    expect(api.effectiveThemeMode.value).toBe('dark')

    vi.setSystemTime(new Date(2026, 6, 2, 7, 0))
    vi.advanceTimersByTime(30_000)
    expect(api.effectiveThemeMode.value).toBe('light')

    wrapper.unmount()
  })

  it('applies the current stretch as soon as 定时切换 is chosen', () => {
    vi.setSystemTime(new Date(2026, 6, 1, 22, 30))
    const { wrapper, api } = mountPreferences()

    expect(api.effectiveThemeMode.value).toBe('light')

    api.setThemeMode('scheduled')

    expect(api.effectiveThemeMode.value).toBe('dark')
    wrapper.unmount()
  })

  it('persists edited switch times and honours them on the next tick', async () => {
    vi.setSystemTime(new Date(2026, 6, 1, 20, 0))
    const { wrapper, api } = mountPreferences()
    await api.load()

    api.setThemeMode('scheduled')
    api.setThemeSchedule({ darkFrom: '21:30' })

    expect(api.effectiveThemeMode.value).toBe('light')
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!).themeSchedule)
      .toEqual({ lightFrom: '07:00', darkFrom: '21:30' })

    vi.setSystemTime(new Date(2026, 6, 1, 21, 30))
    vi.advanceTimersByTime(30_000)

    expect(api.effectiveThemeMode.value).toBe('dark')
    wrapper.unmount()
  })

  it('falls back to the default pair when storage holds an unusable schedule', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      themeMode: 'scheduled',
      themeSchedule: { lightFrom: '99:99', darkFrom: null },
    }))
    const { wrapper, api } = mountPreferences()
    await api.load()

    expect(api.themeSchedule.value).toEqual({ lightFrom: '07:00', darkFrom: '19:00' })
    wrapper.unmount()
  })
})
