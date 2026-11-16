import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

// user:“直接渲染项目真实组件…交互测试、参数调整、变体对比”+(展示工作流运行详情的状态与展开行为)。
describe('workflow runtime gallery', () => {
  it('changes runtime states and expands the real runtime dock', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('WorkflowNodeRuntimeDock')
    expect(wrapper.get('.wf-node-runtime').text()).toContain('运行中')
    expect(wrapper.get('.wf-node-runtime .sunday-spin--fast').exists()).toBe(true)
    await wrapper.get('[data-workflow-runtime-state="error"]').trigger('click')
    expect(wrapper.get('.wf-node-runtime').text()).toContain('失败')
    expect(wrapper.find('.wf-node-runtime .sunday-spin').exists()).toBe(false)
    await wrapper.get('.wf-node-runtime-summary').trigger('click')
    expect(wrapper.get('.wf-node-runtime-summary').attributes('aria-expanded')).toBe('false')
    wrapper.unmount()
  })
})
