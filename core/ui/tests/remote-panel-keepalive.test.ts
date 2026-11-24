import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'

import RemoteConnectionPanel from '../src/components/RemoteConnectionPanel.vue'

// user:“优先保证连接的稳定，减少无故断连”+(手机有配对票据时默认开后台保活；
// 用户关掉开关就立即停服务，不等到下次启动)。
it('turns the background connection service on with a ticket and off on demand', async () => {
  localStorage.setItem('sunday.p2p.ticket', 'sunday1:example')
  const invoke = vi.fn(async (command: string) => {
    if (command === 'p2p_status') return { connected: false, connecting: false, view: 'offline' }
    if (command === 'p2p_devices') return { devices: [], revoked: [] }
    if (command === 'connection_service_set') return { enabled: true }
    return {}
  })
  ;(window as any).__TAURI_INTERNALS__ = { invoke }

  const wrapper = mount(RemoteConnectionPanel, { props: { platform: 'mobile' } })
  await flushPromises()
  expect(invoke).toHaveBeenCalledWith('connection_service_set', { enabled: true })

  const toggle = wrapper.get('[data-p2p-keepalive]')
  await toggle.setValue(false)
  await flushPromises()
  expect(invoke).toHaveBeenCalledWith('connection_service_set', { enabled: false })

  wrapper.unmount()
  delete (window as any).__TAURI_INTERNALS__
  localStorage.clear()
})
