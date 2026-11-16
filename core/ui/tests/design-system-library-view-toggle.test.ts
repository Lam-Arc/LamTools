import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LibraryViewToggle from '../src/components/LibraryViewToggle.vue'
describe('library view switcher', () => {
  it('exposes a labelled, controlled grid/list selection', async () => {
    const wrapper = mount(LibraryViewToggle, { props: { modelValue: 'grid' }, attrs: { 'data-test-view': '' } })
    expect(wrapper.get('[data-test-view]').attributes('role')).toBe('group')
    expect(wrapper.get('[aria-label="网格视图"]').attributes('aria-pressed')).toBe('true')
    await wrapper.get('[aria-label="列表视图"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['list'])
    await wrapper.setProps({ modelValue: 'list' })
    expect(wrapper.get('[aria-label="列表视图"]').attributes('aria-pressed')).toBe('true')
    wrapper.unmount()
  })
})
