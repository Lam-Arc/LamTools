import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import AccountShell from '../src/components/AccountShell.vue'

// user:“交互测试”+(设备连接展厅只调用隔离服务，不启动真实配对或修改剪贴板)。
it('uses injected services for desktop ticket and copy operations', async () => {
  const realInvoke = vi.fn()
  ;(window as any).__TAURI_INTERNALS__ = { invoke: realInvoke }
  const copy = vi.fn(async () => {})
  const invoke = vi.fn(async (command: string) => {
    if (command === 'get_api_base') return 'http://127.0.0.1:1234'
    if (command === 'p2p_ticket') return { ticket: 'sunday1:sample' }
    if (command === 'p2p_status') return { running: true, serving: true, connected: true, peer: 'sample', expiresAt: Math.floor(Date.now() / 1000) + 180 }
    if (command === 'p2p_qr') return { svg: '<svg></svg>' }
    return { devices: [], revoked: [] }
  })
  const wrapper = mount(AccountShell, { props: { appRuntime: { platform: 'desktop' }, remoteServices: { invoke, copy } } }); await flushPromises()
  localStorage.setItem('sunday.p2p.ticket', '保留的真实票据')
  await wrapper.findAll('button').find(button => button.text() === '生成配对二维码')!.trigger('click'); await flushPromises()
  await wrapper.get('[aria-label="复制票据"]').trigger('click'); await flushPromises()
  expect(copy).toHaveBeenCalledWith('sunday1:sample')
  await wrapper.findAll('button').find(button => button.text() === '断开')!.trigger('click'); await flushPromises()
  expect(invoke.mock.calls.some(([command]) => command === 'p2p_disconnect')).toBe(true)
  expect(localStorage.getItem('sunday.p2p.ticket')).toBe('保留的真实票据')
  expect(realInvoke).not.toHaveBeenCalled()
  wrapper.unmount(); localStorage.removeItem('sunday.p2p.ticket'); delete (window as any).__TAURI_INTERNALS__
})
