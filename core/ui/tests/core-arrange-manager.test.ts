import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CoreArrangeManager from '../src/components/CoreArrangeManager.vue'

describe('CoreArrangeManager states', () => {
  it('renders an error without also claiming the list is empty and can retry', async () => {
    const listJobs = vi.fn()
      .mockRejectedValueOnce(new Error('服务不可用'))
      .mockResolvedValueOnce([])
    const wrapper = mount(CoreArrangeManager, {
      props: {
        listJobs,
        updateJob: vi.fn(),
      },
    })

    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('服务不可用')
    expect(wrapper.find('.arrange-empty').exists()).toBe(false)
    expect(wrapper.find('.card-list').exists()).toBe(false)

    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('.arrange-empty').text()).toContain('还没有安排')
  })
})