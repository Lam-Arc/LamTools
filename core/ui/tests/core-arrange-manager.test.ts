import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CoreArrangeManager from '../src/components/CoreArrangeManager.vue'
import { listArrangeJobs } from '../src/durable/api'

// CoreArrangeManager talks to the backend through the durable/api module; mock
// it so the state machine can be driven without a live app server.
vi.mock('../src/durable/api', () => ({
  listArrangeJobs: vi.fn(),
  createArrangeJob: vi.fn(),
  updateArrangeJob: vi.fn(),
  renameArrangeJob: vi.fn(),
  editArrangeJob: vi.fn(),
  listArrangeOccurrences: vi.fn(),
}))

describe('CoreArrangeManager states', () => {
  it('renders an error without also claiming the list is empty and can retry', async () => {
    vi.mocked(listArrangeJobs)
      .mockRejectedValueOnce(new Error('服务不可用'))
      .mockResolvedValueOnce([])
    const wrapper = mount(CoreArrangeManager, {
      // CoreArrangeManager defers its content into .workspace-shell via
      // Teleport, which never exists in jsdom; stub Teleport to keep the
      // content mounted inside the wrapper
      global: { stubs: { Teleport: true } },
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
