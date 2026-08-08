import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CoreSessionRollback from '../src/components/CoreSessionRollback.vue'

const checkpoints = [
  {
    id: 'checkpoint-main',
    session_id: 'session-1',
    turn_id: 'turn-2',
    actor_kind: 'main',
    work_root: 'E:/workspace',
    manifest_hash: 'hash-main',
    status: 'ready',
    created_at: '2026-07-15T08:30:00',
  },
  {
    id: 'checkpoint-sub',
    session_id: 'session-1:sub:reviewer',
    turn_id: 'turn-sub-1',
    actor_kind: 'sub_agent',
    work_root: 'E:/workspace',
    manifest_hash: 'hash-sub',
    status: 'ready',
    created_at: '2026-07-15T08:20:00',
  },
]

describe('CoreSessionRollback', () => {
  it('loads checkpoints through the Core operation and exposes restrained row actions', async () => {
    const request = vi.fn().mockResolvedValue({ checkpoints })
    const wrapper = mount(CoreSessionRollback, {
      props: { sessionId: 'session-1', request },
    })
    await vi.waitFor(() => expect(request).toHaveBeenCalledWith(
      'session.checkpoints.list',
      { session_id: 'session-1' },
    ))

    expect(wrapper.findAll('[data-checkpoint-row]')).toHaveLength(2)
    expect(wrapper.text()).toContain('主 Agent')
    expect(wrapper.text()).toContain('子 Agent')
    expect(wrapper.get('[data-rollback="checkpoint-main"]').attributes('type')).toBe('button')
  })

  it('keeps active turns safe and communicates why rollback is unavailable', async () => {
    const request = vi.fn().mockResolvedValue({ checkpoints })
    const wrapper = mount(CoreSessionRollback, {
      props: { sessionId: 'session-1', activeTurn: true, request },
    })
    await vi.waitFor(() => expect(wrapper.findAll('[data-checkpoint-row]')).toHaveLength(2))

    expect(wrapper.get('[data-active-turn-notice]').text()).toContain('任务结束或停止后')
    expect(wrapper.get('[data-rollback="checkpoint-main"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-rollback="checkpoint-main"]').trigger('click')
    expect(request).toHaveBeenCalledTimes(1)
  })

  it('treats empty, loading failures, and retry as first-class states', async () => {
    const request = vi.fn()
      .mockRejectedValueOnce(new Error('连接已断开'))
      .mockResolvedValueOnce({ checkpoints: [] })
    const wrapper = mount(CoreSessionRollback, {
      props: { sessionId: 'session-1', request },
    })

    await vi.waitFor(() => expect(wrapper.find('[role="alert"]').exists()).toBe(true))
    expect(wrapper.get('[role="alert"]').text()).toContain('连接已断开')
    await wrapper.get('[data-retry-checkpoints]').trigger('click')
    await vi.waitFor(() => expect(wrapper.get('[data-checkpoint-empty]').text()).toContain('还没有可回滚的检查点'))
    expect(request).toHaveBeenCalledTimes(2)
  })
})
