import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

describe('process panel gallery', () => {
  it('shows and updates local sample processes and logs', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('RightSidebarProcesses')
    await vi.waitFor(() => expect(wrapper.find('[data-process-pid="42"]').exists()).toBe(true), { timeout: 5000 })
    await wrapper.get('.core-process-panel__main').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('示例标准输出')
    await wrapper.get('[role="tab"]:last-child').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('示例错误输出')
    await wrapper.get('button[aria-label="终止进程 42"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已退出')
    await wrapper.get('[data-process-preview-reset]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-process-pid="42"]').text()).toContain('运行中')
    wrapper.unmount()
  })
})
