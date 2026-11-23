import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import RemoteConnectionPanel from '../src/components/RemoteConnectionPanel.vue'

// user:“确保视觉、功能和交互不退化”+(生成配对码后立即更新有效期，不等后台轮询)。
it('refreshes ticket expiry while ticket creation is still busy', async () => {
  const expiry = Math.floor(Date.now() / 1000) + 180
  const invoke = vi.fn(async (command: string) => {
    if (command === 'get_api_base') return 'http://127.0.0.1:1234'
    if (command === 'p2p_ticket') return { ticket: 'sunday1:sample' }
    if (command === 'p2p_status') return { running: true, serving: true, expiresAt: expiry }
    if (command === 'p2p_qr') return { svg: '<svg></svg>' }
    return { devices: [], revoked: [] }
  })
  ;(window as any).__TAURI_INTERNALS__ = { invoke }
  const wrapper = mount(RemoteConnectionPanel, { props: { platform: 'desktop' } }); await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '生成配对二维码')!.trigger('click'); await flushPromises()
  expect(invoke.mock.calls.filter(([command]) => command === 'p2p_status')).toHaveLength(2)
  expect(wrapper.text()).toContain('秒后失效')
  wrapper.unmount(); delete (window as any).__TAURI_INTERNALS__
})
