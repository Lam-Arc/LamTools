import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import RemoteConnectionPanel from '../src/components/RemoteConnectionPanel.vue'

// user:“只有业务真正可用才显示「已连接电脑」；Core 无响应时必须降级显示”+
// (设备页以前只看 connected 布尔：隧道还在、电脑上的 Core 已经死了，界面照样说
//  「手机已连上这台电脑」。这几条测试锁住新的显示规则)。
function mountPanel(status: Record<string, unknown>) {
  const invoke = vi.fn(async (command: string) => {
    if (command === 'p2p_status') return status
    if (command === 'p2p_devices') return { devices: [], revoked: [] }
    if (command === 'p2p_qr') return { svg: '<svg></svg>' }
    if (command === 'p2p_config_set') return { autoConnect: true }
    return {}
  })
  ;(window as any).__TAURI_INTERNALS__ = { invoke }
  const wrapper = mount(RemoteConnectionPanel, { props: { platform: 'desktop' } })
  return { wrapper, invoke }
}

it('claims connected only when every layer is up', async () => {
  const { wrapper } = mountPanel({
    running: true,
    serving: true,
    connected: true,
    peer: 'phone-1',
    view: 'connected',
    reason: '-',
    layers: { transport: true, device: 'authenticated', core: 'ready', session: 'resumed' },
  })
  await flushPromises()
  expect(wrapper.get('[data-p2p-connected]').text()).toContain('手机已连上这台电脑')
  expect(wrapper.find('[data-p2p-status-hint]').exists()).toBe(false)
  wrapper.unmount()
  delete (window as any).__TAURI_INTERNALS__
})

it('shows the reason instead of connected when the peer Core is down', async () => {
  const { wrapper } = mountPanel({
    running: true,
    serving: true,
    // 隧道和手机都还在，只有电脑上的 Core 没响应。
    connected: true,
    peer: 'phone-1',
    view: 'degraded',
    reason: 'core_unavailable',
    layers: { transport: true, device: 'authenticated', core: 'down', session: 'not_resumed' },
  })
  await flushPromises()
  expect(wrapper.find('[data-p2p-connected]').exists()).toBe(false)
  expect(wrapper.get('[data-p2p-status-hint]').text()).toContain('电脑上的 Sunday 没有响应')
  wrapper.unmount()
  delete (window as any).__TAURI_INTERNALS__
})

it('does not show a false "connected" while the session is still resuming', async () => {
  const { wrapper } = mountPanel({
    running: true,
    serving: true,
    connected: true,
    peer: 'phone-1',
    view: 'connecting',
    reason: 'session_not_resumed',
    layers: { transport: true, device: 'authenticated', core: 'ready', session: 'not_resumed' },
  })
  await flushPromises()
  expect(wrapper.find('[data-p2p-connected]').exists()).toBe(false)
  expect(wrapper.get('[data-p2p-status-hint]').text()).toContain('正在恢复会话')
  wrapper.unmount()
  delete (window as any).__TAURI_INTERNALS__
})

// user:“记住用户是否开启远程访问（持久化，不依赖临时状态）”+
// (桌面开关必须真的写进宿主，而不是只改本地 ref)。
it('persists the auto-connect switch through the host', async () => {
  const { wrapper, invoke } = mountPanel({
    running: true,
    serving: true,
    connected: false,
    view: 'waiting',
    reason: 'no_device',
    autoConnect: false,
  })
  await flushPromises()
  const toggle = wrapper.get('[data-p2p-autoconnect]')
  expect((toggle.element as HTMLInputElement).checked).toBe(false)
  await toggle.setValue(true)
  await flushPromises()
  expect(invoke.mock.calls.some(([command, args]) => (
    command === 'p2p_config_set'
    && (args as { autoConnect?: boolean } | undefined)?.autoConnect === true
  ))).toBe(true)
  wrapper.unmount()
  delete (window as any).__TAURI_INTERNALS__
})
