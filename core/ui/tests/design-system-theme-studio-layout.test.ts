import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ThemeStudio from '../src/components/ThemeStudio.vue'
import { STUDIO_PREVIEW_STYLE_ID } from '../src/themeStudio/runtime'

const preview = () => document.querySelector<HTMLStyleElement>(`style[data-ui-theme-studio="${STUDIO_PREVIEW_STYLE_ID}"]`)?.textContent || ''
async function choose(wrapper: VueWrapper, selector: string, label: string) {
  await wrapper.get(`${selector} .ui-select-trigger`).trigger('click')
  await wrapper.findAll('.ui-select-option').find(item => item.text() === label)!.trigger('click')
  await flushPromises()
}
afterEach(() => { localStorage.clear(); document.body.innerHTML = ''; document.querySelectorAll('style[data-ui-theme-studio]').forEach(node => node.remove()) })

describe('theme studio layout selectors', () => {
  it('keeps fill, fixed and cleared size behavior', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.app-rail"]').trigger('click')
    await choose(wrapper, '[data-studio-size-mode="width"]', '填充')
    expect(preview()).toContain('width: 100%')
    await choose(wrapper, '[data-studio-size-mode="width"]', '固定值')
    await wrapper.get('[data-studio-size-value="width"]').setValue('240')
    await flushPromises()
    expect(preview()).toContain('width: 240px')
    await choose(wrapper, '[data-studio-size-mode="width"]', '未设置')
    expect(preview()).not.toContain('width: 240px')
    wrapper.unmount()
  })
  it('keeps independent horizontal and vertical anchors and offsets', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="template.message"]').trigger('click')
    await choose(wrapper, '[data-studio-anchor-edge="h"]', '左')
    await wrapper.get('[data-studio-anchor-offset="h"]').setValue('12')
    await choose(wrapper, '[data-studio-anchor-edge="v"]', '上')
    await wrapper.get('[data-studio-anchor-offset="v"]').setValue('8')
    await flushPromises()
    expect(preview()).toContain('left: 12px')
    expect(preview()).toContain('top: 8px')
    wrapper.unmount()
  })
})
