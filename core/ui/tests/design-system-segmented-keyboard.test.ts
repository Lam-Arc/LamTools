import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SundaySegmented from '../src/components/SundaySegmented.vue'
describe('segmented keyboard behavior', () => {
  it('wraps, selects, and moves focus for arrow and boundary keys', async () => {
    const wrapper = mount(SundaySegmented, { attachTo: document.body, props: { modelValue: 'a', label: '示例', options: [{ value: 'a', label: '甲' }, { value: 'b', label: '乙' }, { value: 'c', label: '丙' }] } })
    const radios = wrapper.findAll('[role="radio"]')
    radios[0].element.focus(); await radios[0].trigger('keydown', { key: 'ArrowLeft' })
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['c'])
    expect(document.activeElement).toBe(radios[2].element)
    await wrapper.setProps({ modelValue: 'c' })
    await radios[2].trigger('keydown', { key: 'Home' })
    expect(wrapper.emitted('update:modelValue')?.[1]).toEqual(['a'])
    expect(document.activeElement).toBe(radios[0].element)
    wrapper.unmount()
  })
})
