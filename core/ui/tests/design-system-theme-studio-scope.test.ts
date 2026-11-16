import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ThemeStudio from '../src/components/ThemeStudio.vue'
import { STUDIO_PREVIEW_STYLE_ID } from '../src/themeStudio/runtime'

const preview = () => document.querySelector<HTMLStyleElement>(`style[data-ui-theme-studio="${STUDIO_PREVIEW_STYLE_ID}"]`)?.textContent || ''
afterEach(() => { localStorage.clear(); document.body.innerHTML = ''; document.querySelectorAll('style[data-ui-theme-studio]').forEach(node => node.remove()) })

describe('theme studio scope selector', () => {
  it('preserves instance-only editing and returns to base scope', async () => {
    const node = document.createElement('div')
    node.dataset.uiTemplate = 'template.message'
    node.dataset.uiInstance = 'message:m1'
    document.body.append(node)
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    node.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    await flushPromises()
    await wrapper.get('[data-studio-scope] .ui-select-trigger').trigger('click')
    await wrapper.findAll('.ui-select-option').find(option => option.text().includes('此实例'))!.trigger('click')
    await wrapper.get('[data-studio-field="color"]').setValue('#0a0b0c')
    await flushPromises()
    expect(preview()).toContain('[data-ui-instance="message:m1"]')
    expect(preview()).toContain('#0a0b0c')
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    expect(wrapper.get('[data-studio-scope] .ui-select-trigger').text()).toContain('基础样式')
    wrapper.unmount()
  })
  it('retains breakpoint selection and removal', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-add-breakpoint]').trigger('click')
    expect(wrapper.get('[data-studio-scope] .ui-select-trigger').text()).toContain('窄于')
    await wrapper.get('[data-studio-scope] .ui-select-trigger').trigger('click')
    await wrapper.findAll('.ui-select-option').find(option => option.text().includes('基础样式'))!.trigger('click')
    expect(wrapper.find('[data-studio-remove-breakpoint]').exists()).toBe(false)
    wrapper.unmount()
  })
})
