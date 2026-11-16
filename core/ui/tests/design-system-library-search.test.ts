import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LibrarySearchField from '../src/components/LibrarySearchField.vue'
describe('library search field', () => {
  it('preserves native search semantics, label, input attributes and controlled value', async () => {
    const wrapper = mount(LibrarySearchField, { props: { modelValue: '', label: '搜索资料库', inputAttrs: { 'data-search-example': '' } }, attrs: { class: 'custom-width' } })
    const input = wrapper.get('[data-search-example]')
    expect(input.attributes('type')).toBe('search')
    expect(input.attributes('aria-label')).toBe('搜索资料库')
    expect(wrapper.classes()).toContain('custom-width')
    await input.setValue('关键词')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['关键词'])
    await wrapper.setProps({ modelValue: '关键词' })
    expect((input.element as HTMLInputElement).value).toBe('关键词')
    wrapper.unmount()
  })
  it('allows a consumer to compose an extra action', () => {
    const wrapper = mount(LibrarySearchField, { props: { modelValue: 'x', label: '搜索' }, slots: { default: '<button>清除</button>' } })
    expect(wrapper.get('button').text()).toBe('清除')
    wrapper.unmount()
  })
})
