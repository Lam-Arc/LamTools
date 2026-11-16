import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import StudySidebar from '../src/study/StudySidebar.vue'

describe('study sidebar gallery', () => {
  it('previews the real navigation with isolated tree, selection and source', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('StudySidebar')
    const sidebar = wrapper.getComponent(StudySidebar)
    await sidebar.get('button[aria-label="展开 示例课程"]').trigger('click')
    await flushPromises()
    expect(sidebar.text()).toContain('示例知识点')
    await sidebar.get('button[title="示例知识点"]').trigger('click')
    expect(wrapper.get('[data-study-preview-result]').text()).toContain('示例知识点')
    await wrapper.get('[data-source="StudySidebar"]').trigger('click')
    expect(wrapper.get('[data-source-content="StudySidebar"]').text()).toContain('study-sidebar')
    wrapper.unmount()
  })
  it('can simulate and recover from a local loading failure', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('StudySidebar')
    await wrapper.get('[data-study-preview-failure]').setValue(true)
    const sidebar = wrapper.getComponent(StudySidebar)
    await sidebar.get('button[aria-label="展开 示例课程"]').trigger('click')
    await flushPromises()
    expect(sidebar.get('[role="alert"]').text()).toContain('加载失败')
    await wrapper.get('[data-study-preview-failure]').setValue(false)
    await sidebar.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(sidebar.text()).toContain('示例知识点')
    wrapper.unmount()
  })
})
