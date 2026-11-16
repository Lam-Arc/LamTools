import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SundaySegmented from '../src/components/SundaySegmented.vue'

describe('segmented control with changing options', () => {
  it('keeps one keyboard entry point when the selected option is absent', async () => {
    const wrapper = mount(SundaySegmented, { attachTo: document.body, props: { modelValue: 'missing', label: '选项', options: [{ value: 'a', label: '甲' }, { value: 'b', label: '乙' }] } })
    const radios = wrapper.findAll('[role="radio"]')
    expect(radios.map(radio => radio.attributes('tabindex'))).toEqual(['0', '-1'])
    expect(radios.every(radio => radio.attributes('aria-checked') === 'false')).toBe(true)
    expect(wrapper.get('.sunday-segmented__indicator').element).toHaveProperty('style.display', 'none')
    radios[0].element.focus()
    await radios[0].trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['b'])
    await wrapper.setProps({ modelValue: 'b' })
    expect(radios.map(radio => radio.attributes('tabindex'))).toEqual(['-1', '0'])
    expect(wrapper.get('.sunday-segmented__indicator').element).toHaveProperty('style.display', '')
    await wrapper.setProps({ options: [{ value: 'a', label: '甲' }] })
    expect(wrapper.get('[role="radio"]').attributes('tabindex')).toBe('0')
    wrapper.unmount()
  })
})
