import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ThemeStudio from '../src/components/ThemeStudio.vue'
import { STUDIO_PREVIEW_STYLE_ID } from '../src/themeStudio/runtime'

const preview = () => document.querySelector<HTMLStyleElement>(`style[data-ui-theme-studio="${STUDIO_PREVIEW_STYLE_ID}"]`)?.textContent || ''
afterEach(() => { localStorage.clear(); document.body.innerHTML = ''; document.querySelectorAll('style[data-ui-theme-studio]').forEach(node => node.remove()) })

describe('theme editor shared ranges', () => {
  it('updates background and overall opacity independently using the shared range', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.main"]').trigger('click')
    const background = wrapper.get('.sunday-range input[data-studio-field="background-opacity"]')
    const opacity = wrapper.get('.sunday-range input[data-studio-field="opacity"]')
    await background.setValue('0.5')
    await flushPromises()
    expect(preview()).toContain('--ui-bg-opacity: 0.5')
    expect(preview()).not.toMatch(/(^|[^-])opacity: 0\.5/)
    await opacity.setValue('0.7')
    await flushPromises()
    expect(preview()).toContain('opacity: 0.7')
    expect(preview()).toContain('--ui-bg-opacity: 0.5')
    wrapper.unmount()
  })
})
