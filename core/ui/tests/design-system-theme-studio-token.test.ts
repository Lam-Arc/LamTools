import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ThemeStudio from '../src/components/ThemeStudio.vue'
import { STUDIO_PREVIEW_STYLE_ID } from '../src/themeStudio/runtime'

const preview = () => document.querySelector<HTMLStyleElement>(`style[data-ui-theme-studio="${STUDIO_PREVIEW_STYLE_ID}"]`)?.textContent || ''
afterEach(() => { localStorage.clear(); document.body.innerHTML = ''; document.querySelectorAll('style[data-ui-theme-studio]').forEach(node => node.remove()) })

describe('theme studio color token select', () => {
  it('applies theme tokens, transparency and the custom-color fallback', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    for (const [label, expected] of [['主区域底色', 'background-color: var(--theme-main-background)'], ['透明', 'background-color: transparent']]) {
      await wrapper.get('[data-studio-color-token] .ui-select-trigger').trigger('click')
      const option = wrapper.findAll('.ui-select-option').find(item => item.text() === label)!
      await option.trigger('click')
      await flushPromises()
      expect(preview()).toContain(expected)
      expect((wrapper.get('[data-studio-field="background"]').element as HTMLInputElement).disabled).toBe(true)
    }
    await wrapper.get('[data-studio-color-token] .ui-select-trigger').trigger('click')
    await wrapper.findAll('.ui-select-option').find(item => item.text() === '自定义颜色')!.trigger('click')
    expect((wrapper.get('[data-studio-field="background"]').element as HTMLInputElement).disabled).toBe(false)
    wrapper.unmount()
  })
})
