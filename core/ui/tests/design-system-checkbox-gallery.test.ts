import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import NodeEditCard from '../../src/lamtools_core/plugins/bundled/workflow/ui/NodeEditCard.vue'

describe('checkbox previews and workflow usage', () => {
  it('compares real checkbox states with an interactive example', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('SundayCheckbox')
    const interactive = wrapper.get('input[aria-label="示例复选框"]')
    await interactive.setValue(true)
    expect((interactive.element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.find('input.sunday-checkbox:disabled').exists()).toBe(true)
    expect(wrapper.text()).toContain('src/styles/sunday-controls.css')
    wrapper.unmount()
  })
  it('updates a workflow node tool selection using native checkbox events', async () => {
    const wrapper = mount(NodeEditCard, { props: {
      node: { id: 'n', kind: 'agent', title: 'Agent', ports: [], config: { tools: ['read_file'] } } as any,
      anchor: { x: 200, y: 100 }, availableTools: [{ name: 'read_file', description: '' }, { name: 'write_file', description: '' }],
    } })
    const boxes = wrapper.findAll('.wf-tool-check input.sunday-checkbox')
    expect((boxes[0].element as HTMLInputElement).checked).toBe(true)
    await boxes[1].setValue(true)
    await wrapper.get('.wf-edit-foot button').trigger('click')
    expect(wrapper.emitted('update')?.[0]?.[0]).toMatchObject({ config: { tools: ['read_file', 'write_file'] } })
    wrapper.unmount()
  })
})
