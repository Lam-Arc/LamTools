import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import SessionCard from '../src/pet/ui/SessionCard.vue'
import CoreConfirmDialog from '../src/components/CoreConfirmDialog.vue'
import ChatThread from '../src/components/ChatThread.vue'

function setup() {
  const rollbackTurn = vi.fn(async () => {})
  const active = ref(false)
  const channel = { messages: () => ref([]), decisions: () => ref([]), turnStatus: () => ref('idle'), turnActive: () => active, activeTurnId: () => ref(''), lockedMessageIds: () => ref(new Set()), processExpandedIds: () => ref(new Set()), hasMoreHistory: () => ref(false), rollbackTurn }
  const card = { sessionId: 's', projectId: 'p', title: '示例', draft: '', pinned: false, pendingAttachments: [] }
  const ping = { host: ref({ get: () => channel }), client: ref({ transport: {} }), overlay: { width: 1000 }, pending: {} }
  const wrapper = mount(SessionCard, { attachTo: document.body, props: { card: card as any, ping: ping as any }, global: { stubs: { ChatThread: { template: '<div />' }, ComposerBar: true } } })
  return { wrapper, rollbackTurn, active }
}
describe('Ping card rollback confirmation', () => {
  it('requires in-app confirmation, supports cancel and prevents duplicate actions', async () => {
    const { wrapper, rollbackTurn } = setup()
    wrapper.findComponent(ChatThread).vm.$emit('rollback-message', { turnId: 't1', content: '消息' })
    await wrapper.vm.$nextTick()
    expect(wrapper.getComponent(CoreConfirmDialog).props('open')).toBe(true)
    expect(rollbackTurn).not.toHaveBeenCalled()
    ;(document.querySelector('.core-confirm__cancel') as HTMLButtonElement).click()
    await wrapper.vm.$nextTick()
    expect(rollbackTurn).not.toHaveBeenCalled()
    wrapper.findComponent(ChatThread).vm.$emit('rollback-message', { turnId: 't2', content: '消息' })
    await wrapper.vm.$nextTick()
    await flushPromises()
    ;(document.querySelector('.core-confirm__submit') as HTMLButtonElement).click()
    await flushPromises()
    expect(rollbackTurn).toHaveBeenCalledOnce()
    expect(rollbackTurn).toHaveBeenCalledWith('t2')
    wrapper.unmount()
  })
  it('does not roll back if a turn begins before confirmation', async () => {
    const { wrapper, rollbackTurn, active } = setup()
    wrapper.findComponent(ChatThread).vm.$emit('rollback-message', { turnId: 't1', content: '' })
    await wrapper.vm.$nextTick()
    active.value = true
    wrapper.getComponent(CoreConfirmDialog).vm.$emit('confirm')
    await flushPromises()
    expect(rollbackTurn).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('blocks duplicate confirmation while rollback is in flight', async () => {
    const { wrapper, rollbackTurn } = setup()
    let finish!: () => void
    rollbackTurn.mockImplementation(() => new Promise<void>(resolve => { finish = resolve }))
    wrapper.findComponent(ChatThread).vm.$emit('rollback-message', { turnId: 't1', content: '' })
    await wrapper.vm.$nextTick()
    const dialog = wrapper.getComponent(CoreConfirmDialog)
    dialog.vm.$emit('confirm')
    dialog.vm.$emit('confirm')
    expect(rollbackTurn).toHaveBeenCalledOnce()
    await wrapper.vm.$nextTick()
    expect(dialog.props('loading')).toBe(true)
    finish()
    await flushPromises()
    wrapper.unmount()
  })

})
