import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'

import RemoteConnectionPanel from '../src/components/RemoteConnectionPanel.vue'

// user:“电脑显示待确认设备，用户确认配对”+(扫码只登记申请；确认前不能显示成已授权)。
it('lists a scanned device as pending and confirms it on the computer', async () => {
  const invoke = vi.fn(async (command: string) => {
    if (command === 'p2p_status') {
      return {
        running: true,
        serving: true,
        connected: false,
        pending: [{ id: 'phone-1', name: 'Phone', requestedAt: 10, expiresAt: 300 }],
      }
    }
    if (command === 'p2p_devices') return { devices: [], revoked: [] }
    if (command === 'p2p_qr') return { svg: '<svg></svg>' }
    if (command === 'p2p_confirm_device') return { ok: true }
    return {}
  })
  ;(window as any).__TAURI_INTERNALS__ = { invoke }
  const wrapper = mount(RemoteConnectionPanel, { props: { platform: 'desktop' } })
  await flushPromises()

  const pending = wrapper.get('[data-p2p-pending]')
  expect(pending.text()).toContain('Phone')
  const confirm = pending.findAll('button').find((button) => button.text() === '确认')!
  expect(confirm).toBeTruthy()
  await confirm.trigger('click')
  await flushPromises()
  expect(invoke).toHaveBeenCalledWith('p2p_confirm_device', { id: 'phone-1' })

  wrapper.unmount()
  delete (window as any).__TAURI_INTERNALS__
})
