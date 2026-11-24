import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { expect, it, vi } from 'vitest'

import RemoteConnectionPanel from '../src/components/RemoteConnectionPanel.vue'

const { listen } = vi.hoisted(() => ({ listen: vi.fn() }))
vi.mock('@tauri-apps/api/event', () => ({ listen }))

// user:“针对远程连接/设备配对 去查修目前用户体验最差的一点，并列出接下来的候选”+(扫码后，电脑上无需刷新或展开就能处理配对申请)。
it.each([
  ['确认', 'p2p_confirm_device'],
  ['拒绝', 'p2p_reject_device'],
])('shows a newly scanned device beside the QR code and can choose %s', async (action, command) => {
  const request = { id: 'phone-1', name: '测试设备' }
  let pending: typeof request[] = []
  const invoke = vi.fn(async (name: string) => {
    if (name === 'p2p_status') {
      return { running: true, ticket: 'sunday2:sample', pending, expiresAt: Math.floor(Date.now() / 1000) + 120 }
    }
    if (name === 'p2p_qr') return { svg: '<svg></svg>' }
    if (name === command) pending = []
    return {}
  })
  vi.stubGlobal('__TAURI_INTERNALS__', { invoke })
  const wrapper = mount(RemoteConnectionPanel, { props: { platform: 'desktop' } })

  try {
    await flushPromises()
    expect(wrapper.find('[data-p2p-pending]').exists()).toBe(false)
    const subscribers = listen.mock.calls.filter(([event]) => event === 'p2p-state')
    expect(subscribers.length).toBeGreaterThan(0)

    pending = [request]
    for (const [, push] of subscribers) push({ payload: { pending } })
    await nextTick()

    const approval = wrapper.get('[data-p2p-pending]')
    expect(wrapper.get('[role="status"]').text()).toBe('有设备等待确认配对')
    expect(approval.text()).toContain('测试设备')
    expect(approval.element.closest('details:not([open])')).toBeNull()
    const qr = wrapper.get('.pair-card')
    expect(approval.element.compareDocumentPosition(qr.element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(qr.text()).toContain('扫码后在这台电脑上确认配对')

    const button = approval.findAll('button').find((item) => item.text() === action)
    expect(button).toBeDefined()
    await button!.trigger('click')
    await flushPromises()
    expect(invoke).toHaveBeenCalledWith(command, { id: request.id })
    expect(wrapper.find('[data-p2p-pending]').exists()).toBe(false)
  } finally {
    wrapper.unmount()
    vi.unstubAllGlobals()
    listen.mockClear()
  }
})
