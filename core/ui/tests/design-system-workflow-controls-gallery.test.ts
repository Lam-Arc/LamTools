import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

// user:“直接渲染项目真实组件…参数调整、变体对比”+(工作流工具栏可演示运行、未保存与冲突状态)。
describe('workflow controls gallery', () => {
  it('exercises real controls and configurable running/conflict states locally', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('WorkflowControlBar')
    await wrapper.get('[aria-label="运行整个工作流"]').trigger('click')
    expect(wrapper.text()).toContain('本地操作：run')
    await wrapper.get('[data-workflow-controls-running]').setValue(true)
    expect(wrapper.get('[aria-label="单步调试"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[aria-label="停止工作流"]').trigger('click')
    expect(wrapper.text()).toContain('本地操作：cancel')
    await wrapper.get('[data-workflow-controls-running]').setValue(false)
    await wrapper.get('[data-workflow-controls-conflict]').setValue(true)
    await wrapper.get('[aria-label="采用远端版本"]').trigger('click')
    expect(wrapper.text()).toContain('本地操作：accept-remote')
    wrapper.unmount()
  })
})
