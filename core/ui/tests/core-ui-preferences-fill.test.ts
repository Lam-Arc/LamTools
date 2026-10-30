import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { beforeEach, describe, expect, it } from 'vitest'

import { useCoreUiPreferences } from '../src/composables/useCoreUiPreferences'

const STORAGE_KEY = 'lamtools.core.ui.preferences.fill'

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
})

describe('theme fill preference editing', () => {
  it('把纯色/渐变/玻璃/图片的选择写进当前主题并持久化', () => {
    const { wrapper, api } = mountPreferences()

    api.updateThemeFill('main', 'glass')
    api.updateThemeGlass('main', 'low')
    expect(api.theme.value.mainFill).toBe('glass')
    expect(api.theme.value.mainGlass).toBe('low')

    api.updateThemeFill('backdrop', 'image')
    api.updateThemeImage('backdrop', 'data:image/gif;base64,R0lGODlhAQABAAAAACw=')
    api.updateThemeImageFit('backdrop', 'tile')
    expect(api.theme.value.backdropFill).toBe('image')
    expect(api.theme.value.backdropImage).toBe('data:image/gif;base64,R0lGODlhAQABAAAAACw=')
    expect(api.theme.value.backdropImageFit).toBe('tile')

    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    expect(stored.lightTheme.mainFill).toBe('glass')
    expect(stored.lightTheme.mainGlass).toBe('low')
    expect(stored.lightTheme.backdropFill).toBe('image')
    expect(stored.lightTheme.backdropImageFit).toBe('tile')

    wrapper.unmount()
  })
})
