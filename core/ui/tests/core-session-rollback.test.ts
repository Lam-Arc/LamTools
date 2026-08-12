import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CoreSessionRollback from '../src/components/CoreSessionRollback.vue'

const checkpoints = [
  {
    id: 'checkpoint-main',
    session_id: 'session-1',
    root_session_id: 'session-1',
    parent_checkpoint_id: '',
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
    root_session_id: 'session-1',
    parent_checkpoint_id: 'checkpoint-main',
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
    const request = vi.fn().mockResolvedValue({ nodes: checkpoints, heads: {} })
    const wrapper = mount(CoreSessionRollback, {
      props: { sessionId: 'session-1', request },
    })
    await vi.waitFor(() => expect(request).toHaveBeenCalledWith(
      'session.checkpoints.graph',
      { session_id: 'session-1' },
    ))

    expect(wrapper.findAll('[data-checkpoint-row]')).toHaveLength(2)
    expect(wrapper.get('[data-rollback="checkpoint-main"]').attributes('type')).toBe('button')
    expect(wrapper.get('[data-rollback="checkpoint-sub"]').attributes('type')).toBe('button')
  })

  it('keeps active turns safe and communicates why rollback is unavailable', async () => {
    const request = vi.fn().mockResolvedValue({ nodes: checkpoints, heads: {} })
    const wrapper = mount(CoreSessionRollback, {
      props: { sessionId: 'session-1', activeTurn: true, request },
    })
    await vi.waitFor(() => expect(wrapper.findAll('[data-checkpoint-row]')).toHaveLength(2))

    expect(wrapper.get('[data-active-turn-notice]').text()).toContain('恢复对话需先停止任务')
    // Rows stay selectable for inspection; the confirm actions carry the guard
    expect(wrapper.get('[data-rollback="checkpoint-main"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-rollback="checkpoint-main"]').trigger('click')
    const confirmAll = wrapper.get('[data-confirm-rollback-all="checkpoint-main"]')
    expect(confirmAll.attributes('disabled')).toBeDefined()
    await confirmAll.trigger('click')
    expect(request).toHaveBeenCalledTimes(1)
  })

  it('treats empty, loading failures, and retry as first-class states', async () => {
    const request = vi.fn()
      .mockRejectedValueOnce(new Error('连接已断开'))
      .mockResolvedValueOnce({ nodes: [], heads: {} })
    const wrapper = mount(CoreSessionRollback, {
      props: { sessionId: 'session-1', request },
    })

    await vi.waitFor(() => expect(wrapper.find('[role="alert"]').exists()).toBe(true))
    expect(wrapper.get('[role="alert"]').text()).toContain('连接已断开')
    await wrapper.get('[data-retry-checkpoints]').trigger('click')
    await vi.waitFor(() => expect(wrapper.get('[data-checkpoint-empty]').text()).toContain('暂无节点'))
    expect(request).toHaveBeenCalledTimes(2)
  })
})
