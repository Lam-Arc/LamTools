import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import CaptureApp from '../src/pet/ui/CaptureApp.vue'
import CaptureEditor from '../src/pet/ui/CaptureEditor.vue'
import * as bridge from '../src/pet/bridge'

vi.mock('../src/pet/bridge', () => ({
  showPingCapture: vi.fn(async () => {}), heartbeatPingCapture: vi.fn(async () => {}), closePingCapture: vi.fn(async () => {}),
  readConfigText: vi.fn(async () => null), apiBase: vi.fn(async () => { throw new Error('示例后端不可用') }),
}))

// user:“确保视觉、功能和交互不退化”+(发送准备失败后显示错误并允许重试或退出)。
it('recovers from a failure while preparing the screenshot send', async () => {
  const frame = { width: 2, height: 2, scale: 1, data: new Uint8Array(16) }
  const wrapper = mount(CaptureApp, { props: { frame: frame as any, bootError: '' }, global: { stubs: { CaptureEditor: true } } })
  wrapper.findComponent(CaptureEditor).vm.$emit('send', { blob: new Blob(), text: '', meta: { x: 0, y: 0, width: 2, height: 2, scale: 1 } })
  await flushPromises()
  expect(wrapper.findComponent(CaptureEditor).props('error')).toContain('示例后端不可用')
  expect(wrapper.findComponent(CaptureEditor).props('busy')).toBe(false)
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); await flushPromises()
  expect(bridge.closePingCapture).toHaveBeenCalledOnce()
  wrapper.unmount()
})

it('allows Escape during preparation without continuing the cancelled send', async () => {
  let finish!: (value: string) => void
  vi.mocked(bridge.closePingCapture).mockClear()
  vi.mocked(bridge.apiBase).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const frame = { width: 2, height: 2, scale: 1, data: new Uint8Array(16) }
  const wrapper = mount(CaptureApp, { props: { frame: frame as any, bootError: '' }, global: { stubs: { CaptureEditor: true } } })
  wrapper.findComponent(CaptureEditor).vm.$emit('send', { blob: new Blob(), text: '', meta: { x: 0, y: 0, width: 2, height: 2, scale: 1 } })
  await flushPromises()
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); await flushPromises()
  expect(bridge.closePingCapture).toHaveBeenCalledOnce()
  finish('http://127.0.0.1:1234'); await flushPromises()
  expect(wrapper.findComponent(CaptureEditor).props('error')).toBe('')
  wrapper.unmount()
})
