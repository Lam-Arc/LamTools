import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import UiSelect from '../src/components/UiSelect.vue'

describe('select overlay layer inheritance', () => {
  it('carries the local layer to its teleported menu', async () => {
    const host = document.createElement('div')
    host.style.setProperty('--ui-select-layer', '900')
    document.body.appendChild(host)
    const wrapper = mount(UiSelect, { attachTo: host, props: { modelValue: 'a', options: [{ value: 'a', label: '一' }] } })
    ;(wrapper.get('.ui-select-trigger').element as HTMLElement).style.setProperty('--ui-select-layer', '900')
    await wrapper.get('.ui-select-trigger').trigger('click')
    await wrapper.vm.$nextTick()
    const menu = document.querySelector<HTMLElement>('.ui-select-menu')!
    expect(menu.style.getPropertyValue('--ui-select-layer')).toBe('900')
    wrapper.unmount()
    host.remove()
  })
})
