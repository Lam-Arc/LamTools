import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ChatThread from '../src/components/ChatThread.vue'

describe('ChatThread message rollback entry', () => {
  it('shows one minimal action for a user turn with a checkpoint', async () => {
    const wrapper = mount(ChatThread, {
      props: {
        messages: [
          {
            id: 'user-1',
            role: 'user',
            content: '调整右侧回退节点',
            timestamp: '',
            metadata: { turnId: 'turn-1' },
          },
          {
            id: 'user-2',
            role: 'user',
            content: '没有存档的旧消息',
            timestamp: '',
            metadata: { turnId: 'turn-2' },
          },
        ],
        rollbackTurnIds: new Set(['turn-1']),
      },
    })

    const actions = wrapper.findAll('[data-message-rollback]')
    expect(actions).toHaveLength(1)
    expect(actions[0].attributes('aria-label')).toBe('回到这条指令执行前')
    await actions[0].trigger('click')
    expect(wrapper.emitted('rollback-message')).toEqual([['turn-1']])
  })
})
