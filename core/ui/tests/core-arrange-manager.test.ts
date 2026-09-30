import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CoreArrangeManager from '../src/components/CoreArrangeManager.vue'

describe('CoreArrangeManager states', () => {
  it('renders an error without also claiming the list is empty and can retry', async () => {
    const requestRpc = vi.fn()
      .mockRejectedValueOnce(new Error('服务不可用'))
      .mockResolvedValueOnce({ jobs: [] })
    const wrapper = mount(CoreArrangeManager, {
      props: { requestRpc },
      // 动作组会传送到顶部条（full-area-band-actions）；jsdom 里没有那个节点，
      // 传送目标缺失时内容自会就地渲染。
      global: { stubs: { Teleport: true } },
    })

    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('服务不可用')
    expect(wrapper.find('[data-arrange-empty]').exists()).toBe(false)
    expect(wrapper.find('.card-list').exists()).toBe(false)

    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('[data-arrange-empty]').text()).toContain('还没有安排')
  })
})
