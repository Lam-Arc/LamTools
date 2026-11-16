import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import RuntimeChecklistCard from '../src/components/RuntimeChecklistCard.vue'
import UiSelect from '../src/components/UiSelect.vue'
describe('runtime plan gallery', () => {
  it('opens the real plan and switches the current status', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('RuntimeChecklistCard')
    const card = wrapper.getComponent(RuntimeChecklistCard)
    expect(card.attributes('data-status')).toBe('running')
    await card.trigger('click')
    expect(card.text()).toContain('准备示例结果')
    wrapper.get('[data-gallery-plan-status]').getComponent(UiSelect).vm.$emit('update:modelValue', 'failed')
    await wrapper.vm.$nextTick()
    expect(card.attributes('data-status')).toBe('failed')
    wrapper.unmount()
  })
})
