import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

// user:“直接渲染项目真实组件…交互测试”+(队列预览的清理仅修改本地示例)。
describe('workflow queue gallery', () => {
  it('inspects, switches history and confirms local clearing', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('WorkflowQueuePanel')
    await wrapper.get('.wf-queue-item-main').trigger('click')
    expect(wrapper.get('.wf-queue-detail').text()).toContain('示例运行')
    await wrapper.findAll('[role="tab"]')[1].trigger('click')
    expect(wrapper.get('.wf-queue-list').text()).toContain('示例历史')
    await wrapper.findAll('.wf-queue-danger')[0].trigger('click')
    expect(wrapper.get('[role="alertdialog"]').text()).toContain('删除已结束历史')
    await wrapper.get('.wf-queue-confirm .wf-queue-danger').trigger('click')
    expect(wrapper.text()).toContain('还没有运行历史')
    wrapper.unmount()
  })
})
