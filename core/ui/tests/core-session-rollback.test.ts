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

  it('confirms rollback inline, then offers undo through the same Core operation surface', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ checkpoints })
      .mockResolvedValueOnce({
        operation_id: 'restore-1',
        checkpoint_id: 'checkpoint-main',
        undo_checkpoint_id: 'undo-1',
        status: 'committed',
        restored_paths: ['state.txt'],
      })
      .mockResolvedValueOnce({ checkpoints })
      .mockResolvedValueOnce({
        operation_id: 'restore-2',
        checkpoint_id: 'undo-1',
        undo_checkpoint_id: 'undo-2',
        status: 'committed',
        restored_paths: ['state.txt'],
      })
      .mockResolvedValueOnce({ checkpoints })
    const wrapper = mount(CoreSessionRollback, {
      props: { sessionId: 'session-1', request },
    })
    await vi.waitFor(() => expect(wrapper.findAll('[data-checkpoint-row]')).toHaveLength(2))

    await wrapper.get('[data-rollback="checkpoint-main"]').trigger('click')
    expect(wrapper.get('[data-confirm-rollback="checkpoint-main"]').text()).toContain('确认回滚')
    await wrapper.get('[data-confirm-rollback="checkpoint-main"]').trigger('click')

    await vi.waitFor(() => expect(request).toHaveBeenCalledWith('session.rollback', {
      session_id: 'session-1',
      checkpoint_id: 'checkpoint-main',
    }))
    expect(wrapper.get('[data-undo-rollback]').text()).toContain('撤销回滚')
    expect(wrapper.get('[role="status"]').text()).toContain('已恢复对话与文件')

    await wrapper.get('[data-undo-rollback]').trigger('click')
    await vi.waitFor(() => expect(request).toHaveBeenCalledWith('session.rollback.undo', {
      session_id: 'session-1',
      operation_id: 'restore-1',
    }))
    expect(wrapper.find('[data-undo-rollback]').exists()).toBe(false)
    expect(wrapper.get('[role="status"]').text()).toContain('已撤销回滚')
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
