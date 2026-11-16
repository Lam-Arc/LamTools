import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import CoreLoadToolsEditor from '../src/components/CoreLoadToolsEditor.vue'
import CoreModelCatalog from '../src/components/CoreModelCatalog.vue'
import LibrarySearchField from '../src/components/LibrarySearchField.vue'

describe('settings search integration', () => {
  it('keeps independent mode and tool searches', async () => {
    const requestRpc = vi.fn(async () => ({ modes: { consider: { description: '计划', tools: ['read_file'] }, execute: { description: '执行', tools: [] } }, catalog: [{ name: 'read_file', category: 'file_read' }], source: 'builtin' }))
    const wrapper = mount(CoreLoadToolsEditor, { props: { requestRpc } })
    await flushPromises()
    expect(wrapper.findAllComponents(LibrarySearchField)).toHaveLength(2)
    await wrapper.get('input[aria-label="搜索模式"]').setValue('execute')
    expect(wrapper.findAll('.mode-picker-item')).toHaveLength(1)
    await wrapper.get('input[aria-label="搜索模式"]').setValue('')
    await wrapper.get('input[aria-label="搜索工具"]').setValue('不存在')
    expect(wrapper.text()).toContain('没有找到匹配的工具')
    wrapper.unmount()
  })
  it('preserves model search attributes and filtering', async () => {
    const wrapper = mount(CoreModelCatalog, { props: { models: [], providers: [] } })
    expect(wrapper.findComponent(LibrarySearchField).exists()).toBe(true)
    expect(wrapper.get('[data-model-catalog-search]').attributes('aria-label')).toBe('搜索模型或供应商')
    await wrapper.get('[data-model-catalog-search]').setValue(' none ')
    expect(wrapper.get('[data-model-catalog-search]').element).toHaveProperty('value', 'none')
    wrapper.unmount()
  })
})
