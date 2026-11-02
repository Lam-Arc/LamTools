// user:“hook 界面自行设计”+钩子页重构验收：事件徽标卡片墙、事件筛选、
// 信任/取消信任与删除动作不回退。
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CoreHooksEditor from '../src/components/CoreHooksEditor.vue'
import CoreConfirmDialog from '../src/components/CoreConfirmDialog.vue'

const hooksPayload = {
  hooks: [
    { id: 'user:config:PostToolUse:0:0:aa', event: 'PostToolUse', matcher: '*', source: 'user', source_name: 'config', plugin_name: '', config_path: 'C:/hooks.json', handler_type: 'command', command: 'node lint.mjs', definition_hash: 'aa', trusted: true, status: 'trusted' },
    { id: 'user:config:PreToolUse:0:0:bb', event: 'PreToolUse', matcher: 'Bash', source: 'user', source_name: 'config', plugin_name: '', config_path: 'C:/hooks.json', handler_type: 'prompt', command: '', definition_hash: 'bb', trusted: false, status: 'pending_review' },
  ],
  total_count: 2,
  trusted_count: 1,
  trustable_count: 1,
}

function makeRpc() {
  return vi.fn(async (method: string, _params?: Record<string, unknown>) => {
    if (method === 'hook.list') return hooksPayload
    return {}
  })
}

describe('CoreHooksEditor card wall', () => {
  it('renders one card per hook with event badge and trust state', async () => {
    const wrapper = mount(CoreHooksEditor, { props: { requestRpc: makeRpc() } })
    await flushPromises()

    const cards = wrapper.findAll('[data-hook-card]')
    expect(cards).toHaveLength(2)
    expect(wrapper.get('[data-hook-card="user:config:PostToolUse:0:0:aa"]').text()).toContain('node lint.mjs')
    // 待审核卡片要有醒目标记，不能只靠文字颜色。
    expect(wrapper.get('[data-hook-card="user:config:PreToolUse:0:0:bb"]').classes()).toContain('is-attention')
  })

  it('filters cards through event chips', async () => {
    const wrapper = mount(CoreHooksEditor, { props: { requestRpc: makeRpc() } })
    await flushPromises()

    await wrapper.get('[data-hook-filter="PreToolUse"]').trigger('click')
    const visible = wrapper.findAll('[data-hook-card]')
    expect(visible).toHaveLength(1)
    expect(wrapper.find('[data-hook-card="user:config:PostToolUse:0:0:aa"]').exists()).toBe(false)

    await wrapper.get('[data-hook-filter="all"]').trigger('click')
    expect(wrapper.findAll('[data-hook-card]')).toHaveLength(2)
  })

  it('trusts and untrusts from the card actions', async () => {
    const requestRpc = makeRpc()
    const wrapper = mount(CoreHooksEditor, { props: { requestRpc } })
    await flushPromises()

    const pendingCard = wrapper.get('[data-hook-card="user:config:PreToolUse:0:0:bb"]')
    await pendingCard.get('[data-hook-trust]').trigger('click')
    expect(requestRpc.mock.calls.some(([method, params]) => method === 'hook.trust' && (params as { hook_id: string }).hook_id === 'user:config:PreToolUse:0:0:bb')).toBe(true)

    const trustedCard = wrapper.get('[data-hook-card="user:config:PostToolUse:0:0:aa"]')
    await trustedCard.get('[data-hook-untrust]').trigger('click')
    expect(requestRpc.mock.calls.some(([method, params]) => method === 'hook.untrust' && (params as { hook_id: string }).hook_id === 'user:config:PostToolUse:0:0:aa')).toBe(true)
  })

  it('deletes a config hook through the confirm dialog', async () => {
    const requestRpc = makeRpc()
    const wrapper = mount(CoreHooksEditor, { props: { requestRpc } })
    await flushPromises()

    await wrapper.get('[data-hook-delete="user:config:PostToolUse:0:0:aa"]').trigger('click')
    const dialog = wrapper.findAllComponents(CoreConfirmDialog).find((candidate) => candidate.props('open'))
    expect(dialog).toBeTruthy()
    dialog!.vm.$emit('confirm')
    await flushPromises()

    expect(requestRpc.mock.calls.some(([method, params]) => method === 'hook.delete' && (params as { hook_id: string }).hook_id === 'user:config:PostToolUse:0:0:aa')).toBe(true)
  })
})
