import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'

import RemoteConnectionPanel from '../src/components/RemoteConnectionPanel.vue'

// user:“连接详情展示直连或中继、往返延迟、传输速率和错误原因”+
// (RTT 由宿主从 iroh 当前选中路径读出；界面只在大于 0 时显示)。
it('shows the round-trip latency in the connection details', async () => {
  const invoke = vi.fn(async (command: string) => {
    if (command === 'p2p_status') {
      return {
        running: true,
        serving: true,
        connected: true,
        peer: 'phone-1',
        deviceName: 'Phone',
        path: 'direct',
        rttMs: 42,
        view: 'connected',
        reason: '-',
        layers: { transport: true, device: 'authenticated', core: 'ready', session: 'resumed' },
      }
    }
    if (command === 'p2p_devices') return { devices: [], revoked: [] }
    if (command === 'p2p_qr') return { svg: '<svg></svg>' }
    return {}
  })
  ;(window as any).__TAURI_INTERNALS__ = { invoke }
  const wrapper = mount(RemoteConnectionPanel, { props: { platform: 'desktop' } })
  await flushPromises()
  expect(wrapper.get('[data-p2p-rtt]').text()).toContain('42 ms')
  wrapper.unmount()
  delete (window as any).__TAURI_INTERNALS__
})
